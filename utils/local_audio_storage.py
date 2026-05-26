"""
本地文件系统音频存储管理器
与 FirebaseStorageManager 接口 1:1 对齐，作为 storage_factory 的备选 backend。
路径结构镜像 Firebase Storage 以减小迁移阻力：
  {root}/users/{user_id}/projects/{project_id}/audio/{stage}/{segment_id}.mp3
  {root}/users/{user_id}/projects/{project_id}/output/{filename}
"""

import os
import io
import shutil
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Union, BinaryIO
from loguru import logger


class LocalAudioStorage:
    """本地文件系统音频存储 - 单例"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if getattr(self, '_inited', False):
            return
        self._inited = True
        self.root: Optional[Path] = None
        self.is_connected = False
        self.config: Dict[str, Any] = {}
        # 与 firebase_storage 保持名称一致的占位，部分调用方读 .bucket.name
        self.bucket = None

    # ==================== 初始化 ====================

    def initialize(self, config: Dict[str, Any], force_reinit: bool = False) -> bool:
        if self.is_connected and not force_reinit:
            return True
        try:
            self.config = config
            storage_cfg = config.get('storage', {}) if isinstance(config, dict) else {}
            root = storage_cfg.get('local_audio_root') or os.environ.get('AI_DUBBING_AUDIO_ROOT')
            if not root:
                root = str(Path.home() / '.ai_dubbing_projects' / 'audio')
            self.root = Path(root)
            self.root.mkdir(parents=True, exist_ok=True)
            # 解析 symlink（macOS /var/folders 等场景，确保 relative_to 一致）
            self.root = self.root.resolve()
            self.is_connected = True
            logger.info(f"LocalAudioStorage 初始化成功: root={self.root}")
            return True
        except Exception as e:
            logger.error(f"LocalAudioStorage 初始化失败: {e}")
            self.is_connected = False
            return False

    # ==================== 内部路径辅助 ====================

    def _abs(self, storage_path: str) -> Path:
        """把 storage_path（相对，e.g. 'users/XYC/projects/abc/audio/preview/seg1.mp3'）转绝对路径。"""
        if not self.root:
            raise RuntimeError("LocalAudioStorage 未初始化")
        # 防止绝对路径或 .. 越权
        p = (self.root / storage_path.lstrip('/')).resolve()
        if not str(p).startswith(str(self.root.resolve())):
            raise ValueError(f"非法路径越界: {storage_path}")
        return p

    def _get_user_audio_path(self, user_id: str, project_id: str, filename: str) -> str:
        return f"users/{user_id}/projects/{project_id}/audio/{filename}"

    def _get_staged_audio_path(self, user_id: str, project_id: str, segment_id: str, stage: str) -> str:
        return f"users/{user_id}/projects/{project_id}/audio/{stage}/{segment_id}.mp3"

    def _get_user_output_path(self, user_id: str, project_id: str, filename: str) -> str:
        return f"users/{user_id}/projects/{project_id}/output/{filename}"

    def _atomic_write_bytes(self, target: Path, data: bytes) -> None:
        """原子写：先写 tmp 再 rename。"""
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + '.tmp')
        with open(tmp, 'wb') as f:
            f.write(data)
        tmp.replace(target)

    def _audio_bytes_from(self, audio_data: Any, content_type: str = 'audio/mpeg') -> bytes:
        """把 AudioSegment / bytes / file-like / file-path 统一成 bytes。"""
        if isinstance(audio_data, (bytes, bytearray)):
            return bytes(audio_data)
        if hasattr(audio_data, 'export'):
            buffer = io.BytesIO()
            fmt = 'mp3' if 'mpeg' in content_type or content_type.endswith('mp3') else 'wav'
            audio_data.export(buffer, format=fmt, bitrate='128k')
            return buffer.getvalue()
        if hasattr(audio_data, 'read'):
            return audio_data.read()
        if isinstance(audio_data, (str, Path)) and Path(audio_data).exists():
            return Path(audio_data).read_bytes()
        raise TypeError(f"无法从类型 {type(audio_data).__name__} 提取音频字节")

    # ==================== 上传接口（同 firebase_storage） ====================

    def upload_staged_audio(
        self,
        user_id: str,
        project_id: str,
        segment_id: str,
        stage: str,  # 'preview' | 'confirmed'
        audio_data: Any,
        content_type: str = 'audio/mpeg',
        max_retries: int = 3,
    ) -> Optional[str]:
        if not self.is_connected:
            logger.warning("LocalAudioStorage 未连接")
            return None
        try:
            storage_path = self._get_staged_audio_path(user_id, project_id, segment_id, stage)
            data = self._audio_bytes_from(audio_data, content_type)
            self._atomic_write_bytes(self._abs(storage_path), data)
            logger.debug(f"upload_staged_audio: {storage_path} ({len(data)} bytes)")
            return storage_path
        except Exception as e:
            logger.error(f"upload_staged_audio 失败: {e}")
            return None

    def delete_staged_audio(self, user_id: str, project_id: str, segment_id: str, stage: str) -> bool:
        if not self.is_connected:
            return False
        try:
            storage_path = self._get_staged_audio_path(user_id, project_id, segment_id, stage)
            target = self._abs(storage_path)
            if target.exists():
                target.unlink()
                return True
            return False
        except Exception as e:
            logger.error(f"delete_staged_audio 失败: {e}")
            return False

    def promote_audio_stage(self, user_id: str, project_id: str, segment_id: str, audio_data: Any) -> Optional[str]:
        confirmed_path = self.upload_staged_audio(user_id, project_id, segment_id, 'confirmed', audio_data)
        if confirmed_path:
            self.delete_staged_audio(user_id, project_id, segment_id, 'preview')
        return confirmed_path

    def upload_audio(
        self,
        user_id: str,
        project_id: str,
        filename: str,
        audio_data: Any,
        content_type: str = 'audio/mpeg',
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        if not self.is_connected:
            return None
        try:
            storage_path = self._get_user_audio_path(user_id, project_id, filename)
            data = self._audio_bytes_from(audio_data, content_type)
            self._atomic_write_bytes(self._abs(storage_path), data)
            return storage_path
        except Exception as e:
            logger.error(f"upload_audio 失败: {e}")
            return None

    def upload_final_audio(
        self,
        user_id: str,
        project_id: str,
        filename: str,
        audio_data: Any,
        content_type: str = 'audio/mpeg',
    ) -> Optional[str]:
        if not self.is_connected:
            return None
        try:
            storage_path = self._get_user_output_path(user_id, project_id, filename)
            data = self._audio_bytes_from(audio_data, content_type)
            self._atomic_write_bytes(self._abs(storage_path), data)
            return storage_path
        except Exception as e:
            logger.error(f"upload_final_audio 失败: {e}")
            return None

    def upload_final_subtitle(
        self,
        user_id: str,
        project_id: str,
        filename: str,
        subtitle_data: Union[str, bytes],
        content_type: str = 'text/plain',
    ) -> Optional[str]:
        if not self.is_connected:
            return None
        try:
            storage_path = self._get_user_output_path(user_id, project_id, filename)
            data = subtitle_data.encode('utf-8') if isinstance(subtitle_data, str) else subtitle_data
            self._atomic_write_bytes(self._abs(storage_path), data)
            return storage_path
        except Exception as e:
            logger.error(f"upload_final_subtitle 失败: {e}")
            return None

    def upload_segment_audios_batch(
        self,
        user_id: str,
        project_id: str,
        segments: List[Dict[str, Any]],
        content_type: str = 'audio/mpeg',
    ) -> Dict[str, str]:
        """批量上传 segment.id -> storage_path"""
        result: Dict[str, str] = {}
        for seg in segments:
            sid = seg.get('id') or seg.get('segment_id')
            audio = seg.get('audio_data') or seg.get('audio')
            stage = seg.get('stage', 'preview')
            if sid and audio is not None:
                path = self.upload_staged_audio(user_id, project_id, sid, stage, audio, content_type)
                if path:
                    result[sid] = path
        return result

    # ==================== 下载接口 ====================

    def download_audio(self, storage_path: str) -> Optional[bytes]:
        if not self.is_connected:
            return None
        try:
            p = self._abs(storage_path)
            if not p.exists():
                logger.warning(f"download_audio: 文件不存在 {storage_path}")
                return None
            return p.read_bytes()
        except Exception as e:
            logger.error(f"download_audio 失败: {e}")
            return None

    def download_audio_to_file(self, storage_path: str, local_path: Optional[str] = None) -> Optional[str]:
        if not self.is_connected:
            return None
        try:
            src = self._abs(storage_path)
            if not src.exists():
                return None
            if local_path is None:
                with tempfile.NamedTemporaryFile(delete=False, suffix=Path(storage_path).suffix) as f:
                    local_path = f.name
            shutil.copyfile(src, local_path)
            return local_path
        except Exception as e:
            logger.error(f"download_audio_to_file 失败: {e}")
            return None

    # ==================== URL（本地返回绝对路径，st.audio 兼容） ====================

    def get_download_url(self, storage_path: str, expiration: int = 3600) -> Optional[str]:
        """本地后端：直接返回绝对文件路径。Streamlit st.audio() 既能吃 URL 也能吃路径。"""
        if not self.is_connected:
            return None
        try:
            p = self._abs(storage_path)
            return str(p) if p.exists() else None
        except Exception as e:
            logger.error(f"get_download_url 失败: {e}")
            return None

    # ==================== 删除 ====================

    def delete_audio(self, storage_path: str) -> bool:
        if not self.is_connected:
            return False
        try:
            p = self._abs(storage_path)
            if p.exists():
                p.unlink()
                return True
            return False
        except Exception as e:
            logger.error(f"delete_audio 失败: {e}")
            return False

    def delete_project_audio(self, user_id: str, project_id: str) -> int:
        """删除 users/{user_id}/projects/{project_id}/ 下所有音频。返回删除文件数。"""
        if not self.is_connected:
            return 0
        try:
            prefix = self._abs(f"users/{user_id}/projects/{project_id}")
            if not prefix.exists():
                return 0
            count = sum(1 for _ in prefix.rglob('*') if _.is_file())
            shutil.rmtree(prefix, ignore_errors=True)
            return count
        except Exception as e:
            logger.error(f"delete_project_audio 失败: {e}")
            return 0

    # ==================== 列表 / 存在检查 ====================

    def list_project_audio(self, user_id: str, project_id: str) -> List[Dict[str, Any]]:
        if not self.is_connected:
            return []
        try:
            prefix = self._abs(f"users/{user_id}/projects/{project_id}")
            if not prefix.exists():
                return []
            out: List[Dict[str, Any]] = []
            for f in prefix.rglob('*'):
                if not f.is_file():
                    continue
                st = f.stat()
                rel = str(f.relative_to(self.root))
                out.append({
                    'name': rel,
                    'size': st.st_size,
                    'created': datetime.fromtimestamp(st.st_ctime, tz=timezone.utc).isoformat(),
                    'updated': datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
                    'content_type': 'audio/mpeg' if f.suffix == '.mp3' else 'application/octet-stream',
                })
            return out
        except Exception as e:
            logger.error(f"list_project_audio 失败: {e}")
            return []

    def check_file_exists(self, storage_path: str) -> bool:
        """firebase_storage 缺这个方法（workflow.py 调它），这里补上。"""
        if not self.is_connected:
            return False
        try:
            return self._abs(storage_path).exists()
        except Exception:
            return False

    # ==================== 统计 / 健康 ====================

    def get_storage_usage(self, user_id: str) -> Dict[str, Any]:
        if not self.is_connected:
            return {'total_bytes': 0, 'file_count': 0}
        try:
            prefix = self._abs(f"users/{user_id}")
            if not prefix.exists():
                return {'total_bytes': 0, 'file_count': 0}
            total = 0
            count = 0
            for f in prefix.rglob('*'):
                if f.is_file():
                    total += f.stat().st_size
                    count += 1
            return {'total_bytes': total, 'file_count': count}
        except Exception as e:
            logger.error(f"get_storage_usage 失败: {e}")
            return {'total_bytes': 0, 'file_count': 0}

    def health_check(self) -> Dict[str, Any]:
        return {
            'connected': self.is_connected,
            'backend': 'local',
            'root': str(self.root) if self.root else None,
            'writable': bool(self.root and os.access(self.root, os.W_OK)),
        }


# ==================== Module-level singleton accessors ====================

_local_storage_instance: Optional[LocalAudioStorage] = None


def get_local_audio_storage() -> LocalAudioStorage:
    global _local_storage_instance
    if _local_storage_instance is None:
        _local_storage_instance = LocalAudioStorage()
    return _local_storage_instance


def initialize_local_audio_storage(config: Dict[str, Any]) -> bool:
    mgr = get_local_audio_storage()
    return mgr.initialize(config)
