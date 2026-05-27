"""
Firebase 项目管理器
管理基于 Firebase Firestore 和 Storage 的项目数据存储
支持用户隔离的项目管理

优化特性：
- 增量保存：只更新变化的字段，减少数据传输
- 防抖保存：聚合短时间内的多次变更，减少写入次数
- 本地缓存：本地维护完整状态，定期同步云端
"""

import json
import threading
import hashlib
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple, Set
from datetime import datetime, timezone
from loguru import logger

from models.project_dto import ProjectDTO
from .firebase_manager import get_firebase_manager, FirebaseManager, FIREBASE_AVAILABLE
from .storage_factory import get_storage_manager
from .firebase_storage import FirebaseStorageManager  # 仅类型注解


class SaveDebouncer:
    """
    保存防抖器 - 聚合短时间内的多次保存请求
    
    Firebase 限制：
    - 每个文档每秒约 1 次写入是安全的
    - 超过频率可能导致 429 错误或写入失败
    """
    
    def __init__(self, delay_seconds: float = 2.0):
        """
        初始化防抖器
        
        Args:
            delay_seconds: 防抖延迟时间（秒），默认 2 秒
        """
        self.delay_seconds = delay_seconds
        self._pending_saves: Dict[str, Dict[str, Any]] = {}  # project_id -> {project, fields, timer}
        self._lock = threading.Lock()
        self._save_callback = None
        self._batch_save_callback = None  # 批量保存回调
    
    def set_save_callback(self, callback):
        """设置实际执行保存的回调函数"""
        self._save_callback = callback
    
    def set_batch_save_callback(self, callback):
        """设置批量保存的回调函数（用于同时保存多个项目）"""
        self._batch_save_callback = callback
    
    def request_save(self, project_id: str, project: 'ProjectDTO', fields: Optional[Set[str]] = None):
        """
        请求保存项目（防抖处理）
        
        Args:
            project_id: 项目 ID
            project: 项目对象
            fields: 需要保存的字段集合，None 表示全量保存
        """
        with self._lock:
            # 取消之前的定时器
            if project_id in self._pending_saves:
                timer = self._pending_saves[project_id].get('timer')
                if timer:
                    timer.cancel()
                
                # 合并字段
                existing_fields = self._pending_saves[project_id].get('fields')
                if existing_fields is not None and fields is not None:
                    fields = existing_fields | fields
                elif existing_fields is None or fields is None:
                    fields = None  # 任一方要求全量保存，则全量保存
            
            # 创建新的定时器
            timer = threading.Timer(self.delay_seconds, self._execute_save, args=[project_id])
            timer.start()
            
            # 保存待处理的请求
            self._pending_saves[project_id] = {
                'project': project,
                'fields': fields,
                'timer': timer,
                'requested_at': datetime.now(timezone.utc)
            }
            
            logger.debug(f"保存请求已排队: {project_id}, 将在 {self.delay_seconds}s 后执行")
    
    def _execute_save(self, project_id: str):
        """执行实际的保存操作"""
        with self._lock:
            if project_id not in self._pending_saves:
                return
            
            pending = self._pending_saves.pop(project_id)
            project = pending['project']
            fields = pending['fields']
        
        # 执行保存回调
        if self._save_callback:
            try:
                self._save_callback(project, fields)
                logger.debug(f"防抖保存执行完成: {project_id}")
            except Exception as e:
                logger.error(f"防抖保存执行失败: {project_id} - {e}")
    
    def flush(self, project_id: Optional[str] = None, use_batch: bool = False):
        """
        立即执行待处理的保存
        
        Args:
            project_id: 指定项目 ID，None 表示所有项目
            use_batch: 是否使用批量写入（仅当 project_id=None 且有多个待保存项目时有效）
        """
        with self._lock:
            if project_id:
                ids_to_flush = [project_id] if project_id in self._pending_saves else []
            else:
                ids_to_flush = list(self._pending_saves.keys())
            
            # 取消所有待刷新的定时器
            for pid in ids_to_flush:
                if pid in self._pending_saves:
                    timer = self._pending_saves[pid].get('timer')
                    if timer:
                        timer.cancel()
        
        # 🔥 优化：支持批量保存
        if use_batch and len(ids_to_flush) > 1 and self._batch_save_callback:
            # 收集所有待保存的数据
            batch_data = []
            with self._lock:
                for pid in ids_to_flush:
                    if pid in self._pending_saves:
                        pending = self._pending_saves.pop(pid)
                        batch_data.append({
                            'project': pending['project'],
                            'fields': pending['fields']
                        })
            
            if batch_data:
                try:
                    self._batch_save_callback(batch_data)
                    logger.info(f"批量保存执行完成: {len(batch_data)} 个项目")
                except Exception as e:
                    logger.error(f"批量保存执行失败: {e}")
                    # 失败时回退到逐个保存
                    for item in batch_data:
                        try:
                            self._save_callback(item['project'], item['fields'])
                        except Exception as inner_e:
                            logger.error(f"回退保存失败: {inner_e}")
        else:
            # 逐个保存
            for pid in ids_to_flush:
                self._execute_save(pid)
    
    def cancel(self, project_id: str):
        """取消待处理的保存"""
        with self._lock:
            if project_id in self._pending_saves:
                timer = self._pending_saves[project_id].get('timer')
                if timer:
                    timer.cancel()
                del self._pending_saves[project_id]
    
    def get_pending_count(self) -> int:
        """获取待处理的保存数量"""
        with self._lock:
            return len(self._pending_saves)


