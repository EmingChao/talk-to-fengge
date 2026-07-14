# Fish Audio TTS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将默认 TTS 切换为 Fish Audio `s2.1-pro-free` 和峰哥私有音色，同时完整保留 MiMo TTS 回切能力。

**Architecture:** 新增一个基于 `httpx.AsyncClient` 的 LiveKit Chunked TTS 适配器，直接消费 Fish Audio `/v1/tts` 返回的 PCM16 响应流。TTS 工厂负责读取环境变量和选择 provider，Docker 与示例配置默认选择 Fish Audio，但不保存真实 API Key。

**Tech Stack:** Python 3.12、`httpx`、LiveKit Agents 1.5、`unittest`、Docker Compose

---

## 文件职责

- 创建 `worker/fish_audio_tts.py`：参数校验、请求构造、HTTP 流读取、PCM16 对齐、LiveKit 音频推送和错误映射。
- 创建 `tests/test_fish_audio_tts.py`：不访问真实 API 的请求、流式、错误和工厂测试。
- 修改 `worker/tts_factory.py`：新增 Fish Audio 工厂和 provider 路由，保留 MiMo 路由。
- 修改 `worker/agent.py`：未配置 `TTS_PROVIDER` 时默认选择 Fish Audio，并更新相关注释。
- 修改 `.env.example`：本地配置示例默认使用 Fish Audio，MiMo 作为可切换方案保留。
- 修改 `.env.docker.example`：服务器配置示例默认使用 Fish Audio。
- 修改 `docker-compose.yml`：允许 `.env` 控制 TTS provider，默认值为 Fish Audio。
- 修改 `docs/docker-deployment.md`：更新部署必填项、验收、排错和 MiMo 回切说明。

### Task 1: 用测试定义 Fish Audio 配置与请求协议

**Files:**
- Create: `tests/test_fish_audio_tts.py`
- Create: `worker/fish_audio_tts.py`

- [ ] **Step 1: 编写配置校验和请求体失败测试**

在 `tests/test_fish_audio_tts.py` 中使用 `unittest`，先定义期望接口：

```python
class FishAudioTTSConfigTest(unittest.TestCase):
    """验证 Fish Audio 初始化参数和请求体。"""

    def test_missing_api_key_fails_at_startup(self):
        """缺少 API Key 时必须在启动阶段失败。"""
        with self.assertRaisesRegex(RuntimeError, "FISH_AUDIO_API_KEY"):
            FishAudioTTS(api_key="", reference_id="voice-id")

    def test_build_payload_uses_reference_and_pcm_stream_options(self):
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
```

同时覆盖无效 Base URL、空模型、空音色 ID、不支持的采样率、延迟模式、分块范围和语速范围。

- [ ] **Step 2: 运行测试并确认因 provider 不存在而失败**

Run: `python -m unittest tests.test_fish_audio_tts.FishAudioTTSConfigTest -v`

Expected: FAIL，错误为 `ModuleNotFoundError: No module named 'worker.fish_audio_tts'`。

- [ ] **Step 3: 实现最小配置对象与请求体**

在 `worker/fish_audio_tts.py` 创建以下结构，所有方法添加中文说明和关键流程注释：

```python
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
    """将 Fish Audio PCM 流适配为 LiveKit TTS。"""

    def __init__(self, *, api_key: str, reference_id: str,
                 base_url: str = "https://api.fish.audio/v1",
                 model: str = "s2.1-pro-free", sample_rate: int = 24000,
                 latency: str = "balanced", chunk_length: int = 300,
                 min_chunk_length: int = 50, speed: float = 1.0,
                 http_client: httpx.AsyncClient | None = None) -> None:
        # 校验 API Key、URL、模型、音色 ID 和官方数值范围。
        super().__init__(capabilities=tts.TTSCapabilities(streaming=False),
                         sample_rate=sample_rate, num_channels=1)

    def _build_payload(self, text: str) -> dict[str, object]:
        """构造 Fish Audio 官方 TTS JSON 请求体。"""
        return {
            "text": text,
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
```

