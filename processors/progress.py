import json
from pathlib import Path

import httpx

from .utils import now_iso


def notify_event(event: str, payload: dict, notify_file: str = "", notify_webhook: str = ""):
    body = {
        "event": event,
        "time": now_iso(),
        **payload,
    }

    if notify_file:
        path = Path(notify_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")

    if notify_webhook:
        try:
            with httpx.Client(timeout=15, follow_redirects=True) as client:
                client.post(notify_webhook, json=body)
        except Exception as e:
            print(f"Webhook notify failed: {e}")


def make_progress_callback(notify_file: str = "", notify_webhook: str = "", base_payload: dict | None = None):
    base_payload = base_payload or {}

    def _callback(event: str, payload: dict | None = None):
        merged = dict(base_payload)
        if payload:
            merged.update(payload)
        notify_event(event, merged, notify_file, notify_webhook)

    return _callback
