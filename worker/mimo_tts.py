"""小米 MiMo VoiceClone 的 LiveKit TTS 适配器。"""

from __future__ import annotations

import base64
import binascii
import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator

import httpx
from livekit.agents import APIConnectionError, APIError, APIStatusError, APITimeoutError, tts
from livekit.agents.types import APIConnectOptions, DEFAULT_API_CONNECT_OPTIONS
from livekit.agents.tts import ChunkedStream, TTS

MIMO_TTS_BASE_URL = "https://api.xiaomimimo.com/v1"
MIMO_TTS_MODEL = "mimo-v2.5-tts-voiceclone"
MIMO_TTS_SAMPLE_RATE = 24000
_MAX_VOICE_DATA_URI_BYTES = 10 * 1024 * 1024


@dataclass(frozen=True)
class MiMoTTSOptions:
    """保存 MiMo TTS 请求所需的不可变配置。"""

    api_key: str
    base_url: str
    model: str
    voice_data_uri: str
    style_prompt: str
    sample_rate: int = MIMO_TTS_SAMPLE_RATE
    num_channels: int = 1


def load_voice_data_uri(voice_file: Path) -> str:
    """读取 WAV/MP3 参考音频，并转换为官方要求的 Data URI。"""
    resolved = voice_file.expanduser().resolve()
    if not resolved.is_file():
        raise RuntimeError(f"MiMo TTS 参考音频不存在: {resolved}")

    mime_type = {".wav": "audio/wav", ".mp3": "audio/mpeg"}.get(
        resolved.suffix.lower()
    )
    if mime_type is None:
        raise RuntimeError("MiMo TTS 参考音频仅支持 WAV 或 MP3")

    encoded = base64.b64encode(resolved.read_bytes()).decode("ascii")
    data_uri = f"data:{mime_type};base64,{encoded}"
    if len(data_uri.encode("ascii")) > _MAX_VOICE_DATA_URI_BYTES:
        raise RuntimeError("MiMo TTS 参考音频 Base64 编码后超过 10 MB")
    return data_uri


