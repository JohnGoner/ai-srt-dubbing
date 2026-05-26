"""
工程集成模块
在各个处理阶段集成工程管理功能，提供工程的保存、加载和状态更新
支持本地存储和 Firebase 云端存储两种后端
"""

from typing import Dict, Any, Optional, List, Union
from loguru import logger
from pathlib import Path
import streamlit as st
import hashlib
import time

from .project_manager import get_project_manager, ProjectManager
from .cache_integration import get_cache_integration
from .config_manager import get_global_config_manager
from models.project_dto import ProjectDTO
from models.segment_dto import SegmentDTO

# Firebase 支持（可选）
try:
    from .firebase_project_manager import FirebaseProjectManager, get_firebase_project_manager
    FIREBASE_SUPPORT = True
except ImportError:
    FIREBASE_SUPPORT = False
    logger.debug("Firebase 支持未启用")


class ProjectIntegration:
    """
    工程集成类 - 管理工程的完整生命周期集成
    支持本地存储和 Firebase 云端存储两种后端
    """
    
    def __init__(self, user_id: Optional[str] = None, use_firebase: Optional[bool] = None):
        """
        初始化工程集成
        
        Args:
            user_id: 用户 ID（Firebase 模式必需）
            use_firebase: 是否使用 Firebase 后端（None 则从配置读取）
        """
        self.user_id = user_id
        self.cache_integration = get_cache_integration()  # 兼容旧缓存系统
        
        # 确定存储后端
        config_manager = get_global_config_manager()
        config = config_manager.load_config() or {}
        
        if use_firebase is None:
            # storage.backend = 'local' 时强制本地（即使 firebase.enabled=true，
            # 因为某些环境 Firestore 网络不通但 Storage 通，仍想用 Storage 传音频）
            storage_backend_cfg = config.get('storage', {}).get('backend', 'local')
            firebase_enabled = config.get('firebase', {}).get('enabled', False)
            self._use_firebase = firebase_enabled and storage_backend_cfg == 'firebase'
        else:
            self._use_firebase = use_firebase
        
        # 初始化项目管理器
        if self._use_firebase and FIREBASE_SUPPORT and user_id:
            self.project_manager = get_firebase_project_manager(user_id, config)
            self._storage_backend = "firebase"
            logger.info(f"使用 Firebase 存储后端 (用户: {user_id})")
        else:
            self.project_manager = get_project_manager()
            self._storage_backend = "local"
            if self._use_firebase and not FIREBASE_SUPPORT:
                logger.warning("Firebase 支持未安装，回退到本地存储")
            elif self._use_firebase and not user_id:
                logger.warning("未提供用户 ID，回退到本地存储")
    
    @property
    def storage_backend(self) -> str:
        """获取当前存储后端类型"""
        return self._storage_backend
    
    def set_user(self, user_id: str):
        """
        设置当前用户（用于 Firebase 模式）
        
        Args:
            user_id: 用户 ID
        """
        self.user_id = user_id
        
        if self._use_firebase and FIREBASE_SUPPORT:
            config_manager = get_global_config_manager()
            config = config_manager.load_config() or {}
            self.project_manager = get_firebase_project_manager(user_id, config)
            self._storage_backend = "firebase"
            logger.info(f"切换到 Firebase 存储后端 (用户: {user_id})")
        
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
            
            # 记录项目创建活动日志（仅 firebase 后端，否则会卡死在 Firestore RPC）
            if self.user_id and project and self._use_firebase:
                try:
                    from .firebase_activity_logger import get_activity_logger
                    activity_logger = get_activity_logger()
                    activity_logger.log_project_create(
                        user_id=self.user_id,
                        project_id=project.id,
                        project_name=project.name,
                        filename=filename
                    )
                except Exception as e:
                    logger.debug(f"记录项目创建日志失败（非关键）: {e}")
            
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
            # 安全检查：确保 session_data 不为 None
            if session_data is None:
                logger.warning("session_data 为 None，跳过保存")
                return False
            
            # 从session_data更新工程状态
            processing_stage = session_data.get('processing_stage', 'file_upload')
            
            # 辅助函数：安全获取并转换片段列表
            def safe_convert_segments(key: str) -> List:
                """安全获取并转换片段列表，处理 None 值"""
                segments = session_data.get(key)
                if not segments:  # None 或空列表
                    return []
                return [
                    seg.to_legacy_dict() if isinstance(seg, SegmentDTO) else seg
                    for seg in segments
                ]
            
            # 根据处理阶段更新工程数据
            if processing_stage == 'segmentation':
                # 分段处理阶段
                segments = safe_convert_segments('segments')
                if segments:
                    project.segments = segments
                segmented = safe_convert_segments('segmented_segments')
                if segmented:
                    project.segmented_segments = segmented
                    
            elif processing_stage == 'confirm_segmentation':
                # 确保原始片段数据也被保存
                if not project.segments:
                    segments = safe_convert_segments('segments')
                    if segments:
                        project.segments = segments
                segmented = safe_convert_segments('segmented_segments')
                if segmented:
                    project.segmented_segments = segmented
                confirmed = safe_convert_segments('confirmed_segments')
                if confirmed:
                    project.confirmed_segments = confirmed
                    
            elif processing_stage == 'language_selection':
                # 确认分段阶段完成
                confirmed = safe_convert_segments('confirmed_segments')
                if confirmed:
                    project.confirmed_segments = confirmed
                    
            elif processing_stage == 'translating':
                # 设置目标语言
                if 'target_lang' in session_data:
                    project.target_language = session_data['target_lang']
                    
            elif processing_stage == 'user_confirmation':
                # 翻译阶段完成
                translated = safe_convert_segments('translated_segments')
                if translated:
                    project.translated_segments = translated
                optimized = safe_convert_segments('optimized_segments')
                if optimized:
                    project.optimized_segments = optimized
                # 🔥 关键修复：在音频确认阶段也保存 confirmation_segments 到 final_segments
                # 这样每次用户确认单个片段后，音频数据和确认状态都会被保存到工程中
                final = safe_convert_segments('confirmation_segments')
                if final:
                    project.final_segments = final
                    logger.debug(f"保存了 {len(project.final_segments)} 个确认片段到工程")
                    
            elif processing_stage == 'completion':
                # 用户确认阶段完成，保存最终结果
                final = safe_convert_segments('confirmation_segments')
                if final:
                    project.final_segments = final
                
                # 保存API使用统计
                completion_data = session_data.get('completion_results')
                if completion_data and isinstance(completion_data, dict):
                    if 'api_usage_summary' in completion_data:
                        project.add_api_usage('combined', completion_data['api_usage_summary'])
                    if 'stats' in completion_data:
                        project.update_quality_stats(completion_data['stats'])
            
            # 更新处理阶段和统计信息
            project.processing_stage = processing_stage
            project._update_statistics()
            
            # 确保工程数据同步到session_data中
            session_data['current_project'] = project
            
            # 保存工程（根据阶段选择保存策略）
            # 关键阶段使用立即保存，普通阶段使用防抖保存
            # 注意：confirm_segmentation 阶段不再频繁保存，只在用户点击确认时才触发
            is_critical_stage = processing_stage in ['completion', 'language_selection']
            
            if is_critical_stage and self._storage_backend == "firebase":
                # 关键阶段：立即保存，确保数据不丢失
                if hasattr(self.project_manager, 'save_project_immediate'):
                    success = self.project_manager.save_project_immediate(project)
                    logger.info(f"关键阶段立即保存: {project.name} - {processing_stage}")
                else:
                    success = self.project_manager.save_project(project)
            else:
                # 普通阶段：使用默认保存（Firebase 会防抖）
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
            
            # 🔥 重要：将项目的 audio_storage_paths 应用到加载的片段
            audio_paths = getattr(project, 'audio_storage_paths', {})
            if audio_paths:
                self._apply_audio_paths_to_segments(session_data, audio_paths)
                logger.debug(f"已应用 {len(audio_paths)} 条音频路径到片段")
            
            # 验证数据完整性
            self._validate_session_data_integrity(session_data, project)
            
            # 记录项目加载活动日志（仅 firebase 后端，否则会卡死在 Firestore RPC）
            if self.user_id and self._use_firebase:
                try:
                    from .firebase_activity_logger import get_activity_logger
                    activity_logger = get_activity_logger()
                    activity_logger.log_project_load(
                        user_id=self.user_id,
                        project_id=project.id,
                        project_name=project.name
                    )
                except Exception as e:
                    logger.debug(f"记录项目加载日志失败（非关键）: {e}")
            
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
    
    def _apply_audio_paths_to_segments(self, session_data: Dict[str, Any], audio_paths: Dict[str, str]):
        """
        将项目的音频存储路径应用到加载的片段
        
        这样片段在渲染时可以直接使用 URL 流式播放，无需重新生成音频
        
        Args:
            session_data: 会话数据
            audio_paths: 音频存储路径映射 {segment_id: storage_path, segment_id_preview: storage_path}
        """
        if not audio_paths:
            return
        
        # 需要应用路径的片段字段
        segment_fields = [
            'translated_segments',
            'optimized_segments', 
            'confirmation_segments'
        ]
        
        applied_count = 0
        for field_name in segment_fields:
            segments = session_data.get(field_name, [])
            if not segments:
                logger.debug(f"_apply_audio_paths_to_segments: {field_name} 为空或不存在")
                continue
            
            
            for seg in segments:
                if seg.audio_data is not None:
                    # 已有内存音频数据，跳过
                    continue
                
                # 查找音频路径（优先 confirmed，其次 preview）
                storage_path = audio_paths.get(seg.id) or audio_paths.get(f"{seg.id}_preview")
                logger.debug(f"片段 {seg.id}: 查找路径, seg.id={seg.id}, {seg.id}_preview={seg.id}_preview, 找到={storage_path}")
                if storage_path:
                    seg.audio_path = storage_path
                    applied_count += 1
                    logger.debug(f"片段 {seg.id}: 设置 audio_path = {storage_path}")
    
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
    
    def flush_pending_saves(self):
        """
        刷新所有待保存的数据（用于程序退出或关键节点）
        
        对于 Firebase 后端，会立即执行所有排队中的保存操作
        对于本地后端，此方法无操作（本地保存是同步的）
        """
        if self._storage_backend == "firebase" and hasattr(self.project_manager, 'flush_pending_saves'):
            self.project_manager.flush_pending_saves()
            logger.info("已刷新所有待保存的 Firebase 数据")
    
    def get_save_stats(self) -> Dict[str, Any]:
        """
        获取保存统计信息（用于调试）
        
        Returns:
            保存统计字典
        """
        if self._storage_backend == "firebase" and hasattr(self.project_manager, 'get_save_stats'):
            return self.project_manager.get_save_stats()
        return {'backend': self._storage_backend, 'pending_saves': 0}
    
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


