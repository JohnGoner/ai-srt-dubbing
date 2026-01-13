"""
工程数据模型 - ProjectDTO
管理AI配音工程的完整状态和数据
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
    created_by: str = ""                       # 创建者
    
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
