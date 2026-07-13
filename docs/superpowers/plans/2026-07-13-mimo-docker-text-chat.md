# MiMo、Docker 与文字对话适配实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**目标：** 将现有语音 Agent 改造成可用 Docker Compose 部署、同时支持语音和文字输入、使用小米 MiMo LLM 与 VoiceClone TTS 的混合对话应用。

**架构：** 保留 LiveKit 房间作为唯一会话通道，语音经 STT、文字经 `lk.chat` 进入同一个 AgentSession；LLM 回复经 `lk.transcription` 立即显示，同时交给 MiMo TTS 播放。Docker Compose 分别运行 LiveKit、Worker 和 Web，内外网 LiveKit 地址分离。

**技术栈：** Python 3.12、LiveKit Agents 1.5、httpx、aiohttp、HTML/CSS/JavaScript、Docker Compose。

---

### 任务 1：实现 MiMo LLM provider

**文件：**
- 修改：`worker/llm_factory.py`
- 修改：`worker/agent.py`
- 修改：`.env.example`

- [x] 在 `worker/llm_factory.py` 增加 `MiMoChatStream`，使用 `api-key` 认证头、可配置 Base URL、`mimo-v2.5` 默认模型和 OpenAI 兼容 SSE 解析。
- [x] 将 OpenAI 兼容流基类中的重复客户端、超时、错误正文截断和 SSE 解析逻辑复用到 MiMo，保持 DeepSeek/MiniMax 行为兼容。
- [x] 在 `worker/agent.py` 的 provider、Agent 名称映射、构造方法和日志标签中加入 `mimo`。
- [x] 在 `.env.example` 增加 `MIMO_LLM_BASE_URL`、`MIMO_LLM_API_KEY`、`MIMO_LLM_MODEL` 和 token 上限配置，默认选择 MiMo。
- [x] 运行 `python3 -m py_compile worker/llm_factory.py worker/agent.py`，预期无输出且退出码为 0。
- [x] 提交 `feat: 接入小米 MiMo 大语言模型`。

### 任务 2：实现 MiMo VoiceClone TTS

**文件：**
- 新建：`worker/mimo_tts.py`
- 修改：`worker/tts_factory.py`
- 修改：`.env.example`

- [x] 在 `worker/mimo_tts.py` 实现参考音频校验和 Data URI 缓存，支持 WAV 与 MP3，编码结果不得超过官方限制。
- [x] 实现 LiveKit `tts.TTS`/`ChunkedStream` 适配器，请求 `mimo-v2.5-tts-voiceclone`，目标文本放入 assistant message，音频请求为 24 kHz PCM16。
- [x] 解析非流式 JSON及兼容模式 SSE中的 `message.audio.data` 或 `delta.audio.data`，将 PCM16LE 数据送入 LiveKit AudioByteStream。
- [x] 为 HTTP 非 200、无效 JSON/SSE、Base64 错误和空音频提供中文可读错误，日志不包含密钥和参考音频。
- [x] 在 `worker/tts_factory.py` 增加 `mimo` 分支；MiMo 初始化失败直接报错，不回退到 MOSS。
- [x] 在 `.env.example` 增加 `MIMO_TTS_BASE_URL`、`MIMO_TTS_API_KEY`、`MIMO_TTS_MODEL`、`MIMO_TTS_VOICE_FILE` 和风格指令配置。
- [x] 运行 `python3 -m py_compile worker/mimo_tts.py worker/tts_factory.py`，预期无输出且退出码为 0。
- [x] 提交 `feat: 接入 MiMo 音色克隆语音合成`。

### 任务 3：启用文字输入和文字优先降级

**文件：**
- 修改：`worker/agent.py`
- 修改：`worker/web_server.py`

