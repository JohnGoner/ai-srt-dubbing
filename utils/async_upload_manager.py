"""
异步上传管理器
管理 Firebase Storage 的异步上传操作，避免阻塞主线程
"""

import threading
import queue
from concurrent.futures import ThreadPoolExecutor, Future
from typing import Dict, Any, Optional, List, Callable, Union
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from loguru import logger


class UploadTaskStatus(Enum):
    """上传任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class UploadTask:
    """上传任务"""
    task_id: str
    task_type: str  # 'preview', 'confirmed', 'final_audio', 'final_subtitle'
    user_id: str
    project_id: str
    segment_id: Optional[str] = None
    audio_data: Any = None
    filename: Optional[str] = None
    status: UploadTaskStatus = UploadTaskStatus.PENDING
    result_path: Optional[str] = None
    error: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: Optional[str] = None
    callback: Optional[Callable] = None


class AsyncUploadManager:
    """
    异步上传管理器
    
    使用线程池执行上传任务，不阻塞主线程
    """
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, max_workers: int = 4):
        if hasattr(self, '_initialized') and self._initialized:
            return
        
        self._initialized = True
        self._max_workers = max_workers
        self._executor: Optional[ThreadPoolExecutor] = None
        self._tasks: Dict[str, UploadTask] = {}
        self._futures: Dict[str, Future] = {}
        self._lock = threading.Lock()
        self._task_counter = 0
        
        # 启动线程池
        self._start_executor()
    
    def _start_executor(self):
        """启动线程池"""
        if self._executor is None:
            self._executor = ThreadPoolExecutor(
                max_workers=self._max_workers,
                thread_name_prefix="upload_worker"
            )
            logger.debug(f"异步上传管理器启动，最大工作线程数: {self._max_workers}")
    
    def _generate_task_id(self) -> str:
        """生成任务 ID"""
        with self._lock:
            self._task_counter += 1
            return f"upload_{self._task_counter}_{int(datetime.now().timestamp() * 1000)}"
    
    def submit_preview_upload(
        self,
        user_id: str,
        project_id: str,
        segment_id: str,
        audio_data: Any,
        callback: Optional[Callable[[str, Optional[str], Optional[str]], None]] = None
    ) -> str:
        """
        提交 Stage 1 预览音频上传任务
        
        Args:
            user_id: 用户 ID
            project_id: 项目 ID
            segment_id: 片段 ID
            audio_data: 音频数据
            callback: 完成回调函数 (task_id, result_path, error)
            
        Returns:
            任务 ID
        """
        task_id = self._generate_task_id()
        task = UploadTask(
            task_id=task_id,
            task_type='preview',
            user_id=user_id,
            project_id=project_id,
            segment_id=segment_id,
            audio_data=audio_data,
            callback=callback
        )
        
        return self._submit_task(task, self._execute_preview_upload)
    
    def submit_confirmed_upload(
        self,
        user_id: str,
        project_id: str,
        segment_id: str,
        audio_data: Any,
        callback: Optional[Callable[[str, Optional[str], Optional[str]], None]] = None
    ) -> str:
        """
        提交 Stage 2 确认音频上传任务（上传确认版本并删除预览版本）
        
        Args:
            user_id: 用户 ID
            project_id: 项目 ID
            segment_id: 片段 ID
            audio_data: 音频数据
            callback: 完成回调函数 (task_id, result_path, error)
            
        Returns:
            任务 ID
        """
        task_id = self._generate_task_id()
        task = UploadTask(
            task_id=task_id,
            task_type='confirmed',
            user_id=user_id,
            project_id=project_id,
            segment_id=segment_id,
            audio_data=audio_data,
            callback=callback
        )
        
        return self._submit_task(task, self._execute_confirmed_upload)
    
    def submit_final_audio_upload(
        self,
        user_id: str,
        project_id: str,
        filename: str,
        audio_data: bytes,
        callback: Optional[Callable[[str, Optional[str], Optional[str]], None]] = None
    ) -> str:
        """
        提交最终音频上传任务
        
        Args:
            user_id: 用户 ID
            project_id: 项目 ID
            filename: 文件名
            audio_data: 音频数据（bytes）
            callback: 完成回调函数
            
        Returns:
            任务 ID
        """
        task_id = self._generate_task_id()
        task = UploadTask(
            task_id=task_id,
            task_type='final_audio',
            user_id=user_id,
            project_id=project_id,
            filename=filename,
            audio_data=audio_data,
            callback=callback
        )
        
        return self._submit_task(task, self._execute_final_audio_upload)
    
    def submit_final_subtitle_upload(
        self,
        user_id: str,
        project_id: str,
        filename: str,
        subtitle_data: bytes,
        callback: Optional[Callable[[str, Optional[str], Optional[str]], None]] = None
    ) -> str:
        """
        提交最终字幕上传任务
        
        Args:
            user_id: 用户 ID
            project_id: 项目 ID
            filename: 文件名
            subtitle_data: 字幕数据（bytes）
            callback: 完成回调函数
            
        Returns:
            任务 ID
        """
        task_id = self._generate_task_id()
        task = UploadTask(
            task_id=task_id,
            task_type='final_subtitle',
            user_id=user_id,
            project_id=project_id,
            filename=filename,
            audio_data=subtitle_data,  # 复用字段存储字幕数据
            callback=callback
        )
        
        return self._submit_task(task, self._execute_final_subtitle_upload)
    
    def submit_batch_preview_upload(
        self,
        user_id: str,
        project_id: str,
        segments: List[Dict[str, Any]],
        callback: Optional[Callable[[int, int], None]] = None
    ) -> List[str]:
        """
        批量提交 Stage 1 预览音频上传任务
        
        Args:
            user_id: 用户 ID
            project_id: 项目 ID
            segments: 片段列表 [{'id': str, 'audio_data': Any}, ...]
            callback: 进度回调函数 (completed, total)
            
        Returns:
            任务 ID 列表
        """
        task_ids = []
        total = len(segments)
        completed = [0]  # 使用列表以便在闭包中修改
        
        def progress_callback(task_id, result_path, error):
            completed[0] += 1
            if callback:
                callback(completed[0], total)
        
        for seg in segments:
            if seg.get('audio_data') is None:
                continue
            
            task_id = self.submit_preview_upload(
                user_id=user_id,
                project_id=project_id,
                segment_id=seg['id'],
                audio_data=seg['audio_data'],
                callback=progress_callback
            )
            task_ids.append(task_id)
        
        return task_ids
    
    def _submit_task(self, task: UploadTask, executor_func: Callable) -> str:
        """提交任务到线程池"""
        with self._lock:
            self._tasks[task.task_id] = task
        
        future = self._executor.submit(executor_func, task)
        
        with self._lock:
            self._futures[task.task_id] = future
        
        # 添加完成回调
        future.add_done_callback(lambda f: self._on_task_complete(task.task_id, f))
        
        logger.debug(f"上传任务已提交: {task.task_id} (type={task.task_type})")
        return task.task_id
    
    def _on_task_complete(self, task_id: str, future: Future):
        """任务完成回调"""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
        
        try:
            result_path = future.result()
            task.status = UploadTaskStatus.COMPLETED
            task.result_path = result_path
            task.completed_at = datetime.now(timezone.utc).isoformat()
            logger.debug(f"上传任务完成: {task_id} -> {result_path}")
            
        except Exception as e:
            task.status = UploadTaskStatus.FAILED
            task.error = str(e)
            task.completed_at = datetime.now(timezone.utc).isoformat()
            logger.error(f"上传任务失败: {task_id} - {e}")
        
        # 执行用户回调
        if task.callback:
            try:
                task.callback(task_id, task.result_path, task.error)
            except Exception as e:
                logger.warning(f"上传回调执行失败: {e}")
    
    def _execute_preview_upload(self, task: UploadTask) -> Optional[str]:
        """执行 Stage 1 预览音频上传"""
        task.status = UploadTaskStatus.RUNNING
        
        from .firebase_storage import get_storage_manager
        
        storage = get_storage_manager()
        if not storage.is_connected:
            raise RuntimeError("Firebase Storage 未连接")
        
        return storage.upload_staged_audio(
            user_id=task.user_id,
            project_id=task.project_id,
            segment_id=task.segment_id,
            stage='preview',
            audio_data=task.audio_data
        )
    
    def _execute_confirmed_upload(self, task: UploadTask) -> Optional[str]:
        """执行 Stage 2 确认音频上传（并删除预览版本）"""
        task.status = UploadTaskStatus.RUNNING
        
        from .firebase_storage import get_storage_manager
        
        storage = get_storage_manager()
        if not storage.is_connected:
            raise RuntimeError("Firebase Storage 未连接")
        
        return storage.promote_audio_stage(
            user_id=task.user_id,
            project_id=task.project_id,
            segment_id=task.segment_id,
            audio_data=task.audio_data
        )
    
    def _execute_final_audio_upload(self, task: UploadTask) -> Optional[str]:
        """执行最终音频上传"""
        task.status = UploadTaskStatus.RUNNING
        
        from .firebase_storage import get_storage_manager
        
        storage = get_storage_manager()
        if not storage.is_connected:
            raise RuntimeError("Firebase Storage 未连接")
        
        return storage.upload_final_audio(
            user_id=task.user_id,
            project_id=task.project_id,
            filename=task.filename,
            audio_data=task.audio_data
        )
    
    def _execute_final_subtitle_upload(self, task: UploadTask) -> Optional[str]:
        """执行最终字幕上传"""
        task.status = UploadTaskStatus.RUNNING
        
        from .firebase_storage import get_storage_manager
        
        storage = get_storage_manager()
        if not storage.is_connected:
            raise RuntimeError("Firebase Storage 未连接")
        
        return storage.upload_final_subtitle(
            user_id=task.user_id,
            project_id=task.project_id,
            filename=task.filename,
            subtitle_data=task.audio_data  # 复用字段
        )
    
    def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """获取任务状态"""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None
            
            return {
                'task_id': task.task_id,
                'task_type': task.task_type,
                'status': task.status.value,
                'result_path': task.result_path,
                'error': task.error,
                'created_at': task.created_at,
                'completed_at': task.completed_at
            }
    
    def get_pending_count(self) -> int:
        """获取待处理任务数量"""
        with self._lock:
            return sum(1 for t in self._tasks.values() 
                      if t.status in [UploadTaskStatus.PENDING, UploadTaskStatus.RUNNING])
    
    def get_stats(self) -> Dict[str, Any]:
        """获取上传统计"""
        with self._lock:
            total = len(self._tasks)
            pending = sum(1 for t in self._tasks.values() if t.status == UploadTaskStatus.PENDING)
            running = sum(1 for t in self._tasks.values() if t.status == UploadTaskStatus.RUNNING)
            completed = sum(1 for t in self._tasks.values() if t.status == UploadTaskStatus.COMPLETED)
            failed = sum(1 for t in self._tasks.values() if t.status == UploadTaskStatus.FAILED)
            
            return {
                'total_tasks': total,
                'pending': pending,
                'running': running,
                'completed': completed,
                'failed': failed,
                'max_workers': self._max_workers
            }
    
    def wait_for_task(self, task_id: str, timeout: Optional[float] = None) -> Optional[str]:
        """
        等待指定任务完成
        
        Args:
            task_id: 任务 ID
            timeout: 超时时间（秒）
            
        Returns:
            上传结果路径，失败返回 None
        """
        with self._lock:
            future = self._futures.get(task_id)
            if not future:
                return None
        
        try:
            return future.result(timeout=timeout)
        except Exception as e:
            logger.error(f"等待任务失败: {task_id} - {e}")
            return None
    
    def wait_all(self, timeout: Optional[float] = None):
        """
        等待所有任务完成
        
        Args:
            timeout: 超时时间（秒）
        """
        with self._lock:
            futures = list(self._futures.values())
        
        for future in futures:
            try:
                future.result(timeout=timeout)
            except Exception:
                pass  # 错误已在回调中处理
    
    def shutdown(self, wait: bool = True):
        """
        关闭上传管理器
        
        Args:
            wait: 是否等待所有任务完成
        """
        if self._executor:
            self._executor.shutdown(wait=wait)
            self._executor = None
            logger.info("异步上传管理器已关闭")
    
    def cleanup_completed_tasks(self, max_age_seconds: int = 3600):
        """
        清理已完成的任务记录
        
        Args:
            max_age_seconds: 保留的最大时间（秒）
        """
        from datetime import timedelta
        
        cutoff_time = datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds)
        
        with self._lock:
            to_remove = []
            for task_id, task in self._tasks.items():
                if task.status in [UploadTaskStatus.COMPLETED, UploadTaskStatus.FAILED]:
                    if task.completed_at:
                        completed_time = datetime.fromisoformat(task.completed_at.replace('Z', '+00:00'))
                        if completed_time < cutoff_time:
                            to_remove.append(task_id)
            
            for task_id in to_remove:
                del self._tasks[task_id]
                if task_id in self._futures:
                    del self._futures[task_id]
            
            if to_remove:
                logger.debug(f"清理了 {len(to_remove)} 个已完成的上传任务")


# 全局单例
_upload_manager: Optional[AsyncUploadManager] = None


def get_upload_manager() -> AsyncUploadManager:
    """获取异步上传管理器单例"""
    global _upload_manager
    if _upload_manager is None:
        _upload_manager = AsyncUploadManager()
    return _upload_manager
