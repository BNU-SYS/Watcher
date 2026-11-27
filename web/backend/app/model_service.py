"""Validation and connectivity checks for the browser-supplied model config."""

from __future__ import annotations

import time

import httpx
from fastapi import HTTPException


def normalize_base_url(value: str) -> str:
    value = (value or "").strip().rstrip("/")
    suffix = "/chat/completions"
    if value.lower().endswith(suffix):
        value = value[: -len(suffix)].rstrip("/")
    if not value:
        raise HTTPException(status_code=400, detail="请填写模型 API 根地址")
    try:
        url = httpx.URL(value)
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=422, detail="API 根地址格式不正确") from None
    if (
        url.scheme not in ("http", "https")
        or not url.host
        or url.userinfo
        or url.query
        or url.fragment
    ):
        raise HTTPException(
            status_code=422,
            detail="API 根地址必须是 http(s) 地址，且不能包含账号、查询参数或片段",
        )
    return value


def check_model_config(base_url: str, model: str, api_key: str) -> dict:
    base_url = normalize_base_url(base_url)
    model = (model or "").strip()
    api_key = (api_key or "").strip()
    if not model:
        raise HTTPException(status_code=400, detail="请填写模型名称")
    if not api_key:
        raise HTTPException(status_code=400, detail="请填写 API Key")
    if len(model) > 128 or len(api_key) > 512:
        raise HTTPException(status_code=400, detail="模型名称或 API Key 过长")
    return {"base_url": base_url, "model": model, "api_key": api_key}


def _provider_error(response: httpx.Response, api_key: str) -> str:
    """Return a short provider message without echoing request data or secrets."""
    try:
        data = response.json()
    except ValueError:
        data = None
    text = ""
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict):
            text = "：".join(
                str(error[key]) for key in ("code", "type", "message") if error.get(key)
            )
        elif error:
            text = str(error)
        if not text:
            for key in ("detail", "message", "msg", "error_msg"):
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    text = value
                    break
                if isinstance(value, list) and value:
                    text = "；".join(str(item) for item in value)
                    break
    if not text:
        try:
            text = response.text
        except Exception:  # noqa: BLE001 - diagnostics must never break the check
            text = ""
    text = " ".join(text.split())[:240]
    if api_key and len(api_key) > 4:
        text = text.replace(api_key, "***")
    return text


async def verify_model(base_url: str, model: str, api_key: str) -> dict:
    config = check_model_config(base_url, model, api_key)
    endpoint = config["base_url"] + "/chat/completions"
    # Match the detector's ChatModel payload. Some providers reject max_tokens
    # (for example reasoning models that require max_completion_tokens), which
    # turned a harmless connectivity test into HTTP 400.
    payload = {
        "model": config["model"],
        "messages": [
            {
                "role": "system",
                "content": "You are a connectivity tester. Reply with OK.",
            },
            {"role": "user", "content": "ping"},
        ],
    }
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=False) as client:
            response = await client.post(
                endpoint,
                json=payload,
                headers={"Authorization": f"Bearer {config['api_key']}"},
            )
    except httpx.TimeoutException:
        return {"ok": False, "latency_ms": 0, "message": "请求超时，请检查网络与服务地址"}
    except httpx.HTTPError:
        return {"ok": False, "latency_ms": 0, "message": "无法连接到模型服务"}
    latency = int((time.perf_counter() - started) * 1000)
    if response.status_code != 200:
        detail = _provider_error(response, config["api_key"])
        message = f"服务返回 HTTP {response.status_code}"
        message += f"：{detail}" if detail else "，请检查模型名、根地址和接口兼容性"
        return {"ok": False, "latency_ms": latency, "message": message}
    try:
        choice = response.json()["choices"][0]
        message = choice["message"]
        reason = choice["finish_reason"]
        content = message.get("content")
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        return {
            "ok": False,
            "latency_ms": latency,
            "message": "响应不是有效的 Chat Completions 格式",
        }
    if reason != "stop" or message.get("refusal"):
        return {
            "ok": False,
            "latency_ms": latency,
            "message": "模型拒绝了请求或回复不完整",
        }
    if not isinstance(content, str) or not content.strip():
        return {
            "ok": False,
            "latency_ms": latency,
            "message": "模型没有返回有效文本",
        }
    return {"ok": True, "latency_ms": latency, "message": "连接成功，模型已响应"}
