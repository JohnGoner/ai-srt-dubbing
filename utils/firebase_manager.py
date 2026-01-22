"""
Firebase 管理器模块
负责 Firebase 初始化、Firestore 数据库操作和用户管理
"""

import os
import json
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
from loguru import logger

# Firebase SDK
try:
    import firebase_admin
    from firebase_admin import credentials, firestore, auth
    FIREBASE_AVAILABLE = True
except ImportError:
    FIREBASE_AVAILABLE = False
    logger.warning("Firebase SDK 未安装，请运行: pip install firebase-admin")


class FirebaseManager:
    """Firebase 管理器 - 单例模式"""
    
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if FirebaseManager._initialized:
            return
        
        self.app = None
        self.db = None
        self.is_connected = False
        self.current_user_id = None
        self.config = {}
        
    def initialize(self, config: Dict[str, Any]) -> bool:
        """
        初始化 Firebase 连接
        
        Args:
            config: 配置字典，包含 Firebase 凭证路径等信息
            
        Returns:
            是否初始化成功
        """
        if not FIREBASE_AVAILABLE:
            logger.error("Firebase SDK 未安装")
            return False
        
        if self.is_connected:
            logger.debug("Firebase 已连接，跳过重复初始化")
            return True
        
        try:
            self.config = config
            firebase_config = config.get('firebase', {})
            
            # 获取凭证文件路径
            credentials_path = firebase_config.get('credentials_path', '')
            
            # 支持环境变量
            if not credentials_path:
                credentials_path = os.environ.get('FIREBASE_CREDENTIALS', '')
            
            # 搜索常见位置
            if not credentials_path or not Path(credentials_path).exists():
                # 获取项目根目录（ai-srt-dubbing/ai-srt-dubbing/）
                project_root = Path(__file__).parent.parent
                
                possible_paths = [
                    # 项目目录下
                    project_root / 'firebase-credentials.json',
                    project_root / 'google-credentials.json',
                    # 当前工作目录
                    Path.cwd() / 'firebase-credentials.json',
                    Path.cwd() / 'google-credentials.json',
                    # 用户配置目录
                    Path.home() / '.config' / 'firebase-credentials.json',
                ]
                for p in possible_paths:
                    if p.exists():
                        credentials_path = str(p)
                        logger.info(f"找到 Firebase 凭证文件: {credentials_path}")
                        break
            
            if not credentials_path or not Path(credentials_path).exists():
                logger.error(f"Firebase 凭证文件未找到，请配置 firebase.credentials_path 或设置环境变量 FIREBASE_CREDENTIALS")
                return False
            
            # 初始化 Firebase
            cred = credentials.Certificate(credentials_path)
            
            # 获取 Storage Bucket 配置
            storage_bucket = firebase_config.get('storage_bucket', '')
            logger.info(f"从配置读取 storage_bucket: '{storage_bucket}'")
            if not storage_bucket:
                storage_bucket = os.environ.get('FIREBASE_STORAGE_BUCKET', '')
                logger.info(f"从环境变量读取 FIREBASE_STORAGE_BUCKET: '{storage_bucket}'")
            
            # 检查是否已有应用实例
            try:
                self.app = firebase_admin.get_app()
                # 检查现有应用的 storage bucket 配置是否正确
                existing_bucket = self.app.options.get('storageBucket', '')
                if storage_bucket and existing_bucket != storage_bucket:
                    logger.warning(f"现有 Firebase 应用的 Storage Bucket ({existing_bucket}) 与配置 ({storage_bucket}) 不一致")
                    logger.info(f"删除旧的 Firebase 应用实例，重新初始化...")
                    # 删除旧应用，重新初始化
                    firebase_admin.delete_app(self.app)
                    raise ValueError("重新初始化")
                else:
                    logger.debug(f"使用已存在的 Firebase 应用实例, storageBucket={existing_bucket}")
            except ValueError:
                # 没有已初始化的应用，创建新的
                # 如果配置了 storage bucket，则在初始化时指定
                app_options = {}
                if storage_bucket:
                    app_options['storageBucket'] = storage_bucket
                    logger.info(f"配置 Storage Bucket: {storage_bucket}")
                
                self.app = firebase_admin.initialize_app(cred, app_options if app_options else None)
                logger.info(f"Firebase 应用初始化成功, storageBucket={storage_bucket}")
            
            # 初始化 Firestore
            self.db = firestore.client()
            self.is_connected = True
            
            FirebaseManager._initialized = True
            logger.info("Firebase Firestore 连接成功")
            return True
            
        except Exception as e:
            logger.error(f"Firebase 初始化失败: {e}")
            self.is_connected = False
            return False
    
    def set_current_user(self, user_id: str):
        """设置当前用户 ID"""
        self.current_user_id = user_id
        logger.debug(f"当前用户设置为: {user_id}")
    
    def get_current_user(self) -> Optional[str]:
        """获取当前用户 ID"""
        return self.current_user_id
    
    # ==================== Firestore 基础操作 ====================
    
    def get_collection(self, collection_path: str):
        """获取集合引用"""
        if not self.is_connected:
            raise RuntimeError("Firebase 未连接")
        return self.db.collection(collection_path)
    
    def get_document(self, collection_path: str, doc_id: str) -> Optional[Dict[str, Any]]:
        """
        获取单个文档
        
        Args:
            collection_path: 集合路径
            doc_id: 文档 ID
            
        Returns:
            文档数据字典，不存在则返回 None
        """
        if not self.is_connected:
            raise RuntimeError("Firebase 未连接")
        
        try:
            doc_ref = self.db.collection(collection_path).document(doc_id)
            doc = doc_ref.get()
            
            if doc.exists:
                return doc.to_dict()
            return None
            
        except Exception as e:
            logger.error(f"获取文档失败 [{collection_path}/{doc_id}]: {e}")
            return None
    
    def set_document(self, collection_path: str, doc_id: str, data: Dict[str, Any], merge: bool = False) -> bool:
        """
        设置文档数据
        
        Args:
            collection_path: 集合路径
            doc_id: 文档 ID
            data: 文档数据
            merge: 是否合并（而非覆盖）
            
        Returns:
            是否成功
        """
        if not self.is_connected:
            raise RuntimeError("Firebase 未连接")
        
        try:
            doc_ref = self.db.collection(collection_path).document(doc_id)
            doc_ref.set(data, merge=merge)
            logger.debug(f"文档写入成功: {collection_path}/{doc_id}")
            return True
            
        except Exception as e:
            logger.error(f"写入文档失败 [{collection_path}/{doc_id}]: {e}")
            return False
    
    def update_document(self, collection_path: str, doc_id: str, data: Dict[str, Any]) -> bool:
        """
        更新文档字段
        
        Args:
            collection_path: 集合路径
            doc_id: 文档 ID
            data: 要更新的字段
            
        Returns:
            是否成功
        """
        if not self.is_connected:
            raise RuntimeError("Firebase 未连接")
        
        try:
            doc_ref = self.db.collection(collection_path).document(doc_id)
            doc_ref.update(data)
            return True
            
        except Exception as e:
            logger.error(f"更新文档失败 [{collection_path}/{doc_id}]: {e}")
            return False
    
    def delete_document(self, collection_path: str, doc_id: str) -> bool:
        """
        删除文档
        
        Args:
            collection_path: 集合路径
            doc_id: 文档 ID
            
        Returns:
            是否成功
        """
        if not self.is_connected:
            raise RuntimeError("Firebase 未连接")
        
        try:
            doc_ref = self.db.collection(collection_path).document(doc_id)
            doc_ref.delete()
            logger.debug(f"文档删除成功: {collection_path}/{doc_id}")
            return True
            
        except Exception as e:
            logger.error(f"删除文档失败 [{collection_path}/{doc_id}]: {e}")
            return False
    
    def query_documents(
        self, 
        collection_path: str, 
        filters: Optional[List[tuple]] = None,
        order_by: Optional[str] = None,
        order_direction: str = 'DESCENDING',
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        查询文档
        
        Args:
            collection_path: 集合路径
            filters: 过滤条件列表 [(field, operator, value), ...]
            order_by: 排序字段
            order_direction: 排序方向 ('ASCENDING' 或 'DESCENDING')
            limit: 限制返回数量
            
        Returns:
            文档列表
        """
        if not self.is_connected:
            raise RuntimeError("Firebase 未连接")
        
        try:
            query = self.db.collection(collection_path)
            
            # 应用过滤条件
            if filters:
                for field, operator, value in filters:
                    query = query.where(field, operator, value)
            
            # 应用排序
            if order_by:
                direction = firestore.Query.DESCENDING if order_direction == 'DESCENDING' else firestore.Query.ASCENDING
                query = query.order_by(order_by, direction=direction)
            
            # 应用限制
            if limit:
                query = query.limit(limit)
            
            # 执行查询
            docs = query.stream()
            results = []
            for doc in docs:
                data = doc.to_dict()
                data['_id'] = doc.id  # 添加文档 ID
                results.append(data)
            
            return results
            
        except Exception as e:
            logger.error(f"查询文档失败 [{collection_path}]: {e}")
            return []
    
    def batch_write(self, operations: List[Dict[str, Any]]) -> bool:
        """
        批量写入操作
        
        Args:
            operations: 操作列表 [{'type': 'set'|'update'|'delete', 'collection': str, 'doc_id': str, 'data': dict}, ...]
            
        Returns:
            是否成功
        """
        if not self.is_connected:
            raise RuntimeError("Firebase 未连接")
        
        try:
            batch = self.db.batch()
            
            for op in operations:
                doc_ref = self.db.collection(op['collection']).document(op['doc_id'])
                
                if op['type'] == 'set':
                    batch.set(doc_ref, op.get('data', {}))
                elif op['type'] == 'update':
                    batch.update(doc_ref, op.get('data', {}))
                elif op['type'] == 'delete':
                    batch.delete(doc_ref)
            
            batch.commit()
            logger.debug(f"批量写入成功: {len(operations)} 个操作")
            return True
            
        except Exception as e:
            logger.error(f"批量写入失败: {e}")
            return False
    
    # ==================== 用户相关操作 ====================
    
    def get_user_collection_path(self, user_id: Optional[str] = None) -> str:
        """
        获取用户的项目集合路径
        
        Args:
            user_id: 用户 ID，如果为 None 则使用当前用户
            
        Returns:
            集合路径
        """
        uid = user_id or self.current_user_id
        if not uid:
            raise ValueError("未指定用户 ID")
        return f"users/{uid}/projects"
    
    def ensure_user_exists(self, user_id: str, user_info: Optional[Dict[str, Any]] = None) -> bool:
        """
        确保用户文档存在
        
        Args:
            user_id: 用户 ID
            user_info: 用户信息
            
        Returns:
            是否成功
        """
        try:
            user_doc = self.get_document("users", user_id)
            
            if not user_doc:
                # 创建用户文档
                default_info = {
                    'created_at': datetime.now(timezone.utc).isoformat(),
                    'updated_at': datetime.now(timezone.utc).isoformat(),
                    'projects_count': 0,
                    'storage_used': 0,
                }
                if user_info:
                    default_info.update(user_info)
                
                self.set_document("users", user_id, default_info)
                logger.info(f"创建新用户文档: {user_id}")
            
            return True
            
        except Exception as e:
            logger.error(f"确保用户存在失败: {e}")
            return False
    
    def get_user_stats(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        """
        获取用户统计信息
        
        Args:
            user_id: 用户 ID
            
        Returns:
            统计信息字典
        """
        uid = user_id or self.current_user_id
        if not uid:
            return {}
        
        try:
            user_doc = self.get_document("users", uid)
            return user_doc or {}
        except Exception as e:
            logger.error(f"获取用户统计失败: {e}")
            return {}
    
    def update_user_stats(self, user_id: str, stats: Dict[str, Any]) -> bool:
        """更新用户统计信息"""
        try:
            stats['updated_at'] = datetime.now(timezone.utc).isoformat()
            return self.update_document("users", user_id, stats)
        except Exception as e:
            logger.error(f"更新用户统计失败: {e}")
            return False
    
    # ==================== 健康检查 ====================
    
    def health_check(self) -> Dict[str, Any]:
        """
        检查 Firebase 连接状态
        
        Returns:
            健康状态信息
        """
        status = {
            'firebase_available': FIREBASE_AVAILABLE,
            'connected': self.is_connected,
            'current_user': self.current_user_id,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
        
        if self.is_connected:
            try:
                # 尝试读取一个文档来验证连接
                self.db.collection('_health_check').document('ping').get()
                status['firestore_ok'] = True
            except Exception as e:
                status['firestore_ok'] = False
                status['error'] = str(e)
        
        return status


# 全局单例
_firebase_manager: Optional[FirebaseManager] = None


def get_firebase_manager() -> FirebaseManager:
    """获取 Firebase 管理器单例"""
    global _firebase_manager
    if _firebase_manager is None:
        _firebase_manager = FirebaseManager()
    return _firebase_manager


def initialize_firebase(config: Dict[str, Any]) -> bool:
    """
    初始化 Firebase（便捷函数）
    
    Args:
        config: 配置字典
        
    Returns:
        是否成功
    """
    manager = get_firebase_manager()
    return manager.initialize(config)