# 全局工程集成实例（按用户 ID 缓存）
_project_integrations: Dict[str, ProjectIntegration] = {}
_default_project_integration: Optional[ProjectIntegration] = None


def get_project_integration(user_id: Optional[str] = None) -> ProjectIntegration:
    """
    获取工程集成实例
    
    Args:
        user_id: 用户 ID，如果为 None 则返回默认实例（本地模式）
        
    Returns:
        ProjectIntegration 实例
    """
    global _project_integrations, _default_project_integration
    
    if user_id:
        # 按用户返回实例（支持 Firebase 用户隔离）
        if user_id not in _project_integrations:
            _project_integrations[user_id] = ProjectIntegration(user_id=user_id)
        return _project_integrations[user_id]
    else:
        # 返回默认实例（本地模式）
        if _default_project_integration is None:
            _default_project_integration = ProjectIntegration()
        return _default_project_integration


def clear_project_integration_cache():
    """清除所有缓存的工程集成实例"""
    global _project_integrations, _default_project_integration
    _project_integrations.clear()
    _default_project_integration = None
    logger.debug("工程集成缓存已清除")


def flush_all_pending_saves():
    """
    刷新所有工程集成实例的待保存数据
    应在程序退出时调用，确保所有数据都已保存
    """
    global _project_integrations, _default_project_integration
    
    flushed_count = 0
    
    # 刷新所有用户实例
    for user_id, integration in _project_integrations.items():
        try:
            integration.flush_pending_saves()
            flushed_count += 1
        except Exception as e:
            logger.error(f"刷新用户 {user_id} 的待保存数据失败: {e}")
    
    # 刷新默认实例
    if _default_project_integration:
        try:
            _default_project_integration.flush_pending_saves()
            flushed_count += 1
        except Exception as e:
            logger.error(f"刷新默认实例的待保存数据失败: {e}")
    
    if flushed_count > 0:
        logger.info(f"已刷新 {flushed_count} 个工程集成实例的待保存数据")
