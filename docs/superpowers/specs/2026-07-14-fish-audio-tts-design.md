# Fish Audio TTS 适配设计

## 目标

将项目默认语音合成服务由小米 MiMo VoiceClone 切换为 Fish Audio，同时完整保留现有 MiMo 实现，确保只需修改 `TTS_PROVIDER` 即可随时切回小米 TTS。

默认使用以下 Fish Audio 配置：

- 模型：`s2.1-pro-free`
- 音色 ID：`9344a2478df54929a786395f558b1267`
- 输出格式：PCM16
- 采样率：24000 Hz
- 声道数：单声道
- 延迟模式：`balanced`

Fish Audio API Key 只允许通过运行环境中的 `FISH_AUDIO_API_KEY` 注入，不写入代码、示例配置或 Git 历史。

## 实现方案

新增 `worker/fish_audio_tts.py`，使用项目已有的 `httpx` 直接调用 Fish Audio 官方接口：

```text
POST https://api.fish.audio/v1/tts
Authorization: Bearer <FISH_AUDIO_API_KEY>
model: s2.1-pro-free
Content-Type: application/json
```

请求体包含待合成文本、音色 ID、PCM 输出格式、采样率、延迟策略和分块参数。适配器实现 LiveKit `TTS` 与 `ChunkedStream` 接口，使上层 Agent 无需感知供应商差异。

不引入 Fish Audio SDK。直接使用 `httpx` 可以复用现有依赖，并且能精确控制流式读取、连接池、超时、错误映射和资源关闭。

## 音频数据流

1. LiveKit 将已切分文本传给 Fish Audio TTS 适配器。
2. 适配器校验文本和运行配置，构造 `/v1/tts` 请求。
3. Fish Audio 返回原始 PCM16 HTTP 响应流。
4. 适配器初始化 LiveKit `AudioEmitter`，按网络分块持续推送 PCM 数据。
5. 如果单个网络分块末尾包含半个 PCM16 采样，暂存该字节并与下一分块合并，保证每次推送长度为偶数。
6. 响应结束时若仍有不完整采样，则报告音频格式错误。

Fish Audio 支持真正的音频流式响应，因此不沿用 MiMo 的整句缓冲逻辑。这样可以缩短首包等待时间，并减少因供应商分块间隔造成的句中停顿。

## 配置与切换

TTS 工厂新增 `fish_audio` 和 `fish` 两个 provider 名称。未设置 `TTS_PROVIDER` 时默认选择 `fish_audio`。

新增运行配置：

```env
TTS_PROVIDER=fish_audio
FISH_AUDIO_API_KEY=
FISH_AUDIO_BASE_URL=https://api.fish.audio/v1
FISH_AUDIO_MODEL=s2.1-pro-free
FISH_AUDIO_REFERENCE_ID=9344a2478df54929a786395f558b1267
FISH_AUDIO_SAMPLE_RATE=24000
FISH_AUDIO_LATENCY=balanced
FISH_AUDIO_CHUNK_LENGTH=300
FISH_AUDIO_MIN_CHUNK_LENGTH=50
FISH_AUDIO_SPEED=1.0
```

`docker-compose.yml` 不再把 provider 强制写死为 `mimo`，而是使用 `${TTS_PROVIDER:-fish_audio}`。服务器 `.env` 中仍可通过以下配置恢复小米 TTS：

```env
TTS_PROVIDER=mimo
```

现有 `worker/mimo_tts.py`、`_build_mimo()` 和全部 MiMo 环境变量保持不变。

## 校验与错误处理

启动阶段校验：

- `FISH_AUDIO_API_KEY` 不能为空。
- `FISH_AUDIO_BASE_URL` 必须是 HTTP 或 HTTPS 地址。
- `FISH_AUDIO_MODEL` 和 `FISH_AUDIO_REFERENCE_ID` 不能为空。
- 采样率、分块长度和语速必须处于官方接口允许的范围。
- 延迟模式只允许 `low`、`balanced` 或 `normal`。

运行阶段错误映射：

- 网络连接失败映射为 LiveKit `APIConnectionError`。
- 请求超时映射为 `APITimeoutError`。
- 非 200 响应映射为 `APIStatusError`，日志保留截断后的响应正文和请求 ID。
- 200 响应没有音频或返回奇数长度 PCM 时映射为 `APIError`。

Fish Audio 配置错误和运行失败不静默降级到 MOSS。错误必须明确暴露，由项目现有文字聊天通道继续提供可用交互，避免用户误以为当前正在使用指定音色。

## 测试策略

新增一个聚焦的 Python 测试文件，不访问真实 Fish Audio API，不消耗额度。测试通过模拟 HTTP 传输覆盖：

- 请求 URL、认证头、模型头和 JSON 请求体正确。
- PCM 网络分块能够持续输出，并正确拼接跨分块的半个采样。
- 空文本、空音频、奇数长度 PCM、超时、网络错误和非 200 状态正确映射。
- 工厂默认选择 Fish Audio，支持 `fish` 别名，并可通过 `mimo` 切回原实现。
- 缺少 API Key 或音色 ID 时在启动阶段明确失败。

同时执行 Python 编译检查、现有测试集、Docker Compose 配置渲染和敏感信息扫描。

## 部署文档

更新环境变量示例和 Docker 部署文档，默认展示 Fish Audio 配置，并保留 MiMo 作为可选回退方案。文档不包含真实 API Key，只展示占位符和已确认可公开使用的音色 ID。

## 完成标准

- Docker 部署默认创建 Fish Audio TTS 实例。
- Fish Audio 使用指定模型和指定音色 ID 生成 24 kHz PCM 音频。
- 音频以流式方式进入 LiveKit，不需要等待整句响应完成。
- 将 `TTS_PROVIDER` 改为 `mimo` 后仍能创建原有 MiMo TTS 实例。
- 项目文件和 Git diff 中不存在真实 Fish Audio API Key。
- 新增测试、现有相关测试、编译检查和 Docker Compose 配置检查全部通过。
