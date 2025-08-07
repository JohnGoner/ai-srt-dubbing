"""
字幕处理模块
处理SRT、VTT等字幕文件，提取文本和时间码
"""

import pysrt
from webvtt import read as webvtt_read
from pathlib import Path
from typing import List, Dict, Any
from loguru import logger


class SubtitleProcessor:
    """字幕处理器"""
    
    def __init__(self, config: dict):
        """
        初始化字幕处理器
        
        Args:
            config: 配置字典
        """
        self.config = config
    
    def load_subtitle(self, subtitle_path: str) -> List[Dict[str, Any]]:
        """
        加载字幕文件
        
        Args:
            subtitle_path: 字幕文件路径
            
        Returns:
            包含文本和时间码的片段列表
        """
        try:
            file_path = Path(subtitle_path)
            extension = file_path.suffix.lower()
            
            if extension == '.srt':
                return self._load_srt(subtitle_path)
            elif extension == '.vtt':
                return self._load_vtt(subtitle_path)
            else:
                raise ValueError(f"不支持的字幕格式: {extension}")
                
        except Exception as e:
            logger.error(f"加载字幕文件失败: {str(e)}")
            raise
    
    def _load_srt(self, srt_path: str) -> List[Dict[str, Any]]:
        """
        加载SRT字幕文件
        
        Args:
            srt_path: SRT文件路径
            
        Returns:
            片段列表
        """
        try:
            subs = pysrt.open(srt_path, encoding='utf-8')
            segments = []
            
            for sub in subs:
                # 转换时间码为秒
                start_time = self._time_to_seconds(sub.start)
                end_time = self._time_to_seconds(sub.end)
                
                segment = {
                    'id': sub.index,
                    'start': start_time,
                    'end': end_time,
                    'text': sub.text.replace('\n', ' ').strip(),
                    'duration': end_time - start_time,
                    'confidence': 1.0  # 字幕文件假设为100%准确
                }
                
                segments.append(segment)
            
            logger.info(f"SRT字幕加载成功，共 {len(segments)} 个片段")
            return segments
            
        except Exception as e:
            logger.error(f"加载SRT文件失败: {str(e)}")
            raise
    
    def _load_vtt(self, vtt_path: str) -> List[Dict[str, Any]]:
        """
        加载VTT字幕文件
        
        Args:
            vtt_path: VTT文件路径
            
        Returns:
            片段列表
        """
        try:
            vtt = webvtt_read(vtt_path)
            segments = []
            
            for i, caption in enumerate(vtt.captions):
                # 转换时间码为秒
                start_time = self._vtt_time_to_seconds(caption.start)
                end_time = self._vtt_time_to_seconds(caption.end)
                
                segment = {
                    'id': i,
                    'start': start_time,
                    'end': end_time,
                    'text': caption.text.replace('\n', ' ').strip(),
                    'duration': end_time - start_time,
                    'confidence': 1.0
                }
                
                segments.append(segment)
            
            logger.info(f"VTT字幕加载成功，共 {len(segments)} 个片段")
            return segments
            
        except Exception as e:
            logger.error(f"加载VTT文件失败: {str(e)}")
            raise
    
    def _time_to_seconds(self, time_obj) -> float:
        """
        将pysrt时间对象转换为秒
        
        Args:
            time_obj: pysrt时间对象
            
        Returns:
            秒数
        """
        return (time_obj.hours * 3600 + 
                time_obj.minutes * 60 + 
                time_obj.seconds + 
                time_obj.milliseconds / 1000.0)
    
    def _vtt_time_to_seconds(self, time_str: str) -> float:
        """
        将VTT时间字符串转换为秒
        
        Args:
            time_str: 时间字符串，格式如 "00:01:23.456"
            
        Returns:
            秒数
        """
        try:
            parts = time_str.split(':')
            if len(parts) == 3:
                hours = int(parts[0])
                minutes = int(parts[1])
                seconds_parts = parts[2].split('.')
                seconds = int(seconds_parts[0])
                milliseconds = int(seconds_parts[1]) if len(seconds_parts) > 1 else 0
                
                return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0
            else:
                raise ValueError(f"无效的时间格式: {time_str}")
                
        except Exception as e:
            logger.error(f"解析VTT时间失败: {str(e)}")
            return 0.0
    
    def validate_subtitle_text(self, segments: List[Dict[str, Any]]) -> bool:
        """
        验证字幕文本的一致性
        
        Args:
            segments: 片段列表
            
        Returns:
            是否所有片段都有有效的最终文本
        """
        for segment in segments:
            final_text = (segment.get('final_text') or 
                         segment.get('optimized_text') or 
                         segment.get('translated_text') or 
                         segment.get('original_text'))
            
            if not final_text or final_text.strip() == '':
                logger.warning(f"片段 {segment.get('id')} 缺少有效文本")
                return False
        
        return True

    def save_subtitle(self, segments: List[Dict[str, Any]], output_path: str, format: str = 'srt'):
        """
        保存字幕文件
        
        Args:
            segments: 片段列表
            output_path: 输出文件路径
            format: 输出格式
        """
        try:
            # 添加验证
            if not self.validate_subtitle_text(segments):
                logger.warning("字幕文本验证失败，可能存在空文本片段")
            
            if format.lower() == 'srt':
                self._save_srt(segments, output_path)
            elif format.lower() == 'vtt':
                self._save_vtt(segments, output_path)
            else:
                raise ValueError(f"不支持的字幕格式: {format}")
                
        except Exception as e:
            logger.error(f"保存字幕文件失败: {str(e)}")
            raise
    
    def _save_srt(self, segments: List[Dict[str, Any]], output_path: str):
        """
        保存为SRT格式
        
        Args:
            segments: 片段列表
            output_path: 输出文件路径
        """
        try:
            subs = pysrt.SubRipFile()
            
            for segment in segments:
                start_time = self._seconds_to_srt_time(segment['start'])
                end_time = self._seconds_to_srt_time(segment['end'])
                
                # 修改：优先使用final_text，确保使用最终确认的文本
                text = (segment.get('final_text') or 
                       segment.get('optimized_text') or 
                       segment.get('translated_text') or 
                       segment.get('original_text') or 
                       segment.get('text', ''))
                
                sub = pysrt.SubRipItem(
                    index=segment['id'],
                    start=start_time,
                    end=end_time,
                    text=text
                )
                
                subs.append(sub)
            
            subs.save(output_path, encoding='utf-8')
            logger.info(f"SRT字幕保存成功: {output_path}")
            
        except Exception as e:
            logger.error(f"保存SRT文件失败: {str(e)}")
            raise
    
    def _save_vtt(self, segments: List[Dict[str, Any]], output_path: str):
        """
        保存为VTT格式
        
        Args:
            segments: 片段列表
            output_path: 输出文件路径
        """
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write("WEBVTT\n\n")
                
                for segment in segments:
                    start_time = self._seconds_to_vtt_time(segment['start'])
                    end_time = self._seconds_to_vtt_time(segment['end'])
                    
                    # 优先使用翻译文本，然后是原始文本，最后是text字段
                    text = (segment.get('translated_text') or 
                           segment.get('original_text') or 
                           segment.get('text', ''))
                    
                    f.write(f"{start_time} --> {end_time}\n")
                    f.write(f"{text}\n\n")
            
            logger.info(f"VTT字幕保存成功: {output_path}")
            
        except Exception as e:
            logger.error(f"保存VTT文件失败: {str(e)}")
            raise
    
    def _seconds_to_srt_time(self, seconds: float):
        """
        将秒数转换为SRT时间对象
        
        Args:
            seconds: 秒数
            
        Returns:
            pysrt时间对象
        """
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millisecs = int((seconds % 1) * 1000)
        
        return pysrt.SubRipTime(hours, minutes, secs, millisecs)
    
    def _seconds_to_vtt_time(self, seconds: float) -> str:
        """
        将秒数转换为VTT时间字符串
        
        Args:
            seconds: 秒数
            
        Returns:
            VTT时间字符串
        """
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millisecs = int((seconds % 1) * 1000)
        
        return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millisecs:03d}"
    
    def validate_subtitle_file(self, subtitle_path: str) -> bool:
        """
        验证字幕文件
        
        Args:
            subtitle_path: 字幕文件路径
            
        Returns:
            是否有效
        """
        try:
            segments = self.load_subtitle(subtitle_path)
            
            # 基本验证
            if not segments:
                logger.error("字幕文件为空")
                return False
            
            # 检查时间码顺序
            for i in range(len(segments) - 1):
                if segments[i]['end'] > segments[i + 1]['start']:
                    logger.warning(f"时间码重叠: 片段 {segments[i]['id']} 和 {segments[i+1]['id']}")
            
            # 检查文本内容
            empty_count = sum(1 for seg in segments if not seg['text'].strip())
            if empty_count > len(segments) * 0.1:
                logger.warning(f"空文本片段过多: {empty_count}/{len(segments)}")
            
            logger.info("字幕文件验证通过")
            return True
            
        except Exception as e:
            logger.error(f"字幕文件验证失败: {str(e)}")
            return False 