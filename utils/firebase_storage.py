"""
Firebase Storage 管理器模块
负责音频文件的上传、下载和管理
"""

import os
import io
import tempfile
from pathlib import Path
from typing import Dict, Any, Optional, List, Union, BinaryIO
from datetime import datetime, timezone
from loguru import logger

# Firebase Storage SDK
try:
    from firebase_admin import storage
    from google.cloud.storage import Blob
    STORAGE_AVAILABLE = True
except ImportError:
    STORAGE_AVAILABLE = False
    logger.warning("Firebase Storage SDK 未安装")

from .firebase_manager import get_firebase_manager, FIREBASE_AVAILABLE


class FirebaseStorageManager:
    """Firebase Storage 管理器"""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        self.bucket = None
        self.is_connected = False
        self.config = {}
        
    def initialize(self, config: Dict[str, Any], force_reinit: bool = False) -> bool:
        """
        初始化 Firebase Storage
        
        Args:
            config: 配置字典
            force_reinit: 是否强制重新初始化
            
        Returns:
            是否初始化成功
        """
        if not STORAGE_AVAILABLE or not FIREBASE_AVAILABLE:
            logger.error("Firebase Storage SDK 未安装或 Firebase 未初始化")
            return False
        
        # 检查是否需要强制重新初始化
        firebase_config = config.get('firebase', {})
        expected_bucket = firebase_config.get('storage_bucket', '')
        current_bucket = getattr(self, 'bucket_name', None)
        
        if self.is_connected and not force_reinit:
            # 检查 bucket 名称是否与配置一致
            if expected_bucket and current_bucket and expected_bucket != current_bucket:
                logger.warning(f"Bucket 配置已变更: {current_bucket} -> {expected_bucket}，强制重新初始化")
                force_reinit = True
            else:
                return True
        
        if self.is_connected and not force_reinit:
            return True
        
        # 重置状态
        self.bucket = None
        self.is_connected = False
        
        try:
            # 确保 Firebase 已初始化
            firebase_manager = get_firebase_manager()
            if not firebase_manager.is_connected:
                logger.error("Firebase 未连接，请先初始化 Firebase")
                return False
            
            self.config = config
            firebase_config = config.get('firebase', {})
            
            # 调试：打印完整的 firebase 配置
            logger.debug(f"Firebase 配置内容: {firebase_config}")
            
            # 获取存储桶名称
            bucket_name = firebase_config.get('storage_bucket', '')
            logger.info(f"从配置读取 storage_bucket: '{bucket_name}'")
            
            # 从环境变量获取
            if not bucket_name:
                bucket_name = os.environ.get('FIREBASE_STORAGE_BUCKET', '')
            
            if not bucket_name:
                logger.error("未配置 Firebase Storage Bucket，请设置 firebase.storage_bucket")
                return False
            
            logger.info(f"正在连接 Storage Bucket: {bucket_name}")
            
            # 初始化存储桶 - 必须显式传入 bucket 名称
            # 注意：storage.bucket() 不带参数会使用默认 bucket（可能是 .appspot.com 格式）
            # 所以这里必须传入配置的 bucket 名称
            self.bucket = storage.bucket(bucket_name)
            self.bucket_name = bucket_name  # 保存 bucket 名称以便调试
            self.is_connected = True
            
            logger.info(f"Firebase Storage 连接成功: {bucket_name}, bucket.name={self.bucket.name}")
            return True
            
        except Exception as e:
            logger.error(f"Firebase Storage 初始化失败: {e}")
            self.is_connected = False
            return False
    
    def _get_user_audio_path(self, user_id: str, project_id: str, filename: str) -> str:
        """
        生成用户音频文件的存储路径
        
        格式: users/{user_id}/projects/{project_id}/audio/{filename}
        """
        return f"users/{user_id}/projects/{project_id}/audio/{filename}"
    
    def _get_staged_audio_path(self, user_id: str, project_id: str, segment_id: str, stage: str) -> str:
        """
        生成分阶段音频文件的存储路径
        
        格式: users/{user_id}/projects/{project_id}/audio/{stage}/{segment_id}.mp3
        
        Args:
            user_id: 用户 ID
            project_id: 项目 ID
            segment_id: 片段 ID
            stage: 阶段 ('preview' for Stage 1, 'confirmed' for Stage 2)
        """
        return f"users/{user_id}/projects/{project_id}/audio/{stage}/{segment_id}.mp3"
    
    def upload_staged_audio(
        self,
        user_id: str,
        project_id: str,
        segment_id: str,
        stage: str,
        audio_data: Union[bytes, BinaryIO, 'AudioSegment'],
        content_type: str = 'audio/mpeg',
        max_retries: int = 3
    ) -> Optional[str]:
        """
        上传分阶段音频到 Firebase Storage（带重试机制）
        
        Args:
            user_id: 用户 ID
            project_id: 项目 ID
            segment_id: 片段 ID
            stage: 阶段 ('preview' for Stage 1, 'confirmed' for Stage 2)
            audio_data: 音频数据
            content_type: MIME 类型
            max_retries: 最大重试次数
            
        Returns:
            文件的存储路径，失败返回 None
        """
        if not self.is_connected:
            logger.error("Firebase Storage 未连接")
            return None
        
        import time
        
        try:
            # 处理不同类型的音频数据
            if hasattr(audio_data, 'export'):
                buffer = io.BytesIO()
                audio_data.export(buffer, format='mp3', bitrate='128k')
                buffer.seek(0)
                data = buffer.read()
            elif isinstance(audio_data, bytes):
                data = audio_data
            elif hasattr(audio_data, 'read'):
                data = audio_data.read()
            else:
                raise ValueError(f"不支持的音频数据类型: {type(audio_data)}")
            
            storage_path = self._get_staged_audio_path(user_id, project_id, segment_id, stage)
            blob = self.bucket.blob(storage_path)
            
            # 🔥 带重试的上传逻辑
            last_error = None
            for attempt in range(max_retries):
                try:
                    blob.upload_from_string(data, content_type=content_type)
                    logger.debug(f"分阶段音频上传成功: {storage_path} (stage={stage}, {len(data)} bytes)")
                    return storage_path
                except Exception as upload_error:
                    last_error = upload_error
                    error_str = str(upload_error).lower()
                    
                    # 检查是否是代理/网络错误
                    is_network_error = any(keyword in error_str for keyword in [
                        'proxy', 'connection', 'timeout', 'remotedisconnected', 
                        'connectionreset', 'max retries'
                    ])
                    
                    if is_network_error and attempt < max_retries - 1:
                        wait_time = (attempt + 1) * 2  # 递增等待: 2s, 4s, 6s
                        logger.warning(f"上传失败(网络问题)，{wait_time}秒后重试 ({attempt + 1}/{max_retries}): {upload_error}")
                        time.sleep(wait_time)
                    else:
                        raise
            
            # 所有重试都失败
            raise last_error
            
        except Exception as e:
            error_str = str(e).lower()
            is_proxy_error = 'proxy' in error_str or 'remotedisconnected' in error_str
            
            if is_proxy_error:
                # 代理错误：只记录警告，不阻塞用户操作
                logger.warning(f"上传分阶段音频失败(代理问题，可忽略): {e}")
            else:
                logger.error(f"上传分阶段音频失败: {e}")
            return None
    
    def delete_staged_audio(
        self,
        user_id: str,
        project_id: str,
        segment_id: str,
        stage: str
    ) -> bool:
        """
        删除分阶段音频
        
        Args:
            user_id: 用户 ID
            project_id: 项目 ID
            segment_id: 片段 ID
            stage: 阶段 ('preview' for Stage 1, 'confirmed' for Stage 2)
            
        Returns:
            是否成功
        """
        if not self.is_connected:
            logger.error("Firebase Storage 未连接")
            return False
        
        try:
            storage_path = self._get_staged_audio_path(user_id, project_id, segment_id, stage)
            blob = self.bucket.blob(storage_path)
            
            if blob.exists():
                blob.delete()
                logger.debug(f"分阶段音频删除成功: {storage_path}")
                return True
            else:
                logger.debug(f"分阶段音频不存在，跳过删除: {storage_path}")
                return True
                
        except Exception as e:
            logger.error(f"删除分阶段音频失败: {e}")
            return False
    
    def promote_audio_stage(
        self,
        user_id: str,
        project_id: str,
        segment_id: str,
        audio_data: Union[bytes, BinaryIO, 'AudioSegment']
    ) -> Optional[str]:
        """
        将音频从 Stage 1 升级到 Stage 2（上传确认版本并删除预览版本）
        
        Args:
            user_id: 用户 ID
            project_id: 项目 ID
            segment_id: 片段 ID
            audio_data: 确认版本的音频数据
            
        Returns:
            新的存储路径，失败返回 None
        """
        # 1. 上传 Stage 2 (confirmed)
        confirmed_path = self.upload_staged_audio(
            user_id, project_id, segment_id, 'confirmed', audio_data
        )
        
        if confirmed_path:
            # 2. 删除 Stage 1 (preview)
            self.delete_staged_audio(user_id, project_id, segment_id, 'preview')
            logger.info(f"片段 {segment_id} 音频已升级到确认阶段")
        
        return confirmed_path
    
    def upload_audio(
        self, 
        user_id: str, 
        project_id: str, 
        filename: str,
        audio_data: Union[bytes, BinaryIO, 'AudioSegment'],
        content_type: str = 'audio/mpeg',
        metadata: Optional[Dict[str, str]] = None
    ) -> Optional[str]:
        """
        上传音频文件到 Firebase Storage
        
        Args:
            user_id: 用户 ID
            project_id: 项目 ID
            filename: 文件名
            audio_data: 音频数据（bytes、文件对象或 AudioSegment）
            content_type: MIME 类型
            metadata: 自定义元数据
            
        Returns:
            文件的存储路径，失败返回 None
        """
        if not self.is_connected:
            logger.error("Firebase Storage 未连接")
            return None
        
        try:
            # 处理不同类型的音频数据
            if hasattr(audio_data, 'export'):
                # AudioSegment 对象
                buffer = io.BytesIO()
                format_type = 'mp3' if content_type == 'audio/mpeg' else 'wav'
                
                # 使用 MP3 格式压缩存储
                if format_type == 'mp3':
                    audio_data.export(buffer, format='mp3', bitrate='128k')
                else:
                    audio_data.export(buffer, format='wav')
                
                buffer.seek(0)
                data = buffer.read()
            elif isinstance(audio_data, bytes):
                data = audio_data
            elif hasattr(audio_data, 'read'):
                data = audio_data.read()
            else:
                raise ValueError(f"不支持的音频数据类型: {type(audio_data)}")
            
            # 生成存储路径
            storage_path = self._get_user_audio_path(user_id, project_id, filename)
            
            # 创建 Blob 并上传
            blob = self.bucket.blob(storage_path)
            
            # 设置元数据
            if metadata:
                blob.metadata = metadata
            
            # 上传
            blob.upload_from_string(data, content_type=content_type)
            
            logger.debug(f"音频上传成功: {storage_path} ({len(data)} bytes)")
            return storage_path
            
        except Exception as e:
            logger.error(f"上传音频失败: {e}")
            return None
    
    def download_audio(
        self, 
        storage_path: str
    ) -> Optional[bytes]:
        """
        从 Firebase Storage 下载音频文件
        
        Args:
            storage_path: 存储路径
            
        Returns:
            音频数据（bytes），失败返回 None
        """
        if not self.is_connected:
            logger.error("Firebase Storage 未连接")
            return None
        
        try:
            blob = self.bucket.blob(storage_path)
            
            if not blob.exists():
                logger.warning(f"音频文件不存在: {storage_path}")
                return None
            
            data = blob.download_as_bytes()
            logger.debug(f"音频下载成功: {storage_path} ({len(data)} bytes)")
            return data
            
        except Exception as e:
            logger.error(f"下载音频失败: {e}")
            return None
    
    def download_audio_to_file(
        self, 
        storage_path: str,
        local_path: Optional[str] = None
    ) -> Optional[str]:
        """
        下载音频到本地文件
        
        Args:
            storage_path: 存储路径
            local_path: 本地文件路径，如果为 None 则创建临时文件
            
        Returns:
            本地文件路径
        """
        data = self.download_audio(storage_path)
        if data is None:
            return None
        
        try:
            if local_path is None:
                # 创建临时文件
                suffix = Path(storage_path).suffix or '.mp3'
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
                    f.write(data)
                    local_path = f.name
            else:
                with open(local_path, 'wb') as f:
                    f.write(data)
            
            return local_path
            
        except Exception as e:
            logger.error(f"保存音频到本地失败: {e}")
            return None
    
    def delete_audio(self, storage_path: str) -> bool:
        """
        删除音频文件
        
        Args:
            storage_path: 存储路径
            
        Returns:
            是否成功
        """
        if not self.is_connected:
            logger.error("Firebase Storage 未连接")
            return False
        
        try:
            blob = self.bucket.blob(storage_path)
            blob.delete()
            logger.debug(f"音频删除成功: {storage_path}")
            return True
            
        except Exception as e:
            logger.error(f"删除音频失败: {e}")
            return False
    
    def delete_project_audio(self, user_id: str, project_id: str) -> int:
        """
        删除项目的所有音频文件
        
        Args:
            user_id: 用户 ID
            project_id: 项目 ID
            
        Returns:
            删除的文件数量
        """
        if not self.is_connected:
            return 0
        
        try:
            prefix = f"users/{user_id}/projects/{project_id}/audio/"
            blobs = self.bucket.list_blobs(prefix=prefix)
            
            count = 0
            for blob in blobs:
                blob.delete()
                count += 1
            
            logger.info(f"删除项目音频: {project_id}, 共 {count} 个文件")
            return count
            
        except Exception as e:
            logger.error(f"删除项目音频失败: {e}")
            return 0
    
    def list_project_audio(self, user_id: str, project_id: str) -> List[Dict[str, Any]]:
        """
        列出项目的所有音频文件
        
        Args:
            user_id: 用户 ID
            project_id: 项目 ID
            
        Returns:
            音频文件信息列表
        """
        if not self.is_connected:
            return []
        
        try:
            prefix = f"users/{user_id}/projects/{project_id}/audio/"
            blobs = self.bucket.list_blobs(prefix=prefix)
            
            files = []
            for blob in blobs:
                files.append({
                    'name': Path(blob.name).name,
                    'path': blob.name,
                    'size': blob.size,
                    'content_type': blob.content_type,
                    'created': blob.time_created.isoformat() if blob.time_created else None,
                    'updated': blob.updated.isoformat() if blob.updated else None,
                    'metadata': blob.metadata
                })
            
            return files
            
        except Exception as e:
            logger.error(f"列出项目音频失败: {e}")
            return []
    
    def check_file_exists(self, storage_path: str) -> bool:
        """检查 storage_path 是否存在于 bucket。"""
        if not self.is_connected:
            return False
        try:
            return self.bucket.blob(storage_path).exists()
        except Exception as e:
            logger.debug(f"check_file_exists 失败: {storage_path} -> {e}")
            return False

    def get_download_url(self, storage_path: str, expiration: int = 3600) -> Optional[str]:
        """
        获取音频文件的下载 URL
        
        Args:
            storage_path: 存储路径
            expiration: URL 有效期（秒），默认 1 小时
            
        Returns:
            签名的下载 URL
        """
        if not self.is_connected:
            logger.warning(f"get_download_url: Storage 未连接")
            return None
        
        try:
            from datetime import timedelta
            blob = self.bucket.blob(storage_path)
            
            if not blob.exists():
                logger.warning(f"get_download_url: 文件不存在 - {storage_path}")
                return None
            
            url = blob.generate_signed_url(
                version="v4",
                expiration=timedelta(seconds=expiration),
                method="GET"
            )
            
            logger.debug(f"get_download_url: 成功生成 URL - {storage_path}")
            return url
            
        except Exception as e:
            logger.error(f"生成下载 URL 失败 [{storage_path}]: {e}")
            return None
    
    def get_storage_usage(self, user_id: str) -> Dict[str, Any]:
        """
        获取用户的存储使用情况
        
        Args:
            user_id: 用户 ID
            
        Returns:
            存储使用统计
        """
        if not self.is_connected:
            return {'total_size': 0, 'file_count': 0}
        
        try:
            prefix = f"users/{user_id}/"
            blobs = self.bucket.list_blobs(prefix=prefix)
            
            total_size = 0
            file_count = 0
            
            for blob in blobs:
                total_size += blob.size or 0
                file_count += 1
            
            return {
                'total_size': total_size,
                'total_size_mb': total_size / (1024 * 1024),
                'file_count': file_count,
                'user_id': user_id
            }
            
        except Exception as e:
            logger.error(f"获取存储使用情况失败: {e}")
            return {'total_size': 0, 'file_count': 0, 'error': str(e)}
    
    def health_check(self) -> Dict[str, Any]:
        """检查 Storage 连接状态"""
        status = {
            'storage_available': STORAGE_AVAILABLE,
            'connected': self.is_connected,
            'bucket_name': self.bucket.name if self.bucket else None,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
        
        if self.is_connected:
            try:
                # 尝试列出一个前缀来验证连接
                list(self.bucket.list_blobs(prefix='_health_check/', max_results=1))
                status['storage_ok'] = True
            except Exception as e:
                status['storage_ok'] = False
                status['error'] = str(e)
        
        return status
    
    def _get_user_output_path(self, user_id: str, project_id: str, filename: str) -> str:
        """
        生成用户最终输出文件的存储路径
        
        格式: users/{user_id}/projects/{project_id}/output/{filename}
        """
        return f"users/{user_id}/projects/{project_id}/output/{filename}"
    
    def upload_final_audio(
        self, 
        user_id: str, 
        project_id: str, 
        filename: str,
        audio_data: bytes,
        content_type: str = 'audio/mpeg'
    ) -> Optional[str]:
        """
        上传最终音频文件到 Firebase Storage（带重试机制）
        
        Args:
            user_id: 用户 ID
            project_id: 项目 ID
            filename: 文件名（如 project_en.mp3）
            audio_data: 音频文件数据（bytes）
            content_type: MIME 类型
            
        Returns:
            文件的存储路径，失败返回 None
        """
        if not self.is_connected:
            logger.error("Firebase Storage 未连接")
            return None
        
        import time
        max_retries = 3
        
        try:
            storage_path = self._get_user_output_path(user_id, project_id, filename)
            blob = self.bucket.blob(storage_path)
            
            # 🔥 带重试的上传逻辑
            last_error = None
            for attempt in range(max_retries):
                try:
                    blob.upload_from_string(audio_data, content_type=content_type)
                    logger.info(f"最终音频上传成功: {storage_path} ({len(audio_data)} bytes)")
                    return storage_path
                except Exception as upload_error:
                    last_error = upload_error
                    error_str = str(upload_error).lower()
                    
                    # 检查是否是网络/SSL错误
                    is_network_error = any(keyword in error_str for keyword in [
                        'proxy', 'connection', 'timeout', 'remotedisconnected', 
                        'connectionreset', 'max retries', 'ssl', 'write'
                    ])
                    
                    if is_network_error and attempt < max_retries - 1:
                        wait_time = (attempt + 1) * 3  # 递增等待: 3s, 6s, 9s
                        logger.warning(f"最终音频上传失败(网络问题)，{wait_time}秒后重试 ({attempt + 1}/{max_retries}): {upload_error}")
                        time.sleep(wait_time)
                    else:
                        raise
            
            raise last_error
            
        except Exception as e:
            error_str = str(e).lower()
            is_network_error = any(k in error_str for k in ['proxy', 'ssl', 'connection', 'timeout'])
            
            if is_network_error:
                logger.warning(f"上传最终音频失败(网络问题，本地文件已保存): {e}")
            else:
                logger.error(f"上传最终音频失败: {e}")
            return None
    
    def upload_final_subtitle(
        self, 
        user_id: str, 
        project_id: str, 
        filename: str,
        subtitle_data: bytes,
        content_type: str = 'text/plain'
    ) -> Optional[str]:
        """
        上传最终字幕文件到 Firebase Storage（带重试机制）
        
        Args:
            user_id: 用户 ID
            project_id: 项目 ID
            filename: 文件名（如 project_en.srt）
            subtitle_data: 字幕文件数据（bytes）
            content_type: MIME 类型
            
        Returns:
            文件的存储路径，失败返回 None
        """
        if not self.is_connected:
            logger.error("Firebase Storage 未连接")
            return None
        
        import time
        max_retries = 3
        
        try:
            storage_path = self._get_user_output_path(user_id, project_id, filename)
            blob = self.bucket.blob(storage_path)
            
            # 带重试的上传逻辑
            last_error = None
            for attempt in range(max_retries):
                try:
                    blob.upload_from_string(subtitle_data, content_type=content_type)
                    logger.info(f"最终字幕上传成功: {storage_path} ({len(subtitle_data)} bytes)")
                    return storage_path
                except Exception as upload_error:
                    last_error = upload_error
                    error_str = str(upload_error).lower()
                    
                    is_network_error = any(keyword in error_str for keyword in [
                        'proxy', 'connection', 'timeout', 'ssl', 'write'
                    ])
                    
                    if is_network_error and attempt < max_retries - 1:
                        wait_time = (attempt + 1) * 2
                        logger.warning(f"字幕上传失败(网络问题)，{wait_time}秒后重试 ({attempt + 1}/{max_retries})")
                        time.sleep(wait_time)
                    else:
                        raise
            
            raise last_error
            
        except Exception as e:
            logger.warning(f"上传最终字幕失败(网络问题，可忽略): {e}")
            return None
    
    def upload_segment_audios_batch(
        self,
        user_id: str,
        project_id: str,
        segments: List[Dict[str, Any]],
        content_type: str = 'audio/mpeg'
    ) -> Dict[str, str]:
        """
        批量上传片段音频到 Firebase Storage
        
        Args:
            user_id: 用户 ID
            project_id: 项目 ID
            segments: 片段列表，每个片段需包含 'id' 和 'audio_data'
            content_type: MIME 类型
            
        Returns:
            segment_id -> storage_path 的映射字典
        """
        if not self.is_connected:
            logger.error("Firebase Storage 未连接")
            return {}
        
        storage_paths = {}
        uploaded_count = 0
        
        for seg in segments:
            seg_id = seg.get('id')
            audio_data = seg.get('audio_data')
            
            if not seg_id or audio_data is None:
                continue
            
            try:
                # 如果 audio_data 是 AudioSegment 对象，需要导出为 bytes
                if hasattr(audio_data, 'export'):
                    buffer = io.BytesIO()
                    audio_data.export(buffer, format='mp3', bitrate='128k')
                    buffer.seek(0)
                    data = buffer.read()
                elif isinstance(audio_data, bytes):
                    data = audio_data
                else:
                    logger.warning(f"片段 {seg_id} 音频数据类型不支持: {type(audio_data)}")
                    continue
                
                filename = f"{seg_id}.mp3"
                storage_path = self._get_user_audio_path(user_id, project_id, filename)
                
                blob = self.bucket.blob(storage_path)
                blob.upload_from_string(data, content_type=content_type)
                
                storage_paths[seg_id] = storage_path
                uploaded_count += 1
                
            except Exception as e:
                logger.error(f"上传片段 {seg_id} 音频失败: {e}")
        
        logger.info(f"批量上传片段音频完成: {uploaded_count}/{len(segments)} 个成功")
        return storage_paths


# 全局单例
_storage_manager: Optional[FirebaseStorageManager] = None


def get_storage_manager() -> FirebaseStorageManager:
    """获取 Firebase Storage 管理器单例"""
    global _storage_manager
    if _storage_manager is None:
        _storage_manager = FirebaseStorageManager()
    return _storage_manager


def initialize_storage(config: Dict[str, Any]) -> bool:
    """
    初始化 Firebase Storage（便捷函数）
    
    Args:
        config: 配置字典
        
    Returns:
        是否成功
    """
    manager = get_storage_manager()
    return manager.initialize(config)
