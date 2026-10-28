"""只检查数据结构、溯源和图片分组，不执行评测、服务请求或模型调用。"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aiagent.evaluation.contracts import Dataset, read_json


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def inside(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError(f"数据文件不存在或越界: {relative}")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, default=ROOT, help="原项目根目录；隔离评测副本可指向只读来源")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--adapters", action="store_true", help="在用户修正评测源文件后，额外验证输入模型；仍不执行observe")
    args = parser.parse_args()
    root = args.dataset_dir.resolve()
    manifest = read_json(root / "manifest.json")
    catalog = read_json(root / "catalog.json")
    catalog_ids = {row["case_id"] for row in catalog}
    if len(catalog_ids) != len(catalog):
        raise ValueError("catalog中的用例ID不唯一")
    provenance_splits = defaultdict(set)
    checked_ids = set()
    adapter_cases = 0
    datasets = {}
    for name, metadata in manifest["datasets"].items():
        path = inside(root, name + ".json")
        if sha(path) != metadata["sha256"]:
            raise ValueError(f"数据集哈希变化: {name}")
        dataset = Dataset.model_validate(read_json(path))
        if len(dataset.cases) != metadata["cases"]:
            raise ValueError(f"数据集数量不符: {name}")
        for case in dataset.cases:
            if case.case_id not in catalog_ids:
                raise ValueError("数据集有未登记来源的用例: " + case.case_id)
            provenance_splits[case.group_id].add(case.split)
            checked_ids.add(case.case_id)
            for step in [*case.inputs.get("steps", []), *case.inputs.get("cleanup", [])]:
                if not step.get("checks"):
                    raise ValueError("HTTP步骤没有成功断言: " + case.case_id)
                if step.get("image") and sha(inside(root, step["image"])) != step.get("image_sha256"):
                    raise ValueError("上传图片哈希不符: " + case.case_id)
            if case.kind == "rag" and case.inputs.get("backend", "bm25") == "bm25":
                documents = case.inputs.get("documents", {})
                if not documents or any(not value.strip() for value in documents.values()):
                    raise ValueError("BM25语料为空: " + case.case_id)
                if any(source not in documents for source in case.oracle.relevance):
                    raise ValueError("BM25相关性标注指向不存在的文档")
            if args.adapters:
                from aiagent.evaluation.adapters import validate_inputs

                validate_inputs(case)
                adapter_cases += 1
        datasets[name] = len(dataset.cases)
    mixed = {group: sorted(splits) for group, splits in provenance_splits.items() if len(splits) != 1}
    if mixed:
        raise ValueError("同组用例跨split: " + json.dumps(mixed, ensure_ascii=False))
    if checked_ids != catalog_ids:
        raise ValueError("catalog和数据集的用例并集不一致")
    release = Dataset.model_validate(read_json(root / "release-suite.json"))
    if ({case.domain for case in release.cases if case.layer == "component"} != {"rag", "memory", "vision", "persona"}
            or {case.layer for case in release.cases} != {"component", "trajectory", "task"}
            or {case.domain for case in release.cases if case.oracle.semantic} != {"rag", "memory", "vision", "persona"}
            or not any(case.kind == "vision_api" for case in release.cases)
            or not any(case.kind == "graph" and case.inputs.get("driver") == "runtime" for case in release.cases)):
        raise ValueError("联合验收集输入覆盖不完整")
    for row in catalog:
        for source in row["sources"]:
            if sha(inside(args.source_root.resolve(), source["path"])) != source["sha256"]:
                raise ValueError("来源文件已变化: " + source["path"])
    ledger = read_json(root / "source-ledger.json")
    for doc in ledger:
        if sha(inside(args.source_root.resolve() / "data/knowledge/public", doc["path"])) != doc["sha256"]:
            raise ValueError("原始MD已变化: " + doc["path"])
        path = inside(root / "corpus/public", doc["path"])
        if sha(path) != doc["sha256"]:
            raise ValueError("MD快照哈希不符")
        lines = path.read_text(encoding="utf-8-sig").splitlines()
        for field in doc["fields"]:
            if lines[field["line"] - 1].strip() != field["quote"]:
                raise ValueError("原文行号与引用不符: " + doc["path"])
    corpus_manifest = inside(root, "corpus-manifest.json")
    if sha(corpus_manifest) != manifest["corpus_manifest_sha256"]:
        raise ValueError("语料清单哈希不符")
    for doc in read_json(corpus_manifest):
        if sha(inside(root / "corpus/public", doc["path"])) != doc["sha256"]:
            raise ValueError("语料清单内容不符")
    inventory = read_json(root / "image-inventory.json")
    roles = defaultdict(set)
    query_hashes = set()
    for row in inventory:
        if sha(inside(args.source_root.resolve(), row["source"])) != row["source_sha256"]:
            raise ValueError("原始图片已变化: " + row["source"])
        if not row["usable"]:
            continue
        path = inside(root, row["asset"])
        if sha(path) != row["asset_sha256"]:
            raise ValueError("图片资产哈希不符")
        roles[row["group_id"]].add(row["role"])
        if row["role"] == "query":
            query_hashes.add(row["asset_sha256"])
    if any(len(value) != 1 for value in roles.values()):
        raise ValueError("同一图片近重复组跨越query/reference")
    gallery = list((root / "reference-gallery").glob("*/images/*"))
    if any(sha(path) in query_hashes for path in gallery):
        raise ValueError("参考图库与查询图有精确重复")
    warnings = []
    # 仅做语法/明显录入问题提示，不导入适配器，不运行测试。
    for path in sorted((ROOT / "aiagent/evaluation").glob("*.py")):
        source = path.read_text(encoding="utf-8-sig")
        try:
            ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            warnings.append(f"{path.relative_to(ROOT).as_posix()}:{exc.lineno}: {exc.msg}")
        if "from urrlib.parse import" in source:
            warnings.append(f"{path.relative_to(ROOT).as_posix()}: urrlib应为urllib")
    live_test = ROOT / "tests/integration/test_evaluation_live.py"
    if live_test.exists() and "```" in live_test.read_text(encoding="utf-8-sig"):
        warnings.append("tests/integration/test_evaluation_live.py仍含Markdown代码围栏")
    annotations = inside(root, "visual-annotations.json")
    if sha(annotations) != manifest["visual_annotations_sha256"]:
        raise ValueError("视觉标注快照哈希不符")
    report = {
        "data_integrity_ok": True, "unique_cases": len(checked_ids), "datasets": datasets,
        "source_documents": len(ledger), "source_images": len(inventory), "gallery_images": len(gallery),
        "group_split_integrity_ok": True, "query_gallery_exact_overlap": 0,
        "release_input_coverage_ok": True,
        "adapter_input_models_checked": args.adapters, "adapter_case_occurrences_checked": adapter_cases,
        "source_preflight_warnings": warnings,
        "tests_executed": False, "providers_called": False, "http_requests_sent": 0,
        "limitations": "结构核对不等于评测通过；未审定全部事实、相关性与图片身份；感知近重复仍需人工复核",
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
