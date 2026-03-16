import argparse
import json
import socket
import ssl
import urllib.request

from processors.utils import first_non_empty, get_env, load_config


def mask_secret(value: str | None, keep: int = 6) -> str:
    if not value:
        return "(empty)"
    if len(value) <= keep * 2:
        return value[:2] + "***"
    return value[:keep] + "..." + value[-keep:]


def resolve_summary_config():
    cfg = load_config()
    summary_cfg = cfg.get("summary", {})
    openai_cfg = summary_cfg.get("openai", {})
    env_api_key = get_env("OPENAI_API_KEY")
    env_base_url = get_env("OPENAI_BASE_URL")
    env_model = get_env("OPENAI_MODEL")
    api_key = first_non_empty(env_api_key, openai_cfg.get("api_key"))
    base_url = first_non_empty(env_base_url, openai_cfg.get("base_url"), "https://api.openai.com/v1")
    model = first_non_empty(env_model, openai_cfg.get("model"), "gpt-4o-mini")
    return {
        "enabled": summary_cfg.get("enabled", True),
        "mode": summary_cfg.get("mode", "local"),
        "fallback_to_local": summary_cfg.get("fallback_to_local", True),
        "api_key": api_key,
        "api_key_masked": mask_secret(api_key),
        "api_key_source": "env" if env_api_key else ("config" if openai_cfg.get("api_key") else "missing"),
        "base_url": base_url,
        "base_url_source": "env" if env_base_url else ("config" if openai_cfg.get("base_url") else "default"),
        "model": model,
        "model_source": "env" if env_model else ("config" if openai_cfg.get("model") else "default"),
        "temperature": openai_cfg.get("temperature", 0.2),
        "timeout_sec": openai_cfg.get("timeout_sec", 60),
    }


def test_connectivity(base_url: str) -> dict:
    """测试到 base_url 的网络连通性（TCP + TLS）"""
    from urllib.parse import urlparse
    parsed = urlparse(base_url)
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    result = {"host": host, "port": port}
    try:
        with socket.create_connection((host, port), timeout=10):
            result["tcp"] = "ok"
    except Exception as e:
        result["tcp"] = f"FAIL: {e}"
        return result
    if parsed.scheme == "https":
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        try:
            with socket.create_connection((host, port), timeout=10) as sock:
                with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                    result["tls"] = ssock.version()
        except Exception as e:
            result["tls"] = f"FAIL: {e}"
    return result


def test_api_call(api_key: str, base_url: str, model: str, timeout: int) -> dict:
    """发起最小测试请求，区分错误类型"""
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 5,
    }).encode()
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode()
            return {"status": r.status, "ok": True, "body": body[:200]}
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        status = e.code
        if status == 401:
            reason = "鉴权失败（API key 无效或已过期）"
        elif status == 403:
            reason = "权限不足"
        elif status == 404:
            reason = "接口路径不存在（base_url 或 model 可能有误）"
        elif status == 429:
            reason = "请求频率超限或余额不足"
        elif status >= 500:
            reason = "服务端错误"
        else:
            reason = f"HTTP {status}"
        return {"status": status, "ok": False, "reason": reason, "body": body[:200]}
    except urllib.error.URLError as e:
        return {"status": None, "ok": False, "reason": f"网络错误: {e.reason}"}
    except Exception as e:
        return {"status": None, "ok": False, "reason": f"未知错误: {type(e).__name__}: {e}"}


def main():
    parser = argparse.ArgumentParser(description="检查摘要后端配置并可选发起测试请求")
    parser.add_argument("--test", action="store_true", help="发起一次最小 API 测试请求")
    parser.add_argument("--json", action="store_true", help="以 JSON 格式输出")
    args = parser.parse_args()

    cfg = resolve_summary_config()
    report = {
        "summary_mode": cfg["mode"],
        "enabled": cfg["enabled"],
        "fallback_to_local": cfg["fallback_to_local"],
        "api_key_present": bool(cfg["api_key"]),
        "api_key_masked": cfg["api_key_masked"],
        "api_key_source": cfg["api_key_source"],
        "base_url": cfg["base_url"],
        "base_url_source": cfg["base_url_source"],
        "model": cfg["model"],
        "model_source": cfg["model_source"],
    }

    if args.test:
        if not cfg["api_key"]:
            report["connectivity"] = "跳过（无 API key）"
            report["api_test"] = "跳过（无 API key）"
        else:
            report["connectivity"] = test_connectivity(cfg["base_url"])
            report["api_test"] = test_api_call(
                cfg["api_key"], cfg["base_url"], cfg["model"], cfg["timeout_sec"]
            )

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    print(f"摘要模式:     {report['summary_mode']}")
    print(f"已启用:       {report['enabled']}")
    print(f"失败回退本地: {report['fallback_to_local']}")
    print(f"API key:      {report['api_key_masked']}  [{report['api_key_source']}]")
    print(f"base_url:     {report['base_url']}  [{report['base_url_source']}]")
    print(f"model:        {report['model']}  [{report['model_source']}]")
    if "connectivity" in report:
        print(f"连通性:       {report['connectivity']}")
    if "api_test" in report:
        t = report["api_test"]
        if isinstance(t, dict):
            if t.get("ok"):
                print(f"API 测试:     [OK] 成功 (HTTP {t['status']})")
            else:
                print(f"API 测试:     [FAIL] {t.get('reason', '')}  body: {t.get('body', '')[:100]}")
        else:
            print(f"API 测试:     {t}")


if __name__ == "__main__":
    main()