class MiMoVoiceCloneTTS(TTS):
    """将 MiMo VoiceClone Chat Completions 接口适配为 LiveKit TTS。"""

    def __init__(
        self,
        *,
        api_key: str,
        voice_file: Path,
        base_url: str = MIMO_TTS_BASE_URL,
        model: str = MIMO_TTS_MODEL,
        style_prompt: str = "",
        sample_rate: int = MIMO_TTS_SAMPLE_RATE,
    ) -> None:
        api_key = api_key.strip()
        base_url = base_url.rstrip("/")
        model = model.strip()
        if not api_key:
            raise RuntimeError("MIMO_TTS_API_KEY 未配置")
        if not base_url.startswith(("http://", "https://")):
            raise RuntimeError("MIMO_TTS_BASE_URL 无效")
        if not model:
            raise RuntimeError("MIMO_TTS_MODEL 未配置")

        # VoiceClone 暂无真正的低延迟流式推理，由 LiveKit 按句适配非流式 TTS。
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False),
            sample_rate=sample_rate,
            num_channels=1,
        )
        self._opts = MiMoTTSOptions(
            api_key=api_key,
            base_url=base_url,
            model=model,
            voice_data_uri=load_voice_data_uri(voice_file),
            style_prompt=style_prompt.strip(),
            sample_rate=sample_rate,
        )
        self._client: httpx.AsyncClient | None = None

    @property
    def provider(self) -> str:
        """返回用于日志和监控的 provider 名称。"""
        return "Xiaomi MiMo"

    @property
    def model(self) -> str:
        """返回当前使用的 TTS 模型。"""
        return self._opts.model

    def synthesize(
        self,
        text: str,
        *,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> ChunkedStream:
        """为一段已切分文本创建合成任务。"""
        return _MiMoChunkedStream(tts=self, input_text=text, conn_options=conn_options)

    def _get_client(self) -> httpx.AsyncClient:
        """延迟创建可复用的异步 HTTP 客户端。"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(120.0, connect=15.0),
                trust_env=False,
                http2=False,
                limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
            )
        return self._client

    async def aclose(self) -> None:
        """关闭底层 HTTP 连接池。"""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    def _build_payload(self, text: str) -> dict:
        """构建符合 MiMo VoiceClone 文档的 Chat Completions 请求。"""
        messages = []
        if self._opts.style_prompt:
            messages.append({"role": "user", "content": self._opts.style_prompt})
        messages.append({"role": "assistant", "content": text})
        return {
            "model": self._opts.model,
            "messages": messages,
            "audio": {"format": "pcm16", "voice": self._opts.voice_data_uri},
            "stream": True,
        }

    async def iter_audio(self, text: str) -> AsyncIterator[tuple[str, bytes]]:
        """请求 MiMo，并兼容解析 SSE 或单个 JSON 响应中的音频。"""
        stripped = text.strip()
        if not stripped:
            raise APIError("MiMo TTS 收到空文本")

        headers = {
            "api-key": self._opts.api_key,
            "Content-Type": "application/json",
            "Accept": "text/event-stream, application/json",
        }
        started_at = time.time()
        try:
            async with self._get_client().stream(
                "POST",
                f"{self._opts.base_url}/chat/completions",
                headers=headers,
                json=self._build_payload(stripped),
            ) as response:
                request_id = response.headers.get("x-request-id") or f"mimo-{uuid.uuid4()}"
                if response.status_code != 200:
                    body = (await response.aread()).decode("utf-8", errors="ignore")
                    raise APIStatusError(
                        message=f"MiMo TTS HTTP {response.status_code}: {body[:500]}",
                        status_code=response.status_code,
                        request_id=request_id,
                        body=body[:2000],
                    )

                content_type = response.headers.get("content-type", "").lower()
                chunks = 0
                total_bytes = 0
                first_audio_at: float | None = None
                last_audio_at: float | None = None
                max_chunk_gap_ms = 0.0
                if "text/event-stream" in content_type:
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[len("data:") :].strip()
                        if not data or data == "[DONE]":
                            continue
                        audio_bytes = self._decode_event_audio(data)
                        if audio_bytes:
                            received_at = time.time()
                            if last_audio_at is not None:
                                max_chunk_gap_ms = max(
                                    max_chunk_gap_ms,
                                    (received_at - last_audio_at) * 1000,
                                )
                            chunks += 1
                            total_bytes += len(audio_bytes)
                            first_audio_at = first_audio_at or received_at
                            last_audio_at = received_at
                            yield request_id, audio_bytes
                else:
                    raw = await response.aread()
                    audio_bytes = self._decode_event_audio(raw.decode("utf-8", errors="ignore"))
                    if audio_bytes:
                        chunks = 1
                        total_bytes = len(audio_bytes)
                        first_audio_at = time.time()
                        last_audio_at = first_audio_at
                        yield request_id, audio_bytes

                if total_bytes == 0:
                    raise APIError("MiMo TTS 返回成功，但响应中没有音频")
                elapsed_ms = (time.time() - started_at) * 1000
                ttfb_ms = ((first_audio_at or time.time()) - started_at) * 1000
                print(
                    f"[mimo_tts] ok model={self._opts.model} total={elapsed_ms:.0f}ms "
                    f"ttfb={ttfb_ms:.0f}ms text_len={len(stripped)} "
                    f"chunks={chunks} max_chunk_gap={max_chunk_gap_ms:.0f}ms "
                    f"bytes={total_bytes}",
                    flush=True,
                )
        except httpx.TimeoutException as exc:
            raise APITimeoutError() from exc
        except (APIStatusError, APIError):
            raise
        except httpx.HTTPError as exc:
            raise APIConnectionError(f"MiMo TTS 网络错误: {exc!r}") from exc

    @staticmethod
    def _decode_event_audio(raw_json: str) -> bytes:
        """从 Chat Completions 的 message 或 delta 字段提取 Base64 音频。"""
        try:
            event = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            raise APIError(f"MiMo TTS 返回无效 JSON: {raw_json[:300]}") from exc

        choices = event.get("choices") or []
        if not choices:
            return b""
        choice = choices[0]
        container = choice.get("delta") or choice.get("message") or {}
        audio = container.get("audio") or {}
        audio_data = audio.get("data") if isinstance(audio, dict) else None
        if not audio_data:
            return b""
        try:
            return base64.b64decode(audio_data, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise APIError("MiMo TTS 返回的音频 Base64 无效") from exc


class _MiMoChunkedStream(ChunkedStream):
    """将单句 MiMo PCM16 响应推送到 LiveKit 音频输出。"""

    def __init__(
        self,
        *,
        tts: MiMoVoiceCloneTTS,
        input_text: str,
        conn_options: APIConnectOptions,
    ) -> None:
        self._mimo_tts = tts
        super().__init__(tts=tts, input_text=input_text, conn_options=conn_options)

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        """完整缓冲单句 PCM 后一次推送，避免 API 分块间隔造成播放欠载。"""
        request_id = ""
        audio_chunks: list[bytes] = []
        async for request_id, pcm_bytes in self._mimo_tts.iter_audio(self.input_text):
            audio_chunks.append(pcm_bytes)

        pcm_audio = b"".join(audio_chunks)
        if not pcm_audio:
            raise APIError("MiMo TTS 没有可播放的 PCM 音频")
        if len(pcm_audio) % 2 != 0:
            raise APIError("MiMo TTS 返回的 PCM16 音频长度无效")

        output_emitter.initialize(
            request_id=request_id,
            sample_rate=self._mimo_tts.sample_rate,
            num_channels=self._mimo_tts.num_channels,
            mime_type="audio/pcm",
        )
        output_emitter.push(pcm_audio)
        print(
            f"[mimo_tts] buffered text_len={len(self.input_text)} "
            f"chunks={len(audio_chunks)} bytes={len(pcm_audio)}",
            flush=True,
        )