采样率只允许 `{8000, 16000, 24000, 32000, 44100}`，延迟只允许 `low/balanced/normal`，`chunk_length` 限制为 100 至 300，`min_chunk_length` 限制为 0 至 100，语速限制为 0.5 至 2.0。

- [ ] **Step 4: 运行配置测试并确认通过**

Run: `python -m unittest tests.test_fish_audio_tts.FishAudioTTSConfigTest -v`

Expected: PASS，全部配置和请求体测试成功。

### Task 2: 测试先行实现 HTTP PCM 流与错误映射

**Files:**
- Modify: `tests/test_fish_audio_tts.py`
- Modify: `worker/fish_audio_tts.py`

- [ ] **Step 1: 编写 HTTP 流和错误失败测试**

使用 `httpx.MockTransport` 与自定义 `httpx.AsyncByteStream`，不访问外网：

```python
class ChunkStream(httpx.AsyncByteStream):
    """按指定网络分块返回测试音频。"""

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def __aiter__(self):
        for chunk in self._chunks:
            yield chunk


class FishAudioTTSRequestTest(unittest.IsolatedAsyncioTestCase):
    """验证 Fish Audio HTTP 流和错误映射。"""

    async def test_iter_audio_sends_headers_and_aligns_pcm_chunks(self):
        """跨网络分块的半个采样必须合并后再输出。"""
        async def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.headers["authorization"], "Bearer test-key")
            self.assertEqual(request.headers["model"], "s2.1-pro-free")
            self.assertEqual(request.url.path, "/v1/tts")
            return httpx.Response(
                200,
                headers={"x-request-id": "fish-req-1"},
                stream=ChunkStream([b"\x01", b"\x02\x03", b"\x04"]),
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = FishAudioTTS(
            api_key="test-key", reference_id="voice-id", http_client=client
        )
        chunks = [item async for item in provider.iter_audio("你好")]
        self.assertEqual(chunks, [
            ("fish-req-1", b"\x01\x02"),
            ("fish-req-1", b"\x03\x04"),
        ])
        await provider.aclose()
```

继续增加空文本、200 空响应、最终残留单字节、401/500、`httpx.TimeoutException` 和 `httpx.ConnectError` 测试，并断言分别映射为 `APIError`、`APIStatusError`、`APITimeoutError` 与 `APIConnectionError`。

- [ ] **Step 2: 运行请求测试并确认失败原因是方法未实现**

Run: `python -m unittest tests.test_fish_audio_tts.FishAudioTTSRequestTest -v`

Expected: FAIL，错误指向 `iter_audio`、`synthesize` 或资源关闭方法缺失。

- [ ] **Step 3: 实现流式请求、音频对齐与 LiveKit 推送**

在 `FishAudioTTS` 中实现 `provider`、`model`、`synthesize`、`_get_client`、`aclose` 和 `iter_audio`；新增 `_FishAudioChunkedStream`：

```python
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
    try:
        async with self._get_client().stream(
            "POST", f"{self._opts.base_url}/tts",
            headers=headers, json=self._build_payload(stripped)
        ) as response:
            request_id = response.headers.get("x-request-id") or f"fish-{uuid.uuid4()}"
            if response.status_code != 200:
                body = (await response.aread()).decode("utf-8", errors="ignore")
                raise APIStatusError(
                    message=f"Fish Audio TTS HTTP {response.status_code}: {body[:500]}",
                    status_code=response.status_code,
                    request_id=request_id,
                    body=body[:2000],
                )
            pending = b""
            total_bytes = 0
            async for chunk in response.aiter_bytes():
                combined = pending + chunk
                aligned_length = len(combined) - len(combined) % 2
                pending = combined[aligned_length:]
                if aligned_length:
                    pcm = combined[:aligned_length]
                    total_bytes += len(pcm)
                    yield request_id, pcm
            if pending:
                raise APIError("Fish Audio TTS 返回的 PCM16 音频长度无效")
            if total_bytes == 0:
                raise APIError("Fish Audio TTS 返回成功，但响应中没有音频")
    except httpx.TimeoutException as exc:
        raise APITimeoutError() from exc
    except httpx.HTTPError as exc:
        raise APIConnectionError(f"Fish Audio TTS 网络错误: {exc!r}") from exc
```

