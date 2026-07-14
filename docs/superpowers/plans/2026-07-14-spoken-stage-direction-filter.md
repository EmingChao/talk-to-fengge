# 语音回复舞台说明清理实施计划

> **执行说明：** 按测试先行方式逐项实施，代码与计划在同一次功能提交中完成。

**目标：** 阻止 `（笑）`、`[sarcastic]` 等舞台说明或情绪标签进入页面、记忆、转写和 Fish Audio 原始正文。

**架构：** 新增独立的流式文本过滤器，只处理回复开头的已知舞台说明和已知 Fish Audio 标签，并正确处理跨 LLM 分块的括号内容。MiMo LLM 流在创建 `ChatChunk` 前调用过滤器；人格提示词从源头禁止输出舞台说明，Fish Audio 继续在内部副本上添加方括号标签。

**技术栈：** Python 3.12、LiveKit Agents、unittest

---

### 任务 1：测试先行实现流式过滤器

**涉及文件：**
- 新建：`worker/spoken_text.py`
- 新建：`tests/test_spoken_text.py`

- [x] 编写覆盖中文括号、英文括号、方括号标签、跨块输入和正常括号正文的失败测试。
- [x] 执行 `.venv/bin/python -m unittest tests.test_spoken_text -v`，确认因模块不存在而失败。
- [x] 实现 `LeadingStageDirectionFilter.feed()` 和 `finish()`。
- [x] 重新执行专项测试并确认通过。

### 任务 2：接入 LLM 流与人格提示词

**涉及文件：**
- 修改：`worker/agent.py`
- 修改：`worker/persona.py`
- 修改：`tests/test_spoken_text.py`

- [x] 测试人格提示词明确禁止舞台说明和情绪标签。
- [x] 在 `_OpenAICompatLLMStream._run()` 中清理每个流式片段，并在流结束时输出剩余合法文本。
- [x] 验证页面、记忆、转写和 TTS 共用的上游文本均为清理后文本。

### 任务 3：完整验证与提交

- [x] 执行 Python 编译检查。
- [x] 执行语音文本、人格语气和 Fish Audio 相关测试。
- [x] 执行 `git diff --check` 和敏感信息检查。
- [ ] 提交并推送当前分支。
