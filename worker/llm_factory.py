"""大语言模型工厂及 OpenAI 兼容流式客户端。"""

from __future__ import annotations

import json
import os
import time
from typing import AsyncIterator

import httpx

_DEFAULT_TIMEOUT_S = 30.0
_DEFAULT_MAX_TOKENS = 2048

OPENAI_COMPAT_DEEPSEEK = "https://api.deepseek.com"
OPENAI_COMPAT_MINIMAX = "https://api.minimaxi.com"
OPENAI_COMPAT_MIMO = "https://token-plan-cn.xiaomimimo.com/v1"

MODEL_DEEPSEEK_CHAT = "deepseek-chat"
MODEL_MINIMAX_HS = "MiniMax-M2.7-highspeed"
MODEL_MIMO = "mimo-v2.5"


class OpenAICompatChatStream:
    """为 OpenAI 兼容 Chat Completions API 提供统一的 SSE 客户端。"""

    def __init__(
        self,
        api_key: str,
        *,
        model: str,
        base_url: str,
        provider_name: str,
        auth_header: str = "Authorization",
        auth_prefix: str = "Bearer ",
        completion_path: str = "/v1/chat/completions",
        timeout_s: float = _DEFAULT_TIMEOUT_S,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
        max_tokens_field: str = "max_tokens",
        content_fields: tuple[str, ...] = ("content",),
    ) -> None:
        self.api_key = api_key.strip()
        self.model = model.strip()
        self.base_url = base_url.rstrip("/")
        self.provider_name = provider_name
        self.auth_header = auth_header
        self.auth_prefix = auth_prefix
        self.completion_path = completion_path
        self.timeout_s = timeout_s
        self.max_tokens = max_tokens
        self.max_tokens_field = max_tokens_field
        self.content_fields = content_fields
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        """延迟创建 HTTP 客户端，避免模块导入时建立外部连接。"""
        if self._client is None or self._client.is_closed:
            timeout = httpx.Timeout(
                timeout=self.timeout_s,
                connect=min(self.timeout_s, 10.0),
            )
            self._client = httpx.AsyncClient(
                timeout=timeout,
                trust_env=False,
                http2=False,
                limits=httpx.Limits(max_connections=5, max_keepalive_connections=2),
            )
        return self._client

    def _validate(self) -> None:
        """在发起请求前检查必要配置，避免无凭证请求产生模糊错误。"""
        if not self.api_key:
            raise RuntimeError(f"{self.provider_name} API Key 未配置")
        if not self.model:
            raise RuntimeError(f"{self.provider_name} 模型未配置")
        if not self.base_url.startswith(("http://", "https://")):
            raise RuntimeError(f"{self.provider_name} Base URL 无效")

    def chat(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        """返回逐片段输出的异步迭代器。"""
        return self._stream(messages, temperature)

    async def _stream(
        self,
        messages: list[dict],
        temperature: float,
    ) -> AsyncIterator[str]:
        """调用 Chat Completions SSE 接口并产出文本片段。"""
        self._validate()
        headers = {
            self.auth_header: f"{self.auth_prefix}{self.api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "temperature": temperature,
            self.max_tokens_field: self.max_tokens,
        }
        client = self._get_client()
        started_at = time.time()
        first_token = True

        async with client.stream(
            "POST",
            f"{self.base_url}{self.completion_path}",
            headers=headers,
            json=payload,
        ) as response:
            if response.status_code != 200:
                body = (await response.aread()).decode("utf-8", errors="ignore")
                raise RuntimeError(
                    f"{self.provider_name} HTTP {response.status_code}: {body[:500]}"
                )

            async for line in response.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line[len("data:") :].strip()
                if data == "[DONE]":
                    break
                try:
                    event = json.loads(data)
                except json.JSONDecodeError:
                    continue
                choices = event.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                piece = next(
                    (delta.get(field) for field in self.content_fields if delta.get(field)),
                    None,
                )
                if not piece:
                    continue
                if first_token:
                    elapsed_ms = int((time.time() - started_at) * 1000)
                    print(
                        f"[timing] llm_provider={self.provider_name} "
                        f"llm_ttfb={elapsed_ms}ms",
                        flush=True,
                    )
                    first_token = False
                yield str(piece)


class DeepSeekChatStream(OpenAICompatChatStream):
    """DeepSeek Chat 流式客户端。"""

    def __init__(
        self,
        api_key: str,
        *,
        model: str = MODEL_DEEPSEEK_CHAT,
        base_url: str = OPENAI_COMPAT_DEEPSEEK,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
    ) -> None:
        super().__init__(
            api_key,
            model=model,
            base_url=base_url,
            provider_name="DeepSeek",
            timeout_s=timeout_s,
            max_tokens=max_tokens,
        )


class MiniMaxChatStream(OpenAICompatChatStream):
    """MiniMax M2.7-highspeed 流式客户端。"""

    def __init__(
        self,
        api_key: str,
        *,
        model: str = MODEL_MINIMAX_HS,
        base_url: str = OPENAI_COMPAT_MINIMAX,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
    ) -> None:
        super().__init__(
            api_key,
            model=model,
            base_url=base_url,
            provider_name="MiniMax",
            timeout_s=timeout_s,
            max_tokens=max_tokens,
            content_fields=("content", "reasoning_content"),
        )


class MiMoChatStream(OpenAICompatChatStream):
    """小米 MiMo Token Plan 流式客户端。"""

    def __init__(
        self,
        api_key: str,
        *,
        model: str = MODEL_MIMO,
        base_url: str = OPENAI_COMPAT_MIMO,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
    ) -> None:
        super().__init__(
            api_key,
            model=model,
            base_url=base_url,
            provider_name="MiMo",
            auth_header="api-key",
            auth_prefix="",
            completion_path="/chat/completions",
            timeout_s=timeout_s,
            max_tokens=max_tokens,
            max_tokens_field="max_completion_tokens",
        )


def build_llm_provider(provider: str | None = None):
    """根据环境变量返回对应的大语言模型实例与模型信息。"""
    selected = (provider or os.getenv("LLM_PROVIDER", "mimo")).strip().lower()
    if selected in ("gemini", "google"):
        from livekit.plugins import google

        model = os.getenv("LLM_MODEL", "gemini-2.5-flash")
        return {
            "kind": "google_live",
            "obj": google.LLM(
                model=model,
                api_key=os.getenv("GOOGLE_API_KEY", ""),
                temperature=0.7,
            ),
            "model": model,
        }
    if selected == "deepseek":
        model = os.getenv("DEEPSEEK_MODEL", MODEL_DEEPSEEK_CHAT)
        return {
            "kind": "deepseek",
            "obj": DeepSeekChatStream(
                api_key=os.getenv("DEEPSEEK_API_KEY", ""),
                model=model,
            ),
            "model": model,
        }
    if selected in ("minimax", "minimax_m27", "minimax-hs"):
        model = os.getenv("MINIMAX_MODEL_NAME", MODEL_MINIMAX_HS)
        return {
            "kind": "minimax",
            "obj": MiniMaxChatStream(
                api_key=os.getenv("MINIMAX_API_KEY", ""),
                model=model,
            ),
            "model": model,
        }
    if selected in ("mimo", "xiaomi"):
        model = os.getenv("MIMO_LLM_MODEL", MODEL_MIMO)
        return {
            "kind": "mimo",
            "obj": MiMoChatStream(
                api_key=os.getenv("MIMO_LLM_API_KEY", ""),
                model=model,
                base_url=os.getenv("MIMO_LLM_BASE_URL", OPENAI_COMPAT_MIMO),
                max_tokens=int(os.getenv("MIMO_LLM_MAX_TOKENS", "2048")),
            ),
            "model": model,
        }
    raise ValueError(f"未知的 LLM_PROVIDER: {selected!r}")


if __name__ == "__main__":
    import asyncio

    async def _self_test() -> None:
        """使用当前 provider 做一次手工连通性检查。"""
        provider = build_llm_provider()
        print(f"[llm_factory] kind={provider['kind']} model={provider['model']}")
        if provider["kind"] == "google_live":
            print("[llm_factory] google.LLM 由 LiveKit 包装，跳过独立检查")
            return
        started_at = time.time()
        chunks = []
        async for chunk in provider["obj"].chat(
            [{"role": "user", "content": "用一句话介绍你自己"}],
            temperature=0.7,
        ):
            chunks.append(chunk)
        print(
            f"[llm_factory] {provider['kind']} elapsed="
            f"{time.time() - started_at:.2f}s chunks={len(chunks)}"
        )
        print("output:", "".join(chunks)[:200])

    asyncio.run(_self_test())
