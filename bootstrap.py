import argparse
import json

from doctor import build_report
from processors.db import init_db


def summarize_report(report: dict):
    return {"failed_modules": [name for name, result in report.get("python_modules", {}).items() if not result.get("ok")], "failed_commands": [name for name, result in report.get("commands", {}).items() if not result.get("ok")], "warned_paths": [name for name, result in report.get("paths", {}).items() if not result.get("ok")], "summary_mode": report.get("summary_backend", {}).get("mode"), "summary_api_key_present": report.get("summary_backend", {}).get("api_key_present"), "live_test_ok": report.get("summary_backend_live_test", {}).get("ok") if report.get("summary_backend_live_test") else None}


def print_bootstrap_result(init_result: dict, report: dict):
    summary = summarize_report(report)
    print("Bootstrap Complete\n" + "=" * 72)
    print("Storage\n" + "-" * 72)
    for name, path in init_result["storage"].items():
        print(f"{name}: {path}")
    print(f"db_path: {init_result['db_path']}\n")
    print("Health Summary\n" + "-" * 72)
    print(f"summary_mode: {summary['summary_mode']}")
    print(f"summary_api_key_present: {summary['summary_api_key_present']}")
    if summary["live_test_ok"] is not None:
        print(f"summary_live_test_ok: {summary['live_test_ok']}")
    print("\nProblems\n" + "-" * 72)
    if not summary["failed_modules"] and not summary["failed_commands"] and not summary["warned_paths"]:
        print("No blocking problems found.")
    else:
        if summary["failed_modules"]:
            print("Missing Python modules:"); [print(f"- {item}") for item in summary["failed_modules"]]
        if summary["failed_commands"]:
            print("Missing system commands:"); [print(f"- {item}") for item in summary["failed_commands"]]
        if summary["warned_paths"]:
            print("Path warnings:"); [print(f"- {item}") for item in summary["warned_paths"]]
    print("\nTip\n" + "-" * 72)
    print("If this is a fresh setup, run:\n1. python doctor.py\n2. python doctor.py --live\n3. python ingest.py \"https://example.com\"")


def main():
    parser = argparse.ArgumentParser(description="Bootstrap collector environment")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    init_result = init_db(); report = build_report(run_live=args.live)
    payload = {"init": init_result, "doctor": report, "summary": summarize_report(report)}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2)); return
    print_bootstrap_result(init_result, report)


if __name__ == "__main__":
    main()
