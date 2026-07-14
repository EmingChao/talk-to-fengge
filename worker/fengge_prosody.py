"""峰哥人格的 Fish Audio S2.1 语气编排规则。"""

from __future__ import annotations

import re

_SUPPORTED_MODES = {"persona", "off"}
_SUPPORTED_INTENSITIES = {"subtle"}
_LEADING_FISH_TAG = re.compile(r"^\s*\[[^\]\r\n]{1,64}\]")

_CALM_SIGNALS = (
    "生病",
    "重病",
    "住院",
    "去世",
    "死亡",
    "家暴",
    "打人",
    "威胁",
    "报警",
    "自杀",
    "自伤",
    "轻生",
    "违法",
    "犯罪",
    "诈骗",
    "勒索",
)
_EXCITED_SIGNALS = (
    "终于",
    "跑通了",
    "成功了",
    "搞定了",
    "赢了",
    "赚了",
    "中了",
)
_SARCASTIC_SIGNALS = (
    "不就那么回事吗",
    "这不就完了吗",
    "你说呢",
    "面子有什么用",
)
_CONFIDENT_SIGNALS = (
    "这是个好事儿啊",
    "这不好事吗",
    "我跟你说实话",
    "说白了",
    "你知道最惨的是什么吗",
)
_FENGGE_SLANG = ("苹果用户", "安卓用户", "力工", "魅力男孩")
_COMPARISON_SIGNALS = ("像", "跟", "一样", "不就", "相当于")


class FenggeProsodyPlanner:
    """按峰哥人格强信号为 Fish Audio 文本选择克制语气。"""

    def __init__(
        self,
        *,
        mode: str = "persona",
        intensity: str = "subtle",
    ) -> None:
        """校验模式和强度，并保存不可变配置。"""
        normalized_mode = mode.strip().lower()
        normalized_intensity = intensity.strip().lower()
        if normalized_mode not in _SUPPORTED_MODES:
            raise RuntimeError("FISH_AUDIO_PROSODY_MODE 仅支持 persona 或 off")
        if normalized_intensity not in _SUPPORTED_INTENSITIES:
            raise RuntimeError("FISH_AUDIO_PROSODY_INTENSITY 当前仅支持 subtle")
        self._mode = normalized_mode
        self._intensity = normalized_intensity

    def decorate(self, text: str) -> str:
        """按 calm、excited、sarcastic、confident 优先级装饰文本。"""
        if self._mode == "off" or not text.strip():
            return text
        if _LEADING_FISH_TAG.match(text):
            return text

        tag = self._select_tag(text)
        if tag is None:
            return text
        return f"[{tag}] {text}"

    def _select_tag(self, text: str) -> str | None:
        """按人格优先级选择最多一个 Fish Audio 主情绪。"""
        if self._contains_any(text, _CALM_SIGNALS):
            return "calm"
        if self._contains_any(text, _EXCITED_SIGNALS):
            return "excited"
        if self._contains_any(text, _SARCASTIC_SIGNALS):
            return "sarcastic"
        if self._contains_slang_comparison(text):
            return "sarcastic"
        if self._contains_any(text, _CONFIDENT_SIGNALS):
            return "confident"
        return None

    @staticmethod
    def _contains_any(text: str, signals: tuple[str, ...]) -> bool:
        """判断文本是否包含任一强触发信号。"""
        return any(signal in text for signal in signals)

    def _contains_slang_comparison(self, text: str) -> bool:
        """仅在黑话与类比词同时出现时识别为峰哥式调侃。"""
        return self._contains_any(text, _FENGGE_SLANG) and self._contains_any(
            text,
            _COMPARISON_SIGNALS,
        )
