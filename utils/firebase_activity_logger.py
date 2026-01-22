"""
Firebase 用户活动日志管理器
记录用户操作日志到 Firebase Firestore
"""

from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
from loguru import logger

from .firebase_manager import get_firebase_manager, FIREBASE_AVAILABLE


class ActivityType:
    """活动类型常量"""
    # 项目生命周期
    PROJECT_CREATE = "project_create"
    PROJECT_LOAD = "project_load"
    PROJECT_DELETE = "project_delete"
    PROJECT_SHARE = "project_share"
    
    # 处理阶段
    SEGMENTATION_START = "segmentation_start"
    SEGMENTATION_COMPLETE = "segmentation_complete"
    TRANSLATION_START = "translation_start"
    TRANSLATION_COMPLETE = "translation_complete"
    AUDIO_GENERATION_START = "audio_generation_start"
    AUDIO_GENERATION_COMPLETE = "audio_generation_complete"
    
    # 用户操作
    SEGMENT_CONFIRM = "segment_confirm"
    SEGMENT_REGENERATE = "segment_regenerate"
    TEXT_OPTIMIZE = "text_optimize"
    COMPLETION = "completion"
    
    # 系统事件
    LOGIN = "login"
    LOGOUT = "logout"
    ERROR = "error"


class FirebaseActivityLogger:
    """Firebase 用户活动日志管理器"""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if hasattr(self, '_initialized') and self._initialized:
            return
        
        self._initialized = True
        self._batch_logs: List[Dict[str, Any]] = []
        self._batch_size = 10  # 累积多少条日志后批量写入
    
    @property
    def firebase(self):
        """获取 Firebase 管理器"""
        return get_firebase_manager()
    
    @property
    def is_available(self) -> bool:
        """检查日志功能是否可用"""
        return FIREBASE_AVAILABLE and self.firebase.is_connected
    
    def log_activity(
        self,
        user_id: str,
        activity_type: str,
        project_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        记录用户活动
        
        Args:
            user_id: 用户 ID
            activity_type: 活动类型（使用 ActivityType 常量）
            project_id: 项目 ID（可选）
            details: 活动详情（可选）
            metadata: 额外元数据（可选）
            
        Returns:
            是否记录成功
        """
        if not self.is_available:
            logger.debug(f"Firebase 不可用，跳过活动日志: {activity_type}")
            return False
        
        if not user_id:
            logger.warning("缺少用户 ID，无法记录活动日志")
            return False
        
        try:
            log_entry = {
                'user_id': user_id,
                'activity_type': activity_type,
                'project_id': project_id or '',
                'details': details or {},
                'metadata': metadata or {},
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'created_at': datetime.now(timezone.utc).isoformat()
            }
            
            # 生成日志 ID
            log_id = f"{activity_type}_{int(datetime.now().timestamp() * 1000)}"
            
            # 写入用户活动日志集合
            collection_path = f"users/{user_id}/activity_logs"
            
            success = self.firebase.set_document(collection_path, log_id, log_entry)
            
            if success:
                logger.debug(f"活动日志已记录: {activity_type} (用户: {user_id})")
            else:
                logger.warning(f"活动日志记录失败: {activity_type}")
            
            return success
            
        except Exception as e:
            logger.error(f"记录活动日志异常: {e}")
            return False
    
    def log_project_create(self, user_id: str, project_id: str, project_name: str, filename: str = "") -> bool:
        """记录项目创建"""
        return self.log_activity(
            user_id=user_id,
            activity_type=ActivityType.PROJECT_CREATE,
            project_id=project_id,
            details={
                'project_name': project_name,
                'filename': filename
            }
        )
    
    def log_project_load(self, user_id: str, project_id: str, project_name: str) -> bool:
        """记录项目加载"""
        return self.log_activity(
            user_id=user_id,
            activity_type=ActivityType.PROJECT_LOAD,
            project_id=project_id,
            details={'project_name': project_name}
        )
    
    def log_project_delete(self, user_id: str, project_id: str, project_name: str) -> bool:
        """记录项目删除"""
        return self.log_activity(
            user_id=user_id,
            activity_type=ActivityType.PROJECT_DELETE,
            project_id=project_id,
            details={'project_name': project_name}
        )
    
    def log_stage_complete(
        self, 
        user_id: str, 
        project_id: str, 
        stage: str, 
        segment_count: int = 0,
        duration_seconds: float = 0
    ) -> bool:
        """记录处理阶段完成"""
        activity_type = f"{stage}_complete"
        return self.log_activity(
            user_id=user_id,
            activity_type=activity_type,
            project_id=project_id,
            details={
                'stage': stage,
                'segment_count': segment_count,
                'duration_seconds': duration_seconds
            }
        )
    
    def log_completion(
        self, 
        user_id: str, 
        project_id: str, 
        segment_count: int,
        tts_service: str,
        target_language: str,
        audio_uploaded: bool = False,
        subtitle_uploaded: bool = False
    ) -> bool:
        """记录项目完成"""
        return self.log_activity(
            user_id=user_id,
            activity_type=ActivityType.COMPLETION,
            project_id=project_id,
            details={
                'segment_count': segment_count,
                'tts_service': tts_service,
                'target_language': target_language,
                'audio_uploaded': audio_uploaded,
                'subtitle_uploaded': subtitle_uploaded
            }
        )
    
    def log_error(
        self, 
        user_id: str, 
        error_type: str, 
        error_message: str,
        project_id: Optional[str] = None,
        stack_trace: Optional[str] = None
    ) -> bool:
        """记录错误"""
        return self.log_activity(
            user_id=user_id,
            activity_type=ActivityType.ERROR,
            project_id=project_id,
            details={
                'error_type': error_type,
                'error_message': error_message,
                'stack_trace': stack_trace or ''
            }
        )
    
    def log_login(self, user_id: str, login_method: str = "password") -> bool:
        """记录用户登录"""
        return self.log_activity(
            user_id=user_id,
            activity_type=ActivityType.LOGIN,
            details={'login_method': login_method}
        )
    
    def log_logout(self, user_id: str) -> bool:
        """记录用户登出"""
        return self.log_activity(
            user_id=user_id,
            activity_type=ActivityType.LOGOUT
        )
    
    def get_user_activities(
        self, 
        user_id: str, 
        activity_type: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        获取用户活动日志
        
        Args:
            user_id: 用户 ID
            activity_type: 活动类型过滤（可选）
            limit: 返回数量限制
            
        Returns:
            活动日志列表
        """
        if not self.is_available:
            return []
        
        try:
            collection_path = f"users/{user_id}/activity_logs"
            
            filters = None
            if activity_type:
                filters = [('activity_type', '==', activity_type)]
            
            logs = self.firebase.query_documents(
                collection_path,
                filters=filters,
                order_by='timestamp',
                order_direction='DESCENDING',
                limit=limit
            )
            
            return logs
            
        except Exception as e:
            logger.error(f"获取用户活动日志失败: {e}")
            return []
    
    def get_project_activities(
        self, 
        user_id: str, 
        project_id: str,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        获取项目相关的活动日志
        
        Args:
            user_id: 用户 ID
            project_id: 项目 ID
            limit: 返回数量限制
            
        Returns:
            活动日志列表
        """
        if not self.is_available:
            return []
        
        try:
            collection_path = f"users/{user_id}/activity_logs"
            
            logs = self.firebase.query_documents(
                collection_path,
                filters=[('project_id', '==', project_id)],
                order_by='timestamp',
                order_direction='DESCENDING',
                limit=limit
            )
            
            return logs
            
        except Exception as e:
            logger.error(f"获取项目活动日志失败: {e}")
            return []
    
    def cleanup_old_logs(self, user_id: str, days_to_keep: int = 30) -> int:
        """
        清理旧日志（保留最近 N 天的日志）
        
        Args:
            user_id: 用户 ID
            days_to_keep: 保留天数
            
        Returns:
            删除的日志数量
        """
        if not self.is_available:
            return 0
        
        try:
            from datetime import timedelta
            
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_to_keep)
            cutoff_str = cutoff_date.isoformat()
            
            collection_path = f"users/{user_id}/activity_logs"
            
            # 查询旧日志
            old_logs = self.firebase.query_documents(
                collection_path,
                filters=[('timestamp', '<', cutoff_str)],
                limit=500  # 每次最多删除 500 条
            )
            
            deleted_count = 0
            for log in old_logs:
                log_id = log.get('_id')
                if log_id:
                    if self.firebase.delete_document(collection_path, log_id):
                        deleted_count += 1
            
            if deleted_count > 0:
                logger.info(f"清理了 {deleted_count} 条旧活动日志 (用户: {user_id})")
            
            return deleted_count
            
        except Exception as e:
            logger.error(f"清理旧日志失败: {e}")
            return 0


# 全局单例
_activity_logger: Optional[FirebaseActivityLogger] = None


def get_activity_logger() -> FirebaseActivityLogger:
    """获取活动日志管理器单例"""
    global _activity_logger
    if _activity_logger is None:
        _activity_logger = FirebaseActivityLogger()
    return _activity_logger
