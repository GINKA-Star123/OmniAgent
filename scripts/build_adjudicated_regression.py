"""构建不覆盖r3的审定候选子集，或只读审计历史Judge；不调用服务或模型。"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from collections import defaultdict
from pathlib import Path

from aiagent.evaluation.contracts import Dataset, digest, read_json

ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / "docs/quality/evaluation-adjudication-20261028.json"
CALIBRATION = ROOT / "docs/quality/judge-calibration-20261028.json"
DEFAULT_SOURCE = ROOT / "data/evaluation/project-20261026-r3"
DEFAULT_OUTPUT = ROOT / "data/evaluation/project-20261028-adjudicated-regression-v1"


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def inside(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError("来源文件不存在或越界")
    return path


def snapshot(root: Path) -> dict[str, str]:
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("冻结目录不允许符号链接")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = sha(path)
    return result


def write_new(path: Path, value: dict) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def validate_calibration(calibration: dict) -> None:
    rows = calibration.get("cases", [])
    if (calibration.get("version") != "judge-adjudication-calibration-v1" or not rows
            or len({row["id"] for row in rows}) != len(rows)):
        raise ValueError("校准参照为空、重复或版本无效")
    for row in rows:
        if (not row["answer"].strip() or not row["gold"].strip()
                or row["relation"] not in {"entailed", "partial", "contradicted", "not_addressed"}
                or row["truth"] not in {"correct", "incorrect", "unverifiable"}):
            raise ValueError("校准参照字段无效")
        if "valid_quote" in row and (not row["valid_quote"] or row["valid_quote"] not in row["answer"]):
            raise ValueError("有效引用必须是非空连续原文")
        if "invalid_quote" in row and (not row["invalid_quote"] or row["invalid_quote"] in row["answer"]):
            raise ValueError("无效引用对照不成立")


def build(source: Path, output: Path, review_path: Path = REVIEW,
          calibration_path: Path = CALIBRATION, source_root: Path = ROOT) -> dict:
    source, output = source.resolve(), output.resolve()
    if (not source.is_dir() or output.exists() or output.is_relative_to(source)
            or source.is_relative_to(output)):
        raise ValueError("目标必须是冻结来源目录之外的全新目录，不覆盖已有内容")
    before = snapshot(source)
    review, calibration = read_json(review_path), read_json(calibration_path)
    if (review.get("version") != "project-eval-adjudication-v1"
            or review.get("baseline_eligible") is not False
            or review.get("status") != "agent_reviewed_candidate_not_human_accepted"):
        raise ValueError("仅生成未经用户确认的独立候选版本")
    reviews = review["image_reviews"]
    if not reviews or len({row["group_id"] for row in reviews}) != len(reviews):
        raise ValueError("审定图片组不能为空或重复")
    validate_calibration(calibration)
    inventory = read_json(source / "image-inventory.json")
    visual = Dataset.model_validate(read_json(source / "api-vision-reviewed.json"))
    persona = Dataset.model_validate(read_json(source / "provider-persona.json"))
    original_kinds = read_json(source / "judge-gold-kinds.json")
    selected, assets, changes, sources = [], {}, [], {}
    for row in reviews:
        source_hash = row["source_sha256"]
        matches = [item for item in inventory if item["source_sha256"] == source_hash
                   and item["group_id"] == row["group_id"] and item.get("usable") and item.get("role") == "query"]
        if len(matches) != 1:
            raise ValueError("审定来源与图片清单不一致")
        item = matches[0]
        original_path = inside(source_root, item["source"])
        if sha(original_path) != source_hash:
            raise ValueError("原始图片与冻结清单不一致")
        sources[item["source"]] = source_hash
        cases = [case for case in visual.cases if case.group_id == row["group_id"]]
        expected = {"vision-" + source_hash[:12] + "-" + suffix
                    for suffix in ("normal", "small", "wrong-hint")}
        if (len(cases) != 3 or {case.case_id for case in cases} != expected
                or any(case.split != "regression" or case.kind != "vision_api" for case in cases)):
            raise ValueError("只允许完整的三个regression图片变体，不处理heldout或混组")
        for original in cases:
            case = original.model_copy(deep=True)
            case.oracle.gold = dict(row["gold"])
            case.oracle.rubric += "\n审定口径：" + row["rubric"]
            case = type(case).model_validate(case.model_dump(mode="json"))
            for step in case.inputs["steps"]:
                if step.get("image"):
                    asset = inside(source, step["image"])
                    if sha(asset) != step["image_sha256"]:
                        raise ValueError("实际上传图片摘要变化")
                    assets[step["image"]] = step["image_sha256"]
            selected.append(case)
            changes.append({"case_id": case.case_id, "group_id": case.group_id,
                "old_gold": original.oracle.gold, "new_gold": case.oracle.gold,
                "original_case_sha256": digest(original.model_dump(mode="json")),
                "decision": row["decision"], "inputs_unchanged": case.inputs == original.inputs,
                "limits_unchanged": case.oracle.limits == original.oracle.limits})
    p = review["persona_review"]
    found = [case for case in persona.cases if case.case_id == p["case_id"]]
    if (len(found) != 1 or found[0].split != "regression" or found[0].kind != "persona"
            or p["fact_scope"] != "trajectory" or p["gold_unchanged"] is not True):
        raise ValueError("Persona审定必须是已存在的regression轨迹目标")
    original = found[0]
    revised = original.model_copy(deep=True)
    revised.inputs["fact_scope"] = p["fact_scope"]
    revised.oracle.rubric += "\n审定口径：" + p["rubric"]
    revised = type(revised).model_validate(revised.model_dump(mode="json"))
    kinds = {case.case_id: {key: "fact" for key in case.oracle.gold} for case in selected}
    kinds[revised.case_id] = dict(original_kinds.get(revised.case_id, {}))
    changes.append({"case_id": revised.case_id, "group_id": revised.group_id,
        "old_fact_scope": original.inputs.get("fact_scope", "last_answer"), "new_fact_scope": "trajectory",
        "gold_unchanged": revised.oracle.gold == original.oracle.gold,
        "limits_unchanged": revised.oracle.limits == original.oracle.limits,
        "original_case_sha256": digest(original.model_dump(mode="json")), "decision": p["decision"]})
    datasets = {
        "api-vision-adjudicated": Dataset(version="agent-eval-system-v1",
            description="代理直接复核的regression候选子集，非完整r4、非人工验收基线。", cases=selected),
        "provider-persona-adjudicated": Dataset(version="agent-eval-system-v1",
            description="显式轨迹事实范围的Persona-17候选，不回写旧末轮口径分数。", cases=[revised]),
    }
    # 所有输入先作结构校验；这里只验证输入模型，不执行适配器。
    from aiagent.evaluation.adapters import validate_inputs

    for dataset in datasets.values():
        for case in dataset.cases:
            validate_inputs(case)
    output.mkdir(parents=True, exist_ok=False)
    for name, dataset in datasets.items():
        write_new(output / (name + ".json"), dataset.model_dump(mode="json"))
    for relative, expected_hash in assets.items():
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(inside(source, relative), target)
        if sha(target) != expected_hash:
            raise ValueError("候选图片复制校验失败")
    write_new(output / "judge-gold-kinds.json", kinds)
    write_new(output / "adjudication.json", review)
    write_new(output / "judge-calibration.json", calibration)
    write_new(output / "changes.json", {"changes": changes})
    with (output / "README.md").open("x", encoding="utf-8") as stream:
        stream.write("# 审定候选 regression 子集\n\n未经用户确认，不是完整 r4 或发布基线。"
            f"仅含{len(reviews)}组已复核图片（{len(selected)}例）与Persona轨迹（1例），不含heldout。\n\n"
            "审定说明：../../../docs/quality/evaluation-adjudication-20261028.md。\n"
            "manifest.json 记录来源和产物摘要；changes.json 记录逐例差异；adjudication.json 为口径快照。\n"
            f"judge-calibration.json 的{len(calibration['cases'])}例仅是离线参照，不表示实际Judge已校准。\n"
            "不自动执行模型、API、历史重评分或验收。不要与原r3直接比较通过率。\n")
    after = snapshot(source)
    if before != after:
        raise ValueError("构建期间冻结来源变化；不生成成功清单，不可使用此候选")
    manifest = {"version": "adjudicated-regression-candidate-v1", "baseline_eligible": False,
        "human_accepted": False, "full_r4_dataset": False, "heldout_reviewed": False,
        "semantic_judge_calibrated": False, "providers_called": False, "http_requests_sent": 0,
        "source_directory": source.name, "source_files_sha256": before,
        "source_unchanged": True, "source_images_sha256": sources,
        "review_sha256": sha(review_path), "calibration_sha256": sha(calibration_path),
        "datasets": {name: {"cases": len(dataset.cases), "sha256": sha(output / (name + ".json"))}
                     for name, dataset in datasets.items()},
        "assets": assets, "files_sha256": snapshot(output),
        "calibration_reference_cases": len(calibration["cases"]),
        "note": "结构和摘要校验不等于Judge语义校准或业务评测通过；旧报告不重评分。"}
    write_new(output / "manifest.json", manifest)
    return {"output": str(output), "cases": sum(len(d.cases) for d in datasets.values()),
            "image_groups": len(reviews), "image_assets": len(assets),
            "frozen_files_verified": len(before), "baseline_eligible": False,
            "providers_called": False, "http_requests_sent": 0, "heldout_reviewed": False}


def audit_debug(directory: Path) -> dict:
    if not directory.is_dir() or directory.is_symlink():
        raise ValueError("历史诊断目录不存在或为符号链接")
    attempts = defaultdict(list)
    quote_errors = []
    artifact_hashes = {}
    for path in sorted(directory.glob("*.json")):
        match = re.fullmatch(r"([a-f0-9]{24})-([1-9][0-9]*)\.json", path.name)
        if match is None or path.is_symlink():
            raise ValueError("历史诊断文件名不符合约定")
        record = read_json(path)
        artifact_hashes[path.name] = sha(path)
        payload = record["payload"]
        try:
            raw = json.loads(record["raw_verdict"])
        except (ValueError, TypeError):
            continue
        if not isinstance(raw, dict):
            continue
        invalid = sum(not any(claim["quote"] in answer for answer in payload.get("fact_answers", [payload["answer"]]))
                      for claim in raw.get("claims", []))
        if invalid:
            quote_errors.append({"artifact": path.name, "invalid_quote_count": invalid})
        relations = {key: row.get("relation") for key, row in raw.get("coverage_assessments", {}).items()}
        attempts[match[1]].append((int(match[2]), path.name, relations))
    drift = []
    for rows in attempts.values():
        rows.sort()
        for old, new in zip(rows, rows[1:], strict=False):
            for goal in sorted(old[2].keys() & new[2].keys()):
                if old[2][goal] != new[2][goal]:
                    drift.append({"first_artifact": old[1], "repair_artifact": new[1],
                        "target_id": goal, "from": old[2][goal], "to": new[2][goal],
                        "upgraded_to_entailed": new[2][goal] == "entailed"})
    if not artifact_hashes:
        raise ValueError("历史诊断目录没有可审阅文件")
    return {"version": "historical-judge-adjudication-audit-v1", "source_files": len(artifact_hashes),
            "source_artifacts_sha256": artifact_hashes,
            "invalid_quote_artifacts": quote_errors, "coverage_relation_changes": drift,
            "read_only": True, "historical_scores_rewritten": False, "providers_called": False,
            "note": "只读诊断；格式修复时改变语义结论须复核，不修改原始报告。"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--audit-debug", type=Path, help="只读审计给定本地诊断目录，不构建子集")
    parser.add_argument("--audit-output", type=Path, help="新建安全审计报告，禁止覆盖")
    args = parser.parse_args(argv)
    if args.audit_debug:
        result = audit_debug(args.audit_debug)
        if args.audit_output:
            write_new(args.audit_output, result)
    else:
        if args.audit_output:
            parser.error("--audit-output 必须与 --audit-debug 配合")
        result = build(args.source, args.output, source_root=args.source_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