`_FishAudioChunkedStream._run()` 在收到首个音频块时初始化 `AudioEmitter`，随后立即 `push()` 每个对齐后的 PCM 块，不做整句缓冲。

- [ ] **Step 4: 运行 Fish Audio 全部单测并确认通过**

Run: `python -m unittest tests.test_fish_audio_tts -v`

Expected: PASS，配置、请求、流式和错误测试全部成功。

### Task 3: 测试先行接入 TTS 工厂并保留 MiMo 回切

**Files:**
- Modify: `tests/test_fish_audio_tts.py`
- Modify: `worker/tts_factory.py`
- Modify: `worker/agent.py`

- [ ] **Step 1: 编写工厂选择失败测试**

```python
class FishAudioTTSFactoryTest(unittest.TestCase):
    """验证 Fish Audio 默认选择和 MiMo 回切能力。"""

    @patch.dict(os.environ, {
        "FISH_AUDIO_API_KEY": "test-key",
        "FISH_AUDIO_REFERENCE_ID": "voice-id",
    }, clear=False)
    def test_factory_builds_fish_audio_for_aliases(self):
        """fish_audio 和 fish 必须创建 Fish Audio provider。"""
        for provider in ("fish_audio", "fish"):
            instance, label = build_tts(provider, "http://moss", "fengge")
            self.assertIsInstance(instance, FishAudioTTS)
            self.assertIn("s2.1-pro-free", label)

    @patch("worker.tts_factory._build_mimo")
    def test_factory_keeps_mimo_switch(self, build_mimo):
        """显式 mimo 时必须继续调用原 MiMo 工厂。"""
        expected = object()
        build_mimo.return_value = (expected, "mimo:test")
        instance, label = build_tts("mimo", "http://moss", "fengge")
        self.assertIs(instance, expected)
        self.assertEqual(label, "mimo:test")
```

另增加 `build_tts("")` 默认选择 Fish Audio、缺少 Key 和音色 ID 时直接失败的测试。

- [ ] **Step 2: 运行工厂测试并确认失败**

Run: `python -m unittest tests.test_fish_audio_tts.FishAudioTTSFactoryTest -v`

Expected: FAIL，当前工厂尚不认识 `fish_audio`，空 provider 仍选择 `mimo`。

- [ ] **Step 3: 实现 Fish Audio 工厂与默认值**

在 `worker/tts_factory.py` 新增 `_build_fish_audio()`，读取全部 `FISH_AUDIO_*` 环境变量并实例化 `FishAudioTTS`。`build_tts()` 将空 provider 归一化为 `fish_audio`，`fish_audio/fish` 直接创建 Fish Audio 且失败时不降级；现有 `mimo/xiaomi` 分支保持不变。

在 `worker/agent.py` 修改：

```python
TTS_PROVIDER = os.getenv("TTS_PROVIDER", "fish_audio").strip().lower()
```

并把启动处注释改为“部署环境默认使用 Fish Audio，可通过 `TTS_PROVIDER=mimo` 切回 MiMo”。

- [ ] **Step 4: 运行工厂与全部 Fish Audio 测试**

Run: `python -m unittest tests.test_fish_audio_tts -v`

Expected: PASS，Fish Audio 默认值、别名和 MiMo 回切全部成功。

### Task 4: 更新 Docker 配置和部署文档

**Files:**
- Modify: `.env.example`
- Modify: `.env.docker.example`
- Modify: `docker-compose.yml`
- Modify: `docs/docker-deployment.md`

- [ ] **Step 1: 更新示例环境变量**

把两个示例文件的默认 TTS 配置改为：

