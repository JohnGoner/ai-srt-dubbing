"""
音频处理模块
包含字幕处理和智能分段等功能
"""

# 基础模块（无额外依赖）
from .subtitle_processor import SubtitleProcessor
from .subtitle_segmenter import SubtitleSegmenter

__all__ = ['SubtitleProcessor', 'SubtitleSegmenter'] 