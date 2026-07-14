"""峰哥 Fish Audio 人格语气编排单元测试。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from worker.fengge_prosody import FenggeProsodyPlanner  # noqa: E402


class FenggeProsodyPlannerTest(unittest.TestCase):
    """验证克制自然的峰哥语气选择规则。"""

    def setUp(self) -> None:
        """为每个用例创建默认人格编排器。"""
        self.planner = FenggeProsodyPlanner(mode="persona", intensity="subtle")

    def test_plain_text_keeps_original(self) -> None:
        """普通短句没有强信号时不得滥用标签。"""
        self.assertEqual(self.planner.decorate("你好啊，今天怎么样？"), "你好啊，今天怎么样？")

    def test_empty_text_keeps_original(self) -> None:
        """空文本和纯空白文本必须原样返回。"""
        self.assertEqual(self.planner.decorate(""), "")
        self.assertEqual(self.planner.decorate("  "), "  ")

    def test_confident_signal_uses_confident_tag(self) -> None:
        """判断前置和辩证反转应使用自信语气。"""
        for text in ("这是个好事儿啊", "我跟你说实话，这事别做", "说白了就是不合适"):
            with self.subTest(text=text):
                self.assertEqual(self.planner.decorate(text), f"[confident] {text}")

    def test_sarcastic_signal_uses_sarcastic_tag(self) -> None:
        """明显反讽和峰哥式收尾应使用调侃语气。"""
        for text in ("不就那么回事吗", "这不就完了吗", "面子有什么用，你说呢"):
            with self.subTest(text=text):
                self.assertEqual(self.planner.decorate(text), f"[sarcastic] {text}")

    def test_slang_requires_comparison_context(self) -> None:
        """峰哥黑话只有出现在明显类比中才触发调侃。"""
        comparison = "你这想法跟安卓用户一样，不就图个便宜吗"
        self.assertEqual(
            self.planner.decorate(comparison),
            f"[sarcastic] {comparison}",
        )
        self.assertEqual(self.planner.decorate("他说自己以前是力工"), "他说自己以前是力工")

    def test_excited_signal_uses_excited_tag(self) -> None:
        """真实成功和完成时刻应使用兴奋语气。"""
        for text in ("终于跑通了", "这个事成功了", "今天赢了"):
            with self.subTest(text=text):
                self.assertEqual(self.planner.decorate(text), f"[excited] {text}")

    def test_serious_signal_uses_calm_tag(self) -> None:
        """严肃敏感话题应使用克制语气。"""
        for text in ("这属于家暴，必须报警", "有人说自己想轻生", "这是诈骗和勒索"):
            with self.subTest(text=text):
                self.assertEqual(self.planner.decorate(text), f"[calm] {text}")

    def test_serious_signal_has_highest_priority(self) -> None:
        """严肃词与兴奋、调侃、自信同时出现时只能选择 calm。"""
        text = "终于发现这是家暴了，这不好事吗"

        decorated = self.planner.decorate(text)

        self.assertEqual(decorated, f"[calm] {text}")
        self.assertEqual(decorated.count("["), 1)

    def test_existing_bracket_tag_is_not_decorated_again(self) -> None:
        """已有 S2.1 方括号标签时不得叠加冲突情绪。"""
        text = "[relaxed] 这是个好事儿啊"
        self.assertEqual(self.planner.decorate(text), text)

    def test_off_mode_keeps_original(self) -> None:
        """关闭模式必须完全绕过人格标签。"""
        planner = FenggeProsodyPlanner(mode="off", intensity="subtle")
        self.assertEqual(planner.decorate("终于跑通了"), "终于跑通了")

    def test_invalid_mode_fails_at_startup(self) -> None:
        """未知模式必须在启动阶段明确失败。"""
        with self.assertRaisesRegex(RuntimeError, "FISH_AUDIO_PROSODY_MODE"):
            FenggeProsodyPlanner(mode="auto", intensity="subtle")

    def test_invalid_intensity_fails_at_startup(self) -> None:
        """未实现的强度必须在启动阶段明确失败。"""
        with self.assertRaisesRegex(RuntimeError, "FISH_AUDIO_PROSODY_INTENSITY"):
            FenggeProsodyPlanner(mode="persona", intensity="dramatic")


if __name__ == "__main__":
    unittest.main()
