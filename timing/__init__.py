"""
时间同步模块
提供精确时间同步和音频合成功能
"""

from .sync_manager import PreciseSyncManager
from .audio_synthesizer import AudioSynthesizer

__all__ = ['PreciseSyncManager', 'AudioSynthesizer'] 