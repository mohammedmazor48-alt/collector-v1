import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CLOUD_DIR = Path(__file__).resolve().parent
PYTHON = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"


def load_local_env():
    env_path = CLOUD_DIR / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_local_env()

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "uploads")
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "30"))


def require_env():
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")
    if not PYTHON.exists():
        raise RuntimeError(f"Python not found: {PYTHON}")


def headers():
    return {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }


def log_task(task_id: str, level: str, message: str):
    payload = {"task_id": task_id, "level": level, "message": message}
    try:
        httpx.post(
            f"{SUPABASE_URL}/rest/v1/task_logs",
            headers=headers(),
            content=json.dumps(payload),
            timeout=20,
        )
    except Exception:
        pass


def fetch_pending_task():
    url = (
        f"{SUPABASE_URL}/rest/v1/tasks"
        "?status=eq.pending"
        "&order=priority.asc,created_at.asc"
        "&limit=1"
    )
    resp = httpx.get(url, headers=headers(), timeout=20)
    resp.raise_for_status()
    rows = resp.json()
    return rows[0] if rows else None


def update_task(task_id: str, patch: dict):
    url = f"{SUPABASE_URL}/rest/v1/tasks?id=eq.{task_id}"
    resp = httpx.patch(
        url,
        headers=headers() | {"Prefer": "return=representation"},
        content=json.dumps(patch),
        timeout=20,
    )
    resp.raise_for_status()
    rows = resp.json()
    return rows[0] if rows else None


def claim_task(task: dict):
    return update_task(task["id"], {"status": "processing"})


def run_command(args: list[str]):
    return subprocess.run(
        args,
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def download_storage_file(storage_path: str, target_path: Path):
    target_path.parent.mkdir(parents=True, exist_ok=True)
    url = f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{storage_path}"
    with httpx.stream("GET", url, headers=headers(), timeout=300) as resp:
        resp.raise_for_status()
        with open(target_path, "wb") as f:
            for chunk in resp.iter_bytes():
                if chunk:
                    f.write(chunk)


def normalize_tags(task: dict):
    tags = task.get("tags") or []
    if isinstance(tags, str):
        return [t.strip() for t in tags.split(",") if t.strip()]
    if isinstance(tags, list):
        return [str(t).strip() for t in tags if str(t).strip()]
    return []


def handle_web_url(task: dict):
    cmd = [str(PYTHON), "ingest.py", task["source_url"]]
    if task.get("title"):
        cmd.extend(["--title", task["title"]])
    tags = normalize_tags(task)
    if tags:
        cmd.extend(["--tags", ",".join(tags)])
    return run_command(cmd)


def handle_remote_file(task: dict):
    cmd = [str(PYTHON), "ingest_remote.py", task["source_url"]]
    if task.get("title"):
        cmd.extend(["--title", task["title"]])
    tags = normalize_tags(task)
    if tags:
        cmd.extend(["--tags", ",".join(tags)])
    return run_command(cmd)


def handle_uploaded_file(task: dict):
    storage_path = task["storage_path"]
    incoming_dir = PROJECT_ROOT / "knowledge-vault" / "raw" / "incoming"
    incoming_dir.mkdir(parents=True, exist_ok=True)
    filename = Path(storage_path).name
    local_path = incoming_dir / filename
    download_storage_file(storage_path, local_path)

    cmd = [str(PYTHON), "ingest.py", str(local_path)]
    if task.get("title"):
        cmd.extend(["--title", task["title"]])
    tags = normalize_tags(task)
    if tags:
        cmd.extend(["--tags", ",".join(tags)])
    return run_command(cmd)


def parse_result(stdout: str):
    result = {}
    for line in stdout.splitlines():
        if line.startswith("id: "):
            result["result_doc_id"] = line.replace("id: ", "", 1).strip()
        elif line.startswith("note: "):
            result["result_note_path"] = line.replace("note: ", "", 1).strip()
        elif line.startswith("meta: "):
            result["result_meta_path"] = line.replace("meta: ", "", 1).strip()
    return result


def process_task(task: dict):
    task_type = task["task_type"]
    if task_type == "web_url":
        return handle_web_url(task)
    if task_type == "remote_file":
        return handle_remote_file(task)
    if task_type == "uploaded_file":
        return handle_uploaded_file(task)
    raise ValueError(f"Unsupported task_type: {task_type}")


def run_once():
    task = fetch_pending_task()
    if not task:
        print("No pending tasks.")
        return False

    claimed = claim_task(task)
    if not claimed or claimed.get("status") != "processing":
        print("Failed to claim task.")
        return False

    task_id = task["id"]
    log_task(task_id, "info", "Task claimed")

    try:
        result = process_task(task)
        if result.returncode == 0:
            parsed = parse_result(result.stdout)
            patch = {"status": "done", "error_message": None, **parsed}
            update_task(task_id, patch)
            log_task(task_id, "info", "Task completed successfully")
            print(result.stdout)
        else:
            err = (result.stderr or result.stdout or "")[-4000:]
            update_task(task_id, {"status": "failed", "error_message": err})
            log_task(task_id, "error", "Task failed")
            print(result.stdout)
            print(result.stderr, file=sys.stderr)
        return True
    except Exception as e:
        update_task(task_id, {"status": "failed", "error_message": str(e)})
        log_task(task_id, "error", f"Unhandled exception: {e}")
        raise


def main():
    require_env()
    loop = "--loop" in sys.argv

    if not loop:
        run_once()
        return

    print(f"Polling tasks every {POLL_INTERVAL_SECONDS}s ...")
    while True:
        try:
            run_once()
        except Exception as e:
            print(f"poll error: {e}", file=sys.stderr)
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
