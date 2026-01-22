"""
工程数据模型 - ProjectDTO
管理AI配音工程的完整状态和数据
支持本地存储和 Firebase Firestore 云端存储
"""

import json
import hashlib
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from pathlib import Path
from loguru import logger

from .segment_dto import SegmentDTO


@dataclass
class ProjectDTO:
    """工程数据传输对象 - 包含配音工程的所有状态和数据"""
    
    # 基础信息
    id: str                                     # 工程唯一标识符
    name: str                                   # 工程名称
    description: str = ""                       # 工程描述
    
    # 元数据
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    version: str = "1.0"                       # 工程版本
    
    # 原始文件信息
    original_filename: str = ""                 # 原始SRT文件名
    file_hash: str = ""                        # 原始文件哈希
    file_size: int = 0                         # 原始文件大小
    
    # 处理状态
    processing_stage: str = "file_upload"       # 当前处理阶段
    completion_percentage: float = 0.0          # 完成百分比
    
    # 配置信息
    target_language: str = ""                   # 目标语言
    translation_service: str = "gpt"           # 翻译服务
    voice_settings: Dict[str, Any] = field(default_factory=dict)  # 语音设置
    
    # 处理数据 - 各阶段的结果
    segments: List[Dict[str, Any]] = field(default_factory=list)  # 原始片段
    segmented_segments: List[Dict[str, Any]] = field(default_factory=list)  # 分段结果
    confirmed_segments: List[Dict[str, Any]] = field(default_factory=list)  # 确认分段
    translated_segments: List[Dict[str, Any]] = field(default_factory=list)  # 翻译结果
    optimized_segments: List[Dict[str, Any]] = field(default_factory=list)  # 优化结果
    final_segments: List[Dict[str, Any]] = field(default_factory=list)  # 最终确认
    
    # 统计信息
    total_segments: int = 0                     # 总片段数
    total_duration: float = 0.0                 # 总时长（秒）
    processing_time: float = 0.0               # 处理用时（秒）
    
    # API使用统计
    api_usage: Dict[str, Any] = field(default_factory=dict)  # API使用统计
    
    # 质量评估
    quality_stats: Dict[str, Any] = field(default_factory=dict)  # 质量统计
    
    # 标签和分类
    tags: List[str] = field(default_factory=list)  # 工程标签
    category: str = ""                          # 工程类别
    
    # 共享信息
    is_shared: bool = False                     # 是否共享
    share_url: str = ""                        # 分享链接
    created_by: str = ""                       # 创建者（向后兼容）
    
    # Firebase 用户隔离
    owner_id: str = ""                          # 所属用户 ID（Firebase 用户隔离）
    storage_backend: str = "local"              # 存储后端: "local" 或 "firebase"
    audio_storage_paths: Dict[str, str] = field(default_factory=dict)  # 音频文件云端路径映射
    
    # 最终输出文件存储路径（Firebase Storage）
    final_audio_storage_path: str = ""          # 最终音频文件云端路径
    final_subtitle_storage_path: str = ""       # 最终字幕文件云端路径
    
    # TTS 配置
    tts_service: str = ""                       # 使用的 TTS 服务 (minimax/elevenlabs)
    tts_voice_id: str = ""                      # 使用的音色 ID
    
    def __post_init__(self):
        """初始化后处理"""
        if not self.id:
            self.id = self._generate_project_id()
        
        # 更新统计信息
        self._update_statistics()
    
    def _generate_project_id(self) -> str:
        """生成工程唯一标识符"""
        # 基于创建时间和随机数生成唯一ID
        content = f"{self.name}_{self.created_at}_{self.original_filename}_{id(self)}"
        return hashlib.md5(content.encode('utf-8')).hexdigest()[:12]
    
    def _update_statistics(self):
        """更新统计信息"""
        try:
            # 统计片段数
            active_segments = self.get_active_segments()
            self.total_segments = len(active_segments)
            
            # 计算总时长
            if active_segments:
                self.total_duration = max(
                    seg.get('end', 0) for seg in active_segments
                ) if active_segments else 0.0
            
            # 更新完成百分比
            self.completion_percentage = self._calculate_completion_percentage()
            
            # 更新时间
            self.updated_at = datetime.now(timezone.utc).isoformat()
            
        except Exception as e:
            logger.warning(f"更新工程统计信息失败: {e}")
    
    def _calculate_completion_percentage(self) -> float:
        """计算完成百分比"""
        stage_weights = {
            'file_upload': 0.0,
            'segmentation': 10.0,
            'confirm_segmentation': 20.0,
            'language_selection': 30.0,
            'translating': 50.0,
            'user_confirmation': 80.0,
            'completion': 100.0
        }
        return stage_weights.get(self.processing_stage, 0.0)
    
    def get_active_segments(self) -> List[Dict[str, Any]]:
        """获取当前活跃的片段数据（根据处理阶段）"""
        if self.final_segments:
            return self.final_segments
        elif self.optimized_segments:
            return self.optimized_segments
        elif self.translated_segments:
            return self.translated_segments
        elif self.confirmed_segments:
            return self.confirmed_segments
        elif self.segmented_segments:
            return self.segmented_segments
        else:
            return self.segments
    
    def update_processing_stage(self, stage: str, segments: Optional[List[SegmentDTO]] = None):
        """更新处理阶段和相关数据"""
        self.processing_stage = stage
        
        # 根据阶段保存相应的片段数据
        if segments:
            segment_dicts = [
                seg.to_legacy_dict() if isinstance(seg, SegmentDTO) else seg
                for seg in segments
            ]
            
            if stage in ['segmentation', 'confirm_segmentation']:
                if stage == 'segmentation':
                    self.segmented_segments = segment_dicts
                else:
                    self.confirmed_segments = segment_dicts
            elif stage == 'translating':
                self.translated_segments = segment_dicts
            elif stage == 'user_confirmation':
                self.optimized_segments = segment_dicts
            elif stage == 'completion':
                self.final_segments = segment_dicts
        
        # 更新统计信息
        self._update_statistics()
        
        logger.info(f"工程 {self.name} 更新至阶段: {stage} ({self.completion_percentage:.1f}%)")
    
    def set_file_info(self, filename: str, file_content: bytes):
        """设置原始文件信息"""
        self.original_filename = filename
        self.file_hash = hashlib.md5(file_content).hexdigest()
        self.file_size = len(file_content)
        self.updated_at = datetime.now(timezone.utc).isoformat()
    
    def set_translation_config(self, target_lang: str, service: str = "gpt", voice_settings: Optional[Dict] = None):
        """设置翻译和语音配置"""
        self.target_language = target_lang
        self.translation_service = service
        if voice_settings:
            self.voice_settings.update(voice_settings)
        self._update_statistics()
    
    def add_api_usage(self, service: str, usage_data: Dict[str, Any]):
        """添加API使用统计"""
        if service not in self.api_usage:
            self.api_usage[service] = {}
        
        # 累加使用量
        for key, value in usage_data.items():
            if isinstance(value, (int, float)):
                self.api_usage[service][key] = self.api_usage[service].get(key, 0) + value
            else:
                self.api_usage[service][key] = value
        
        self.updated_at = datetime.now(timezone.utc).isoformat()
    
    def update_quality_stats(self, quality_data: Dict[str, Any]):
        """更新质量统计"""
        self.quality_stats.update(quality_data)
        self.updated_at = datetime.now(timezone.utc).isoformat()
    
    def add_tags(self, tags: List[str]):
        """添加标签"""
        for tag in tags:
            if tag not in self.tags:
                self.tags.append(tag)
        self.updated_at = datetime.now(timezone.utc).isoformat()
    
    def set_share_info(self, share_url: str = "", created_by: str = ""):
        """设置分享信息"""
        self.is_shared = bool(share_url)
        self.share_url = share_url
        if created_by:
            self.created_by = created_by
        self.updated_at = datetime.now(timezone.utc).isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return asdict(self)
    
    def to_json(self, indent: int = 2) -> str:
        """转换为JSON字符串"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ProjectDTO':
        """从字典创建工程对象"""
        return cls(**data)
    
    @classmethod
    def from_json(cls, json_str: str) -> 'ProjectDTO':
        """从JSON字符串创建工程对象"""
        data = json.loads(json_str)
        return cls.from_dict(data)
    
    @classmethod
    def create_from_file(cls, filename: str, file_content: bytes, name: str = "", description: str = "") -> 'ProjectDTO':
        """从SRT文件创建新工程"""
        if not name:
            name = Path(filename).stem
        
        project = cls(
            id="",  # 将在__post_init__中生成
            name=name,
            description=description
        )
        
        project.set_file_info(filename, file_content)
        return project
    
    @classmethod
    def from_legacy_cache(cls, cache_data: Dict[str, Any], name: str = "") -> 'ProjectDTO':
        """从旧的缓存数据创建工程"""
        project = cls(
            id="",  # 将在__post_init__中生成
            name=name or "导入的工程",
            description="从缓存数据导入的工程"
        )
        
        # 映射缓存数据到工程结构
        if 'segmentation' in cache_data:
            seg_data = cache_data['segmentation']
            if 'original_segments' in seg_data:
                project.segments = seg_data['original_segments']
            if 'confirmed_segments' in seg_data:
                project.confirmed_segments = seg_data['confirmed_segments']
                project.processing_stage = 'confirm_segmentation'
        
        if 'translation' in cache_data:
            trans_data = cache_data['translation']
            if 'translated_segments' in trans_data:
                project.translated_segments = trans_data['translated_segments']
                project.processing_stage = 'translating'
        
        if 'confirmation' in cache_data:
            conf_data = cache_data['confirmation']
            if 'optimized_segments' in conf_data:
                project.optimized_segments = conf_data['optimized_segments']
                project.processing_stage = 'user_confirmation'
        
        # 设置目标语言
        if 'target_lang' in cache_data:
            project.target_language = cache_data['target_lang']
        
        project._update_statistics()
        return project
    
    def get_display_name(self) -> str:
        """获取显示名称"""
        return f"{self.name} ({self.target_language})" if self.target_language else self.name
    
    def get_status_text(self) -> str:
        """获取状态文本"""
        stage_names = {
            'file_upload': '文件上传',
            'segmentation': '智能分段',
            'confirm_segmentation': '分段确认',
            'language_selection': '语言选择',
            'translating': '翻译中',
            'user_confirmation': '音频确认',
            'completion': '已完成'
        }
        return stage_names.get(self.processing_stage, self.processing_stage)
    
    def is_completed(self) -> bool:
        """工程是否已完成"""
        return self.processing_stage == 'completion'
    
    def can_resume(self) -> bool:
        """工程是否可以继续"""
        return self.processing_stage not in ['file_upload', 'completion']
    
    def get_summary(self) -> Dict[str, Any]:
        """获取工程摘要信息"""
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'status': self.get_status_text(),
            'progress': f"{self.completion_percentage:.1f}%",
            'target_language': self.target_language,
            'total_segments': self.total_segments,
            'total_duration': f"{self.total_duration:.1f}s",
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'is_shared': self.is_shared,
            'tags': self.tags
        }
    
    # ==================== Firebase/Firestore 支持 ====================
    
    def set_owner(self, user_id: str):
        """设置项目所有者"""
        self.owner_id = user_id
        # 向后兼容
        if not self.created_by:
            self.created_by = user_id
        self.updated_at = datetime.now(timezone.utc).isoformat()
    
    def to_firestore_dict(self) -> Dict[str, Any]:
        """
        转换为 Firestore 兼容的字典格式
        - 移除不可序列化的对象（如 AudioSegment）
        - 移除不需要持久化的调试数据（节省存储空间）
        - 移除重复的向后兼容字段
        - 清理空值和 None
        
        Returns:
            Firestore 兼容的字典
        """
        data = asdict(self)
        
        # === 优化：定义需要从 segment 中移除的字段 ===
        # 1. 调试/临时数据（用完即弃，不需要持久化）
        # 2. 重复的向后兼容字段
        SEGMENT_FIELDS_TO_EXCLUDE = {
            # 调试数据 - UI 展示用，确认后无需保存
            'timing_analysis',        # 时长分析详情，约 200 字节/段
            'adjustment_suggestions', # 调整建议列表，约 300+ 字节/段
            'processing_metadata',    # 临时处理元数据
            # 重复字段 - 与其他字段完全相同
            'text',                   # 与 original_text 重复
            'duration',               # 与 target_duration 重复
            'text_modified',          # 与 user_modified 重复
            # 不可序列化
            'audio_data',             # AudioSegment 对象
        }
        
        segment_fields = [
            'segments', 'segmented_segments', 'confirmed_segments',
            'translated_segments', 'optimized_segments', 'final_segments'
        ]
        
        for field_name in segment_fields:
            if field_name in data and data[field_name]:
                cleaned_segments = []
                for seg in data[field_name]:
                    if isinstance(seg, dict):
                        # 移除不需要的字段
                        clean_seg = {
                            k: v for k, v in seg.items() 
                            if k not in SEGMENT_FIELDS_TO_EXCLUDE
                        }
                        # 移除空值（空字符串、空列表、空字典）以节省空间
                        clean_seg = {
                            k: v for k, v in clean_seg.items() 
                            if v not in [None, "", [], {}]
                        }
                        # 确保 audio_path 存在（用于 Firebase Storage 引用）
                        if 'audio_path' not in clean_seg:
                            clean_seg['audio_path'] = None
                        cleaned_segments.append(clean_seg)
                    else:
                        cleaned_segments.append(seg)
                data[field_name] = cleaned_segments
        
        # 确保所有值都是 Firestore 兼容的类型
        data = self._clean_for_firestore(data)
        
        return data
    
    def _clean_for_firestore(self, data: Any) -> Any:
        """
        递归清理数据，确保 Firestore 兼容
        """
        if data is None:
            return None
        elif isinstance(data, dict):
            return {k: self._clean_for_firestore(v) for k, v in data.items() if v is not None}
        elif isinstance(data, list):
            return [self._clean_for_firestore(item) for item in data if item is not None]
        elif isinstance(data, (str, int, float, bool)):
            return data
        elif hasattr(data, '__class__') and data.__class__.__name__ == 'AudioSegment':
            # AudioSegment 对象不存储
            return None
        else:
            # 尝试转换为字符串
            try:
                return str(data)
            except:
                return None
    
    @classmethod
    def from_firestore_dict(cls, data: Dict[str, Any]) -> 'ProjectDTO':
        """
        从 Firestore 文档创建 ProjectDTO 对象
        
        Args:
            data: Firestore 文档数据
            
        Returns:
            ProjectDTO 实例
        """
        # 移除 Firestore 特有的字段
        clean_data = {k: v for k, v in data.items() if not k.startswith('_')}
        
        # 处理可能缺失的新字段（向后兼容）
        if 'owner_id' not in clean_data:
            clean_data['owner_id'] = clean_data.get('created_by', '')
        if 'storage_backend' not in clean_data:
            clean_data['storage_backend'] = 'firebase'
        if 'audio_storage_paths' not in clean_data:
            clean_data['audio_storage_paths'] = {}
        
        return cls(**clean_data)
    
    def get_index_entry(self) -> Dict[str, Any]:
        """
        获取用于索引的简化数据（用于 Firestore 索引集合）
        
        Returns:
            索引条目字典
        """
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description[:200] if self.description else '',
            'owner_id': self.owner_id,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'processing_stage': self.processing_stage,
            'completion_percentage': self.completion_percentage,
            'target_language': self.target_language,
            'total_segments': self.total_segments,
            'total_duration': self.total_duration,
            'original_filename': self.original_filename,
            'file_size': self.file_size,
            'tags': self.tags,
            'category': self.category,
            'is_shared': self.is_shared,
            'storage_backend': self.storage_backend
        }
    
    def update_audio_storage_path(self, segment_id: str, storage_path: str):
        """
        更新片段的音频存储路径（Firebase Storage）
        
        Args:
            segment_id: 片段 ID
            storage_path: Firebase Storage 路径
        """
        self.audio_storage_paths[segment_id] = storage_path
        self.updated_at = datetime.now(timezone.utc).isoformat()
    
    def get_audio_storage_path(self, segment_id: str) -> Optional[str]:
        """获取片段的音频存储路径"""
        return self.audio_storage_paths.get(segment_id)
    
    def set_final_output_paths(self, audio_path: str = "", subtitle_path: str = ""):
        """
        设置最终输出文件的云端存储路径
        
        Args:
            audio_path: 最终音频文件的 Firebase Storage 路径
            subtitle_path: 最终字幕文件的 Firebase Storage 路径
        """
        if audio_path:
            self.final_audio_storage_path = audio_path
        if subtitle_path:
            self.final_subtitle_storage_path = subtitle_path
        self.updated_at = datetime.now(timezone.utc).isoformat()
    
    def set_tts_config(self, service: str, voice_id: str = ""):
        """
        设置 TTS 服务配置
        
        Args:
            service: TTS 服务名称 (minimax/elevenlabs)
            voice_id: 使用的音色 ID
        """
        self.tts_service = service
        self.tts_voice_id = voice_id
        self.updated_at = datetime.now(timezone.utc).isoformat()
    
    def get_tts_config(self) -> Dict[str, str]:
        """获取 TTS 服务配置"""
        return {
            'service': self.tts_service,
            'voice_id': self.tts_voice_id
        }