- [x] 使用 `room_io.RoomOptions` 显式启用音频输入、文字输入、音频输出和文字输出，并设置 `sync_transcription=False`。
- [x] 保留 `conversation_item_added` 作为语音与文字共用的记忆入口，移除 STT final 事件中的重复用户记忆写入。
- [x] 扩展 Agent 错误事件日志，使 TTS 错误可观察但不泄漏请求凭证。
- [x] 将 Web Server 的监听地址改为 `WEB_HOST`，默认 `0.0.0.0`。
- [x] 将浏览器地址与容器内地址分离：`LIVEKIT_URL` 用于服务端，`LIVEKIT_PUBLIC_URL` 返回给前端。
- [x] 运行 `python3 -m py_compile worker/agent.py worker/web_server.py`，预期无输出且退出码为 0。
- [x] 提交 `feat: 启用 LiveKit 混合文字语音会话`。

### 任务 4：实现前端文字对话和静音

**文件：**
- 修改：`web/index.html`

- [x] 移除前端模型选择器和多 Worker 房间路由，固定显示 MiMo，避免选择不存在的 Agent。
- [x] 增加滚动消息区、用户/AI 消息样式、输入框、发送按钮和扬声器静音按钮，适配桌面和移动端安全区。
- [x] 将 `/token` 返回值整体交给连接流程，使用 `livekit_url` 连接，不再硬编码 localhost。
- [x] 注册 `lk.transcription` text stream handler，按 segment id 合并增量内容并区分本地用户与 Agent。
- [x] 使用 `sendText(text, {topic: 'lk.chat'})` 发送；Enter 发送、Shift+Enter 换行，发送失败时恢复输入。
- [x] 麦克风授权失败只提示，不断开 LiveKit 房间；文字输入在连接后保持可用。
- [x] 静音按钮只控制远端 `<audio>`，状态写入 `localStorage`，并补齐 tooltip 与无障碍名称。
- [x] 使用浏览器静态语法检查或 `node --check` 提取后的脚本进行检查；预期无 JavaScript 语法错误。
- [x] 提交 `feat: 增加文字输入和混合回复界面`。

### 任务 5：编写 Docker 部署配置

**文件：**
- 新建：`Dockerfile`
- 新建：`.dockerignore`
- 新建：`docker-compose.yml`
- 新建：`deploy/livekit.yaml`
- 新建：`.env.docker.example`

- [x] 编写 Python 3.12 slim 多阶段镜像，使用 `uv` 按 `pyproject.toml` 安装依赖，最终阶段使用非 root 用户。
- [x] 编写 `.dockerignore`，排除 Git、本地环境、密钥、缓存和不需要的个人数据，保留峰哥参考音频。
- [x] 编写 Compose：LiveKit 暴露信令与 RTC 端口，Worker/Web 复用应用镜像，通过健康检查和依赖条件启动。
- [x] 编写 LiveKit 单节点配置，通过部署环境注入 API Key/Secret，配置 WebRTC TCP/UDP 端口范围。
- [x] 编写 `.env.docker.example`，只放安全占位符，包含内外 LiveKit 地址、Cartesia、MiMo LLM/TTS 和 Web 配置。
- [x] 如本机已有 Docker 且不会拉取镜像，运行 `docker compose --env-file .env.docker.example config --quiet`；否则只做 YAML 和变量引用人工检查并明确记录未执行原因。
- [x] 提交 `build: 增加 Docker Compose 部署配置`。

### 任务 6：更新部署文档与完成静态验证

**文件：**
- 修改：`README.md`
- 新建：`docs/docker-deployment.md`

- [x] 更新 README 快速开始，增加服务器 Docker 部署入口、文字对话说明和 MiMo provider 配置摘要。
- [x] 编写服务器部署文档，说明 Docker/Compose、域名、HTTPS/WSS、防火墙、RTC 端口、密钥文件、启动、日志、更新和故障排查。
- [x] 明确 MiMo Token Plan `tp-` 密钥与按量 TTS `sk-` 密钥不可混用。
- [x] 运行 `python3 -m compileall -q worker`，预期退出码为 0。
- [x] 运行 `git diff --check`，预期无输出且退出码为 0。
- [x] 使用 `rg` 扫描用户提供的密钥完整值和常见密钥格式，确认受 Git 管理文件不包含真实密钥。
- [x] 对照设计文档检查环境变量名称、端口和服务名一致。
- [x] 提交 `docs: 补充 MiMo Docker 服务器部署指南`。