class FirebaseProjectManager:
    """
    Firebase 项目管理器
    - 项目元数据存储在 Firestore
    - 音频文件存储在 Firebase Storage
    - 支持按用户隔离数据
    
    优化特性：
    - 增量保存：只更新变化的字段
    - 防抖保存：聚合多次变更后一次写入
    - 本地快照：跟踪上次保存的状态，避免额外网络请求
    - 智能字段检测：基于数据大小判断是否使用增量更新
    """
    
    # 大数据字段列表（这些字段数据量大，变化时建议全量保存）
    _LARGE_DATA_FIELDS = {
        'segments', 'segmented_segments', 'confirmed_segments',
        'translated_segments', 'optimized_segments', 'final_segments',
        'audio_storage_paths'
    }
    
    # 增量更新的数据大小阈值（字节）
    _INCREMENTAL_UPDATE_SIZE_THRESHOLD = 10 * 1024  # 10KB
    
    def __init__(self, user_id: Optional[str] = None):
        """
        初始化 Firebase 项目管理器
        
        Args:
            user_id: 用户 ID，如果为 None 则需要后续设置
        """
        self.user_id = user_id
        self.firebase: Optional[FirebaseManager] = None
        self.storage: Optional[FirebaseStorageManager] = None
        self.is_initialized = False
        
        # 增量保存相关 - 缓存完整数据用于本地比较，避免额外网络请求
        self._project_snapshots: Dict[str, str] = {}  # project_id -> hash of last saved state
        self._project_data_cache: Dict[str, Dict[str, Any]] = {}  # project_id -> last saved data (本地缓存)
        self._save_debouncer = SaveDebouncer(delay_seconds=2.0)
        self._save_debouncer.set_save_callback(self._do_save_project)
        self._save_debouncer.set_batch_save_callback(self._do_batch_save_projects)
        
    def initialize(self, config: Dict[str, Any]) -> bool:
        """
        初始化 Firebase 连接
        
        Args:
            config: 配置字典
            
        Returns:
            是否初始化成功
        """
        if not FIREBASE_AVAILABLE:
            logger.error("Firebase SDK 未安装，请运行: pip install firebase-admin")
            return False
        
        try:
            # 初始化 Firebase
            self.firebase = get_firebase_manager()
            if not self.firebase.initialize(config):
                logger.error("Firebase 初始化失败")
                return False
            
            # 初始化 Storage
            self.storage = get_storage_manager()
            if not self.storage.initialize(config):
                logger.warning("Firebase Storage 初始化失败，音频将不能云端存储")
            
            # 设置当前用户
            if self.user_id:
                self.firebase.set_current_user(self.user_id)
                self.firebase.ensure_user_exists(self.user_id)
            
            self.is_initialized = True
            logger.info(f"Firebase 项目管理器初始化成功 (用户: {self.user_id})")
            return True
            
        except Exception as e:
            logger.error(f"Firebase 项目管理器初始化失败: {e}")
            return False
    
    def set_user(self, user_id: str):
        """
        设置当前用户
        
        Args:
            user_id: 用户 ID
        """
        self.user_id = user_id
        if self.firebase:
            self.firebase.set_current_user(user_id)
            self.firebase.ensure_user_exists(user_id)
        logger.debug(f"当前用户设置为: {user_id}")
    
    def _get_projects_collection(self) -> str:
        """获取用户项目集合路径"""
        if not self.user_id:
            raise ValueError("未设置用户 ID")
        return f"users/{self.user_id}/projects"
    
    # ==================== 项目 CRUD 操作 ====================
    
    def create_project(
        self, 
        name: str, 
        filename: str = "", 
        file_content: bytes = b"",
        description: str = ""
    ) -> Optional[ProjectDTO]:
        """
        创建新项目
        
        Args:
            name: 项目名称
            filename: 原始文件名
            file_content: 文件内容
            description: 项目描述
            
        Returns:
            创建的项目对象，失败返回 None
        """
        if not self.is_initialized or not self.user_id:
            logger.error("Firebase 未初始化或未设置用户")
            return None
        
        try:
            # 创建项目对象
            if filename and file_content:
                project = ProjectDTO.create_from_file(filename, file_content, name, description)
            else:
                project = ProjectDTO(
                    id="",
                    name=name,
                    description=description
                )
            
            # 设置所有者和存储后端
            project.set_owner(self.user_id)
            project.storage_backend = "firebase"
            
            # 保存到 Firestore
            if self.save_project(project):
                logger.info(f"创建项目成功: {project.name} (ID: {project.id})")
                return project
            else:
                return None
                
        except Exception as e:
            logger.error(f"创建项目失败: {e}")
            return None
    
    def _compute_project_hash(self, project_data: Dict[str, Any]) -> str:
        """
        计算项目数据的哈希值（用于检测变化）
        
        Args:
            project_data: 项目数据字典
            
        Returns:
            数据哈希值
        """
        # 排除频繁变化的字段
        exclude_fields = {'updated_at'}
        filtered_data = {k: v for k, v in project_data.items() if k not in exclude_fields}
        data_str = json.dumps(filtered_data, sort_keys=True, ensure_ascii=False)
        return hashlib.md5(data_str.encode('utf-8')).hexdigest()
    
    def _detect_changed_fields(self, old_data: Dict[str, Any], new_data: Dict[str, Any]) -> Set[str]:
        """
        检测两个项目数据之间变化的字段
        
        Args:
            old_data: 旧数据
            new_data: 新数据
            
        Returns:
            变化的字段名集合
        """
        changed_fields = set()
        
        all_keys = set(old_data.keys()) | set(new_data.keys())
        
        for key in all_keys:
            old_val = old_data.get(key)
            new_val = new_data.get(key)
            
            # 使用 JSON 序列化比较，处理嵌套对象
            old_json = json.dumps(old_val, sort_keys=True, ensure_ascii=False) if old_val else None
            new_json = json.dumps(new_val, sort_keys=True, ensure_ascii=False) if new_val else None
            
            if old_json != new_json:
                changed_fields.add(key)
        
        return changed_fields
    
    def save_project(self, project: ProjectDTO, force_full: bool = False, use_debounce: bool = True) -> bool:
        """
        保存项目到 Firestore（智能保存）
        
        Args:
            project: 项目对象
            force_full: 是否强制全量保存
            use_debounce: 是否使用防抖（默认 True，关键节点可设为 False）
            
        Returns:
            是否保存成功（防抖模式下返回 True 表示已排队）
        """
        if not self.is_initialized:
            logger.error("Firebase 未初始化")
            return False
        
        try:
            # 确保设置了所有者
            if not project.owner_id and self.user_id:
                project.set_owner(self.user_id)
            
            # 更新时间戳
            project.updated_at = datetime.now(timezone.utc).isoformat()
            
            if use_debounce:
                # 使用防抖保存
                fields = None if force_full else set()  # 空集合表示需要检测变化
                self._save_debouncer.request_save(project.id, project, fields)
                return True
            else:
                # 直接保存
                return self._do_save_project(project, None if force_full else set())
            
        except Exception as e:
            logger.error(f"保存项目失败: {e}")
            return False
    
    def _do_save_project(self, project: ProjectDTO, fields: Optional[Set[str]] = None) -> bool:
        """
        执行实际的项目保存（内部方法）
        
        优化策略：
        1. 使用本地缓存数据进行比较，避免额外网络请求
        2. 智能判断是否使用增量更新（基于数据大小和字段类型）
        3. 大数据字段变化时直接使用全量保存
        
        Args:
            project: 项目对象
            fields: 需要保存的字段集合，None 或空集合表示全量/智能检测
            
        Returns:
            是否保存成功
        """
        try:
            # 转换为 Firestore 兼容格式
            project_data = project.to_firestore_dict()
            collection_path = self._get_projects_collection()
            
            # 检查是否有上次保存的快照
            last_hash = self._project_snapshots.get(project.id)
            current_hash = self._compute_project_hash(project_data)
            
            if last_hash == current_hash:
                logger.debug(f"项目无变化，跳过保存: {project.id}")
                return True
            
            # 如果有上次的数据，尝试增量更新
            # 🔥 优化：使用本地缓存数据，避免额外网络请求
            if last_hash and fields is not None:
                # 优先使用本地缓存的数据进行比较
                old_data = self._project_data_cache.get(project.id)
                
                if old_data:
                    changed_fields = self._detect_changed_fields(old_data, project_data)
                    
                    if not changed_fields:
                        logger.debug(f"项目无字段变化，跳过保存: {project.id}")
                        return True
                    
                    # 🔥 优化：智能判断是否使用增量更新
                    use_incremental = self._should_use_incremental_update(changed_fields, project_data)
                    
                    if use_incremental:
                        update_data = {k: project_data[k] for k in changed_fields if k in project_data}
                        update_data['updated_at'] = project.updated_at
                        
                        success = self.firebase.update_document(collection_path, project.id, update_data)
                        
                        if success:
                            self._project_snapshots[project.id] = current_hash
                            self._project_data_cache[project.id] = project_data.copy()  # 更新本地缓存
                            logger.info(f"增量保存成功: {project.name} (更新了 {len(changed_fields)} 个字段: {changed_fields})")
                        return success
            
            # 全量保存
            success = self.firebase.set_document(collection_path, project.id, project_data)
            
            if success:
                self._project_snapshots[project.id] = current_hash
                self._project_data_cache[project.id] = project_data.copy()  # 更新本地缓存
                logger.debug(f"全量保存成功: {project.name} (ID: {project.id})")
            
            return success
            
        except Exception as e:
            logger.error(f"执行保存失败: {e}")
            return False
    
    def _should_use_incremental_update(self, changed_fields: Set[str], project_data: Dict[str, Any]) -> bool:
        """
        智能判断是否应该使用增量更新
        
        决策逻辑：
        1. 如果变化的字段包含大数据字段（segments 等），使用全量保存
        2. 如果变化数据的总大小超过阈值，使用全量保存
        3. 如果变化字段数量超过 5 个，使用全量保存
        4. 否则使用增量更新
        
        Args:
            changed_fields: 变化的字段集合
            project_data: 新的项目数据
            
        Returns:
            是否使用增量更新
        """
        # 检查是否包含大数据字段
        if changed_fields & self._LARGE_DATA_FIELDS:
            logger.debug(f"变化字段包含大数据字段，使用全量保存: {changed_fields & self._LARGE_DATA_FIELDS}")
            return False
        
        # 检查字段数量
        if len(changed_fields) > 5:
            logger.debug(f"变化字段数量过多 ({len(changed_fields)})，使用全量保存")
            return False
        
        # 检查变化数据的总大小
        try:
            changed_data_size = 0
            for field in changed_fields:
                if field in project_data:
                    field_data = json.dumps(project_data[field], ensure_ascii=False)
                    changed_data_size += len(field_data.encode('utf-8'))
            
            if changed_data_size > self._INCREMENTAL_UPDATE_SIZE_THRESHOLD:
                logger.debug(f"变化数据大小 ({changed_data_size} bytes) 超过阈值，使用全量保存")
                return False
        except Exception:
            pass  # 计算失败时继续使用字段数量判断
        
        return True
    
    def _do_batch_save_projects(self, batch_data: List[Dict[str, Any]]) -> bool:
        """
        批量保存多个项目（内部方法）
        
        🔥 优化：使用 Firebase batch write 一次性写入多个文档
        减少网络往返次数，提高吞吐量
        
        Args:
            batch_data: 批量数据列表 [{'project': ProjectDTO, 'fields': Set[str]}, ...]
            
        Returns:
            是否保存成功
        """
        if not batch_data:
            return True
        
        try:
            collection_path = self._get_projects_collection()
            operations = []
            update_cache = []  # 用于成功后更新缓存
            
            for item in batch_data:
                project = item['project']
                project_data = project.to_firestore_dict()
                current_hash = self._compute_project_hash(project_data)
                
                # 检查是否有变化
                last_hash = self._project_snapshots.get(project.id)
                if last_hash == current_hash:
                    logger.debug(f"批量保存: 项目 {project.id} 无变化，跳过")
                    continue
                
                # 准备操作
                operations.append({
                    'type': 'set',
                    'collection': collection_path,
                    'doc_id': project.id,
                    'data': project_data
                })
                
                update_cache.append({
                    'project_id': project.id,
                    'hash': current_hash,
                    'data': project_data
                })
            
            if not operations:
                logger.debug("批量保存: 所有项目均无变化")
                return True
            
            # 执行批量写入
            success = self.firebase.batch_write(operations)
            
            if success:
                # 更新本地缓存
                for cache_item in update_cache:
                    self._project_snapshots[cache_item['project_id']] = cache_item['hash']
                    self._project_data_cache[cache_item['project_id']] = cache_item['data'].copy()
                
                logger.info(f"批量保存成功: {len(operations)} 个项目")
            
            return success
            
        except Exception as e:
            logger.error(f"批量保存失败: {e}")
            return False
    
    def save_project_immediate(self, project: ProjectDTO) -> bool:
        """
        立即保存项目（跳过防抖，用于关键节点）
        
        Args:
            project: 项目对象
            
        Returns:
            是否保存成功
        """
        # 先刷新该项目的待保存队列
        self._save_debouncer.flush(project.id)
        # 直接保存
        return self.save_project(project, force_full=False, use_debounce=False)
    
    def flush_pending_saves(self, use_batch: bool = True):
        """
        刷新所有待保存的项目（用于程序退出或关键节点）
        
        Args:
            use_batch: 是否使用批量写入（默认 True，可减少网络请求）
        """
        self._save_debouncer.flush(use_batch=use_batch)
        logger.info("已刷新所有待保存的项目")
    
    def load_project(self, project_id: str, user_id: Optional[str] = None) -> Optional[ProjectDTO]:
        """
        加载项目

        Args:
            project_id: 项目 ID
            user_id: 接口对齐参数；Firebase 后端已通过 user collection 隔离，此处忽略

        Returns:
            项目对象，不存在返回 None
        """
        if not self.is_initialized:
            logger.error("Firebase 未初始化")
            return None
        
        try:
            collection_path = self._get_projects_collection()
            project_data = self.firebase.get_document(collection_path, project_id)
            
            if not project_data:
                logger.warning(f"项目不存在: {project_id}")
                return None
            
            # 从 Firestore 数据创建项目对象
            project = ProjectDTO.from_firestore_dict(project_data)
            
            # 保存快照 hash 和完整数据（用于后续增量保存比较，避免额外网络请求）
            self._project_snapshots[project_id] = self._compute_project_hash(project_data)
            self._project_data_cache[project_id] = project_data.copy()  # 🔥 缓存完整数据
            
            logger.debug(f"项目加载成功: {project.name} (ID: {project_id})")
            return project
            
        except Exception as e:
            logger.error(f"加载项目失败: {e}")
            return None
    
    def delete_project(self, project_id: str, delete_audio: bool = True, user_id: Optional[str] = None) -> bool:
        """
        删除项目

        Args:
            project_id: 项目 ID
            delete_audio: 是否同时删除音频文件
            user_id: 接口对齐参数；Firebase 后端已通过 user collection 隔离，此处忽略

        Returns:
            是否删除成功
        """
        if not self.is_initialized:
            logger.error("Firebase 未初始化")
            return False
        
        try:
            # 删除音频文件
            if delete_audio and self.storage and self.storage.is_connected:
                deleted_count = self.storage.delete_project_audio(self.user_id, project_id)
                logger.debug(f"删除了 {deleted_count} 个音频文件")
            
            # 删除 Firestore 文档
            collection_path = self._get_projects_collection()
            success = self.firebase.delete_document(collection_path, project_id)
            
            if success:
                logger.info(f"项目删除成功: {project_id}")
            
            return success
            
        except Exception as e:
            logger.error(f"删除项目失败: {e}")
            return False
    
    def list_projects(
        self,
        include_shared: bool = False,
        order_by: str = 'updated_at',
        limit: Optional[int] = None,
        user_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        获取项目列表

        Args:
            include_shared: 是否包含共享项目
            order_by: 排序字段
            limit: 限制返回数量
            user_id: 接口对齐参数；Firebase 后端已通过 user collection 隔离，此处忽略

        Returns:
            项目信息列表
        """
        if not self.is_initialized:
            logger.error("Firebase 未初始化")
            return []
        
        try:
            collection_path = self._get_projects_collection()
            
            # 查询项目
            projects = self.firebase.query_documents(
                collection_path,
                order_by=order_by,
                order_direction='DESCENDING',
                limit=limit
            )
            
            # 过滤共享项目（如果需要）
            if not include_shared:
                projects = [p for p in projects if not p.get('is_shared', False)]
            
            logger.debug(f"获取到 {len(projects)} 个项目")
            return projects
            
        except Exception as e:
            logger.error(f"获取项目列表失败: {e}")
            return []
    
    def search_projects(
        self, 
        query: str, 
        search_in: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        搜索项目
        
        Args:
            query: 搜索关键词
            search_in: 搜索字段列表
            
        Returns:
            匹配的项目列表
        """
        if search_in is None:
            search_in = ['name', 'description', 'tags']
        
        try:
            # 获取所有项目
            all_projects = self.list_projects()
            
            # 客户端过滤（Firestore 不支持全文搜索）
            query_lower = query.lower()
            matched = []
            
            for project in all_projects:
                for field in search_in:
                    value = project.get(field, '')
                    if isinstance(value, str) and query_lower in value.lower():
                        matched.append(project)
                        break
                    elif isinstance(value, list):
                        if any(query_lower in str(item).lower() for item in value):
                            matched.append(project)
                            break
            
            return matched
            
        except Exception as e:
            logger.error(f"搜索项目失败: {e}")
            return []
    
    def duplicate_project(self, project_id: str, new_name: str = "", user_id: Optional[str] = None) -> Optional[ProjectDTO]:
        """
        复制项目

        Args:
            project_id: 原项目 ID
            new_name: 新项目名称
            user_id: 接口对齐参数；Firebase 后端已通过 user collection 隔离，此处忽略

        Returns:
            新项目对象
        """
        try:
            # 加载原项目
            original = self.load_project(project_id)
            if not original:
                return None
            
            # 创建副本
            project_dict = original.to_dict()
            project_dict['id'] = ""  # 重新生成 ID
            project_dict['name'] = new_name or f"{original.name} - 副本"
            project_dict['created_at'] = datetime.now(timezone.utc).isoformat()
            project_dict['updated_at'] = datetime.now(timezone.utc).isoformat()
            project_dict['is_shared'] = False
            project_dict['share_url'] = ""
            project_dict['audio_storage_paths'] = {}  # 音频需要重新生成
            
            new_project = ProjectDTO.from_dict(project_dict)
            new_project.set_owner(self.user_id)
            
            if self.save_project(new_project):
                logger.info(f"项目复制成功: {new_project.name}")
                return new_project
            
            return None
            
        except Exception as e:
            logger.error(f"复制项目失败: {e}")
            return None
    
    # ==================== 音频文件操作 ====================
    
    def upload_segment_audio(
        self, 
        project: ProjectDTO, 
        segment_id: str, 
        audio_data,
        format: str = 'mp3'
    ) -> Optional[str]:
        """
        上传片段音频到 Firebase Storage
        
        Args:
            project: 项目对象
            segment_id: 片段 ID
            audio_data: 音频数据（bytes 或 AudioSegment）
            format: 音频格式
            
        Returns:
            存储路径，失败返回 None
        """
        if not self.storage or not self.storage.is_connected:
            logger.warning("Firebase Storage 未连接，无法上传音频")
            return None
        
        try:
            filename = f"{segment_id}.{format}"
            content_type = 'audio/mpeg' if format == 'mp3' else 'audio/wav'
            
            storage_path = self.storage.upload_audio(
                user_id=self.user_id,
                project_id=project.id,
                filename=filename,
                audio_data=audio_data,
                content_type=content_type
            )
            
            if storage_path:
                # 更新项目的音频路径映射
                project.update_audio_storage_path(segment_id, storage_path)
            
            return storage_path
            
        except Exception as e:
            logger.error(f"上传音频失败: {e}")
            return None
    
    def download_segment_audio(
        self, 
        project: ProjectDTO, 
        segment_id: str
    ) -> Optional[bytes]:
        """
        下载片段音频
        
        Args:
            project: 项目对象
            segment_id: 片段 ID
            
        Returns:
            音频数据
        """
        if not self.storage or not self.storage.is_connected:
            return None
        
        try:
            storage_path = project.get_audio_storage_path(segment_id)
            if not storage_path:
                return None
            
            return self.storage.download_audio(storage_path)
            
        except Exception as e:
            logger.error(f"下载音频失败: {e}")
            return None
    
    def get_audio_url(
        self, 
        project: ProjectDTO, 
        segment_id: str,
        expiration: int = 3600
    ) -> Optional[str]:
        """
        获取音频的临时下载 URL
        
        Args:
            project: 项目对象
            segment_id: 片段 ID
            expiration: URL 有效期（秒）
            
        Returns:
            下载 URL
        """
        if not self.storage or not self.storage.is_connected:
            return None
        
        storage_path = project.get_audio_storage_path(segment_id)
        if not storage_path:
            return None
        
        return self.storage.get_download_url(storage_path, expiration)
    
    # ==================== 统计和工具方法 ====================
    
    def get_user_statistics(self) -> Dict[str, Any]:
        """
        获取用户统计信息
        
        Returns:
            统计信息字典
        """
        if not self.is_initialized:
            return {}
        
        try:
            # 项目统计
            projects = self.list_projects()
            
            stage_stats = {}
            language_stats = {}
            total_duration = 0
            
            for p in projects:
                # 阶段统计
                stage = p.get('processing_stage', 'unknown')
                stage_stats[stage] = stage_stats.get(stage, 0) + 1
                
                # 语言统计
                lang = p.get('target_language', '')
                if lang:
                    language_stats[lang] = language_stats.get(lang, 0) + 1
                
                # 总时长
                total_duration += p.get('total_duration', 0)
            
            # 存储使用情况
            storage_usage = {}
            if self.storage and self.storage.is_connected:
                storage_usage = self.storage.get_storage_usage(self.user_id)
            
            return {
                'total_projects': len(projects),
                'stage_statistics': stage_stats,
                'language_statistics': language_stats,
                'total_duration': total_duration,
                'total_duration_formatted': f"{total_duration / 60:.1f} 分钟",
                'storage_usage': storage_usage,
                'user_id': self.user_id
            }
            
        except Exception as e:
            logger.error(f"获取用户统计失败: {e}")
            return {}
    
    def health_check(self) -> Dict[str, Any]:
        """健康检查"""
        status = {
            'initialized': self.is_initialized,
            'user_id': self.user_id,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'pending_saves': self._save_debouncer.get_pending_count(),
            'cached_snapshots': len(self._project_snapshots)
        }
        
        if self.firebase:
            status['firestore'] = self.firebase.health_check()
        
        if self.storage:
            status['storage'] = self.storage.health_check()
        
        return status
    
    def get_save_stats(self) -> Dict[str, Any]:
        """
        获取保存统计信息
        
        Returns:
            保存统计字典
        """
        # 计算缓存数据的大小
        cache_size_bytes = 0
        for data in self._project_data_cache.values():
            try:
                cache_size_bytes += len(json.dumps(data, ensure_ascii=False).encode('utf-8'))
            except Exception:
                pass
        
        return {
            'pending_saves': self._save_debouncer.get_pending_count(),
            'cached_project_count': len(self._project_snapshots),
            'cached_data_count': len(self._project_data_cache),
            'cached_data_size_kb': cache_size_bytes / 1024,
            'debounce_delay_seconds': self._save_debouncer.delay_seconds,
            'incremental_update_threshold_kb': self._INCREMENTAL_UPDATE_SIZE_THRESHOLD / 1024,
            'large_data_fields': list(self._LARGE_DATA_FIELDS)
        }


# 全局实例管理
_firebase_project_managers: Dict[str, FirebaseProjectManager] = {}


def get_firebase_project_manager(user_id: str, config: Optional[Dict[str, Any]] = None) -> FirebaseProjectManager:
    """
    获取或创建用户的 Firebase 项目管理器
    
    Args:
        user_id: 用户 ID
        config: 配置字典（首次创建时需要）
        
    Returns:
        FirebaseProjectManager 实例
    """
    global _firebase_project_managers
    
    if user_id not in _firebase_project_managers:
        manager = FirebaseProjectManager(user_id)
        if config:
            manager.initialize(config)
        _firebase_project_managers[user_id] = manager
    
    return _firebase_project_managers[user_id]
