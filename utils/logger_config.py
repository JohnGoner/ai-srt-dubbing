"""
日志配置模块
读取配置文件中的日志设置并配置loguru
"""

import sys
from pathlib import Path
from typing import Dict, Any, Optional
from loguru import logger


class LoggerConfig:
    """日志配置管理器"""
    
    def __init__(self):
        """初始化日志配置管理器"""
        self.is_configured = False
    
    def configure_logger(self, config: Optional[Dict[str, Any]] = None, log_level: str = "INFO"):
        """
        配置loguru日志器
        
        Args:
            config: 完整配置字典
            log_level: 日志级别，如果config为None时使用
        """
        if self.is_configured:
            return
        
        # 移除默认的处理器
        logger.remove()
        
        # 从配置中获取日志设置
        if config and 'logging' in config:
            logging_config = config['logging']
            level = logging_config.get('level', 'INFO').upper()
            log_file = logging_config.get('log_file', 'logs/dubbing.log')
            max_log_size = logging_config.get('max_log_size', '10MB')
            backup_count = logging_config.get('backup_count', 5)
        else:
            level = log_level.upper()
            log_file = 'logs/dubbing.log'
            max_log_size = '10MB'
            backup_count = 5
        
        # 配置控制台输出 - 只显示指定级别及以上的日志
        logger.add(
            sys.stderr,
            level=level,
            format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
            colorize=True
        )
        
        # 配置文件输出（如果指定了日志文件）
        if log_file:
            try:
                # 确保日志目录存在
                log_path = Path(log_file)
                log_path.parent.mkdir(parents=True, exist_ok=True)
                
                logger.add(
                    log_file,
                    level=level,
                    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
                    rotation=max_log_size,
                    retention=backup_count,
                    compression="zip",
                    encoding="utf-8"
                )
            except Exception as e:
                logger.warning(f"无法配置文件日志记录: {e}")
        
        self.is_configured = True
        logger.info(f"日志系统已配置，级别: {level}")
    
    def set_level(self, level: str):
        """
        动态设置日志级别
        
        Args:
            level: 日志级别 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        """
        level = level.upper()
        
        # 移除现有处理器并重新配置
        logger.remove()
        
        # 重新添加控制台处理器
        logger.add(
            sys.stderr,
            level=level,
            format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
            colorize=True
        )
        
        logger.info(f"日志级别已更新为: {level}")


# 全局日志配置实例
logger_config = LoggerConfig()


def setup_logging(config: Optional[Dict[str, Any]] = None, log_level: str = "INFO"):
    """
    设置日志配置的便捷函数
    
    Args:
        config: 完整配置字典
        log_level: 日志级别
    """
    logger_config.configure_logger(config, log_level)


def set_log_level(level: str):
    """
    设置日志级别的便捷函数
    
    Args:
        level: 日志级别
    """
    logger_config.set_level(level) 