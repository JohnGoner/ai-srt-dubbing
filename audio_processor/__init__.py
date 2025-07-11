"""
音频处理模块
包含字幕处理和智能分段等功能
"""

# 基础模块（无额外依赖）
from .subtitle_processor import SubtitleProcessor
from .subtitle_segmenter import SubtitleSegmenter

# 可选模块（有额外依赖，按需导入）
__all__ = ['SubtitleProcessor', 'SubtitleSegmenter']

# 延迟导入（避免启动时的依赖问题）
def get_audio_extractor():
    """获取音频提取器（延迟导入）"""
    try:
        from .audio_extractor import AudioExtractor
        return AudioExtractor
    except ImportError as e:
        raise ImportError(f"音频提取功能需要额外的依赖包") from e 