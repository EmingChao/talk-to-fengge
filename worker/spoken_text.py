"""语音回复公共文本的流式清理规则。"""

from __future__ import annotations

_STAGE_DIRECTIONS = {
    "笑",
    "笑着",
    "大笑",
    "轻笑",
    "冷笑",
    "苦笑",
    "叹气",
    "沉默",
    "停顿",
    "摇头",
    "点头",
    "清嗓",
    "咳嗽",
}
_FISH_AUDIO_TAGS = {
    "angry",
    "calm",
    "confident",
    "disgusted",
    "excited",
    "laughing",
    "sad",
    "sarcastic",
    "scared",
    "shouting",
    "sighing",
    "surprised",
    "whispering",
}
_MAX_PREFIX_LENGTH = 64


class LeadingStageDirectionFilter:
    """跨 LLM 分块删除回复开头的已知舞台说明和情绪标签。"""

    def __init__(self) -> None:
        """初始化尚未判断完成的回复前缀。"""
        self._buffer = ""
        self._resolved = False

    def feed(self, chunk: str) -> str:
        """接收一个 LLM 文本块，并返回当前可以安全公开的正文。"""
        if self._resolved:
            return chunk
        self._buffer += chunk
        return self._resolve(final=False)

    def finish(self) -> str:
        """结束输入并返回未构成已知舞台说明的剩余文字。"""
        if self._resolved:
            return ""
        return self._resolve(final=True)

    def _resolve(self, *, final: bool) -> str:
        """持续剥离已知前缀，遇到普通正文后停止缓冲。"""
        while self._buffer:
            prefix_start = len(self._buffer) - len(self._buffer.lstrip())
            candidate = self._buffer[prefix_start:]
            if not candidate:
                if final:
                    return self._release_buffer()
                return ""

            opening = candidate[0]
            closing = {"（": "）", "(": ")", "[": "]"}.get(opening)
            if closing is None:
                return self._release_buffer()

            closing_index = candidate.find(closing, 1)
            if closing_index < 0:
                if not final and len(candidate) <= _MAX_PREFIX_LENGTH:
                    return ""
                return self._release_buffer()

            marker = candidate[1:closing_index].strip().lower()
            known_marker = (
                marker in _FISH_AUDIO_TAGS
                if opening == "["
                else marker in _STAGE_DIRECTIONS
            )
            if not known_marker:
                return self._release_buffer()

            # 已识别的标记及其后空白只用于表达控制，不进入公共正文。
            self._buffer = candidate[closing_index + 1 :].lstrip()

        if final:
            self._resolved = True
        return ""

    def _release_buffer(self) -> str:
        """确认是普通正文后一次释放缓冲，并直接透传后续分块。"""
        output = self._buffer
        self._buffer = ""
        self._resolved = True
        return output
