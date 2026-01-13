"""
工程集成模块
在各个处理阶段集成工程管理功能，提供工程的保存、加载和状态更新
"""

from typing import Dict, Any, Optional, List
from loguru import logger
from pathlib import Path
import streamlit as st
import hashlib
import time

from .project_manager import get_project_manager
from .cache_integration import get_cache_integration
from models.project_dto import ProjectDTO
from models.segment_dto import SegmentDTO


class ProjectIntegration:
    """工程集成类 - 管理工程的完整生命周期集成"""
    
    def __init__(self):
        """初始化工程集成"""
        self.project_manager = get_project_manager()
        self.cache_integration = get_cache_integration()  # 兼容旧缓存系统
        
    def create_project_from_file(self, filename: str, file_content: bytes, 
                               project_name: str = "", description: str = "") -> Optional[ProjectDTO]:
        """
        从SRT文件创建新工程
        
        Args:
            filename: 文件名
            file_content: 文件内容
            project_name: 工程名称
            description: 工程描述
            
        Returns:
            创建的工程对象
        """
        try:
            if not project_name:
                project_name = Path(filename).stem
                
            project = self.project_manager.create_project(
                name=project_name,
                filename=filename,
                file_content=file_content,
                description=description
            )
            
            logger.info(f"从文件创建工程成功: {project.name}")
            return project
            
        except Exception as e:
            logger.error(f"从文件创建工程失败: {e}")
            return None
    
    def save_project_state(self, project: ProjectDTO, session_data: Dict[str, Any]) -> bool:
        """
        保存工程状态（从session数据更新工程）
        
        Args:
            project: 工程对象
            session_data: 当前会话数据
            
        Returns:
            是否保存成功
        """
        try:
            # 从session_data更新工程状态
            processing_stage = session_data.get('processing_stage', 'file_upload')
            
            # 根据处理阶段更新工程数据
            if processing_stage == 'segmentation':
                # 分段处理阶段
                if 'segments' in session_data:
                    project.segments = [
                        seg.to_legacy_dict() if isinstance(seg, SegmentDTO) else seg
                        for seg in session_data['segments']
                    ]
                if 'segmented_segments' in session_data:
                    project.segmented_segments = [
                        seg.to_legacy_dict() if isinstance(seg, SegmentDTO) else seg
                        for seg in session_data['segmented_segments']
                    ]
            elif processing_stage == 'confirm_segmentation':
                # 确保原始片段数据也被保存
                if 'segments' in session_data and not project.segments:
                    project.segments = [
                        seg.to_legacy_dict() if isinstance(seg, SegmentDTO) else seg
                        for seg in session_data['segments']
                    ]
                if 'segmented_segments' in session_data:
                    project.segmented_segments = [
                        seg.to_legacy_dict() if isinstance(seg, SegmentDTO) else seg
                        for seg in session_data['segmented_segments']
                    ]
                if 'confirmed_segments' in session_data:
                    project.confirmed_segments = [
                        seg.to_legacy_dict() if isinstance(seg, SegmentDTO) else seg
                        for seg in session_data['confirmed_segments']
                    ]
            elif processing_stage == 'language_selection':
                # 确认分段阶段完成
                if 'confirmed_segments' in session_data:
                    project.confirmed_segments = [
                        seg.to_legacy_dict() if isinstance(seg, SegmentDTO) else seg
                        for seg in session_data['confirmed_segments']
                    ]
            elif processing_stage == 'translating':
                # 设置目标语言
                if 'target_lang' in session_data:
                    project.target_language = session_data['target_lang']
            elif processing_stage == 'user_confirmation':
                # 翻译阶段完成
                if 'translated_segments' in session_data:
                    project.translated_segments = [
                        seg.to_legacy_dict() if isinstance(seg, SegmentDTO) else seg
                        for seg in session_data['translated_segments']
                    ]
                if 'optimized_segments' in session_data:
                    project.optimized_segments = [
                        seg.to_legacy_dict() if isinstance(seg, SegmentDTO) else seg
                        for seg in session_data['optimized_segments']
                    ]
                # 🔥 关键修复：在音频确认阶段也保存 confirmation_segments 到 final_segments
                # 这样每次用户确认单个片段后，音频数据和确认状态都会被保存到工程中
                if 'confirmation_segments' in session_data and session_data['confirmation_segments']:
                    project.final_segments = [
                        seg.to_legacy_dict() if isinstance(seg, SegmentDTO) else seg
                        for seg in session_data['confirmation_segments']
                    ]
                    logger.debug(f"保存了 {len(project.final_segments)} 个确认片段到工程")
            elif processing_stage == 'completion':
                # 用户确认阶段完成，保存最终结果
                if 'confirmation_segments' in session_data:
                    project.final_segments = [
                        seg.to_legacy_dict() if isinstance(seg, SegmentDTO) else seg
                        for seg in session_data['confirmation_segments']
                    ]
                
                # 保存API使用统计
                if 'completion_results' in session_data:
                    completion_data = session_data['completion_results']
                    if 'api_usage_summary' in completion_data:
                        project.add_api_usage('combined', completion_data['api_usage_summary'])
                    if 'stats' in completion_data:
                        project.update_quality_stats(completion_data['stats'])
            
            # 更新处理阶段和统计信息
            project.processing_stage = processing_stage
            project._update_statistics()
            
            # 确保工程数据同步到session_data中
            session_data['current_project'] = project
            
            # 保存工程
            success = self.project_manager.save_project(project)
            if success:
                logger.info(f"工程状态保存成功: {project.name} - {processing_stage} ({project.completion_percentage:.1f}%)")
            else:
                logger.error(f"工程状态保存失败: {project.name} - {processing_stage}")
            
            return success
            
        except Exception as e:
            logger.error(f"保存工程状态失败: {e}")
            return False
    
    def load_project_to_session(self, project_id: str, session_data: Dict[str, Any]) -> bool:
        """
        加载工程到会话状态
        
        Args:
            project_id: 工程ID
            session_data: 会话数据字典（将被修改）
            
        Returns:
            是否加载成功
        """
        try:
            project = self.project_manager.load_project(project_id)
            if not project:
                logger.error(f"工程不存在: {project_id}")
                return False
            
            # 转换工程数据到会话状态
            session_data['current_project'] = project
            session_data['processing_stage'] = project.processing_stage
            session_data['target_lang'] = project.target_language
            
            # 根据工程状态恢复相应的数据 - 确保数据完整性
            if project.segments:
                session_data['segments'] = [
                    SegmentDTO.from_legacy_segment(seg) for seg in project.segments
                ]
                logger.debug(f"恢复原始片段: {len(session_data['segments'])} 个")
            
            if project.segmented_segments:
                session_data['segmented_segments'] = [
                    SegmentDTO.from_legacy_segment(seg) for seg in project.segmented_segments
                ]
                logger.debug(f"恢复分段结果: {len(session_data['segmented_segments'])} 个")
            
            if project.confirmed_segments:
                session_data['confirmed_segments'] = [
                    SegmentDTO.from_legacy_segment(seg) for seg in project.confirmed_segments
                ]
                logger.debug(f"恢复确认分段: {len(session_data['confirmed_segments'])} 个")
                
                # 如果有确认分段但没有分段结果，用确认分段填充
                if not session_data.get('segmented_segments'):
                    session_data['segmented_segments'] = [
                        SegmentDTO.from_legacy_segment(seg) for seg in project.confirmed_segments
                    ]
                    logger.info("使用确认分段填充缺失的分段结果数据")
            
            if project.translated_segments:
                session_data['translated_segments'] = [
                    SegmentDTO.from_legacy_segment(seg) for seg in project.translated_segments
                ]
            
            if project.optimized_segments:
                session_data['optimized_segments'] = [
                    SegmentDTO.from_legacy_segment(seg) for seg in project.optimized_segments
                ]
            
            if project.final_segments:
                session_data['confirmation_segments'] = [
                    SegmentDTO.from_legacy_segment(seg) for seg in project.final_segments
                ]
            
            # 验证数据完整性
            self._validate_session_data_integrity(session_data, project)
            
            logger.info(f"工程加载到会话成功: {project.name} - {project.processing_stage}")
            return True
            
        except Exception as e:
            logger.error(f"加载工程到会话失败: {e}")
            return False
    
    def _validate_session_data_integrity(self, session_data: Dict[str, Any], project: ProjectDTO):
        """验证会话数据的完整性"""
        try:
            stage = session_data.get('processing_stage', '')
            issues = []
            
            # 根据处理阶段验证必需的数据
            if stage in ['confirm_segmentation', 'language_selection']:
                if not session_data.get('segments'):
                    issues.append("缺少原始片段数据")
                if not session_data.get('segmented_segments'):
                    issues.append("缺少分段结果数据")
            
            elif stage == 'translating':
                if not session_data.get('confirmed_segments'):
                    issues.append("缺少确认分段数据")
            
            elif stage == 'user_confirmation':
                if not session_data.get('translated_segments'):
                    issues.append("缺少翻译数据")
            
            if issues:
                logger.warning(f"数据完整性检查发现问题: {', '.join(issues)}")
                logger.info(f"工程 {project.name} 当前阶段: {stage}")
            else:
                logger.debug(f"数据完整性检查通过: {stage}")
                
        except Exception as e:
            logger.error(f"数据完整性验证失败: {e}")
    
    def check_existing_projects_for_file(self, filename: str, file_content: bytes) -> List[Dict[str, Any]]:
        """
        检查文件是否已有对应的工程
        
        Args:
            filename: 文件名
            file_content: 文件内容
            
        Returns:
            匹配的工程列表
        """
        try:
            file_hash = hashlib.md5(file_content).hexdigest()
            projects = self.project_manager.list_projects()
            
            matching_projects = []
            for project_info in projects:
                # 按文件哈希匹配
                if project_info.get("file_hash") and project_info["file_hash"] == file_hash:
                    matching_projects.append(project_info)
                # 按文件名匹配（备选）
                elif project_info.get("original_filename") == filename:
                    matching_projects.append(project_info)
            
            return matching_projects
            
        except Exception as e:
            logger.error(f"检查现有工程失败: {e}")
            return []
    
    def migrate_cache_to_project(self, cache_data: Dict[str, Any], project_name: str = "") -> Optional[ProjectDTO]:
        """
        从缓存数据迁移到工程
        
        Args:
            cache_data: 缓存数据
            project_name: 工程名称
            
        Returns:
            创建的工程对象
        """
        try:
            if not project_name:
                project_name = f"迁移工程_{int(time.time())}"
            
            project = ProjectDTO.from_legacy_cache(cache_data, project_name)
            project.description = "从缓存数据迁移的工程"
            project.add_tags(["迁移"])
            
            if self.project_manager.save_project(project):
                logger.info(f"缓存迁移为工程成功: {project.name}")
                return project
            else:
                return None
                
        except Exception as e:
            logger.error(f"缓存迁移工程失败: {e}")
            return None
    
    def auto_save_project_progress(self, session_data: Dict[str, Any]) -> bool:
        """
        自动保存工程进度（当处理阶段变化时）
        
        Args:
            session_data: 会话数据
            
        Returns:
            是否保存成功
        """
        try:
            current_project = session_data.get('current_project')
            if not current_project or not isinstance(current_project, ProjectDTO):
                return False
            
            return self.save_project_state(current_project, session_data)
            
        except Exception as e:
            logger.error(f"自动保存工程进度失败: {e}")
            return False
    
    def get_compatible_cache_data(self, file_content: bytes) -> Optional[Dict[str, Any]]:
        """
        获取兼容的缓存数据（支持旧缓存系统）
        
        Args:
            file_content: 文件内容
            
        Returns:
            缓存数据或None
        """
        try:
            # 首先检查工程
            projects = self.check_existing_projects_for_file("", file_content)
            if projects:
                # 如果有工程，返回最新的工程信息
                latest_project = max(projects, key=lambda x: x.get("updated_at", ""))
                return {
                    "type": "project",
                    "data": latest_project,
                    "source": "project_system"
                }
            
            # 检查旧缓存系统
            file_hash = hashlib.md5(file_content).hexdigest()
            related_caches = self.cache_integration.get_all_related_caches(file_hash, skip_validation=True)
            
            if related_caches:
                return {
                    "type": "cache",
                    "data": related_caches,
                    "source": "legacy_cache"
                }
            
            return None
            
        except Exception as e:
            logger.error(f"获取兼容缓存数据失败: {e}")
            return None
    
    def show_project_selection_interface(self, file_content: bytes, filename: str = "") -> Optional[Dict[str, Any]]:
        """
        显示工程/缓存选择界面
        
        Args:
            file_content: 文件内容
            filename: 文件名
            
        Returns:
            用户选择的结果
        """
        try:
            # 检查现有工程和缓存
            projects = self.check_existing_projects_for_file(filename, file_content)
            compatible_data = self.get_compatible_cache_data(file_content)
            
            if not projects and not compatible_data:
                # 没有现有数据
                st.header("🆕 创建新工程")
                st.info("未发现此文件的现有工程或缓存数据")
                
                project_name = st.text_input("工程名称", value=Path(filename).stem if filename else "新工程")
                description = st.text_area("工程描述（可选）", placeholder="描述这个配音工程的用途...")
                
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("🚀 创建新工程", type="primary", use_container_width=True):
                        project = self.create_project_from_file(filename, file_content, project_name, description)
                        if project:
                            return {
                                "action": "new_project",
                                "project": project
                            }
                
                with col2:
                    if st.button("🔙 返回", use_container_width=True):
                        return {"action": "back"}
                
                return {"action": "none"}
            
            # 显示现有工程和缓存
            st.header("🔍 发现现有数据")
            
            options = ["创建新工程"]
            option_data: List[Optional[Dict[str, Any]]] = [None]
            
            # 添加工程选项
            if projects:
                st.subheader("📂 现有工程")
                for project_info in projects:
                    status = project_info.get("processing_stage", "unknown")
                    progress = project_info.get("completion_percentage", 0)
                    updated = project_info.get("updated_at", "").split("T")[0]  # 只显示日期
                    
                    options.append(f"工程: {project_info['name']} ({progress:.0f}%, {status}, 更新于{updated})")
                    option_data.append({"type": "project", "data": project_info})
            
            # 添加缓存选项
            if compatible_data and compatible_data.get("type") == "cache":
                st.subheader("💾 旧缓存数据")
                cache_data = compatible_data["data"]
                for cache_type, cache_entries in cache_data.items():
                    cache_name = self._get_cache_type_name(cache_type)
                    options.append(f"缓存: {cache_name} ({len(cache_entries)}个条目)")
                    option_data.append({"type": "cache", "data": cache_data})
            
            # 用户选择
            selected_index = st.radio(
                "选择处理方式",
                range(len(options)),
                format_func=lambda x: options[x]
            )
            
            col1, col2 = st.columns(2)
            with col1:
                if st.button("✅ 确认选择", type="primary", use_container_width=True):
                    if selected_index == 0:
                        # 创建新工程
                        project_name = st.text_input("工程名称", value=Path(filename).stem if filename else "新工程") or "新工程"
                        description = st.text_area("工程描述（可选）") or ""
                        
                        project = self.create_project_from_file(filename, file_content, project_name, description)
                        if project:
                            return {
                                "action": "new_project", 
                                "project": project
                            }
                    else:
                        selected_data = option_data[selected_index]
                        if selected_data and selected_data["type"] == "project":
                            return {
                                "action": "load_project",
                                "project_id": selected_data["data"]["id"]
                            }
                        elif selected_data and selected_data["type"] == "cache":
                            # 将缓存迁移为工程
                            project = self.migrate_cache_to_project(
                                selected_data["data"], 
                                f"迁移_{Path(filename).stem}" if filename else "迁移工程"
                            )
                            if project:
                                return {
                                    "action": "migrated_project",
                                    "project": project
                                }
            
            with col2:
                if st.button("🔙 返回", use_container_width=True):
                    return {"action": "back"}
            
            return {"action": "none"}
            
        except Exception as e:
            logger.error(f"显示工程选择界面失败: {e}")
            st.error(f"❌ 显示选择界面时发生错误: {str(e)}")
            return {"action": "error"}
    
    def _get_cache_type_name(self, cache_type: str) -> str:
        """获取缓存类型的中文名称"""
        type_names = {
            "srt_info": "SRT文件信息",
            "segmentation": "智能分段",
            "translation": "翻译结果",
            "confirmation": "用户确认"
        }
        return type_names.get(cache_type, cache_type)
    
    def cleanup_orphaned_cache(self) -> int:
        """
        清理已迁移的孤立缓存数据
        
        Returns:
            清理的缓存条目数
        """
        try:
            # 获取所有工程的文件哈希
            projects = self.project_manager.list_projects()
            project_hashes = set()
            for project_info in projects:
                if project_info.get("file_hash"):
                    project_hashes.add(project_info["file_hash"])
            
            # 检查缓存条目
            cache_entries = self.cache_integration.cache_manager.cache_index.get("cache_entries", {})
            orphaned_keys = []
            
            for cache_key, cache_entry in cache_entries.items():
                file_hash = cache_entry.get("file_hash", "")
                if file_hash and file_hash in project_hashes:
                    # 这个缓存已经有对应的工程了
                    orphaned_keys.append(cache_key)
            
            # 清理孤立缓存
            for cache_key in orphaned_keys:
                self.cache_integration.cache_manager._remove_cache_entry(cache_key)
            
            logger.info(f"清理了 {len(orphaned_keys)} 个孤立缓存条目")
            return len(orphaned_keys)
            
        except Exception as e:
            logger.error(f"清理孤立缓存失败: {e}")
            return 0


# 全局工程集成实例
_global_project_integration = None


def get_project_integration() -> ProjectIntegration:
    """获取全局工程集成实例"""
    global _global_project_integration
    if _global_project_integration is None:
        _global_project_integration = ProjectIntegration()
    return _global_project_integration
