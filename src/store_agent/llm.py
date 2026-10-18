"""大模型调用:OpenAI 兼容接口,无密钥/断网/报错时抛 LLMUnavailable,由上层走兜底模板。

环境变量(或 .env):LLM_API_KEY、LLM_BASE_URL(默认 https://api.openai.com/v1)、LLM_MODEL。
大模型只写文字,不算价格(价格由 pricing.py 完成)。
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import httpx

_ENV = Path(__file__).resolve().parents[2] / ".env"
TIMEOUT = float(os.environ.get("LLM_TIMEOUT", "40"))


class LLMUnavailable(RuntimeError):
    pass


def _load_dotenv() -> None:
    if not _ENV.exists():
        return
    for line in _ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()


def available() -> bool:
    return bool(os.environ.get("LLM_API_KEY")) and os.environ.get("FORCE_OFFLINE") != "1"


def chat(system: str, user: str, temperature: float = 0.4, retries: int = 1) -> str:
    """调用一次;失败自动重试 retries 次,仍失败抛 LLMUnavailable。"""
    if not available():
        raise LLMUnavailable("未配置 LLM_API_KEY 或已强制离线")
    base = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.environ.get("LLM_MODEL", "gpt-4o-mini")
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            r = httpx.post(
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {os.environ['LLM_API_KEY']}"},
                json={
                    "model": model,
                    "temperature": temperature,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                },
                timeout=TIMEOUT,
            )
            r.raise_for_status()
            text = r.json()["choices"][0]["message"]["content"]
            if not text or not text.strip():
                raise ValueError("模型返回空内容")
            return text.strip()
        except Exception as e:  # noqa: BLE001 - 任何失败都进入重试/兜底
            last = e
            if attempt < retries:
                time.sleep(1.0)
    raise LLMUnavailable(f"模型调用失败: {type(last).__name__}: {last}")
