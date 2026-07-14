"""Cartesia STT with proxy support."""

from __future__ import annotations

import os
import aiohttp
from livekit.plugins import cartesia

def build_cartesia_stt(*, sample_rate: int | None = None):
    api_key = os.getenv("CARTESIA_API_KEY", "")
    if not api_key:
        raise ValueError("CARTESIA_API_KEY is required")

    # 创建带代理的aiohttp session
    session = aiohttp.ClientSession(
        trust_env=False,
        timeout=aiohttp.ClientTimeout(total=120, connect=15),
    )

    return cartesia.STT(
        model=os.getenv("CARTESIA_STT_MODEL", "ink-whisper"),
        sample_rate=sample_rate or int(os.getenv("DEEPGRAM_SAMPLE_RATE", "22050")),
        api_key=api_key,
        language="zh",
        http_session=session,
    )
