"""固定小图最近邻2倍/4倍诊断；最多8次请求，不补原图细节，不运行SUT。"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from PIL import Image

from aiagent.evaluation.contracts import digest
from aiagent.evaluation.semantic import Judge
from scripts.build_adjudicated_regression import ROOT, sha, write_new
from scripts.calibrate_evaluation_channels import CANDIDATE, calibrate
from scripts.diagnose_judge_grounding import CASE_IDS, REFERENCES, selected_rows

SCALES = (2, 4)
TRANSFORM = "integer-nearest-neighbor-rgb-png-v1"


def source_images(rows: list[dict]) -> dict:
    if tuple(row["id"] for row in rows) != CASE_IDS or any(len(row["images"]) != 1 for row in rows):
        raise ValueError("只允许固定四条small参照")
    images = {}
    for row in rows:
        item = row["images"][0]
        if sha(Path(item["path"])) != item["sha256"]:
            raise ValueError("小图来源摘要不一致")
        if row["payload"].get("images_sha256") != [item["sha256"]]:
            raise ValueError("payload与小图摘要不一致")
        if item["sha256"] not in images:
            with Image.open(item["path"]) as image:
                images[item["sha256"]] = image.convert("RGB")
    if len(images) != 2:
        raise ValueError("只允许两张固定小图")
    return images


def prepare_scaled_rows(rows: list[dict], directory: Path) -> tuple[list[dict], dict]:
    sources = source_images(rows)
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    images, entries = {}, []
    for source_sha, image in sources.items():
        for scale in SCALES:
            resized = image.resize((image.width * scale, image.height * scale), Image.Resampling.NEAREST)
            path = directory / f"{source_sha[:16]}-nn{scale}.png"
            resized.save(path, format="PNG")
            # PNG不再做有损压缩；验证实际落盘图可恢复源小图的全部解码RGB像素。
            with Image.open(path) as stored:
                recovered = stored.convert("RGB").resize(image.size, Image.Resampling.NEAREST)
            if recovered.tobytes() != image.tobytes():
                raise ValueError("放大图未通过RGB像素恢复校验")
            image_sha = sha(path)
            images[(source_sha, scale)] = {"path": str(path.resolve()), "sha256": image_sha}
            entries.append({"source_image_sha256": source_sha, "source_size": list(image.size),
                "scale": scale, "generated_size": list(resized.size), "generated_image_sha256": image_sha,
                "generated_file": path.name, "decoded_rgb_recovered_exactly": True})
    scaled_rows = []
    for row in rows:
        for scale in SCALES:
            result = deepcopy(row)
            result["id"] += f"-nn{scale}"
            image = images[(row["images"][0]["sha256"], scale)]
            result["images"] = [image]
            result["payload"]["images_sha256"] = [image["sha256"]]
            scaled_rows.append(result)
    manifest = {"transform": TRANSFORM, "scales": list(SCALES), "generative_enhancement": False,
        "original_resolution_pixels_used": False, "source_case_ids": list(CASE_IDS), "images": entries,
        "baseline_eligible": False, "human_accepted": False, "heldout_touched": False}
    write_new(directory.parent / "image-scale-manifest.json", manifest)
    return scaled_rows, manifest


def main(argv=None) -> int:
    import json
    import os

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "data/cache/reports/judge-image-scale")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--allow-provider", action="store_true")
    parser.add_argument("--debug-local", action="store_true")
    args = parser.parse_args(argv)
    rows = selected_rows()
    source_images(rows)
    if not args.execute:
        print(json.dumps({"execute": False, "network": False, "request_budget": 8,
                          "transform": TRANSFORM, "scales": list(SCALES), "source_case_ids": list(CASE_IDS)}))
        return 0
    if not args.allow_provider:
        parser.error("真实诊断需要--allow-provider")
    if os.environ.get("EVAL_JUDGE_VISION") != "1":
        parser.error("真实图片诊断需要EVAL_JUDGE_VISION=1")
    output = args.output.resolve() / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8])
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    scaled, manifest = prepare_scaled_rows(rows, output / "scaled-images")
    judge = Judge("provider", max_repairs=0, request_budget=8, thinking_mode="disabled", max_output_tokens=8192,
        debug_directory=output / ".judge-debug" if args.debug_local else None)
    identity = {"diagnostic": "fixed-small-image-scale-only", "transform": TRANSFORM,
        "image_scale_manifest_sha256": digest(manifest), "source_case_ids": list(CASE_IDS),
        "source_payloads_sha256": digest([row["payload"] for row in rows]),
        "payloads_sha256": digest([row["payload"] for row in scaled]),
        "candidate_manifest_sha256": sha(CANDIDATE / "manifest.json"), "reference_sha256": sha(REFERENCES),
        "runner_source_sha256": sha(Path(__file__)), "fixed_answers_not_sut_generated": True,
        "not_same_condition_as_unscaled_inputs": True, "original_resolution_pixels_used": False}
    report = calibrate(scaled, judge, output, suite="visual", identity=identity)
    code = 2 if report["summary"]["judge_errors"] else (0 if report["all_references_matched"] else 1)
    print(json.dumps({"exit_code": code, "report": str(output / "report.json"),
                      "summary": report["summary"], "usage": report["usage"]}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
