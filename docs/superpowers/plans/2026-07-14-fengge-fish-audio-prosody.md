# 峰哥 Fish Audio 人格语气编排实施计划

> **执行说明：** 按任务逐项实施并使用复选框（`- [ ]`）跟踪状态。

**目标：** 在不污染页面文字和记忆的前提下，为 Fish Audio TTS 请求添加克制自然的峰哥人格语气标签。

**架构：** 新增独立纯规则 `FenggeProsodyPlanner`，根据 TTS 文本选择最多一个 S2.1 方括号标签。Fish Audio 供应商仅在构造请求体时装饰文本，MiMo 和公共文字链路不引用编排器。

**技术栈：** Python 3.12、LiveKit Agents、httpx、unittest

---

### Task 1: 测试先行实现人格语气规则

**涉及文件：**
- 新建：`worker/fengge_prosody.py`
- 新建：`tests/test_fengge_prosody.py`

- [x] **Step 1: 编写失败测试**

测试期望接口和优先级：

```python
planner = FenggeProsodyPlanner(mode="persona", intensity="subtle")
assert planner.decorate("你好啊") == "你好啊"
assert planner.decorate("这是个好事儿啊") == "[confident] 这是个好事儿啊"
assert planner.decorate("不就那么回事吗") == "[sarcastic] 不就那么回事吗"
assert planner.decorate("终于跑通了") == "[excited] 终于跑通了"
assert planner.decorate("家暴还能叫好事吗") == "[calm] 家暴还能叫好事吗"
```

同时测试空文本、`off` 模式、已有方括号标签不重复、无效模式和无效强度。

- [x] **Step 2: 验证 RED**

执行：`.venv/bin/python -m unittest tests.test_fengge_prosody -v`

预期：失败，`worker.fengge_prosody` 不存在。

- [x] **Step 3: 实现最小规则编排器**

```python
class FenggeProsodyPlanner:
    """按峰哥人格强信号为 Fish Audio 文本选择克制语气。"""

    def __init__(self, *, mode: str = "persona", intensity: str = "subtle") -> None:
        """校验模式和强度，并保存不可变配置。"""

    def decorate(self, text: str) -> str:
        """按 calm、excited、sarcastic、confident 优先级装饰文本。"""
```

规则使用按优先级排列的不可变关键词集合；无强信号时返回原文，每次最多添加一个标签。

- [x] **Step 4: 验证 GREEN**

执行：`.venv/bin/python -m unittest tests.test_fengge_prosody -v`

预期：通过。

### Task 2: 测试先行接入 Fish Audio 请求体

**涉及文件：**
- 修改：`tests/test_fish_audio_tts.py`
- 修改：`worker/fish_audio_tts.py`
- 修改：`worker/tts_factory.py`

- [x] **Step 1: 编写失败测试**

扩展测试，期望 `_build_payload("这是个好事儿啊")` 的 `text` 为 `[confident] 这是个好事儿啊`，同时原始字符串不变；`prosody_mode="off"` 时请求体使用原文；无效配置启动失败。

- [x] **Step 2: 验证 RED**

执行：`.venv/bin/python -m unittest tests.test_fish_audio_tts.FishAudioTTSConfigTest -v`

预期：失败，构造函数尚不支持 `prosody_mode`，请求体也未装饰。

- [x] **Step 3: 实现 provider 与工厂接入**

`FishAudioTTS` 构造函数新增：

```python
prosody_mode: str = "persona"
prosody_intensity: str = "subtle"
```

构造时创建 `FenggeProsodyPlanner`，`_build_payload()` 只装饰局部请求文本。工厂读取：

```python
FISH_AUDIO_PROSODY_MODE=persona
FISH_AUDIO_PROSODY_INTENSITY=subtle
```

编排异常时回退原文，只记录异常类型和文本长度。

- [x] **Step 4: 验证 GREEN 与 MiMo 隔离**

执行：`.venv/bin/python -m unittest tests.test_fengge_prosody tests.test_fish_audio_tts -v`

预期：通过；`worker/mimo_tts.py` 和公共文字链路不引用 `FenggeProsodyPlanner`。

### Task 3: 配置、文档、验证、提交与推送

**涉及文件：**
- 修改：`.env.example`
- 修改：`.env.docker.example`
- 修改：`docs/docker-deployment.md`
- 修改：`docs/superpowers/plans/2026-07-14-fengge-fish-audio-prosody.md`

- [x] **Step 1: 更新配置和部署说明**

在 Fish Audio 配置区加入：

```env
FISH_AUDIO_PROSODY_MODE=persona
FISH_AUDIO_PROSODY_INTENSITY=subtle
```

说明 `off` 可关闭内部标签，标签不显示在页面和记忆中。

- [x] **Step 2: 执行完整验证**

执行：`.venv/bin/python -m compileall -q worker tests/test_fengge_prosody.py tests/test_fish_audio_tts.py`

执行：`.venv/bin/python -m unittest tests.test_fengge_prosody tests.test_fish_audio_tts tests.test_runtime_env tests.test_moss_tts -v`

执行：`git diff --check`

预期：编译成功、测试 0 个失败、差异无格式错误。

- [x] **Step 3: 检查隔离和敏感信息**

执行：`! rg -n 'FenggeProsodyPlanner' worker/agent.py worker/mimo_tts.py web`

执行：使用已知密钥的精确只读扫描检查仓库。

预期：公共文字、MiMo 和前端无编排器引用，真实密钥无命中。

- [ ] **Step 4: 提交并推送当前分支**

```bash
git add worker/fengge_prosody.py worker/fish_audio_tts.py worker/tts_factory.py \
  tests/test_fengge_prosody.py tests/test_fish_audio_tts.py \
  .env.example .env.docker.example docs/docker-deployment.md \
  docs/superpowers/plans/2026-07-14-fengge-fish-audio-prosody.md
git commit -m "feat: 为 Fish Audio 添加峰哥人格语气"
git push origin feat/mimo-docker-text-chat
```
