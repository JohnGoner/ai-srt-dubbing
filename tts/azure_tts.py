"""
Azure TTS模块 - 支持循环逼近算法的精确语速控制
使用Azure Speech Services进行多语言语音合成，支持SSML层面的语速微调
"""

import azure.cognitiveservices.speech as speechsdk
from typing import List, Dict, Any, Optional
from loguru import logger
import tempfile
import os
from pydub import AudioSegment
import io
import time
import threading
from datetime import datetime, timedelta


class AzureTTS:
    """Azure TTS语音合成器 - 支持精确语速控制"""
    
    def __init__(self, config: dict):
        """
        初始化Azure TTS
        
        Args:
            config: 配置字典
        """
        self.config = config
        api_keys = config.get('api_keys', {})
        
        # 获取两个Azure Speech key用于故障切换
        self.api_key_1 = api_keys.get('azure_speech_key_1')
        self.api_key_2 = api_keys.get('azure_speech_key_2')
        
        # 向后兼容：如果只有一个key配置
        if not self.api_key_1 and not self.api_key_2:
            self.api_key_1 = api_keys.get('azure_speech_key')
        
        self.region = api_keys.get('azure_speech_region')
        self.endpoint = api_keys.get('azure_speech_endpoint')
        self.tts_config = config.get('tts', {})
        
        # 当前使用的key索引（0表示key_1，1表示key_2）
        self.current_key_index = 0
        
        # 配置语音合成
        self.speech_config = self._create_speech_config(self.api_key_1)
        
        # 设置输出格式 - 使用48kHz获得高保真音质
        self.speech_config.set_speech_synthesis_output_format(
            speechsdk.SpeechSynthesisOutputFormat.Raw48Khz16BitMonoPcm
        )
        
        # 语音映射
        self.voice_map = self.tts_config.get('azure', {}).get('voices', {})
        
        # 基础语音参数
        self.base_speech_rate = self.tts_config.get('speech_rate', 1.0)
        self.pitch = self.tts_config.get('pitch', 0)
        self.volume = self.tts_config.get('volume', 90)  # 调整为90%，避免音量过大
        
        # 请求频率控制
        self.request_lock = threading.Lock()
        self.last_request_time = datetime.now()
        self.min_request_interval = 0.2  # 每个请求之间最小间隔200ms
        self.request_count = 0
        self.rate_limit_reset_time = datetime.now()
        self.max_requests_per_minute = 200  # 每分钟最大请求数
        
        # 错误恢复相关
        self.consecutive_errors = 0
        self.max_consecutive_errors = 3
        self.error_cooldown_time = 5  # 连续错误后的冷却时间（秒）
        self.last_error_time = None
        
        # 循环逼近相关参数
        self.language_specific_adjustments = {
            'en': {'rate_offset': 0.08},    # 英语稍快
            'es': {'rate_offset': 0.06},    # 西班牙语中等调整
            'fr': {'rate_offset': 0.10},    # 法语快一点
            'de': {'rate_offset': 0.05},    # 德语较稳重
            'ja': {'rate_offset': 0.02},    # 日语较慢
            'ko': {'rate_offset': 0.04}     # 韩语中等调整
        }
    
    def _create_speech_config(self, api_key: str) -> speechsdk.SpeechConfig:
        """
        创建语音配置对象
        
        Args:
            api_key: Azure Speech API key
            
        Returns:
            SpeechConfig对象
        """
        if self.endpoint:
            # 使用endpoint创建配置
            config = speechsdk.SpeechConfig(
                subscription=api_key,
                endpoint=self.endpoint
            )
        else:
            # 使用region创建配置
            config = speechsdk.SpeechConfig(
                subscription=api_key,
                region=self.region
            )
        return config
    
    def _switch_to_backup_key(self) -> bool:
        """
        切换到备用key
        
        Returns:
            是否成功切换
        """
        try:
            if self.current_key_index == 0 and self.api_key_2:
                # 切换到第二个key
                self.current_key_index = 1
                self.speech_config = self._create_speech_config(self.api_key_2)
                # 重新设置输出格式
                self.speech_config.set_speech_synthesis_output_format(
                    speechsdk.SpeechSynthesisOutputFormat.Raw48Khz16BitMonoPcm
                )
                logger.warning("Azure Speech key 1 失败，已切换到 key 2")
                return True
            elif self.current_key_index == 1 and self.api_key_1:
                # 切换到第一个key
                self.current_key_index = 0
                self.speech_config = self._create_speech_config(self.api_key_1)
                # 重新设置输出格式
                self.speech_config.set_speech_synthesis_output_format(
                    speechsdk.SpeechSynthesisOutputFormat.Raw48Khz16BitMonoPcm
                )
                logger.warning("Azure Speech key 2 失败，已切换到 key 1")
                return True
            else:
                logger.error("无法切换到备用key，或备用key不存在")
                return False
        except Exception as e:
            logger.error(f"切换到备用key失败: {str(e)}")
            return False
    
    def generate_audio_segments(self, segments: List[Dict[str, Any]], target_language: str) -> List[Dict[str, Any]]:
        """
        生成音频片段（基础版本，不含循环逼近）
        
        Args:
            segments: 翻译后的片段列表
            target_language: 目标语言代码
            
        Returns:
            包含音频数据的片段列表
        """
        try:
            logger.info(f"开始生成 {len(segments)} 个音频片段")
            
            # 获取对应语言的语音
            voice_name = self.voice_map.get(target_language)
            if not voice_name:
                raise ValueError(f"不支持的语言: {target_language}")
            
            audio_segments = []
            
            for i, segment in enumerate(segments):
                logger.info(f"生成音频片段 {i+1}/{len(segments)}")
                
                try:
                    # 使用默认语速生成
                    audio_data = self._generate_single_audio(
                        segment['translated_text'],
                        voice_name,
                        self.base_speech_rate,  # 使用默认语速
                        segment.get('duration', 0)
                    )
                    
                    # 创建音频片段对象
                    audio_segment = {
                        'id': segment['id'],
                        'start': segment['start'],
                        'end': segment['end'],
                        'original_text': segment.get('original_text', ''),
                        'translated_text': segment['translated_text'],
                        'audio_data': audio_data,
                        'duration': segment.get('duration', 0)
                    }
                    
                    audio_segments.append(audio_segment)
                    
                except Exception as e:
                    logger.error(f"生成片段 {segment['id']} 音频失败: {str(e)}")
                    # 创建静音片段作为备选
                    audio_segment = self._create_silence_segment(segment)
                    audio_segments.append(audio_segment)
            
            logger.info("音频片段生成完成")
            return audio_segments
            
        except Exception as e:
            logger.error(f"生成音频片段失败: {str(e)}")
            raise
    
    def _generate_single_audio(self, text: str, voice_name: str, 
                              speech_rate: float = None, 
                              target_duration: float = None) -> AudioSegment:
        """
        生成单个音频片段 - 支持精确语速控制和故障切换
        
        Args:
            text: 文本内容
            voice_name: 语音名称
            speech_rate: 语速倍率 (1.0-1.12)
            target_duration: 目标时长（用于记录，不影响生成）
            
        Returns:
            音频片段对象
        """
        max_retries = 3  # 增加重试次数
        
        for attempt in range(max_retries):
            try:
                # 应用请求频率控制
                self._wait_for_rate_limit()
                
                # 使用传入的语速，或默认语速
                effective_rate = speech_rate if speech_rate is not None else self.base_speech_rate
                
                # 构建优化的SSML
                ssml = self._build_precise_ssml(text, voice_name, effective_rate)
                
                # 创建合成器
                synthesizer = speechsdk.SpeechSynthesizer(
                    speech_config=self.speech_config,
                    audio_config=None
                )
                
                # 合成语音
                result = synthesizer.speak_ssml_async(ssml).get()
                
                if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
                    # 成功，重置错误计数
                    self.consecutive_errors = 0
                    self.last_error_time = None
                    
                    # 转换为AudioSegment - Raw PCM格式
                    # Azure TTS返回的是Raw 48kHz 16-bit mono PCM数据
                    audio_segment = AudioSegment(
                        data=result.audio_data,
                        sample_width=2,  # 16-bit = 2 bytes
                        frame_rate=48000,
                        channels=1
                    )
                    
                    actual_duration = len(audio_segment) / 1000.0
                    logger.debug(f"音频生成成功 - 语速: {effective_rate:.3f}, 时长: {actual_duration:.2f}s")
                    
                    return audio_segment
                    
                else:
                    error_details = result.cancellation_details
                    error_msg = f"语音合成失败: {result.reason}"
                    if error_details:
                        error_msg += f" - {error_details.reason}, {error_details.error_details}"
                    
                    logger.error(error_msg)
                    
                    # 处理特定错误类型
                    if error_details:
                        error_str = str(error_details.error_details).lower()
                        
                        # 429 Too Many Requests 错误
                        if '429' in error_str or 'too many requests' in error_str:
                            self._handle_rate_limit_error(attempt, max_retries)
                            if attempt < max_retries - 1:
                                continue
                        
                        # 认证或配额错误
                        elif any(keyword in error_str for keyword in ['unauthorized', 'forbidden', 'quota', 'authentication']):
                            if attempt < max_retries - 1:
                                logger.info(f"尝试切换到备用key... (第{attempt + 1}次尝试)")
                                if self._switch_to_backup_key():
                                    continue
                        
                        # 超时错误
                        elif 'timeout' in error_str:
                            self._handle_timeout_error(attempt, max_retries)
                            if attempt < max_retries - 1:
                                continue
                    
                    self._record_error()
                    raise Exception(error_msg)
                    
            except Exception as e:
                self._record_error()
                error_msg = f"生成单个音频失败 (第{attempt + 1}次尝试): {str(e)}"
                logger.error(error_msg)
                
                # 处理特定错误类型
                error_str = str(e).lower()
                
                # 处理429错误
                if '429' in error_str or 'too many requests' in error_str:
                    self._handle_rate_limit_error(attempt, max_retries)
                    if attempt < max_retries - 1:
                        continue
                
                # 处理认证相关错误
                elif any(keyword in error_str for keyword in ['unauthorized', 'forbidden', 'quota', 'authentication']):
                    if attempt < max_retries - 1:
                        logger.info(f"尝试切换到备用key... (第{attempt + 1}次尝试)")
                        if self._switch_to_backup_key():
                            continue
                
                # 处理超时错误
                elif 'timeout' in error_str:
                    self._handle_timeout_error(attempt, max_retries)
                    if attempt < max_retries - 1:
                        continue
                
                # 如果是最后一次尝试，抛出异常
                if attempt == max_retries - 1:
                    raise Exception(f"所有重试都失败: {error_msg}")
                
        raise Exception("所有Azure Speech key都已尝试，音频生成失败")
    
    def _build_precise_ssml(self, text: str, voice_name: str, speech_rate: float) -> str:
        """
        构建精确的SSML标记 - 支持细粒度语速控制
        
        Args:
            text: 文本内容
            voice_name: 语音名称
            speech_rate: 语速倍率
            
        Returns:
            SSML字符串
        """
        # 确保语速在合理范围内（0.95-1.15）
        rate = max(0.95, min(1.15, speech_rate))
        
        # 转换为SSML rate格式（百分比）
        if rate == 1.0:
            rate_percentage = "medium"  # 使用medium作为标准语速
        elif rate > 1.0:
            # 快于标准语速，使用+百分比
            rate_percentage = f"+{int((rate - 1.0) * 100)}%"
        else:
            # 慢于标准语速，使用-百分比
            rate_percentage = f"-{int((1.0 - rate) * 100)}%"
        
        # 音调保持默认值，不进行调整
        pitch_value = "medium"  # 使用默认音调
        
        # 构建SSML，使用精确的语音控制
        ssml = f"""<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="{self._get_language_from_voice(voice_name)}">
    <voice name="{voice_name}">
        <prosody rate="{rate_percentage}" pitch="{pitch_value}" volume="{self.volume}%">
            <break time="100ms"/>
            {self._preprocess_text_for_speech(text)}
            <break time="50ms"/>
        </prosody>
    </voice>
</speak>"""
        
        logger.debug(f"生成SSML - 语速: {rate_percentage}, 音调: {pitch_value}")
        return ssml
    
    def _preprocess_text_for_speech(self, text: str) -> str:
        """
        为语音合成预处理文本
        
        Args:
            text: 原始文本
            
        Returns:
            处理后的文本
        """
        # 处理常见的发音问题
        processed_text = text
        
        # 添加适当的停顿
        processed_text = processed_text.replace('.', '.<break time="300ms"/>')
        processed_text = processed_text.replace(',', ',<break time="150ms"/>')
        processed_text = processed_text.replace(';', ';<break time="200ms"/>')
        processed_text = processed_text.replace(':', ':<break time="200ms"/>')
        
        # 处理重音和强调
        # 可以在这里添加更多的文本处理逻辑
        
        return processed_text
    
    def _get_language_from_voice(self, voice_name: str) -> str:
        """
        从语音名称提取语言代码
        
        Args:
            voice_name: 语音名称 (如: en-US-AriaNeural)
            
        Returns:
            语言代码 (如: en-US)
        """
        parts = voice_name.split('-')
        if len(parts) >= 2:
            return f"{parts[0]}-{parts[1]}"
        return "en-US"  # 默认
    
    def estimate_speech_duration(self, text: str, language: str, speech_rate: float = 1.0) -> float:
        """
        估算语音时长 - 更精确的估算算法
        
        Args:
            text: 文本内容
            language: 语言代码
            speech_rate: 语速倍率
            
        Returns:
            估算的时长（秒）
        """
        # 不同语言的基础朗读速度（字符/秒）
        base_rates = {
            'en': 12.5,   # 英语
            'es': 11.0,   # 西班牙语
            'fr': 11.8,   # 法语
            'de': 10.5,   # 德语
            'ja': 7.5,    # 日语
            'ko': 8.5,    # 韩语
            'zh': 6.8     # 中文
        }
        
        base_rate = base_rates.get(language, 11.0)
        char_count = len(text)
        
        # 基础时间计算
        base_time = char_count / base_rate
        
        # 考虑标点符号停顿
        pause_chars = '.!?。！？'
        major_pause_count = sum(1 for char in text if char in pause_chars)
        minor_pause_chars = ',;，；:'
        minor_pause_count = sum(1 for char in text if char in minor_pause_chars)
        
        pause_time = major_pause_count * 0.3 + minor_pause_count * 0.15
        
        # 应用语速调整
        total_time = (base_time + pause_time) / speech_rate
        
        # 添加起始和结束缓冲
        buffer_time = 0.2
        
        return total_time + buffer_time
    
    def _create_silence_segment(self, segment: Dict[str, Any]) -> Dict[str, Any]:
        """
        创建静音片段
        
        Args:
            segment: 原始片段信息
            
        Returns:
            静音音频片段
        """
        duration_ms = int(segment.get('duration', 1.0) * 1000)
        silence = AudioSegment.silent(duration=duration_ms)
        
        return {
            'id': segment['id'],
            'start': segment['start'],
            'end': segment['end'],
            'original_text': segment.get('original_text', ''),
            'translated_text': segment.get('translated_text', ''),
            'audio_data': silence,
            'duration': segment.get('duration', 0)
        }
    
    def get_current_key_info(self) -> dict:
        """
        获取当前使用的key信息
        
        Returns:
            包含当前key信息的字典
        """
        current_key = self.api_key_1 if self.current_key_index == 0 else self.api_key_2
        return {
            'current_key_index': self.current_key_index,
            'current_key': current_key[:8] + '...' if current_key else None,
            'has_backup_key': bool(self.api_key_2 if self.current_key_index == 0 else self.api_key_1),
            'region': self.region,
            'endpoint': self.endpoint
        }
    
    def test_voice_synthesis(self, text: str = "这是一个测试", voice_name: str = None) -> bool:
        """
        测试语音合成功能，支持故障切换
        
        Args:
            text: 测试文本
            voice_name: 语音名称
            
        Returns:
            测试是否成功
        """
        try:
            if not voice_name:
                voice_name = list(self.voice_map.values())[0]
            
            # 显示当前使用的key信息
            key_info = self.get_current_key_info()
            logger.info(f"当前使用key {key_info['current_key_index'] + 1}: {key_info['current_key']}")
            
            # 使用基础语速进行测试
            test_audio = self._generate_single_audio(text, voice_name, 1.0)
            
            logger.info(f"语音合成测试成功 - 时长: {len(test_audio)/1000:.2f}s")
            return True
                
        except Exception as e:
            logger.error(f"语音合成测试失败: {str(e)}")
            return False
    
    def get_available_voices(self, language: str = None) -> List[str]:
        """
        获取可用的语音列表
        
        Args:
            language: 语言代码（可选）
            
        Returns:
            可用语音列表
        """
        if language:
            return [voice for lang, voice in self.voice_map.items() if lang == language]
        else:
            return list(self.voice_map.values())
    
    def get_optimal_rate_for_language(self, language: str, base_rate: float = 1.0) -> float:
        """
        获取语言的最优语速
        
        Args:
            language: 语言代码
            base_rate: 基础语速
            
        Returns:
            最优语速
        """
        # 获取语言特定的调整，如果没有则使用默认值
        rate_offset = self.language_specific_adjustments.get(language, {}).get('rate_offset', 0)
        
        optimal_rate = base_rate + rate_offset
        # 确保在合理范围内：0.8 - 1.15
        return max(0.8, min(1.15, optimal_rate))
    
    def create_synthesis_report(self, segments: List[Dict[str, Any]]) -> str:
        """
        创建语音合成报告
        
        Args:
            segments: 处理过的片段列表
            
        Returns:
            报告文本
        """
        if not segments:
            return "无音频片段数据"
        
        total_segments = len(segments)
        total_duration = sum(seg.get('actual_duration', seg.get('duration', 0)) for seg in segments)
        
        # 统计语速分布（优化：一次遍历收集所有需要的数据）
        speeds = []
        quality_counts = {'excellent': 0, 'good': 0, 'short_text': 0, 'long_text': 0, 'fallback': 0}
        
        for seg in segments:
            speed = seg.get('final_speed', 1.0)
            speeds.append(speed)
            
            quality = seg.get('sync_quality', 'unknown')
            if quality in quality_counts:
                quality_counts[quality] += 1
        
        # 计算速度统计
        avg_speed = sum(speeds) / len(speeds)
        min_speed = min(speeds)
        max_speed = max(speeds)
        
        # 语速分布统计（新的范围：0.95-1.15）
        speed_distribution = {
            '0.95-1.00': sum(1 for s in speeds if 0.95 <= s < 1.00),
            '1.00-1.05': sum(1 for s in speeds if 1.00 <= s < 1.05),
            '1.05-1.10': sum(1 for s in speeds if 1.05 <= s < 1.10),
            '1.10-1.15': sum(1 for s in speeds if 1.10 <= s <= 1.15)
        }
        
        report = f"""Azure TTS语音合成报告
========================

基本信息:
  - 总片段数: {total_segments}
  - 总音频时长: {total_duration:.1f}秒
  - 平均语速: {avg_speed:.3f}
  - 语速范围: {min_speed:.3f} - {max_speed:.3f}

质量分析:
  - 优秀片段: {quality_counts['excellent']} ({quality_counts['excellent']/total_segments*100:.1f}%)
  - 良好片段: {quality_counts['good']} ({quality_counts['good']/total_segments*100:.1f}%)
  - 短文本片段: {quality_counts['short_text']} ({quality_counts['short_text']/total_segments*100:.1f}%)
  - 长文本片段: {quality_counts['long_text']} ({quality_counts['long_text']/total_segments*100:.1f}%)
  - 兜底片段: {quality_counts['fallback']} ({quality_counts['fallback']/total_segments*100:.1f}%)

语速分布:
  - 0.95-1.00: {speed_distribution['0.95-1.00']} 片段
  - 1.00-1.05: {speed_distribution['1.00-1.05']} 片段
  - 1.05-1.10: {speed_distribution['1.05-1.10']} 片段
  - 1.10-1.15: {speed_distribution['1.10-1.15']} 片段
"""
        
        return report

    def _wait_for_rate_limit(self):
        """
        等待满足请求频率限制
        """
        with self.request_lock:
            current_time = datetime.now()
            
            # 重置分钟计数器
            if current_time - self.rate_limit_reset_time >= timedelta(minutes=1):
                self.request_count = 0
                self.rate_limit_reset_time = current_time
            
            # 检查是否达到每分钟请求限制
            if self.request_count >= self.max_requests_per_minute:
                wait_time = 60 - (current_time - self.rate_limit_reset_time).seconds
                if wait_time > 0:
                    logger.warning(f"达到每分钟请求限制，等待 {wait_time} 秒...")
                    time.sleep(wait_time)
                    self.request_count = 0
                    self.rate_limit_reset_time = datetime.now()
            
            # 检查请求间隔
            time_since_last = (current_time - self.last_request_time).total_seconds()
            if time_since_last < self.min_request_interval:
                wait_time = self.min_request_interval - time_since_last
                time.sleep(wait_time)
            
            # 检查是否在错误冷却期
            if (self.last_error_time and 
                self.consecutive_errors >= self.max_consecutive_errors):
                cooldown_elapsed = (current_time - self.last_error_time).total_seconds()
                if cooldown_elapsed < self.error_cooldown_time:
                    wait_time = self.error_cooldown_time - cooldown_elapsed
                    logger.warning(f"错误冷却期，等待 {wait_time:.1f} 秒...")
                    time.sleep(wait_time)
                    self.consecutive_errors = 0
            
            self.last_request_time = datetime.now()
            self.request_count += 1
    
    def _record_error(self):
        """
        记录错误发生
        """
        self.consecutive_errors += 1
        self.last_error_time = datetime.now()
        logger.debug(f"连续错误次数: {self.consecutive_errors}")
    
    def _handle_rate_limit_error(self, attempt: int, max_retries: int):
        """
        处理429限流错误
        """
        base_wait = 2 ** attempt  # 指数退避
        jitter = 0.1 * base_wait  # 添加随机性
        wait_time = base_wait + jitter
        
        logger.warning(f"遇到429错误，等待 {wait_time:.1f} 秒后重试 (第{attempt + 1}/{max_retries}次)")
        time.sleep(wait_time)
    
    def _handle_timeout_error(self, attempt: int, max_retries: int):
        """
        处理超时错误
        """
        wait_time = 1.0 + (attempt * 0.5)  # 渐进式等待
        logger.warning(f"遇到超时错误，等待 {wait_time:.1f} 秒后重试 (第{attempt + 1}/{max_retries}次)")
        time.sleep(wait_time) 