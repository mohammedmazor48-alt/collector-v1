import argparse
import importlib
import json
import shutil
import subprocess
from pathlib import Path

from processors.utils import first_non_empty, get_env, load_config, resolve_tool_path


def check_python_module(module_name: str):
    try:
        importlib.import_module(module_name)
        return {"ok": True, "message": "installed"}
    except Exception as e:
        return {"ok": False, "message": str(e)}


def check_command(cmd: list[str], success_hint: str = ""):
    exe = resolve_tool_path(cmd[0])
    resolved_cmd = list(cmd)
    resolved_cmd[0] = exe
    if not Path(exe).exists() and shutil.which(exe) is None:
        return {"ok": False, "message": f"command not found: {cmd[0]}", "hint": success_hint}
    try:
        result = subprocess.run(resolved_cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)
        ok = result.returncode == 0
        output = (result.stdout or result.stderr or "").strip()
        return {"ok": ok, "message": output[:500] if output else "ok", "hint": success_hint}
    except Exception as e:
        return {"ok": False, "message": str(e), "hint": success_hint}


def check_paths():
    cfg = load_config(); storage = cfg.get("storage", {}); db_cfg = cfg.get("database", {})
    base_dir = Path(storage.get("base_dir", "./knowledge-vault")); raw_dir = base_dir / storage.get("raw_dir", "raw"); notes_dir = base_dir / storage.get("notes_dir", "notes"); meta_dir = base_dir / storage.get("meta_dir", "meta"); assets_dir = base_dir / storage.get("assets_dir", "assets"); logs_dir = base_dir / storage.get("logs_dir", "logs"); db_path = Path(db_cfg.get("path", "./knowledge-vault/index.sqlite"))
    items = {"base_dir": base_dir, "raw_dir": raw_dir, "notes_dir": notes_dir, "meta_dir": meta_dir, "assets_dir": assets_dir, "logs_dir": logs_dir, "db_path_parent": db_path.parent}
    result = {name: {"ok": path.exists(), "path": str(path), "message": "exists" if path.exists() else "missing"} for name, path in items.items()}
    result["db_path"] = {"ok": True, "path": str(db_path), "message": "configured"}
    return result


def check_summary_backend_config():
    cfg = load_config(); summary_cfg = cfg.get("summary", {}); openai_cfg = summary_cfg.get("openai", {})
    return {"enabled": summary_cfg.get("enabled", True), "mode": summary_cfg.get("mode", "local"), "fallback_to_local": summary_cfg.get("fallback_to_local", True), "api_key_present": bool(first_non_empty(get_env("OPENAI_API_KEY"), openai_cfg.get("api_key"))), "api_key_source": "env" if get_env("OPENAI_API_KEY") else ("config" if openai_cfg.get("api_key") else "missing"), "base_url": first_non_empty(get_env("OPENAI_BASE_URL"), openai_cfg.get("base_url"), "https://api.openai.com/v1"), "model": first_non_empty(get_env("OPENAI_MODEL"), openai_cfg.get("model"), "gpt-4o-mini")}


def run_live_summary_test():
    cfg = load_config(); summary_cfg = cfg.get("summary", {}); mode = summary_cfg.get("mode", "local")
    if mode != "openai":
        return {"ok": True, "skipped": True, "message": f"summary.mode={mode}, skipped remote test"}
    try:
        from openai import OpenAI
        openai_cfg = summary_cfg.get("openai", {})
        api_key = first_non_empty(get_env("OPENAI_API_KEY"), openai_cfg.get("api_key"))
        base_url = first_non_empty(get_env("OPENAI_BASE_URL"), openai_cfg.get("base_url"), "https://api.openai.com/v1")
        model = first_non_empty(get_env("OPENAI_MODEL"), openai_cfg.get("model"), "gpt-4o-mini")
        if not api_key:
            return {"ok": False, "skipped": False, "message": "missing OPENAI_API_KEY / summary.openai.api_key"}
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=openai_cfg.get("timeout_sec", 60))
        resp = client.chat.completions.create(model=model, temperature=0, response_format={"type": "json_object"}, messages=[{"role": "system", "content": "你是一个测试助手，只输出合法 JSON。"}, {"role": "user", "content": '{"ok": true, "message": "doctor works"}'}])
        data = json.loads(resp.choices[0].message.content.strip())
        return {"ok": bool(data.get("ok")), "skipped": False, "message": json.dumps(data, ensure_ascii=False)}
    except Exception as e:
        return {"ok": False, "skipped": False, "message": str(e)}


def build_report(run_live: bool = False):
    report = {"python_modules": {"yaml": check_python_module("yaml"), "httpx": check_python_module("httpx"), "bs4": check_python_module("bs4"), "trafilatura": check_python_module("trafilatura"), "slugify": check_python_module("slugify"), "fitz": check_python_module("fitz"), "pytesseract": check_python_module("pytesseract"), "PIL": check_python_module("PIL"), "faster_whisper": check_python_module("faster_whisper"), "openai": check_python_module("openai")}, "commands": {"ffmpeg": check_command(["ffmpeg", "-version"], "Install ffmpeg and ensure it is in PATH"), "tesseract": check_command(["tesseract", "--version"], "Install Tesseract OCR and ensure it is in PATH"), "pdftoppm": check_command(["pdftoppm", "-h"], "Install Poppler and ensure pdftoppm is in PATH")}, "paths": check_paths(), "summary_backend": check_summary_backend_config()}
    if run_live:
        report["summary_backend_live_test"] = run_live_summary_test()
    return report


def print_human(report: dict):
    print("Collector Doctor\n" + "=" * 72)
    print("Python Modules\n" + "-" * 72)
    for name, result in report["python_modules"].items():
        print(f"[{'OK' if result['ok'] else 'FAIL'}] {name}: {result['message']}")
    print("\nCommands\n" + "-" * 72)
    for name, result in report["commands"].items():
        print(f"[{'OK' if result['ok'] else 'FAIL'}] {name}: {result['message']}")
        if result.get("hint"):
            print(f"       hint: {result['hint']}")
    print("\nPaths\n" + "-" * 72)
    for name, result in report["paths"].items():
        print(f"[{'OK' if result['ok'] else 'WARN'}] {name}: {result['path']} ({result['message']})")
    print("\nSummary Backend\n" + "-" * 72)
    sb = report["summary_backend"]
    for k in ["enabled", "mode", "fallback_to_local", "api_key_present", "api_key_source", "base_url", "model"]:
        print(f"{k}: {sb[k]}")
    if "summary_backend_live_test" in report:
        lt = report["summary_backend_live_test"]
        print("\nSummary Backend Live Test\n" + "-" * 72)
        print(f"ok: {lt['ok']}\nskipped: {lt['skipped']}\nmessage: {lt['message']}")


def main():
    parser = argparse.ArgumentParser(description="Doctor check for collector environment")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    report = build_report(run_live=args.live)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2)); return
    print_human(report)


if __name__ == "__main__":
    main()