```env
TTS_PROVIDER=fish_audio
FISH_AUDIO_API_KEY=replace-with-fish-audio-api-key
FISH_AUDIO_BASE_URL=https://api.fish.audio/v1
FISH_AUDIO_MODEL=s2.1-pro-free
FISH_AUDIO_REFERENCE_ID=9344a2478df54929a786395f558b1267
FISH_AUDIO_SAMPLE_RATE=24000
FISH_AUDIO_LATENCY=balanced
FISH_AUDIO_CHUNK_LENGTH=300
FISH_AUDIO_MIN_CHUNK_LENGTH=50
FISH_AUDIO_SPEED=1.0
```

将现有 `MIMO_TTS_*` 配置移到“可选：切回小米 MiMo TTS”小节，不删除任何配置项。

- [ ] **Step 2: 让 Compose 尊重服务器环境配置**

修改 worker 环境：

```yaml
environment:
  LIVEKIT_URL: ws://livekit:7880
  AGENT_NAME: talk-to-me-mimo
  LLM_PROVIDER: mimo
  TTS_PROVIDER: ${TTS_PROVIDER:-fish_audio}
```

保留 Agent 名称，避免改变 Web dispatch 契约。

- [ ] **Step 3: 更新服务器部署指南**

文档必须说明：

- 必填项由 `MIMO_TTS_API_KEY` 改为 `FISH_AUDIO_API_KEY`。
- 默认模型和音色 ID 已配置，API Key 仍必须由服务器 `.env` 提供。
- Worker 正常日志应包含 `[fish_audio_tts]`。
- `401/403` 检查 Fish Audio Key，空音频和超时查看 Fish Audio 错误日志。
- 回切 MiMo 时设置 `TTS_PROVIDER=mimo` 并填写原有 `MIMO_TTS_*` 配置。

- [ ] **Step 4: 检查 Compose 展开和配置引用**

Run: `docker compose --env-file .env.docker.example config --quiet`

Expected: exit 0。

Run: `rg -n "TTS_PROVIDER=mimo|TTS_PROVIDER: mimo|默认使用小米 MiMo VoiceClone" .env.example .env.docker.example docker-compose.yml docs/docker-deployment.md worker/agent.py`

Expected: 只允许在明确说明“切回 MiMo”的文档或注释中出现，不得作为默认配置出现。

### Task 5: 全量验证、提交和推送

**Files:**
- Verify: all modified files

- [ ] **Step 1: 执行 Python 编译检查**

Run: `python -m compileall -q worker tests/test_fish_audio_tts.py`

Expected: exit 0。

- [ ] **Step 2: 执行不访问外网的测试集**

Run: `python -m unittest tests.test_fish_audio_tts tests.test_runtime_env tests.test_moss_tts -v`

Expected: PASS，0 failures，0 errors。

- [ ] **Step 3: 检查差异和敏感信息**

Run: `git diff --check`

Expected: exit 0。

Run: `! rg --pcre2 -n 'FISH_AUDIO_API_KEY=(?!replace-with-fish-audio-api-key$).+' . -g '!\.git/**'`

Expected: exit 0，仓库中不存在真实 Fish Audio API Key。

- [ ] **Step 4: 审阅最终 diff 并提交**

Run: `git diff --stat && git diff -- worker/fish_audio_tts.py worker/tts_factory.py worker/agent.py tests/test_fish_audio_tts.py .env.example .env.docker.example docker-compose.yml docs/docker-deployment.md`

Expected: 只包含 Fish Audio provider、默认选择、配置、测试和部署文档相关改动。

```bash
git add worker/fish_audio_tts.py worker/tts_factory.py worker/agent.py \
  tests/test_fish_audio_tts.py .env.example .env.docker.example \
  docker-compose.yml docs/docker-deployment.md \
  docs/superpowers/plans/2026-07-14-fish-audio-tts.md
git commit -m "feat: 默认使用 Fish Audio 语音合成"
```

- [ ] **Step 5: 推送当前分支**

Run: `git push origin feat/mimo-docker-text-chat`

Expected: 远程分支更新到本次功能提交，MiMo 代码仍保留。
