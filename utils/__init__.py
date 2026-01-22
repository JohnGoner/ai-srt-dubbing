"""
工具模块
包含配置管理、文件处理、Firebase 云端存储等工具函数
"""

from .config_manager import ConfigManager, get_global_config_manager
from .file_utils import validate_input_file, create_output_dir, get_file_info
from .cache_manager import get_cache_manager, LocalCacheManager
from .cache_integration import get_cache_integration, CacheIntegration
from .project_manager import ProjectManager, get_project_manager
from .project_integration import ProjectIntegration, get_project_integration

# Firebase 支持（可选导入）
try:
    from .firebase_manager import (
        FirebaseManager, 
        get_firebase_manager, 
        initialize_firebase,
        FIREBASE_AVAILABLE
    )
    from .firebase_storage import (
        FirebaseStorageManager, 
        get_storage_manager, 
        initialize_storage
    )
    from .firebase_project_manager import (
        FirebaseProjectManager, 
        get_firebase_project_manager
    )
    from .firebase_migration import FirebaseMigration
    _FIREBASE_MODULES_AVAILABLE = True
except ImportError:
    _FIREBASE_MODULES_AVAILABLE = False
    FIREBASE_AVAILABLE = False

__all__ = [
    # 配置管理
    'ConfigManager', 'get_global_config_manager',
    # 文件工具
    'validate_input_file', 'create_output_dir', 'get_file_info',
    # 缓存管理
    'get_cache_manager', 'LocalCacheManager',
    'get_cache_integration', 'CacheIntegration',
    # 项目管理
    'ProjectManager', 'get_project_manager',
    'ProjectIntegration', 'get_project_integration',
    # Firebase（如果可用）
    'FIREBASE_AVAILABLE',
]

# 如果 Firebase 模块可用，添加到导出列表
if _FIREBASE_MODULES_AVAILABLE:
    __all__.extend([
        'FirebaseManager', 'get_firebase_manager', 'initialize_firebase',
        'FirebaseStorageManager', 'get_storage_manager', 'initialize_storage',
        'FirebaseProjectManager', 'get_firebase_project_manager',
        'FirebaseMigration',
    ]) 