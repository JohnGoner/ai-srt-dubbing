"""
统一的字幕片段数据结构
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from pydub import AudioSegment


@dataclass
class SegmentDTO:
    """
    统一的字幕片段数据传输对象
    用于标准化所有处理阶段的数据结构
    """
    # === 基础信息 ===
    id: str  # 片段唯一标识
    start: float  # 开始时间（秒）
    end: float  # 结束时间（秒）
    
    # === 文本内容 ===
    original_text: str  # 永远是最初字幕原文
    translated_text: str = ""  # 第一轮直译结果
    optimized_text: str = ""  # 算法/模型优化后的结果
    final_text: str = ""  # 给TTS用、且可被用户修改的最后文本
    
    # === 时间和音频信息 ===
    target_duration: float = 0.0  # 目标时长（秒）
    actual_duration: Optional[float] = None  # 实际音频时长（秒）
    speech_rate: float = 1.0  # 语速倍率
    
    # === 质量和状态 ===
    quality: Optional[str] = None  # 质量评级：excellent/good/fair/poor/error
    needs_user_confirmation: bool = False  # 是否需要用户确认
    confirmed: bool = False  # 用户是否已确认
    
    # === 时间同步分析 ===
    timing_error_ms: Optional[float] = None  # 时长误差（毫秒）
    timing_analysis: Dict[str, Any] = field(default_factory=dict)  # 详细时间分析
    
    # === 音频相关 ===
    audio_path: Optional[str] = None  # 音频文件路径（节省内存）
    audio_data: Optional[AudioSegment] = None  # 音频数据（临时使用）
    
    # === 处理历史和元数据 ===
    iterations: int = 0  # 优化迭代次数
    adjustment_suggestions: List[Dict[str, Any]] = field(default_factory=list)  # 调整建议
    user_modified: bool = False  # 用户是否手动修改过
    processing_metadata: Dict[str, Any] = field(default_factory=dict)  # 处理元数据
    
    # === 原始片段追踪 ===
    original_indices: List[int] = field(default_factory=list)  # 包含的原始片段编号（从1开始）
    
    # 兼容性字段（用于过渡期）
    text: str = ""  # 向后兼容
    duration: float = 0.0  # 向后兼容
    
    def __post_init__(self):
        """初始化后处理"""
        # 自动计算target_duration
        if self.target_duration == 0.0:
            self.target_duration = self.end - self.start
        
        # 向后兼容处理
        if self.duration == 0.0:
            self.duration = self.target_duration
        
        if not self.text and self.original_text:
            self.text = self.original_text
        
        # 确保original_indices存在且为列表
        if not hasattr(self, 'original_indices') or not isinstance(self.original_indices, list):
            self.original_indices = []
        
        # 修改：更明确的final_text设置逻辑
        if not self.final_text:
            # 优先使用optimized_text（经过优化的文本）
            if self.optimized_text:
                self.final_text = self.optimized_text
            # 其次使用translated_text（翻译文本）
            elif self.translated_text:
                self.final_text = self.translated_text
            # 最后使用original_text（原始文本）
            else:
                self.final_text = self.original_text
    
    @property 
    def sync_ratio(self) -> float:
        """时长同步比例"""
        if self.actual_duration is None or self.target_duration == 0:
            return 1.0
        return self.actual_duration / self.target_duration
    
    @property
    def timing_error_percent(self) -> float:
        """时长误差百分比"""
        return abs(self.sync_ratio - 1.0) * 100
    
    def get_current_text(self) -> str:
        """获取当前应该使用的文本"""
        return self.final_text or self.optimized_text or self.translated_text or self.original_text
    
    def update_final_text(self, new_text: str, mark_modified: bool = True):
        """更新最终文本"""
        self.final_text = new_text
        if mark_modified:
            self.user_modified = True
    
    def set_audio_data(self, audio: AudioSegment):
        """设置音频数据并自动计算actual_duration"""
        self.audio_data = audio
        if audio:
            self.actual_duration = len(audio) / 1000.0  # 转换为秒
    
    def clear_audio_data(self):
        """清理音频数据以节省内存"""
        self.audio_data = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于缓存和序列化）"""
        data = {
            'id': self.id,
            'start': self.start,
            'end': self.end,
            'original_text': self.original_text,
            'translated_text': self.translated_text,
            'optimized_text': self.optimized_text,
            'final_text': self.final_text,
            'target_duration': self.target_duration,
            'actual_duration': self.actual_duration,
            'speech_rate': self.speech_rate,
            'quality': self.quality,
            'needs_user_confirmation': self.needs_user_confirmation,
            'confirmed': self.confirmed,
            'timing_error_ms': self.timing_error_ms,
            'timing_analysis': self.timing_analysis,
            'audio_path': self.audio_path,
            'iterations': self.iterations,
            'adjustment_suggestions': self.adjustment_suggestions,
            'user_modified': self.user_modified,
            'processing_metadata': self.processing_metadata,
            'original_indices': self.original_indices,
            # 向后兼容字段
            'text': self.text,
            'duration': self.duration
        }
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SegmentDTO':
        """从字典创建实例（用于缓存恢复）"""
        # 处理audio_data字段（不从字典恢复，避免序列化问题）
        data = data.copy()
        data.pop('audio_data', None)
        
        return cls(**data)
    
    @classmethod
    def from_legacy_segment(cls, legacy_seg: Dict[str, Any]) -> 'SegmentDTO':
        """从旧版本的segment字典创建SegmentDTO实例"""
        return cls(
            id=legacy_seg.get('id', ''),
            start=legacy_seg.get('start', 0.0),
            end=legacy_seg.get('end', 0.0),
            original_text=legacy_seg.get('original_text', legacy_seg.get('text', '')),
            translated_text=legacy_seg.get('translated_text', ''),
            optimized_text=legacy_seg.get('optimized_text', ''),
            final_text=legacy_seg.get('final_text', ''),
            target_duration=legacy_seg.get('target_duration', legacy_seg.get('duration', 0.0)),
            actual_duration=legacy_seg.get('actual_duration'),
            speech_rate=legacy_seg.get('speech_rate', 1.0),
            quality=legacy_seg.get('quality'),
            needs_user_confirmation=legacy_seg.get('needs_user_confirmation', False),
            confirmed=legacy_seg.get('confirmed', False),
            timing_error_ms=legacy_seg.get('timing_error_ms'),
            timing_analysis=legacy_seg.get('timing_analysis', {}),
            audio_path=legacy_seg.get('audio_path'),
            audio_data=legacy_seg.get('audio_data'),
            iterations=legacy_seg.get('iterations', 0),
            adjustment_suggestions=legacy_seg.get('adjustment_suggestions', []),
            user_modified=legacy_seg.get('user_modified', legacy_seg.get('text_modified', False)),
            processing_metadata=legacy_seg.get('processing_metadata', {}),
            original_indices=legacy_seg.get('original_indices', []),
            # 向后兼容
            text=legacy_seg.get('text', ''),
            duration=legacy_seg.get('duration', 0.0)
        )
    
    def to_legacy_dict(self) -> Dict[str, Any]:
        """转换为旧版本兼容的字典格式"""
        return {
            'id': self.id,
            'start': self.start,
            'end': self.end,
            'text': self.original_text,
            'original_text': self.original_text,
            'translated_text': self.translated_text,
            'optimized_text': self.optimized_text,
            'final_text': self.final_text,
            'duration': self.target_duration,
            'target_duration': self.target_duration,
            'actual_duration': self.actual_duration,
            'speech_rate': self.speech_rate,
            'quality': self.quality,
            'needs_user_confirmation': self.needs_user_confirmation,
            'confirmed': self.confirmed,
            'timing_error_ms': self.timing_error_ms,
            'timing_analysis': self.timing_analysis,
            'audio_data': self.audio_data,
            'audio_path': self.audio_path,
            'iterations': self.iterations,
            'adjustment_suggestions': self.adjustment_suggestions,
            'text_modified': self.user_modified,
            'user_modified': self.user_modified,
            'processing_metadata': self.processing_metadata,
            'original_indices': self.original_indices
        } 