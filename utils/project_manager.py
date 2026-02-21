"""
工程管理器
管理AI配音工程的创建、保存、加载和分享
"""

import json
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from loguru import logger
from datetime import datetime, timezone
import pickle

from models.project_dto import ProjectDTO


class ProjectManager:
    """工程管理器 - 管理配音工程的完整生命周期"""
    
    def __init__(self, projects_dir: Optional[str] = None):
        """
        初始化工程管理器
        
        Args:
            projects_dir: 工程存储目录，默认为用户主目录下的.ai_dubbing_projects
        """
        if projects_dir is None:
            self.projects_dir = Path.home() / ".ai_dubbing_projects"
        else:
            self.projects_dir = Path(projects_dir)
        
        # 创建工程目录结构
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        self.projects_index_file = self.projects_dir / "projects_index.json"
        self.projects_data_dir = self.projects_dir / "data"
        self.projects_data_dir.mkdir(exist_ok=True)
        
        # 导入/导出临时目录
        self.temp_dir = self.projects_dir / "temp"
        self.temp_dir.mkdir(exist_ok=True)
        
        # 加载工程索引
        self.projects_index = self._load_projects_index()
        
        # 自动进行完整性检查和修复
        try:
            repair_stats = self.check_and_repair_integrity()
            if repair_stats.get("orphaned_index_removed", 0) > 0 or repair_stats.get("orphaned_data_removed", 0) > 0:
                logger.info(f"完成数据完整性修复: 移除孤立索引{repair_stats.get('orphaned_index_removed', 0)}个, "
                          f"移除孤立文件{repair_stats.get('orphaned_data_removed', 0)}个")
        except Exception as e:
            logger.warning(f"完整性检查失败，但不影响正常使用: {e}")
        
        logger.info(f"工程管理器初始化完成: {self.projects_dir}")
        logger.info(f"发现 {len(self.projects_index.get('projects', {}))} 个工程")
    
    def _load_projects_index(self) -> Dict[str, Any]:
        """加载工程索引"""
        try:
            if self.projects_index_file.exists():
                with open(self.projects_index_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            else:
                return {
                    "version": "1.0",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "projects": {},  # project_id -> project_info
                    "statistics": {
                        "total_projects": 0,
                        "total_size": 0,
                        "last_cleanup": None
                    }
                }
        except Exception as e:
            logger.warning(f"加载工程索引失败: {e}")
            return {
                "version": "1.0",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "projects": {},
                "statistics": {
                    "total_projects": 0,
                    "total_size": 0,
                    "last_cleanup": None
                }
            }
    
    def _save_projects_index(self) -> bool:
        """保存工程索引"""
        try:
            # 更新统计信息
            self.projects_index["statistics"]["total_projects"] = len(self.projects_index["projects"])
            
            # 使用原子保存方式
            temp_index_file = self.projects_index_file.with_suffix('.json.tmp')
            
            try:
                with open(temp_index_file, 'w', encoding='utf-8') as f:
                    json.dump(self.projects_index, f, ensure_ascii=False, indent=2)
                
                # 原子性移动临时文件（Windows兼容）
                temp_index_file.replace(self.projects_index_file)
                return True
                
            except Exception as e:
                # 清理临时文件
                if temp_index_file.exists():
                    try:
                        temp_index_file.unlink()
                    except:
                        pass
                raise e
            
        except Exception as e:
            logger.error(f"保存工程索引失败: {e}")
            return False
    
    def create_project(self, name: str, filename: str = "", file_content: bytes = b"", 
                      description: str = "") -> ProjectDTO:
        """
        创建新工程
        
        Args:
            name: 工程名称
            filename: 原始文件名
            file_content: 文件内容
            description: 工程描述
            
        Returns:
            创建的工程对象
        """
        try:
            # 创建工程对象
            if filename and file_content:
                project = ProjectDTO.create_from_file(filename, file_content, name, description)
            else:
                project = ProjectDTO(
                    id="",  # 将在__post_init__中生成
                    name=name,
                    description=description
                )
            
            # 保存工程
            if self.save_project(project):
                logger.info(f"创建工程成功: {project.name} (ID: {project.id})")
                return project
            else:
                raise Exception("保存工程失败")
                
        except Exception as e:
            logger.error(f"创建工程失败: {e}")
            raise
    
    def save_project(self, project: ProjectDTO) -> bool:
        """
        保存工程（使用原子操作防止数据丢失）
        
        Args:
            project: 工程对象
            
        Returns:
            是否保存成功
        """
        try:
            project_data_file = self.projects_data_dir / f"{project.id}.pkl"
            temp_data_file = self.projects_data_dir / f"{project.id}.pkl.tmp"
            
            # 使用临时文件实现原子保存
            try:
                # 1. 先保存到临时文件
                with open(temp_data_file, 'wb') as f:
                    pickle.dump(project, f)
                
                # 2. 验证临时文件写入完整性
                with open(temp_data_file, 'rb') as f:
                    test_project = pickle.load(f)
                    if not isinstance(test_project, ProjectDTO):
                        raise ValueError("保存的工程数据格式错误")
                
                # 3. 原子性移动临时文件到目标位置（Windows兼容）
                temp_data_file.replace(project_data_file)
                
                logger.debug(f"工程数据文件保存成功: {project_data_file}")
                
            except Exception as e:
                # 清理临时文件
                if temp_data_file.exists():
                    try:
                        temp_data_file.unlink()
                    except:
                        pass
                raise Exception(f"保存工程数据失败: {e}")
            
            # 4. 更新索引（也使用原子操作）
            try:
                project_info = {
                    "id": project.id,
                    "name": project.name,
                    "description": project.description,
                    "created_at": project.created_at,
                    "updated_at": project.updated_at,
                    "processing_stage": project.processing_stage,
                    "completion_percentage": project.completion_percentage,
                    "target_language": project.target_language,
                    "total_segments": project.total_segments,
                    "total_duration": project.total_duration,
                    "original_filename": project.original_filename,
                    "file_size": project.file_size,
                    "tags": project.tags,
                    "category": project.category,
                    "is_shared": project.is_shared,
                    "data_file_size": project_data_file.stat().st_size,
                    "file_hash": getattr(project, 'file_hash', '')
                }
                
                # 备份当前索引
                backup_index = self.projects_index.copy()
                
                # 更新索引
                self.projects_index["projects"][project.id] = project_info
                
                # 保存索引
                if not self._save_projects_index():
                    # 如果索引保存失败，恢复备份
                    self.projects_index = backup_index
                    raise Exception("索引保存失败")
                
                logger.debug(f"工程保存成功: {project.name} (ID: {project.id})")
                return True
                
            except Exception as e:
                # 如果索引更新失败，删除已保存的数据文件以保持一致性
                try:
                    if project_data_file.exists():
                        project_data_file.unlink()
                        logger.warning(f"因索引更新失败，已删除数据文件: {project_data_file}")
                except:
                    pass
                raise Exception(f"更新索引失败: {e}")
            
        except Exception as e:
            logger.error(f"保存工程失败: {e}")
            return False
    
    def load_project(self, project_id: str) -> Optional[ProjectDTO]:
        """
        加载工程
        
        Args:
            project_id: 工程ID
            
        Returns:
            工程对象，如果不存在则返回None
        """
        try:
            if project_id not in self.projects_index["projects"]:
                logger.warning(f"工程不存在: {project_id}")
                return None
            
            project_data_file = self.projects_data_dir / f"{project_id}.pkl"
            if not project_data_file.exists():
                logger.warning(f"工程数据文件不存在: {project_data_file}")
                # 从索引中移除无效工程
                self._remove_project_from_index(project_id)
                return None
            
            with open(project_data_file, 'rb') as f:
                project = pickle.load(f)
            
            # 验证工程对象类型
            if not isinstance(project, ProjectDTO):
                logger.error(f"工程数据格式错误: {project_id}")
                return None
            
            # 更新访问时间（通过索引）
            self.projects_index["projects"][project_id]["last_accessed"] = datetime.now(timezone.utc).isoformat()
            self._save_projects_index()
            
            logger.debug(f"工程加载成功: {project.name} (ID: {project_id})")
            return project
            
        except Exception as e:
            logger.error(f"加载工程失败: {e}")
            return None
    
    def list_projects(self, include_shared: bool = True) -> List[Dict[str, Any]]:
        """
        获取工程列表
        
        Args:
            include_shared: 是否包含共享工程
            
        Returns:
            工程信息列表
        """
        try:
            projects_list = []
            
            for project_id, project_info in self.projects_index["projects"].items():
                if not include_shared and project_info.get("is_shared", False):
                    continue
                
                # 检查数据文件是否存在
                project_data_file = self.projects_data_dir / f"{project_id}.pkl"
                if not project_data_file.exists():
                    logger.warning(f"工程数据文件丢失: {project_id}")
                    continue
                
                projects_list.append(project_info.copy())
            
            # 按更新时间排序（最新的在前）
            projects_list.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
            
            return projects_list
            
        except Exception as e:
            logger.error(f"获取工程列表失败: {e}")
            return []
    
    def delete_project(self, project_id: str) -> bool:
        """
        删除工程
        
        Args:
            project_id: 工程ID
            
        Returns:
            是否删除成功
        """
        try:
            if project_id not in self.projects_index["projects"]:
                logger.warning(f"要删除的工程不存在: {project_id}")
                return False
            
            # 删除数据文件
            project_data_file = self.projects_data_dir / f"{project_id}.pkl"
            if project_data_file.exists():
                project_data_file.unlink()
            
            # 从索引中移除
            project_name = self.projects_index["projects"][project_id].get("name", "未知")
            del self.projects_index["projects"][project_id]
            self._save_projects_index()
            
            logger.info(f"工程删除成功: {project_name} (ID: {project_id})")
            return True
            
        except Exception as e:
            logger.error(f"删除工程失败: {e}")
            return False
    
    def _remove_project_from_index(self, project_id: str):
        """从索引中移除工程"""
        if project_id in self.projects_index["projects"]:
            del self.projects_index["projects"][project_id]
            self._save_projects_index()
    
    def duplicate_project(self, project_id: str, new_name: str = "") -> Optional[ProjectDTO]:
        """
        复制工程
        
        Args:
            project_id: 原工程ID
            new_name: 新工程名称
            
        Returns:
            新工程对象
        """
        try:
            # 加载原工程
            original_project = self.load_project(project_id)
            if not original_project:
                return None
            
            # 创建副本
            project_dict = original_project.to_dict()
            project_dict["id"] = ""  # 重新生成ID
            project_dict["name"] = new_name or f"{original_project.name} - 副本"
            project_dict["created_at"] = datetime.now(timezone.utc).isoformat()
            project_dict["updated_at"] = datetime.now(timezone.utc).isoformat()
            project_dict["is_shared"] = False
            project_dict["share_url"] = ""
            
            new_project = ProjectDTO.from_dict(project_dict)
            
            # 保存新工程
            if self.save_project(new_project):
                logger.info(f"工程复制成功: {new_project.name} (ID: {new_project.id})")
                return new_project
            else:
                return None
                
        except Exception as e:
            logger.error(f"复制工程失败: {e}")
            return None
    
    def export_project(self, project_id: str, export_path: Optional[str] = None) -> Optional[str]:
        """
        导出工程到ZIP文件（包含音频数据）
        
        Args:
            project_id: 工程ID
            export_path: 导出路径，如果为None则导出到临时目录
            
        Returns:
            导出文件路径
        """
        try:
            project = self.load_project(project_id)
            if not project:
                return None
            
            # 确定导出路径
            if export_path is None:
                export_file = self.temp_dir / f"{project.name}_{project.id}.zip"
            else:
                export_file = Path(export_path)
            
            # 创建导出用的工程数据并提取音频文件
            export_project_data, audio_files = self._prepare_project_for_export_with_audio(project)
            
            # 创建ZIP文件
            with zipfile.ZipFile(str(export_file), 'w', zipfile.ZIP_DEFLATED) as zipf:
                # 添加工程数据
                project_json = json.dumps(export_project_data, ensure_ascii=False, indent=2)
                zipf.writestr("project.json", project_json)
                
                # 添加音频文件
                audio_count = 0
                for audio_filename, audio_data in audio_files.items():
                    zipf.writestr(f"audio/{audio_filename}", audio_data)
                    audio_count += 1
                
                # 添加元数据
                metadata = {
                    "export_version": "2.0",  # 升级版本号
                    "export_time": datetime.now(timezone.utc).isoformat(),
                    "project_id": project.id,
                    "project_name": project.name,
                    "contains_audio_data": audio_count > 0,
                    "audio_file_count": audio_count,
                    "audio_format": "wav",
                    "note": f"包含{audio_count}个音频文件的完整工程导出"
                }
                zipf.writestr("metadata.json", json.dumps(metadata, ensure_ascii=False, indent=2))
            
            logger.info(f"工程导出成功: {export_file}, 包含{audio_count}个音频文件")
            return str(export_file)
            
        except Exception as e:
            logger.error(f"导出工程失败: {e}")
            return None
    
    def _prepare_project_for_export_with_audio(self, project: ProjectDTO) -> Tuple[Dict[str, Any], Dict[str, bytes]]:
        """
        准备工程数据用于导出，提取音频数据为文件
        
        Args:
            project: 原始工程对象
            
        Returns:
            (清理后的工程数据字典, 音频文件字典{文件名: 二进制数据})
        """
        try:
            from pydub import AudioSegment
            from models.segment_dto import SegmentDTO
            import io
            
            # 获取工程数据字典
            project_data = project.to_dict()
            audio_files = {}
            audio_counter = 1
            
            # 处理各阶段的segments数据
            segment_fields = [
                'segments', 'segmented_segments', 'confirmed_segments',
                'translated_segments', 'optimized_segments', 'final_segments'
            ]
            
            for field_name in segment_fields:
                if field_name in project_data and project_data[field_name]:
                    cleaned_segments = []
                    
                    for seg_data in project_data[field_name]:
                        clean_seg = None
                        audio_segment = None
                        
                        # 提取音频数据
                        if isinstance(seg_data, dict):
                            clean_seg = seg_data.copy()
                            # 检查字典中是否有AudioSegment对象
                            if 'audio_data' in seg_data:
                                audio_data = seg_data['audio_data']
                                if audio_data and hasattr(audio_data, '__class__') and audio_data.__class__.__name__ == 'AudioSegment':
                                    audio_segment = audio_data
                                    logger.debug(f"从字典中提取到AudioSegment对象")
                            clean_seg.pop('audio_data', None)  # 移除原始对象引用
                        else:
                            # 如果是SegmentDTO对象，提取音频数据
                            try:
                                if isinstance(seg_data, SegmentDTO):
                                    audio_segment = seg_data.audio_data
                                    clean_seg = seg_data.to_dict()  # 这会自动排除audio_data
                                elif hasattr(seg_data, 'to_dict'):
                                    clean_seg = seg_data.to_dict()
                                else:
                                    clean_seg = seg_data
                            except Exception as e:
                                logger.warning(f"处理片段数据时出错: {e}")
                                continue
                        
                        # 如果有音频数据，转换为文件
                        if audio_segment and isinstance(audio_segment, AudioSegment):
                            try:
                                # 创建唯一的音频文件名
                                segment_id = clean_seg.get('id', f'segment_{audio_counter}')
                                audio_filename = f"{segment_id}.wav"
                                
                                # 将AudioSegment转换为WAV二进制数据
                                audio_buffer = io.BytesIO()
                                
                                # Windows系统优化：使用更兼容的音频导出参数
                                import platform
                                from utils.windows_audio_utils import is_windows
                                
                                if is_windows():
                                    # 在Windows下使用标准的WAV参数
                                    audio_segment.export(
                                        audio_buffer, 
                                        format="wav",
                                        parameters=[
                                            "-acodec", "pcm_s16le",  # 16-bit PCM编码
                                            "-ar", "44100",          # 44.1kHz采样率
                                            "-ac", "1"               # 单声道
                                        ]
                                    )
                                else:
                                    # 非Windows系统使用原有逻辑
                                    audio_segment.export(audio_buffer, format="wav")
                                
                                audio_data = audio_buffer.getvalue()
                                
                                # 验证音频数据
                                if len(audio_data) < 100:  # 音频文件至少应该有100字节
                                    raise Exception(f"音频数据过小，可能损坏: {len(audio_data)} bytes")
                                
                                audio_files[audio_filename] = audio_data
                                
                                # 更新片段数据中的音频路径
                                clean_seg['audio_path'] = audio_filename
                                clean_seg.pop('audio_data', None)  # 确保移除原始对象
                                
                                logger.debug(f"提取音频文件: {audio_filename}, 大小: {len(audio_files[audio_filename])} bytes")
                                audio_counter += 1
                                
                            except Exception as e:
                                logger.warning(f"转换音频数据失败: {e}")
                                clean_seg.pop('audio_data', None)  # 移除有问题的数据
                        
                        if clean_seg:
                            cleaned_segments.append(clean_seg)
                    
                    project_data[field_name] = cleaned_segments
                    logger.debug(f"处理了 {field_name}: {len(cleaned_segments)} 个片段")
            
            logger.info(f"提取了 {len(audio_files)} 个音频文件用于导出")
            return project_data, audio_files
            
        except Exception as e:
            logger.error(f"准备导出数据失败: {e}")
            # 返回最小化的安全数据
            safe_data = {
                "id": project.id,
                "name": project.name,
                "description": project.description,
                "created_at": project.created_at,
                "updated_at": project.updated_at,
                "processing_stage": project.processing_stage,
                "completion_percentage": project.completion_percentage,
                "target_language": project.target_language,
                "original_filename": project.original_filename,
                "export_error": "部分数据因处理错误被跳过"
            }
            return safe_data, {}
    
    def import_project(self, import_path: str, new_name: str = "") -> Optional[ProjectDTO]:
        """
        从ZIP文件导入工程（支持音频数据恢复）
        
        Args:
            import_path: 导入文件路径
            new_name: 新工程名称（可选）
            
        Returns:
            导入的工程对象
        """
        try:
            import_file = Path(import_path)
            if not import_file.exists():
                logger.error(f"导入文件不存在: {import_file}")
                return None
            
            # 提取ZIP文件
            with zipfile.ZipFile(str(import_file), 'r') as zipf:
                # 验证文件结构
                file_list = zipf.namelist()
                if "project.json" not in file_list:
                    logger.error("无效的工程导入文件：缺少project.json")
                    return None
                
                # 读取元数据（如果存在）
                metadata = {}
                if "metadata.json" in file_list:
                    try:
                        metadata_json = zipf.read("metadata.json").decode('utf-8')
                        metadata = json.loads(metadata_json)
                        logger.info(f"导入工程版本: {metadata.get('export_version', '1.0')}")
                    except Exception as e:
                        logger.warning(f"读取元数据失败: {e}")
                
                # 读取工程数据
                project_json = zipf.read("project.json").decode('utf-8')
                project_data = json.loads(project_json)
                
                # 读取音频文件（如果存在）
                audio_files = {}
                audio_file_count = 0
                for file_name in file_list:
                    if file_name.startswith('audio/') and file_name.endswith('.wav'):
                        audio_filename = Path(file_name).name
                        audio_data = zipf.read(file_name)
                        audio_files[audio_filename] = audio_data
                        audio_file_count += 1
                
                logger.info(f"发现 {audio_file_count} 个音频文件")
                
                # 恢复音频数据到工程对象中
                if audio_files:
                    self._restore_audio_data_to_project(project_data, audio_files)
                
                # 创建工程对象
                project = ProjectDTO.from_dict(project_data)
                
                # 重置工程信息
                old_id = project.id
                project.id = ""  # 重新生成ID
                if new_name:
                    project.name = new_name
                project.created_at = datetime.now(timezone.utc).isoformat()
                project.updated_at = datetime.now(timezone.utc).isoformat()
                project.is_shared = False
                project.share_url = ""
                
                # 调用__post_init__重新生成ID和更新统计
                project.__post_init__()
            
            # 保存导入的工程
            if self.save_project(project):
                logger.info(f"工程导入成功: {project.name} (旧ID: {old_id}, 新ID: {project.id}), 包含{audio_file_count}个音频文件")
                return project
            else:
                return None
                
        except Exception as e:
            logger.error(f"导入工程失败: {e}")
            return None
    
    def _restore_audio_data_to_project(self, project_data: Dict[str, Any], audio_files: Dict[str, bytes]):
        """
        将音频数据恢复到工程数据中
        
        Args:
            project_data: 工程数据字典
            audio_files: 音频文件字典 {文件名: 二进制数据}
        """
        try:
            from pydub import AudioSegment
            from io import BytesIO
            from models.segment_dto import SegmentDTO
            
            # 处理各阶段的segments数据
            segment_fields = [
                'segments', 'segmented_segments', 'confirmed_segments',
                'translated_segments', 'optimized_segments', 'final_segments'
            ]
            
            restored_count = 0
            
            for field_name in segment_fields:
                if field_name in project_data and project_data[field_name]:
                    for seg_data in project_data[field_name]:
                        if isinstance(seg_data, dict) and 'audio_path' in seg_data:
                            audio_filename = seg_data['audio_path']
                            
                            if audio_filename in audio_files:
                                try:
                                    # 从二进制数据重新创建AudioSegment对象
                                    audio_buffer = BytesIO(audio_files[audio_filename])
                                    audio_segment = AudioSegment.from_wav(audio_buffer)
                                    
                                    # 由于我们不能直接在字典中存储AudioSegment对象，
                                    # 我们只更新audio_path，实际的AudioSegment会在需要时重新加载
                                    seg_data['has_audio_file'] = True
                                    seg_data['audio_file_size'] = len(audio_files[audio_filename])
                                    
                                    restored_count += 1
                                    logger.debug(f"标记音频文件: {audio_filename}")
                                    
                                except Exception as e:
                                    logger.warning(f"恢复音频文件失败 {audio_filename}: {e}")
                                    seg_data.pop('audio_path', None)
            
            logger.info(f"成功标记了 {restored_count} 个音频文件用于恢复")
            
        except Exception as e:
            logger.error(f"恢复音频数据失败: {e}")
    
    def search_projects(self, query: str, search_in: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        搜索工程
        
        Args:
            query: 搜索关键词
            search_in: 搜索字段列表，默认为名称、描述、标签
            
        Returns:
            匹配的工程列表
        """
        try:
            if search_in is None:
                search_in = ["name", "description", "tags"]
            
            query_lower = query.lower()
            matched_projects = []
            
            for project_info in self.list_projects():
                match_found = False
                
                for field in search_in:
                    if field in project_info:
                        value = project_info[field]
                        if isinstance(value, str) and query_lower in value.lower():
                            match_found = True
                            break
                        elif isinstance(value, list):  # 用于标签
                            if any(query_lower in str(tag).lower() for tag in value):
                                match_found = True
                                break
                
                if match_found:
                    matched_projects.append(project_info)
            
            return matched_projects
            
        except Exception as e:
            logger.error(f"搜索工程失败: {e}")
            return []
    
    def get_projects_statistics(self) -> Dict[str, Any]:
        """获取工程统计信息"""
        try:
            stats = self.projects_index["statistics"].copy()
            
            # 按状态统计
            stage_stats = {}
            language_stats = {}
            total_size = 0
            
            for project_info in self.projects_index["projects"].values():
                # 状态统计
                stage = project_info.get("processing_stage", "unknown")
                stage_stats[stage] = stage_stats.get(stage, 0) + 1
                
                # 语言统计
                lang = project_info.get("target_language", "")
                if lang:
                    language_stats[lang] = language_stats.get(lang, 0) + 1
                
                # 大小统计
                total_size += project_info.get("data_file_size", 0)
            
            stats.update({
                "stage_statistics": stage_stats,
                "language_statistics": language_stats,
                "total_size_bytes": total_size,
                "total_size_mb": total_size / (1024 * 1024)
            })
            
            return stats
            
        except Exception as e:
            logger.error(f"获取工程统计失败: {e}")
            return {}
    
    def check_and_repair_integrity(self) -> Dict[str, Any]:
        """
        检查并修复工程数据完整性
        
        Returns:
            修复结果统计
        """
        try:
            repair_stats = {
                "orphaned_index_removed": 0,
                "orphaned_data_removed": 0,
                "corrupted_data_fixed": 0,
                "total_projects": len(self.projects_index.get("projects", {}))
            }
            
            logger.info("开始工程数据完整性检查...")
            
            # 1. 检查索引中的工程是否有对应数据文件
            projects_to_remove = []
            for project_id, project_info in self.projects_index["projects"].items():
                project_data_file = self.projects_data_dir / f"{project_id}.pkl"
                
                if not project_data_file.exists():
                    logger.warning(f"发现孤立索引记录: {project_id} - {project_info.get('name', '未知')}")
                    projects_to_remove.append(project_id)
                else:
                    # 检查数据文件是否可读
                    try:
                        with open(project_data_file, 'rb') as f:
                            project = pickle.load(f)
                        
                        if not isinstance(project, ProjectDTO):
                            logger.warning(f"工程数据格式错误: {project_id}")
                            projects_to_remove.append(project_id)
                            project_data_file.unlink()  # 删除损坏的文件
                            repair_stats["corrupted_data_fixed"] += 1
                    except Exception as e:
                        logger.warning(f"工程数据文件损坏: {project_id} - {e}")
                        projects_to_remove.append(project_id)
                        try:
                            project_data_file.unlink()  # 删除损坏的文件
                            repair_stats["corrupted_data_fixed"] += 1
                        except:
                            pass
            
            # 移除孤立的索引记录
            for project_id in projects_to_remove:
                project_name = self.projects_index["projects"][project_id].get("name", "未知")
                del self.projects_index["projects"][project_id]
                repair_stats["orphaned_index_removed"] += 1
                logger.info(f"移除孤立索引记录: {project_name} (ID: {project_id})")
            
            # 2. 检查数据文件是否有对应索引记录
            if self.projects_data_dir.exists():
                for data_file in self.projects_data_dir.glob("*.pkl"):
                    project_id = data_file.stem
                    if project_id not in self.projects_index["projects"]:
                        logger.warning(f"发现孤立数据文件: {data_file}")
                        try:
                            data_file.unlink()
                            repair_stats["orphaned_data_removed"] += 1
                            logger.info(f"删除孤立数据文件: {data_file}")
                        except Exception as e:
                            logger.error(f"删除孤立数据文件失败: {e}")
            
            # 保存修复后的索引
            if repair_stats["orphaned_index_removed"] > 0:
                self._save_projects_index()
                logger.info("索引文件已更新")
            
            repair_stats["final_projects"] = len(self.projects_index.get("projects", {}))
            
            logger.info(f"工程完整性检查完成: {repair_stats}")
            return repair_stats
            
        except Exception as e:
            logger.error(f"工程完整性检查失败: {e}")
            return {"error": str(e)}

    def cleanup_old_projects(self, max_age_days: int = 90, max_projects: int = 50):
        """
        清理旧工程
        
        Args:
            max_age_days: 最大保留天数
            max_projects: 最大工程数量
        """
        try:
            current_time = datetime.now(timezone.utc)
            projects_list = self.list_projects()
            
            # 按更新时间排序（旧的在前）
            projects_list.sort(key=lambda x: x.get("updated_at", ""))
            
            removed_count = 0
            
            # 按年龄清理
            for project_info in projects_list:
                try:
                    updated_time = datetime.fromisoformat(project_info["updated_at"])
                    age_days = (current_time - updated_time).days
                    
                    if age_days > max_age_days:
                        self.delete_project(project_info["id"])
                        removed_count += 1
                except Exception:
                    continue
            
            # 按数量清理
            remaining_projects = self.list_projects()
            if len(remaining_projects) > max_projects:
                # 删除最旧的工程
                remaining_projects.sort(key=lambda x: x.get("updated_at", ""))
                for i in range(len(remaining_projects) - max_projects):
                    self.delete_project(remaining_projects[i]["id"])
                    removed_count += 1
            
            # 更新清理时间
            self.projects_index["statistics"]["last_cleanup"] = current_time.isoformat()
            self._save_projects_index()
            
            logger.info(f"工程清理完成: 移除了 {removed_count} 个工程")
            
        except Exception as e:
            logger.error(f"清理工程失败: {e}")
    
    def migrate_from_cache(self, cache_manager) -> int:
        """
        从旧的缓存系统迁移数据到工程系统
        
        Args:
            cache_manager: 旧的缓存管理器实例
            
        Returns:
            迁移的工程数量
        """
        try:
            migrated_count = 0
            
            # 获取所有缓存条目
            cache_entries = cache_manager.cache_index.get("cache_entries", {})
            
            # 按文件哈希分组缓存
            file_groups = {}
            for cache_key, cache_entry in cache_entries.items():
                file_hash = cache_entry.get("file_hash", "")
                if file_hash:
                    if file_hash not in file_groups:
                        file_groups[file_hash] = []
                    file_groups[file_hash].append(cache_entry)
            
            # 为每个文件组创建工程
            for file_hash, cache_group in file_groups.items():
                try:
                    # 构建缓存数据结构
                    cache_data = {}
                    file_path = ""
                    
                    for cache_entry in cache_group:
                        cache_type = cache_entry.get("cache_type", "")
                        if not file_path and cache_entry.get("file_path"):
                            file_path = cache_entry["file_path"]
                        
                        # 加载缓存数据
                        cache_file = cache_manager.cache_data_dir / f"{cache_entry['cache_key']}.pkl"
                        if cache_file.exists():
                            import pickle
                            with open(cache_file, 'rb') as f:
                                data = pickle.load(f)
                            cache_data[cache_type] = data
                    
                    if cache_data:
                        # 从文件路径生成工程名称
                        project_name = Path(file_path).stem if file_path else f"迁移工程_{file_hash[:8]}"
                        
                        # 创建工程
                        project = ProjectDTO.from_legacy_cache(cache_data, project_name)
                        project.description = f"从缓存系统迁移的工程 (文件哈希: {file_hash[:12]})"
                        project.add_tags(["迁移", "缓存"])
                        
                        if self.save_project(project):
                            migrated_count += 1
                            logger.info(f"迁移工程成功: {project.name}")
                
                except Exception as e:
                    logger.warning(f"迁移文件组 {file_hash[:8]} 失败: {e}")
                    continue
            
            logger.info(f"缓存迁移完成: 成功迁移 {migrated_count} 个工程")
            return migrated_count
            
        except Exception as e:
            logger.error(f"从缓存系统迁移失败: {e}")
            return 0


# 全局工程管理器实例
_global_project_manager = None


def get_project_manager() -> ProjectManager:
    """获取全局工程管理器实例"""
    global _global_project_manager
    if _global_project_manager is None:
        _global_project_manager = ProjectManager()
    return _global_project_manager
