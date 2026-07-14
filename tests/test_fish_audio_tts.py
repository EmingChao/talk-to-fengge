"""Fish Audio TTS 单元测试，不访问真实外部接口。"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from typing import AsyncIterator
from unittest.mock import patch

import httpx
from livekit.agents import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from worker.fish_audio_tts import FishAudioTTS  # noqa: E402
from worker.tts_factory import build_tts  # noqa: E402


class ChunkStream(httpx.AsyncByteStream):
    """按指定网络分块返回测试音频。"""

    def __init__(self, chunks: list[bytes]) -> None:
        """保存需要依次产出的字节块。"""
        self._chunks = chunks

    async def __aiter__(self) -> AsyncIterator[bytes]:
        """按传入顺序异步产出所有字节块。"""
        for chunk in self._chunks:
            yield chunk


class FakeAudioEmitter:
    """记录 LiveKit emitter 初始化参数和推送数据。"""

    def __init__(self) -> None:
        """初始化空的调用记录。"""
        self.initialize_kwargs: dict[str, object] | None = None
        self.pushed: list[bytes] = []

    def initialize(self, **kwargs: object) -> None:
        """记录一次音频输出初始化。"""
        self.initialize_kwargs = kwargs

    def push(self, data: bytes) -> None:
        """按调用顺序记录推送的 PCM 数据。"""
        self.pushed.append(data)


class FishAudioTTSConfigTest(unittest.TestCase):
    """验证 Fish Audio 初始化参数和请求体。"""

    def test_missing_api_key_fails_at_startup(self) -> None:
        """缺少 API Key 时必须在启动阶段失败。"""
        with self.assertRaisesRegex(RuntimeError, "FISH_AUDIO_API_KEY"):
            FishAudioTTS(api_key="", reference_id="voice-id")

    def test_missing_reference_id_fails_at_startup(self) -> None:
        """缺少音色 ID 时必须在启动阶段失败。"""
        with self.assertRaisesRegex(RuntimeError, "FISH_AUDIO_REFERENCE_ID"):
            FishAudioTTS(api_key="test-key", reference_id="")

    def test_invalid_base_url_fails_at_startup(self) -> None:
        """非 HTTP 地址必须在启动阶段失败。"""
        with self.assertRaisesRegex(RuntimeError, "FISH_AUDIO_BASE_URL"):
            FishAudioTTS(
                api_key="test-key",
                reference_id="voice-id",
                base_url="api.fish.audio/v1",
            )

    def test_invalid_model_fails_at_startup(self) -> None:
        """空模型名称必须在启动阶段失败。"""
        with self.assertRaisesRegex(RuntimeError, "FISH_AUDIO_MODEL"):
            FishAudioTTS(api_key="test-key", reference_id="voice-id", model="")

    def test_invalid_sample_rate_fails_at_startup(self) -> None:
        """不受支持的 PCM 采样率必须被拒绝。"""
        with self.assertRaisesRegex(RuntimeError, "FISH_AUDIO_SAMPLE_RATE"):
            FishAudioTTS(
                api_key="test-key",
                reference_id="voice-id",
                sample_rate=22050,
            )

    def test_invalid_latency_fails_at_startup(self) -> None:
        """未知延迟模式必须被拒绝。"""
        with self.assertRaisesRegex(RuntimeError, "FISH_AUDIO_LATENCY"):
            FishAudioTTS(
                api_key="test-key",
                reference_id="voice-id",
                latency="fastest",
            )

    def test_invalid_chunk_lengths_fail_at_startup(self) -> None:
        """超出官方范围的分块长度必须被拒绝。"""
        with self.assertRaisesRegex(RuntimeError, "FISH_AUDIO_CHUNK_LENGTH"):
            FishAudioTTS(
                api_key="test-key",
                reference_id="voice-id",
                chunk_length=99,
            )
        with self.assertRaisesRegex(RuntimeError, "FISH_AUDIO_MIN_CHUNK_LENGTH"):
            FishAudioTTS(
                api_key="test-key",
                reference_id="voice-id",
                min_chunk_length=101,
            )

    def test_invalid_speed_fails_at_startup(self) -> None:
        """超出官方范围的语速必须被拒绝。"""
        with self.assertRaisesRegex(RuntimeError, "FISH_AUDIO_SPEED"):
            FishAudioTTS(
                api_key="test-key",
                reference_id="voice-id",
                speed=2.1,
            )

    def test_build_payload_uses_reference_and_pcm_stream_options(self) -> None:
        """请求体必须使用指定音色、24 kHz PCM 和低延迟分块参数。"""
        provider = FishAudioTTS(api_key="test-key", reference_id="voice-id")

        payload = provider._build_payload("你好")

        self.assertEqual(payload["text"], "你好")
        self.assertEqual(payload["reference_id"], "voice-id")
        self.assertEqual(payload["format"], "pcm")
        self.assertEqual(payload["sample_rate"], 24000)
        self.assertEqual(payload["latency"], "balanced")
        self.assertEqual(payload["chunk_length"], 300)
        self.assertEqual(payload["min_chunk_length"], 50)
        self.assertTrue(payload["normalize"])
        self.assertTrue(payload["condition_on_previous_chunks"])
        self.assertEqual(payload["prosody"], {"speed": 1.0, "volume": 0})


class FishAudioTTSRequestTest(unittest.IsolatedAsyncioTestCase):
    """验证 Fish Audio HTTP 流和错误映射。"""

    async def test_iter_audio_sends_headers_and_aligns_pcm_chunks(self) -> None:
        """跨网络分块的半个采样必须合并后再输出。"""
        async def handler(request: httpx.Request) -> httpx.Response:
            """校验请求协议并返回人为拆分的 PCM16。"""
            self.assertEqual(request.headers["authorization"], "Bearer test-key")
            self.assertEqual(request.headers["model"], "s2.1-pro-free")
            self.assertEqual(request.url.path, "/v1/tts")
            payload = json.loads(request.content)
            self.assertEqual(payload["text"], "你好")
            self.assertEqual(payload["reference_id"], "voice-id")
            return httpx.Response(
                200,
                headers={"x-request-id": "fish-req-1"},
                stream=ChunkStream([b"\x01", b"\x02\x03", b"\x04"]),
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = FishAudioTTS(
            api_key="test-key",
            reference_id="voice-id",
            http_client=client,
        )

        chunks = [item async for item in provider.iter_audio("你好")]

        self.assertEqual(
            chunks,
            [
                ("fish-req-1", b"\x01\x02"),
                ("fish-req-1", b"\x03\x04"),
            ],
        )
        await provider.aclose()

    async def test_empty_text_raises_api_error(self) -> None:
        """空白文本不应向 Fish Audio 发起请求。"""
        provider = FishAudioTTS(api_key="test-key", reference_id="voice-id")
        with self.assertRaisesRegex(APIError, "空文本"):
            _ = [item async for item in provider.iter_audio("  ")]
        await provider.aclose()

    async def test_empty_audio_response_raises_api_error(self) -> None:
        """成功状态但没有音频时必须明确报错。"""
        async def handler(request: httpx.Request) -> httpx.Response:
            """返回不包含音频字节的成功响应。"""
            return httpx.Response(200, stream=ChunkStream([]))

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = FishAudioTTS(
            api_key="test-key",
            reference_id="voice-id",
            http_client=client,
        )
        with self.assertRaisesRegex(APIError, "没有音频"):
            _ = [item async for item in provider.iter_audio("你好")]
        await provider.aclose()

    async def test_odd_pcm_tail_raises_api_error(self) -> None:
        """响应结束后残留半个 PCM16 采样时必须报错。"""
        async def handler(request: httpx.Request) -> httpx.Response:
            """返回奇数长度 PCM 字节。"""
            return httpx.Response(200, stream=ChunkStream([b"\x01\x02\x03"]))

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = FishAudioTTS(
            api_key="test-key",
            reference_id="voice-id",
            http_client=client,
        )
        with self.assertRaisesRegex(APIError, "PCM16"):
            _ = [item async for item in provider.iter_audio("你好")]
        await provider.aclose()

    async def test_http_error_maps_to_api_status_error(self) -> None:
        """非 200 响应必须保留状态码、请求 ID 和错误正文。"""
        async def handler(request: httpx.Request) -> httpx.Response:
            """返回带请求 ID 的鉴权错误。"""
            return httpx.Response(
                401,
                headers={"x-request-id": "fish-auth-1"},
                json={"message": "invalid token"},
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = FishAudioTTS(
            api_key="test-key",
            reference_id="voice-id",
            http_client=client,
        )
        with self.assertRaises(APIStatusError) as context:
            _ = [item async for item in provider.iter_audio("你好")]
        self.assertEqual(context.exception.status_code, 401)
        self.assertEqual(context.exception.request_id, "fish-auth-1")
        self.assertIn("invalid token", str(context.exception.body))
        await provider.aclose()

    async def test_timeout_maps_to_api_timeout_error(self) -> None:
        """httpx 超时必须映射为 LiveKit 超时错误。"""
        async def handler(request: httpx.Request) -> httpx.Response:
            """模拟建立请求后的读取超时。"""
            raise httpx.ReadTimeout("timeout", request=request)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = FishAudioTTS(
            api_key="test-key",
            reference_id="voice-id",
            http_client=client,
        )
        with self.assertRaises(APITimeoutError):
            _ = [item async for item in provider.iter_audio("你好")]
        await provider.aclose()

    async def test_connection_error_maps_to_api_connection_error(self) -> None:
        """httpx 连接失败必须映射为 LiveKit 连接错误。"""
        async def handler(request: httpx.Request) -> httpx.Response:
            """模拟网络连接失败。"""
            raise httpx.ConnectError("unreachable", request=request)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = FishAudioTTS(
            api_key="test-key",
            reference_id="voice-id",
            http_client=client,
        )
        with self.assertRaises(APIConnectionError):
            _ = [item async for item in provider.iter_audio("你好")]
        await provider.aclose()

    async def test_synthesize_returns_livekit_chunked_stream(self) -> None:
        """synthesize 必须返回持有原文本的 LiveKit 分段流。"""
        provider = FishAudioTTS(api_key="test-key", reference_id="voice-id")

        stream = provider.synthesize("你好")

        self.assertEqual(stream.input_text, "你好")
        self.assertIs(stream._fish_audio_tts, provider)
        await provider.aclose()

    async def test_chunked_stream_pushes_each_pcm_block(self) -> None:
        """LiveKit 输出必须逐块推送 PCM，不等待整句缓冲。"""
        async def handler(request: httpx.Request) -> httpx.Response:
            """返回两个完整的 PCM16 网络分块。"""
            return httpx.Response(
                200,
                headers={"x-request-id": "fish-stream-1"},
                stream=ChunkStream([b"\x01\x02", b"\x03\x04"]),
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = FishAudioTTS(
            api_key="test-key",
            reference_id="voice-id",
            http_client=client,
        )
        stream = provider.synthesize("你好")
        emitter = FakeAudioEmitter()

        await stream._run(emitter)

        self.assertEqual(
            emitter.initialize_kwargs,
            {
                "request_id": "fish-stream-1",
                "sample_rate": 24000,
                "num_channels": 1,
                "mime_type": "audio/pcm",
            },
        )
        self.assertEqual(emitter.pushed, [b"\x01\x02", b"\x03\x04"])
        await provider.aclose()


class FishAudioTTSFactoryTest(unittest.TestCase):
    """验证 Fish Audio 默认选择和 MiMo 回切能力。"""

    @patch.dict(
        os.environ,
        {
            "FISH_AUDIO_API_KEY": "test-key",
            "FISH_AUDIO_REFERENCE_ID": "voice-id",
        },
        clear=False,
    )
    def test_factory_builds_fish_audio_for_aliases(self) -> None:
        """fish_audio 和 fish 必须创建 Fish Audio provider。"""
        for provider in ("fish_audio", "fish"):
            instance, label = build_tts(provider, "http://moss", "fengge")
            self.assertIsInstance(instance, FishAudioTTS)
            self.assertIn("s2.1-pro-free", label)

    @patch.dict(
        os.environ,
        {
            "FISH_AUDIO_API_KEY": "test-key",
            "FISH_AUDIO_REFERENCE_ID": "voice-id",
        },
        clear=False,
    )
    def test_empty_provider_defaults_to_fish_audio(self) -> None:
        """空 provider 必须默认选择 Fish Audio。"""
        instance, label = build_tts("", "http://moss", "fengge")
        self.assertIsInstance(instance, FishAudioTTS)
        self.assertTrue(label.startswith("fish_audio:"))

    @patch.dict(
        os.environ,
        {"FISH_AUDIO_API_KEY": "", "FISH_AUDIO_REFERENCE_ID": "voice-id"},
        clear=False,
    )
    def test_missing_fish_audio_key_fails_without_fallback(self) -> None:
        """缺少 Fish Audio Key 时必须失败，不能静默降级 MOSS。"""
        with self.assertRaisesRegex(RuntimeError, "FISH_AUDIO_API_KEY"):
            build_tts("fish_audio", "http://moss", "fengge")

    @patch.dict(
        os.environ,
        {"FISH_AUDIO_API_KEY": "test-key", "FISH_AUDIO_REFERENCE_ID": ""},
        clear=False,
    )
    def test_missing_reference_id_fails_without_fallback(self) -> None:
        """缺少 Fish Audio 音色 ID 时必须失败，不能静默降级 MOSS。"""
        with self.assertRaisesRegex(RuntimeError, "FISH_AUDIO_REFERENCE_ID"):
            build_tts("fish_audio", "http://moss", "fengge")

    @patch("worker.tts_factory._build_mimo")
    def test_factory_keeps_mimo_switch(self, build_mimo) -> None:
        """显式选择 mimo 时必须继续调用原 MiMo 工厂。"""
        expected = object()
        build_mimo.return_value = (expected, "mimo:test")

        instance, label = build_tts("mimo", "http://moss", "fengge")

        self.assertIs(instance, expected)
        self.assertEqual(label, "mimo:test")
        build_mimo.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
