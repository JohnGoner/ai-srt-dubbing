"""
配置管理模块
处理系统配置文件的加载、验证和管理
"""

import yaml
import os
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from loguru import logger
import hashlib
import time


# 全局配置管理器单例
_global_config_manager = None


def get_global_config_manager():
    """获取全局配置管理器单例"""
    global _global_config_manager
    if _global_config_manager is None:
        _global_config_manager = ConfigManager()
    return _global_config_manager


class ConfigManager:
    """配置管理器"""
    
    def __init__(self):
        """初始化配置管理器"""
        self.config_filenames = [
            'config.yaml',
            'config.yml'
        ]
        self.config = None
        self.config_path = None
        self._config_loaded = False  # 添加加载状态标记
        
    def find_config_file(self, config_path: Optional[str] = None) -> Optional[str]:
        """
        智能查找配置文件
        
        Returns:
            配置文件路径，如果未找到则返回None
        """
        # 获取当前脚本的目录
        current_script_dir = Path(__file__).parent
        
        # 可能的配置文件目录（按优先级排序）
        possible_dirs = [
            # 项目根目录（从utils目录向上一级）
            current_script_dir.parent,
            
            # 当前脚本目录
            current_script_dir,
            
            # 当前工作目录
            Path.cwd(),
            
            # 用户主目录
            Path.home(),
            
            # 系统配置目录
            Path("/etc"),
        ]
        
        # 在每个目录中搜索配置文件
        for directory in possible_dirs:
            for filename in self.config_filenames:
                # 对于用户主目录，使用隐藏文件名
                if directory == Path.home():
                    path = directory / f".{filename}"
                else:
                    path = directory / filename
                
                if path.exists() and path.is_file():
                    # 只在首次找到或路径变化时输出日志
                    if not self._config_loaded or self.config_path != str(path.resolve()):
                        logger.info(f"找到配置文件: {path}")
                    return str(path.resolve())
        
        # 只在首次查找失败时输出警告
        if not self._config_loaded:
            logger.warning(f"未找到配置文件 (搜索了: {', '.join(self.config_filenames)})")
        return None
    
    def load_config(self, config_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        加载配置文件
        
        Args:
            config_path: 指定的配置文件路径，如果为None则自动查找
            
        Returns:
            配置字典，如果加载失败则返回None
        """
        if config_path is None:
            config_path = self.find_config_file()
        
        if config_path is None:
            return None
        
        # 检查是否已经加载了相同的配置文件
        if (self._config_loaded and 
            self.config_path == config_path and 
            self.config is not None):
            logger.debug(f"使用已缓存的配置: {config_path}")
            return self.config
        
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            
            self.config_path = config_path
            self.config = config
            self._config_loaded = True
            
            # 只在首次加载成功或配置文件变化时输出信息日志
            logger.info(f"配置文件加载成功: {config_path}")
            return config
            
        except FileNotFoundError:
            logger.error(f"配置文件不存在: {config_path}")
            return None
        except yaml.YAMLError as e:
            logger.error(f"YAML格式错误: {e}")
            return None
        except Exception as e:
            logger.error(f"加载配置文件失败: {e}")
            return None
    
    def get_config_info(self) -> Dict[str, Any]:
        """
        获取配置文件信息
        
        Returns:
            配置信息字典
        """
        if self.config is None or self.config_path is None:
            return {"status": "未加载", "path": None}
        
        config_file = Path(self.config_path)
        
        return {
            "status": "已加载",
            "path": str(config_file.resolve()),
            "size": f"{config_file.stat().st_size} bytes",
            "modified": config_file.stat().st_mtime,
            "translation_service": self.config.get('translation', {}).get('service', 'N/A'),
            "supported_languages": list(self.config.get('tts', {}).get('minimax', {}).get('voices', {}).keys()),
            "speech_rate": self.config.get('tts', {}).get('speech_rate', 1.0),
            "volume": self.config.get('tts', {}).get('volume', 90),
            "has_google_credentials": bool(self.config.get('api_keys', {}).get('google_credentials_path')),
        }
    
    def get_search_paths(self) -> List[str]:
        """
        获取配置文件搜索路径列表
        
        Returns:
            搜索路径列表
        """
        current_script_dir = Path(__file__).parent
        
        paths = []
        possible_dirs = [
            current_script_dir.parent,
            current_script_dir,
            Path.cwd(),
            Path.home(),
            Path("/etc"),
        ]
        
        for directory in possible_dirs:
            for filename in self.config_filenames:
                if directory == Path.home():
                    paths.append(str(directory / f".{filename}"))
                else:
                    paths.append(str(directory / filename))
        
        return paths
    
    def validate_config(self, config: Optional[Dict[str, Any]] = None) -> Tuple[bool, List[str]]:
        """
        验证配置文件
        
        Args:
            config: 要验证的配置字典，如果为None则使用当前加载的配置
            
        Returns:
            (是否有效, 错误消息列表)
        """
        if config is None:
            config = self.config
        
        if config is None:
            return False, ["配置未加载"]
        
        errors = []
        warnings = []
        
        # 检查必需的顶级键
        required_keys = ['api_keys', 'translation', 'tts', 'timing', 'output']
        for key in required_keys:
            if key not in config:
                errors.append(f"缺少必需的配置项: {key}")
        
        # 检查API密钥
        api_keys = config.get('api_keys', {})
        translation_config = config.get('translation', {})
        translation_service = translation_config.get('service', 'google')
        
        # 检查翻译服务密钥
        if translation_service == 'google':
            if not api_keys.get('google_credentials_path'):
                warnings.append("Google Cloud Translation认证文件路径未配置")
        
        # 检查MiniMax TTS密钥
        if not api_keys.get('minimax_api_key'):
            warnings.append("MiniMax TTS API密钥未配置")
        
        # 检查TTS配置
        tts_config = config.get('tts', {})
        if not tts_config.get('minimax', {}).get('voices'):
            errors.append("TTS语音配置缺失")
        
        # 如果有警告，将其添加到错误列表（但不影响有效性）
        all_messages = errors + [f"警告: {w}" for w in warnings]
        
        return len(errors) == 0, all_messages
    
    def save_config(self, config: Dict[str, Any], path: Optional[str] = None) -> bool:
        """
        保存配置文件
        
        Args:
            config: 要保存的配置字典
            path: 保存路径，如果为None则使用当前路径
            
        Returns:
            是否保存成功
        """
        if path is None:
            if self.config_path is None:
                # 如果没有指定路径且没有当前路径，则保存到项目根目录
                current_script_dir = Path(__file__).parent
                path = str(current_script_dir.parent / self.config_filenames[0])
            else:
                path = self.config_path
        
        try:
            with open(path, 'w', encoding='utf-8') as f:
                yaml.dump(config, f, default_flow_style=False, allow_unicode=True, indent=2)
            
            self.config_path = path
            self.config = config
            
            logger.info(f"配置文件保存成功: {path}")
            return True
            
        except Exception as e:
            logger.error(f"保存配置文件失败: {e}")
            return False
    
    def reload_config(self) -> bool:
        """
        重新加载配置文件
        
        Returns:
            是否重新加载成功
        """
        if self.config_path is None:
            return False
        
        new_config = self.load_config(self.config_path)
        return new_config is not None
    
    def get_config_template(self) -> Dict[str, Any]:
        """
        获取配置文件模板
        
        Returns:
            配置模板字典
        """
        return {
            "api_keys": {
                "openai_api_key": "",
                "google_credentials_path": "",
                "minimax_api_key": "",
                "minimax_group_id": "",
            },
            "translation": {
                "service": "google",
                "context_window_size": 5,
                "batch_size": 10,
                "max_concurrent_requests": 5,
                "use_context": True
            },
            "tts": {
                "service": "minimax",
                "minimax": {
                    "voices": {
                        "en": "English_ReservedYoungMan",
                        "es": "Spanish_MaturePartner",
                        "fr": "French_FriendlyWoman",
                        "de": "German_FriendlyWoman",
                        "ja": "Japanese_FriendlyWoman",
                        "ko": "Korean_FriendlyWoman"
                    }
                },
                "speech_rate": 1.0,
                "pitch": 0,
                "volume": 1.0
            },
            "timing": {
                "max_speed_ratio": 1.15,
                "min_speed_ratio": 0.95,
                "silence_padding": 0.1,
                "sync_tolerance": 0.15,
                "preferred_breathing_gap": 0.3,
                "min_overlap_buffer": 0.05
            },
            "output": {
                "audio_format": "mp3",
                "sample_rate": 48000,
                "channels": 1,
                "bit_depth": 16
            },
            "logging": {
                "level": "INFO",
                "log_file": "logs/dubbing.log",
                "max_log_size": "10MB",
                "backup_count": 5
            }
        } 