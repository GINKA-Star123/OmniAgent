from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path

from aiagent.evaluation.adapters import INPUTS, RAG_GENERATION_PROMPT, observe, provider_session, validate_inputs
from aiagent.evaluation.contracts import Dataset, digest, read_json
from aiagent.evaluation.reporting import PROTOCOL, compare_reports, summarize
from aiagent.evaluation.scoring import evaluate_one
from aiagent.evaluation.semantic import Judge, JudgeError

ROOT = Path(__file__).resolve().parents[2]


def code_identity() -> dict:
    def git(*args):
        response = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=False)
        if response.returncode:
            raise RuntimeError("git identity unavailable")
        return response.stdout.strip()

    source = hashlib.sha256()
    for package in ("aiagent", "apps/core", "apps/api", "cloud", "config", "integrations"):
        for path in sorted((ROOT / package).rglob("*.py")):
            source.update(path.relative_to(ROOT).as_posix().encode())
            source.update(path.read_bytes())
    return {"head": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain")),
            "source_sha256": source.hexdigest()}


def conditions(dataset: Dataset, args, judge: Judge) -> dict:
    from config.settings import Settings

    settings = Settings()
    def nonsecret_config(model):
        return {name: str(value) for name, value in model.model_dump().items()
                if not any(part in name.lower() for part in ("api_key", "access_key", "secret", "password"))
                and not name.lower().endswith("_token")}

    from cloud.config import CloudSettings

    values = {"settings": nonsecret_config(settings), "cloud": nonsecret_config(CloudSettings())}
    result = {"dataset_sha256": digest(dataset.model_dump(mode="json")), "repeat": args.repeat,
            "split": args.split, "python": platform.python_version(), "judge": judge.identity,
            "sut_config_sha256": digest(values), "sut_identity": os.environ.get("EVAL_SUT_IDENTITY", "local-offline"),
            "api_origin_sha256": digest(os.environ.get("EVAL_BASE_URL", "")),
            "corpus_sha256": os.environ.get("EVAL_CORPUS_SHA256", "not_applicable")}
    case_ids = set(getattr(args, "case_ids", None) or [])
    if case_ids:
        result["case_ids"] = sorted(case_ids)
    if any(case.kind == "rag" and case.inputs.get("generate")
           and (args.split == "all" or case.split == args.split)
           and (not case_ids or case.case_id in case_ids) for case in dataset.cases):
        result["rag_generation_prompt_sha256"] = digest(RAG_GENERATION_PROMPT)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Four-layer AIagent evaluation")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "data/cache/reports/evaluation")
    parser.add_argument("--repeat", type=int, choices=range(1, 11), default=1)
    parser.add_argument("--split", choices=("all", "dev", "regression", "heldout", "adversarial"), default="all")
    parser.add_argument("--case-id", dest="case_ids", action="append",
                        help="Run only these exact case IDs within the selected split; repeat the option as needed")
    parser.add_argument("--judge", choices=("none", "manual", "provider"), default="none")
    parser.add_argument("--manual", type=Path)
    parser.add_argument("--allow-provider", action="store_true")
    parser.add_argument("--allow-api", action="store_true")
    parser.add_argument("--judge-max-repairs", type=int, choices=(0, 1), default=1)
    parser.add_argument("--judge-request-budget", type=int)
    parser.add_argument("--judge-max-output-tokens", type=int, default=4096)
    parser.add_argument("--judge-verify-visual-gold", action="store_true",
                        help="Separate pixel review from a second text-only gold review; both share the request budget")
    parser.add_argument("--judge-thinking", choices=("default", "disabled"), default="default",
                        help="Explicitly disable thinking only on the official HTTPS DeepSeek judge endpoint")
    parser.add_argument("--judge-gold-kinds", type=Path,
                        help="Reviewed fact/behavior annotations; defaults to dataset sibling judge-gold-kinds.json")
    parser.add_argument("--debug-local", action="store_true",
                        help="Explicit local-only redacted answer and verdict artifacts (potentially sensitive)")
    parser.add_argument("--variant", default="default")
    parser.add_argument("--overrides", type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--max-drop", type=float, default=0)
    parser.add_argument("--release", action="store_true")
    args = parser.parse_args(argv)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    output = args.output.resolve() / run_id
    output.mkdir(parents=True, exist_ok=False)
    report = {"protocol": PROTOCOL, "run_id": run_id, "ok": False,
              "variant": args.variant, "results": [], "summary": {}, "local_debug_artifacts": args.debug_local}
    judge = None
    exit_code = 2
    try:
        dataset = Dataset.model_validate(read_json(args.dataset))
        requested_ids = set(args.case_ids or [])
        eligible = [case for case in dataset.cases if args.split == "all" or case.split == args.split]
        if not requested_ids <= {case.case_id for case in eligible}:
            raise ValueError("case IDs must exist within the selected split")
        if args.release and requested_ids:
            raise ValueError("case filtering is diagnostic only and cannot be used with --release")
        eligible = [case for case in eligible if not requested_ids or case.case_id in requested_ids]
        if not eligible:
            raise ValueError("no applicable cases")
        if args.judge == "provider" and not args.allow_provider:
            raise ValueError("provider judge requires --allow-provider")
        if args.judge == "manual" and args.manual is None:
            raise ValueError("manual verdict file required")
        kinds_path = args.judge_gold_kinds or args.dataset.resolve().parent / "judge-gold-kinds.json"
        kinds = read_json(kinds_path) if args.judge_gold_kinds or kinds_path.exists() else {}
        repairs = args.judge_max_repairs if args.judge == "provider" else 0
        semantic_count = sum(c.oracle.semantic for c in eligible) * args.repeat
        budget = args.judge_request_budget
        if budget is None:
            visual_count = sum(bool(c.oracle.semantic and (c.kind == "vision_api" or c.inputs.get("image")
                or any(step.get("image") for step in c.inputs.get("steps", [])))) for c in eligible) * args.repeat
            reviews = semantic_count + (visual_count if args.judge_verify_visual_gold else 0)
            budget = reviews * (1 + repairs) if args.judge == "provider" else 0
        judge = Judge(args.judge, args.manual, max_repairs=repairs, request_budget=budget,
                      gold_kinds=kinds, debug_directory=output / ".judge-debug" if args.debug_local else None,
                      max_output_tokens=args.judge_max_output_tokens, thinking_mode=args.judge_thinking,
                      verify_visual_gold=args.judge_verify_visual_gold)
        report["conditions"] = conditions(dataset, args, judge)
        report["code"] = code_identity()
        patches = read_json(args.overrides) if args.overrides else {}
        if not isinstance(patches, dict) or not set(patches) <= {c.case_id for c in dataset.cases}:
            raise ValueError("invalid override case IDs")
        report["overrides_sha256"] = digest(patches)
        selected = []
        for original in eligible:
            raw = original.model_dump(mode="json")
            patch = patches.get(original.case_id, {})
            if not isinstance(patch, dict) or not set(patch) <= set(INPUTS[original.kind].model_fields):
                raise ValueError("only known adapter input fields may be overridden")
            raw["inputs"].update(patch)
            case = type(original).model_validate(raw)
            params = validate_inputs(case)
            api = case.kind in {"api", "vision_api"} or (case.kind == "rag" and params.backend == "api")
            runtime_graph = case.kind == "graph" and params.driver == "runtime"
            paid = (case.kind == "persona" or (case.kind == "rag" and params.generate) or runtime_graph
                    or (case.kind in {"api", "vision_api"} and any(
                        step.get("path") in {"/chat", "/chat/multimodal", "/vision/analyze", "/vision/chat"}
                        for step in params.steps)))
            if (api or runtime_graph) and not args.allow_api:
                raise ValueError("live deployment access requires --allow-api")
            if paid and not args.allow_provider:
                raise ValueError("provider calls require --allow-provider")
            if api or runtime_graph:
                if not os.environ.get("EVAL_SUT_IDENTITY"):
                    raise ValueError("live deployment must specify EVAL_SUT_IDENTITY")
                if case.kind == "rag" and not os.environ.get("EVAL_CORPUS_SHA256"):
                    raise ValueError("live RAG requires corpus manifest SHA256")
            if case.oracle.semantic and args.judge == "none":
                raise ValueError("semantic case requires a judge")
            selected.append(case)
        if not selected:
            raise ValueError("no applicable cases")
        rows = []
        snapshot = {name: report[name] for name in ("protocol", "run_id", "variant", "conditions", "code",
                                                   "overrides_sha256")}
        snapshot["selected_cases"] = [{"case_id": case.case_id, "group_id": case.group_id} for case in selected]
        snapshot["planned_evaluations"] = len(selected) * args.repeat
        snapshot["complete"] = False
        with (output / "run.json").open("x", encoding="utf-8") as stream:
            json.dump(snapshot, stream, ensure_ascii=False, indent=2, allow_nan=False)
        # Keep completed, non-text results even if a later native call kills the process.
        with provider_session(), (output / "results.jsonl").open("x", encoding="utf-8") as journal:
            for case in selected:
                for iteration in range(args.repeat):
                    key = f"{case.case_id}@{iteration + 1}"
                    user = f"eval-{run_id.lower()}-{case.case_id}-{iteration + 1}"
                    row = evaluate_one(case, args.dataset.resolve().parent, user, judge, key, observe)
                    journal.write(row.model_dump_json() + "\n")
                    journal.flush()
                    rows.append(row)
        report["results"] = [row.model_dump(mode="json") for row in rows]
        report["summary"] = summarize(rows)
        report["ok"] = bool(rows) and all(row.status == "passed" for row in rows)
        if args.release:
            components = {row.domain for row in rows if row.layer == "component"}
            layers = {row.layer for row in rows}
            semantic_domains = {case.domain for case in selected if case.oracle.semantic}
            scopes = {row.scope for row in rows}
            report["release_coverage_ok"] = (
                components == {"rag", "memory", "vision", "persona"}
                and layers == {"component", "trajectory", "task"}
                and semantic_domains == {"rag", "memory", "vision", "persona"}
                and "real_image_api" in scopes and "isolated_api" in scopes
                and "isolated_graph_configured_providers" in scopes
            )
            report["ok"] = report["ok"] and report["release_coverage_ok"]
        if args.baseline:
            report["comparison"] = compare_reports(report, read_json(args.baseline), args.max_drop)
            report["ok"] = report["ok"] and report["comparison"]["ok"]
        exit_code = 0 if report["ok"] else 1
        if any(row.status in {"error", "judge_error"} for row in rows):
            exit_code = 2
    except Exception as exc:
        report["operational_error"] = type(exc).__name__
        if isinstance(exc, JudgeError):
            report["operational_diagnostic"] = {"stage": exc.stage, "code": exc.code}
        report["ok"] = False
    if judge is not None:
        report["judge_usage"] = {**judge.usage,
            "requests_without_usage": judge.usage["logical_requests"] - judge.usage["responses_with_usage"]}
    failures = [{"key": row["key"], "status": row["status"], "failures": row["failures"],
                 "error_type": row["error_type"], "error_code": row["error_code"], "error_stage": row["error_stage"],
                 "execution_diagnostic": row["execution_diagnostic"],
                 "judge_diagnostics": row["judge_diagnostics"]} for row in report["results"] if row["status"] != "passed"]
    if report.get("operational_error"):
        failures.append({"operational_error": report["operational_error"]})
    if report.get("release_coverage_ok") is False:
        failures.append({"release_coverage": "incomplete"})
    if report.get("comparison", {}).get("ok") is False:
        failures.append({"baseline_comparison": report["comparison"]})
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    (output / "failures.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in failures), encoding="utf-8")
    table = ["# AIagent 评测摘要", "", "| 分组 | 通过/总数 | 通过率 |", "| --- | --- | --- |"]
    for name, summary in report["summary"].items():
        table.append(f"| {name} | {summary['passed']}/{summary['total']} | {summary['pass_rate']:.4f} |")
    (output / "summary.md").write_text("\n".join(table) + "\n", encoding="utf-8")
    print(json.dumps({"ok": report["ok"], "exit_code": exit_code, "report": str(output / "report.json")}))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
