"""
Windows系统音频处理工具
专门处理Windows系统下的音频文件操作问题
"""

import os
import platform
import tempfile
import time
from pathlib import Path
from typing import Optional, List
from loguru import logger


class WindowsAudioUtils:
    """Windows系统音频工具类"""
    
    def __init__(self):
        """初始化Windows音频工具"""
        self.temp_base_dir = Path(tempfile.gettempdir()) / "ai_dubbing"
        self.audio_temp_dir = self.temp_base_dir / "audio"
        self.tts_temp_dir = self.temp_base_dir / "tts"
        
        # 创建临时目录
        self.audio_temp_dir.mkdir(parents=True, exist_ok=True)
        self.tts_temp_dir.mkdir(parents=True, exist_ok=True)
        
        # 清理队列文件
        self.cleanup_queue_file = self.temp_base_dir / "cleanup_queue.txt"
        
        logger.debug(f"Windows音频工具初始化完成: {self.temp_base_dir}")
    
    def create_temp_audio_path(self, prefix: str = "audio", segment_id: str = "") -> Path:
        """
        创建临时音频文件路径
        
        Args:
            prefix: 文件名前缀
            segment_id: 片段ID
            
        Returns:
            临时文件路径
        """
        timestamp = int(time.time() * 1000000)  # 微秒级时间戳
        
        if segment_id:
            filename = f"{prefix}_{segment_id}_{timestamp}.wav"
        else:
            filename = f"{prefix}_{timestamp}.wav"
        
        return self.audio_temp_dir / filename
    
    def create_temp_tts_path(self, prefix: str = "tts_segment") -> Path:
        """
        创建临时TTS文件路径
        
        Args:
            prefix: 文件名前缀
            
        Returns:
            临时文件路径
        """
        timestamp = int(time.time() * 1000000)  # 微秒级时间戳
        filename = f"{prefix}_{timestamp}.wav"
        return self.tts_temp_dir / filename
    
    def safe_export_audio(self, audio_segment, file_path: Path, format: str = "wav") -> bool:
        """
        安全地导出音频文件（Windows优化）
        
        Args:
            audio_segment: pydub AudioSegment对象
            file_path: 目标文件路径
            format: 音频格式
            
        Returns:
            是否导出成功
        """
        try:
            # Windows系统使用标准的WAV参数
            if platform.system() == "Windows":
                audio_segment.export(
                    str(file_path), 
                    format=format,
                    parameters=[
                        "-acodec", "pcm_s16le",  # 16-bit PCM编码
                        "-ar", "44100",          # 44.1kHz采样率
                        "-ac", "1"               # 单声道
                    ]
                )
            else:
                # 非Windows系统使用原有逻辑
                audio_segment.export(str(file_path), format=format)
            
            # 验证文件是否成功创建
            if file_path.exists() and file_path.stat().st_size > 0:
                logger.debug(f"音频文件导出成功: {file_path} ({file_path.stat().st_size} bytes)")
                return True
            else:
                logger.error(f"音频文件导出失败或文件为空: {file_path}")
                return False
                
        except Exception as e:
            logger.error(f"音频文件导出异常: {e}")
            return False
    
    def safe_cleanup_file(self, file_path: Path) -> bool:
        """
        安全地清理临时文件
        
        Args:
            file_path: 要清理的文件路径
            
        Returns:
            是否清理成功
        """
        try:
            if file_path.exists():
                file_path.unlink()
                logger.debug(f"临时文件已清理: {file_path}")
                return True
            return True  # 文件不存在也算清理成功
            
        except Exception as e:
            logger.warning(f"清理临时文件失败: {file_path} - {e}")
            
            # 添加到延迟清理队列
            try:
                with open(self.cleanup_queue_file, "a", encoding="utf-8") as f:
                    f.write(f"{file_path}\n")
                logger.debug(f"文件已添加到延迟清理队列: {file_path}")
            except:
                pass
            
            return False
    
    def cleanup_old_files(self, max_age_hours: int = 24) -> int:
        """
        清理旧的临时文件
        
        Args:
            max_age_hours: 最大保留时间（小时）
            
        Returns:
            清理的文件数量
        """
        cleaned_count = 0
        current_time = time.time()
        max_age_seconds = max_age_hours * 3600
        
        try:
            # 清理音频临时目录
            for temp_file in self.audio_temp_dir.glob("*.wav"):
                try:
                    file_age = current_time - temp_file.stat().st_mtime
                    if file_age > max_age_seconds:
                        temp_file.unlink()
                        cleaned_count += 1
                        logger.debug(f"清理旧音频文件: {temp_file}")
                except Exception as e:
                    logger.warning(f"清理文件失败: {temp_file} - {e}")
            
            # 清理TTS临时目录
            for temp_file in self.tts_temp_dir.glob("*.wav"):
                try:
                    file_age = current_time - temp_file.stat().st_mtime
                    if file_age > max_age_seconds:
                        temp_file.unlink()
                        cleaned_count += 1
                        logger.debug(f"清理旧TTS文件: {temp_file}")
                except Exception as e:
                    logger.warning(f"清理文件失败: {temp_file} - {e}")
            
            # 处理延迟清理队列
            if self.cleanup_queue_file.exists():
                cleaned_count += self._process_cleanup_queue()
            
            if cleaned_count > 0:
                logger.info(f"清理了 {cleaned_count} 个旧临时文件")
            
        except Exception as e:
            logger.error(f"清理临时文件时出错: {e}")
        
        return cleaned_count
    
    def _process_cleanup_queue(self) -> int:
        """
        处理延迟清理队列
        
        Returns:
            清理的文件数量
        """
        cleaned_count = 0
        remaining_files = []
        
        try:
            with open(self.cleanup_queue_file, "r", encoding="utf-8") as f:
                file_paths = [line.strip() for line in f.readlines() if line.strip()]
            
            for file_path_str in file_paths:
                try:
                    file_path = Path(file_path_str)
                    if file_path.exists():
                        file_path.unlink()
                        cleaned_count += 1
                        logger.debug(f"从队列清理文件: {file_path}")
                    # 如果文件不存在，也算清理成功，不加入remaining_files
                except Exception as e:
                    logger.warning(f"队列清理文件失败: {file_path_str} - {e}")
                    remaining_files.append(file_path_str)
            
            # 更新清理队列文件
            if remaining_files:
                with open(self.cleanup_queue_file, "w", encoding="utf-8") as f:
                    for file_path in remaining_files:
                        f.write(f"{file_path}\n")
            else:
                # 如果队列为空，删除队列文件
                self.cleanup_queue_file.unlink()
            
        except Exception as e:
            logger.error(f"处理清理队列失败: {e}")
        
        return cleaned_count
    
    def get_temp_dir_stats(self) -> dict:
        """
        获取临时目录统计信息
        
        Returns:
            统计信息字典
        """
        stats = {
            "audio_files": 0,
            "tts_files": 0,
            "total_size_mb": 0,
            "queue_size": 0
        }
        
        try:
            # 统计音频文件
            audio_files = list(self.audio_temp_dir.glob("*.wav"))
            stats["audio_files"] = len(audio_files)
            
            # 统计TTS文件
            tts_files = list(self.tts_temp_dir.glob("*.wav"))
            stats["tts_files"] = len(tts_files)
            
            # 计算总大小
            total_size = 0
            for file_path in audio_files + tts_files:
                try:
                    total_size += file_path.stat().st_size
                except:
                    pass
            stats["total_size_mb"] = total_size / (1024 * 1024)
            
            # 统计清理队列
            if self.cleanup_queue_file.exists():
                try:
                    with open(self.cleanup_queue_file, "r", encoding="utf-8") as f:
                        stats["queue_size"] = len([line for line in f.readlines() if line.strip()])
                except:
                    pass
            
        except Exception as e:
            logger.error(f"获取临时目录统计失败: {e}")
        
        return stats


# 全局Windows音频工具实例
_global_windows_audio_utils = None


def get_windows_audio_utils() -> WindowsAudioUtils:
    """获取全局Windows音频工具实例"""
    global _global_windows_audio_utils
    if _global_windows_audio_utils is None:
        _global_windows_audio_utils = WindowsAudioUtils()
    return _global_windows_audio_utils


def is_windows() -> bool:
    """检查是否为Windows系统"""
    return platform.system() == "Windows"


def cleanup_windows_temp_files():
    """清理Windows临时文件的便捷函数"""
    if is_windows():
        utils = get_windows_audio_utils()
        return utils.cleanup_old_files()
    return 0

