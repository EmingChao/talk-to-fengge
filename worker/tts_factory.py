"""TTS 工厂：根据 TTS_PROVIDER 创建语音合成实现。

设计目标：
- 单一入口 build_tts(provider, ...) -> (tts_instance, label)
- 各 provider 互不耦合，加新 provider 只改这里
- 旧 provider 仍可降级到 MOSS；Fish Audio 与 MiMo 配置错误直接报告
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Tuple

from dotenv import load_dotenv

# 兼容单元测试：factory 被直接 import 时也读到 .env.local
PROJECT_ROOT = Path(__file__).resolve().parent.parent
for env_name in (".env.local", ".env"):
    env_file = PROJECT_ROOT / env_name
    if env_file.exists():
        load_dotenv(env_file)
        break

from worker.moss_tts import MossHttpTTS


def _build_voxcpm() -> Tuple[object, str]:
    """VoxCPM2 声音克隆 TTS（RunPod 云 GPU + SSH 隧道）。"""
    from worker.voxcpm_tts import VoxCPMHttpTTS

    url = os.getenv("VOXCPM_URL", "http://localhost:8000").strip()
    voice = os.getenv("VOXCPM_VOICE", "fengge").strip()
    style = os.getenv("VOXCPM_STYLE", "").strip()
    sample_rate = int(os.getenv("VOXCPM_SAMPLE_RATE", "24000").strip())

    tts = VoxCPMHttpTTS(url=url, voice=voice, style=style, sample_rate=sample_rate)
    label = f"voxcpm:{url}/{voice}"
    return tts, label


def _build_cartesia() -> Tuple[object, str]:
    """Cartesia sonic-3 工厂。"""
    from livekit.plugins.cartesia import TTS as CartesiaTTS

    api_key = os.getenv("CARTESIA_API_KEY", "").strip()
    voice_id = os.getenv("CARTESIA_VOICE_ID", "").strip()
    model = os.getenv("CARTESIA_MODEL", "sonic-3").strip()
    language = os.getenv("CARTESIA_LANGUAGE", "zh").strip()
    _speed_raw = os.getenv("CARTESIA_SPEED", "").strip()
    speed: float | None = float(_speed_raw) if _speed_raw else None

    if not api_key:
        raise RuntimeError("CARTESIA_API_KEY not set in .env.local")
    if not voice_id:
        raise RuntimeError("CARTESIA_VOICE_ID not set in .env.local")

    tts = CartesiaTTS(
        api_key=api_key,
        model=model,
        voice=voice_id,
        language=language,
        sample_rate=24000,
        word_timestamps=False,  # 中文用 sonic 模型时不支持 word_timestamps，关闭避免 warning
        speed=speed,
    )
    label = f"cartesia:{model}/{voice_id[:8]}/{language}"
    return tts, label


def _build_minimax() -> Tuple[object, str]:
    """MiniMax speech-02 工厂。"""
    from worker.minimax_tts_plugin import MinimaxTTS  # 阶段 24

    api_key = os.getenv("MINIMAX_API_KEY", "").strip()
    voice_id = os.getenv("MINIMAX_VOICE_ID", "").strip()
    model = os.getenv("MINIMAX_MODEL", "speech-02-turbo").strip()
    sample_rate = int(os.getenv("MINIMAX_SAMPLE_RATE", "24000").strip())
    language_boost = os.getenv("MINIMAX_LANGUAGE_BOOST", "Chinese").strip()

    if not api_key:
        raise RuntimeError("MINIMAX_API_KEY not set in .env.local")
    if not voice_id:
        raise RuntimeError("MINIMAX_VOICE_ID not set in .env.local")

    tts = MinimaxTTS(
        api_key=api_key,
        voice_id=voice_id,
        model=model,
        sample_rate=sample_rate,
        language_boost=language_boost,
    )
    label = f"minimax:{model}/{voice_id[:12]}/{language_boost}/{sample_rate}Hz"
    return tts, label


def _build_mimo() -> Tuple[object, str]:
    """创建小米 MiMo VoiceClone TTS。"""
    from worker.mimo_tts import MiMoVoiceCloneTTS

    api_key = os.getenv("MIMO_TTS_API_KEY", "").strip()
    base_url = os.getenv(
        "MIMO_TTS_BASE_URL",
        "https://api.xiaomimimo.com/v1",
    ).strip()
    model = os.getenv("MIMO_TTS_MODEL", "mimo-v2.5-tts-voiceclone").strip()
    voice_file_raw = os.getenv(
        "MIMO_TTS_VOICE_FILE",
        "assets/voice_samples/fengge_ref.wav",
    ).strip()
    voice_file = Path(voice_file_raw)
    if not voice_file.is_absolute():
        voice_file = PROJECT_ROOT / voice_file
    style_prompt = os.getenv("MIMO_TTS_STYLE_PROMPT", "").strip()

    tts = MiMoVoiceCloneTTS(
        api_key=api_key,
        base_url=base_url,
        model=model,
        voice_file=voice_file,
        style_prompt=style_prompt,
    )
    return tts, f"mimo:{model}/{voice_file.name}/24000Hz"


def _build_fish_audio() -> Tuple[object, str]:
    """创建 Fish Audio 流式音色克隆 TTS。"""
    from worker.fish_audio_tts import FishAudioTTS

    api_key = os.getenv("FISH_AUDIO_API_KEY", "").strip()
    base_url = os.getenv(
        "FISH_AUDIO_BASE_URL",
        "https://api.fish.audio/v1",
    ).strip()
    model = os.getenv("FISH_AUDIO_MODEL", "s2.1-pro-free").strip()
    reference_id = os.getenv(
        "FISH_AUDIO_REFERENCE_ID",
        "9344a2478df54929a786395f558b1267",
    ).strip()
    sample_rate = int(os.getenv("FISH_AUDIO_SAMPLE_RATE", "24000").strip())
    latency = os.getenv("FISH_AUDIO_LATENCY", "balanced").strip()
    chunk_length = int(os.getenv("FISH_AUDIO_CHUNK_LENGTH", "300").strip())
    min_chunk_length = int(
        os.getenv("FISH_AUDIO_MIN_CHUNK_LENGTH", "50").strip()
    )
    speed = float(os.getenv("FISH_AUDIO_SPEED", "1.0").strip())

    tts = FishAudioTTS(
        api_key=api_key,
        base_url=base_url,
        model=model,
        reference_id=reference_id,
        sample_rate=sample_rate,
        latency=latency,
        chunk_length=chunk_length,
        min_chunk_length=min_chunk_length,
        speed=speed,
    )
    label = f"fish_audio:{model}/{reference_id[:12]}/{sample_rate}Hz/{latency}"
    return tts, label


def _build_moss(moss_url: str, moss_voice: str) -> Tuple[object, str]:
    """MOSS 本地 CPU TTS（兜底方案）。"""
    tts = MossHttpTTS(url=moss_url, voice=moss_voice)
    return tts, f"moss:{moss_voice}"


def build_tts(provider: str, moss_url: str, moss_voice: str) -> Tuple[object, str]:
    """按 provider 选 TTS；provider 失败自动降级到 moss。

    Returns:
        (tts_instance, label_for_log)
    """
    provider = (provider or "fish_audio").strip().lower()
    started = time.time()

    # 默认供应商配置错误必须在启动阶段暴露，避免静默换成错误音色。
    if provider in ("fish_audio", "fish"):
        tts, label = _build_fish_audio()
        print(f"[tts_factory] loaded {label} in {(time.time()-started)*1000:.0f}ms", flush=True)
        return tts, label

    # MiMo 的 Token Plan 与按量密钥不可混用，因此同样不做静默降级。
    if provider in ("mimo", "xiaomi"):
        tts, label = _build_mimo()
        print(f"[tts_factory] loaded {label} in {(time.time()-started)*1000:.0f}ms", flush=True)
        return tts, label

    # 1. 优先按 provider 选
    if provider == "voxcpm":
        try:
            tts, label = _build_voxcpm()
            print(f"[tts_factory] loaded {label} in {(time.time()-started)*1000:.0f}ms", flush=True)
            return tts, label
        except Exception as exc:
            print(f"[tts_factory] voxcpm init failed: {exc!r} - falling back to moss", flush=True)

    elif provider == "cartesia":
        try:
            tts, label = _build_cartesia()
            print(f"[tts_factory] loaded {label} in {(time.time()-started)*1000:.0f}ms", flush=True)
            return tts, label
        except Exception as exc:
            print(f"[tts_factory] cartesia init failed: {exc!r} - falling back to moss", flush=True)

    if provider == "minimax":
        try:
            tts, label = _build_minimax()
            print(f"[tts_factory] loaded {label} in {(time.time()-started)*1000:.0f}ms", flush=True)
            return tts, label
        except Exception as exc:
            print(f"[tts_factory] minimax init failed: {exc!r} - falling back to moss", flush=True)

    elif provider == "moss":
        tts, label = _build_moss(moss_url, moss_voice)
        print(f"[tts_factory] loaded {label} in {(time.time()-started)*1000:.0f}ms", flush=True)
        return tts, label

    else:
        print(f"[tts_factory] unknown provider={provider!r} - falling back to moss", flush=True)

    # 2. 兜底 MOSS
    tts, label = _build_moss(moss_url, moss_voice)
    print(f"[tts_factory] fallback to {label}", flush=True)
    return tts, label
