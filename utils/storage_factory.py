"""
Storage 后端工厂
按 config 选择 Firebase Storage 或 Local Audio Storage。
所有业务代码应该走这里拿 storage manager，而不是直接 import firebase_storage。
"""

from typing import Any, Dict, Optional
from loguru import logger

from .config_manager import get_global_config_manager


_initialized = False
_active_backend_name: Optional[str] = None


def _read_config() -> Dict[str, Any]:
    try:
        cfg = get_global_config_manager().load_config()
        return cfg or {}
    except Exception:
        return {}


def _select_backend_name(config: Dict[str, Any]) -> str:
    """根据 config 决定用哪个 backend。返回 'firebase' 或 'local'。"""
    storage_cfg = config.get('storage', {}) if isinstance(config, dict) else {}
    backend = (storage_cfg.get('backend') or 'local').strip().lower()
    if backend == 'firebase':
        # 只有 firebase.enabled 也为 true 时才真用 firebase
        firebase_enabled = bool(config.get('firebase', {}).get('enabled', False))
        return 'firebase' if firebase_enabled else 'local'
    return 'local'


def get_storage_manager():
    """
    返回当前 backend 的 storage manager 实例。
    Drop-in 替代 `from utils.firebase_storage import get_storage_manager`。
    """
    global _initialized, _active_backend_name
    cfg = _read_config()
    backend = _select_backend_name(cfg)

    if backend == 'firebase':
        from .firebase_storage import get_storage_manager as _f, initialize_storage as _fi
        mgr = _f()
        if not _initialized or _active_backend_name != 'firebase':
            _fi(cfg)
            _initialized = True
            _active_backend_name = 'firebase'
            logger.info("storage_factory: using FirebaseStorageManager")
        return mgr
    else:
        from .local_audio_storage import get_local_audio_storage, initialize_local_audio_storage
        mgr = get_local_audio_storage()
        if not _initialized or _active_backend_name != 'local':
            initialize_local_audio_storage(cfg)
            _initialized = True
            _active_backend_name = 'local'
            logger.info("storage_factory: using LocalAudioStorage")
        return mgr


def initialize_storage(config: Dict[str, Any]) -> bool:
    """初始化当前选定 backend。返回 True/False。"""
    global _initialized, _active_backend_name
    backend = _select_backend_name(config)
    if backend == 'firebase':
        from .firebase_storage import initialize_storage as _fi
        ok = _fi(config)
    else:
        from .local_audio_storage import initialize_local_audio_storage
        ok = initialize_local_audio_storage(config)
    if ok:
        _initialized = True
        _active_backend_name = backend
    return ok


def active_backend() -> Optional[str]:
    """当前激活的 backend 名（'firebase' 或 'local' 或 None 未初始化）。"""
    return _active_backend_name
