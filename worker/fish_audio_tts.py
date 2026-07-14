"""Fish Audio 的 LiveKit TTS 适配器。"""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass
from typing import AsyncIterator

import httpx
from livekit.agents import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    tts,
)
from livekit.agents.types import APIConnectOptions, DEFAULT_API_CONNECT_OPTIONS
from livekit.agents.tts import ChunkedStream, TTS
from worker.fengge_prosody import FenggeProsodyPlanner

FISH_AUDIO_BASE_URL = "https://api.fish.audio/v1"
FISH_AUDIO_MODEL = "s2.1-pro-free"
FISH_AUDIO_SAMPLE_RATE = 24000
_SUPPORTED_SAMPLE_RATES = {8000, 16000, 24000, 32000, 44100}
_SUPPORTED_LATENCIES = {"low", "balanced", "normal"}


@dataclass(frozen=True)
class FishAudioTTSOptions:
    """保存 Fish Audio TTS 请求所需的不可变配置。"""

    api_key: str
    base_url: str
    model: str
    reference_id: str
    sample_rate: int
    latency: str
    chunk_length: int
    min_chunk_length: int
    speed: float
    num_channels: int = 1


class FishAudioTTS(TTS):
    """将 Fish Audio PCM 响应适配为 LiveKit TTS。"""

    def __init__(
        self,
        *,
        api_key: str,
        reference_id: str,
        base_url: str = FISH_AUDIO_BASE_URL,
        model: str = FISH_AUDIO_MODEL,
        sample_rate: int = FISH_AUDIO_SAMPLE_RATE,
        latency: str = "balanced",
        chunk_length: int = 300,
        min_chunk_length: int = 50,
        speed: float = 1.0,
        prosody_mode: str = "persona",
        prosody_intensity: str = "subtle",
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        """校验 Fish Audio 配置并初始化 LiveKit TTS 能力。"""
        api_key = api_key.strip()
        reference_id = reference_id.strip()
        base_url = base_url.rstrip("/")
        model = model.strip()
        latency = latency.strip().lower()

        if not api_key:
            raise RuntimeError("FISH_AUDIO_API_KEY 未配置")
        if not reference_id:
            raise RuntimeError("FISH_AUDIO_REFERENCE_ID 未配置")
        if not base_url.startswith(("http://", "https://")):
            raise RuntimeError("FISH_AUDIO_BASE_URL 无效")
        if not model:
            raise RuntimeError("FISH_AUDIO_MODEL 未配置")
        if sample_rate not in _SUPPORTED_SAMPLE_RATES:
            raise RuntimeError("FISH_AUDIO_SAMPLE_RATE 不受支持")
        if latency not in _SUPPORTED_LATENCIES:
            raise RuntimeError("FISH_AUDIO_LATENCY 无效")
        if not 100 <= chunk_length <= 300:
            raise RuntimeError("FISH_AUDIO_CHUNK_LENGTH 必须在 100 到 300 之间")
        if not 0 <= min_chunk_length <= 100:
            raise RuntimeError("FISH_AUDIO_MIN_CHUNK_LENGTH 必须在 0 到 100 之间")
        if not 0.5 <= speed <= 2.0:
            raise RuntimeError("FISH_AUDIO_SPEED 必须在 0.5 到 2.0 之间")

        # Fish Audio 支持 HTTP 音频流，但输入仍按已切分文本逐段合成。
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False),
            sample_rate=sample_rate,
            num_channels=1,
        )
        self._opts = FishAudioTTSOptions(
            api_key=api_key,
            base_url=base_url,
            model=model,
            reference_id=reference_id,
            sample_rate=sample_rate,
            latency=latency,
            chunk_length=chunk_length,
            min_chunk_length=min_chunk_length,
            speed=speed,
        )
        self._client = http_client
        self._prosody_planner = FenggeProsodyPlanner(
            mode=prosody_mode,
            intensity=prosody_intensity,
        )

    @property
    def provider(self) -> str:
        """返回用于日志和监控的 provider 名称。"""
        return "Fish Audio"

    @property
    def model(self) -> str:
        """返回当前使用的 Fish Audio 模型。"""
        return self._opts.model

    def synthesize(
        self,
        text: str,
        *,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> ChunkedStream:
        """为一段已切分文本创建流式音频合成任务。"""
        return _FishAudioChunkedStream(
            tts=self,
            input_text=text,
            conn_options=conn_options,
        )

    def _get_client(self) -> httpx.AsyncClient:
        """延迟创建可复用的异步 HTTP 客户端。"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(120.0, connect=15.0),
                trust_env=True,
                proxy=os.environ.get("EGRESS_PROXY_URL"),
                http2=False,
                limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
            )
        return self._client

    async def aclose(self) -> None:
        """关闭底层 HTTP 连接池。"""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    def _build_payload(self, text: str) -> dict[str, object]:
        """构造 Fish Audio 官方 TTS JSON 请求体。"""
        decorated_text = self._decorate_text(text)
        return {
            "text": decorated_text,
            "reference_id": self._opts.reference_id,
            "format": "pcm",
            "sample_rate": self._opts.sample_rate,
            "latency": self._opts.latency,
            "chunk_length": self._opts.chunk_length,
            "min_chunk_length": self._opts.min_chunk_length,
            "normalize": True,
            "condition_on_previous_chunks": True,
            "prosody": {"speed": self._opts.speed, "volume": 0},
        }

    def _decorate_text(self, text: str) -> str:
        """生成仅供 TTS 使用的文本副本，异常时安全回退原文。"""
        try:
            decorated = self._prosody_planner.decorate(text)
        except Exception as exc:
            print(
                f"[fish_audio_tts] prosody fallback error={type(exc).__name__} "
                f"text_len={len(text)}",
                flush=True,
            )
            return text

        if decorated != text:
            tag = decorated.split("]", 1)[0] + "]"
            print(
                f"[fish_audio_tts] prosody tag={tag} text_len={len(text)}",
                flush=True,
            )
        return decorated

    async def iter_audio(self, text: str) -> AsyncIterator[tuple[str, bytes]]:
        """请求 Fish Audio，并按完整 PCM16 采样持续产出音频。"""
        stripped = text.strip()
        if not stripped:
            raise APIError("Fish Audio TTS 收到空文本")

        headers = {
            "Authorization": f"Bearer {self._opts.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/octet-stream",
            "model": self._opts.model,
        }
        started_at = time.monotonic()
        try:
            async with self._get_client().stream(
                "POST",
                f"{self._opts.base_url}/tts",
                headers=headers,
                json=self._build_payload(stripped),
            ) as response:
                request_id = response.headers.get("x-request-id") or f"fish-{uuid.uuid4()}"
                if response.status_code != 200:
                    body = (await response.aread()).decode("utf-8", errors="ignore")
                    raise APIStatusError(
                        message=(
                            f"Fish Audio TTS HTTP {response.status_code}: {body[:500]}"
                        ),
                        status_code=response.status_code,
                        request_id=request_id,
                        body=body[:2000],
                    )

                pending = b""
                total_bytes = 0
                chunk_count = 0
                first_audio_at: float | None = None
                async for chunk in response.aiter_bytes():
                    if not chunk:
                        continue
                    # 网络分块不保证落在 16-bit 采样边界，需要保留最后一个单字节。
                    combined = pending + chunk
                    aligned_length = len(combined) - len(combined) % 2
                    pending = combined[aligned_length:]
                    if aligned_length == 0:
                        continue
                    pcm = combined[:aligned_length]
                    chunk_count += 1
                    total_bytes += len(pcm)
                    first_audio_at = first_audio_at or time.monotonic()
                    yield request_id, pcm

                if pending:
                    raise APIError("Fish Audio TTS 返回的 PCM16 音频长度无效")
                if total_bytes == 0:
                    raise APIError("Fish Audio TTS 返回成功，但响应中没有音频")

                elapsed_ms = (time.monotonic() - started_at) * 1000
                ttfb_ms = ((first_audio_at or time.monotonic()) - started_at) * 1000
                print(
                    f"[fish_audio_tts] ok model={self._opts.model} "
                    f"total={elapsed_ms:.0f}ms ttfb={ttfb_ms:.0f}ms "
                    f"text_len={len(stripped)} chunks={chunk_count} bytes={total_bytes}",
                    flush=True,
                )
        except httpx.TimeoutException as exc:
            raise APITimeoutError() from exc
        except (APIStatusError, APIError):
            raise
        except httpx.HTTPError as exc:
            raise APIConnectionError(f"Fish Audio TTS 网络错误: {exc!r}") from exc


class _FishAudioChunkedStream(ChunkedStream):
    """将 Fish Audio PCM16 HTTP 流持续推送到 LiveKit。"""

    def __init__(
        self,
        *,
        tts: FishAudioTTS,
        input_text: str,
        conn_options: APIConnectOptions,
    ) -> None:
        """保存 Fish Audio provider 并初始化 LiveKit 分段流。"""
        self._fish_audio_tts = tts
        super().__init__(tts=tts, input_text=input_text, conn_options=conn_options)

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        """首块到达后初始化输出，并持续推送后续 PCM 音频。"""
        initialized = False
        async for request_id, pcm_bytes in self._fish_audio_tts.iter_audio(
            self.input_text
        ):
            if not initialized:
                output_emitter.initialize(
                    request_id=request_id,
                    sample_rate=self._fish_audio_tts.sample_rate,
                    num_channels=self._fish_audio_tts.num_channels,
                    mime_type="audio/pcm",
                )
                initialized = True
            output_emitter.push(pcm_bytes)
