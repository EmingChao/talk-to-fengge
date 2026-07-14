"""语音回复舞台说明清理测试。"""

from __future__ import annotations

import unittest

from worker.persona import build_system_prompt
from worker.spoken_text import LeadingStageDirectionFilter


class LeadingStageDirectionFilterTest(unittest.TestCase):
    """验证回复开头的舞台说明不会进入公共文字链路。"""

    def test_removes_known_chinese_stage_direction(self) -> None:
        """中文括号包裹的已知舞台说明必须被删除。"""
        text_filter = LeadingStageDirectionFilter()

        output = text_filter.feed("（笑）牛逼什么啊") + text_filter.finish()

        self.assertEqual(output, "牛逼什么啊")

    def test_removes_stage_direction_across_chunks(self) -> None:
        """舞台说明被 LLM 拆成多个片段时也必须被完整删除。"""
        text_filter = LeadingStageDirectionFilter()

        output = "".join(
            [
                text_filter.feed("（"),
                text_filter.feed("笑"),
                text_filter.feed("）牛逼什么啊"),
                text_filter.finish(),
            ]
        )

        self.assertEqual(output, "牛逼什么啊")

    def test_removes_known_english_stage_direction(self) -> None:
        """英文括号包裹的已知舞台说明必须被删除。"""
        text_filter = LeadingStageDirectionFilter()

        output = text_filter.feed("(叹气) 这事没法说") + text_filter.finish()

        self.assertEqual(output, "这事没法说")

    def test_removes_leaked_fish_audio_tag(self) -> None:
        """LLM 泄漏的 Fish Audio 标签不得进入公共文字链路。"""
        text_filter = LeadingStageDirectionFilter()

        output = text_filter.feed("[sarcastic] 这不就完了吗") + text_filter.finish()

        self.assertEqual(output, "这不就完了吗")

    def test_preserves_normal_parenthetical_text(self) -> None:
        """不在舞台说明白名单中的正常括号正文必须保留。"""
        text_filter = LeadingStageDirectionFilter()

        output = text_filter.feed("（Python）这个工具能用") + text_filter.finish()

        self.assertEqual(output, "（Python）这个工具能用")

    def test_preserves_plain_streaming_text(self) -> None:
        """普通流式正文必须按原顺序输出。"""
        text_filter = LeadingStageDirectionFilter()

        output = "".join(
            [
                text_filter.feed("这是"),
                text_filter.feed("个好事儿啊"),
                text_filter.finish(),
            ]
        )

        self.assertEqual(output, "这是个好事儿啊")


class FenggePromptStageDirectionTest(unittest.TestCase):
    """验证人格提示词从源头约束舞台说明。"""

    def test_prompt_forbids_stage_directions(self) -> None:
        """提示词必须明确禁止括号动作和可见情绪标签。"""
        prompt = build_system_prompt("fengge")

        self.assertIn("禁止输出舞台说明", prompt)
        self.assertIn("Fish Audio 情绪标签", prompt)


if __name__ == "__main__":
    unittest.main()
