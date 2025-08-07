"""
Azure TTS模块 - 支持循环逼近算法的精确语速控制
使用Azure Speech Services进行多语言语音合成，支持SSML层面的语速微调
"""

import azure.cognitiveservices.speech as speechsdk
from typing import List, Dict, Any, Optional, Tuple
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
        
        # 请求频率控制 - 针对并发优化的参数
        self.request_lock = threading.Lock()
        self.last_request_time = datetime.now()
        self.min_request_interval = 0.15  # 每个请求之间最小间隔150ms（为并发优化）
        self.request_count = 0
        self.rate_limit_reset_time = datetime.now()
        self.max_requests_per_minute = 120  # 每分钟最大请求数（为并发控制更保守）
        
        # 并发控制相关
        self.concurrent_requests = 0  # 当前并发请求数
        self.max_concurrent_requests = 8  # 最大并发请求数
        
        # 错误恢复相关
        self.consecutive_errors = 0
        self.max_consecutive_errors = 3
        self.error_cooldown_time = 5  # 连续错误后的冷却时间（秒）
        self.last_error_time = None
        
        # 成本跟踪
        self.api_call_count = 0
        self.total_characters = 0
        self.cost_per_character = 0.000015  # Azure TTS定价（约$15/1M字符）
        self.session_start_time = datetime.now()
        
        # 循环逼近相关参数
        self.language_specific_adjustments = {
            'en': {'rate_offset': 0.08},    # 英语稍快
            'es': {'rate_offset': 0.06},    # 西班牙语中等调整
            'fr': {'rate_offset': 0.10},    # 法语快一点
            'de': {'rate_offset': 0.05},    # 德语较稳重
            'ja': {'rate_offset': 0.02},    # 日语较慢
            'ko': {'rate_offset': 0.04}     # 韩语中等调整
        }

        # === 动态校准相关 ===
        # 记录各语言的估算校准因子（actual / estimated）及样本数量
        # 通过滑动平均逐步提升估算精度，进而减少TTS调用次数
        self._calibration_factors: Dict[str, Dict[str, float]] = {}
    
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
        
        # 设置超时参数以解决解码器启动超时问题
        config.set_property(speechsdk.PropertyId.SpeechServiceConnection_InitialSilenceTimeoutMs, "15000")  # 15秒初始静音超时
        config.set_property(speechsdk.PropertyId.SpeechServiceConnection_EndSilenceTimeoutMs, "8000")  # 8秒结束静音超时
        config.set_property(speechsdk.PropertyId.SpeechServiceConnection_InitialSilenceTimeoutMs, "15000")  # 15秒连接超时
        config.set_property(speechsdk.PropertyId.SpeechServiceConnection_EndSilenceTimeoutMs, "8000")  # 8秒结束超时
        
        # 设置更保守的连接参数以减少解码器超时
        config.set_property(speechsdk.PropertyId.Speech_LogFilename, "")  # 禁用日志文件
        config.set_property(speechsdk.PropertyId.SpeechServiceConnection_RecoMode, "INTERACTIVE")  # 使用交互模式
        
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
        生成音频片段（并发版本，提高效率）
        
        Args:
            segments: 翻译后的片段列表
            target_language: 目标语言代码
            
        Returns:
            包含音频数据的片段列表
        """
        try:
            logger.info(f"开始并发生成 {len(segments)} 个音频片段")
            
            # 获取对应语言的语音
            voice_name = self.voice_map.get(target_language)
            if not voice_name:
                raise ValueError(f"不支持的语言: {target_language}")
            
            return self._generate_audio_segments_concurrent(segments, voice_name)
            
        except Exception as e:
            logger.error(f"生成音频片段失败: {str(e)}")
            raise
    
    def _generate_audio_segments_concurrent(self, segments: List[Dict[str, Any]], voice_name: str) -> List[Dict[str, Any]]:
        """
        并发生成音频片段
        
        Args:
            segments: 片段列表
            voice_name: 语音名称
            
        Returns:
            音频片段列表
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import threading
        
        # 控制并发数，考虑API限制
        max_workers = min(6, len(segments), max(2, len(segments) // 4))
        
        results_lock = threading.Lock()
        completed_count = 0
        
        logger.info(f"启动并发音频生成: {max_workers}个worker处理{len(segments)}个片段")
        
        def generate_single_segment(segment: Dict, index: int) -> Tuple[int, Dict]:
            """生成单个片段的音频"""
            try:
                # 使用默认语速生成
                audio_data = self._generate_single_audio(
                    segment['translated_text'],
                    voice_name,
                    self.base_speech_rate,
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
                
                return index, audio_segment
                
            except Exception as e:
                logger.error(f"并发生成片段 {segment['id']} 音频失败: {str(e)}")
                # 创建静音片段作为备选
                audio_segment = self._create_silence_segment(segment)
                return index, audio_segment
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 提交所有任务
            future_to_index = {
                executor.submit(generate_single_segment, segment, i): i
                for i, segment in enumerate(segments)
            }
            
            # 收集结果
            indexed_results = {}
            for future in as_completed(future_to_index):
                index = future_to_index[future]
                try:
                    result_index, audio_segment = future.result()
                    indexed_results[result_index] = audio_segment
                    
                    # 线程安全的进度报告
                    with results_lock:
                        completed_count += 1
                        logger.info(f"音频生成进度: {completed_count}/{len(segments)}")
                        
                except Exception as e:
                    logger.error(f"获取并发结果异常 {index}: {e}")
                    # 创建错误片段
                    error_segment = self._create_silence_segment(segments[index])
                    indexed_results[index] = error_segment
            
            # 按原始顺序组织结果
            audio_segments = [indexed_results[i] for i in range(len(segments))]
        
        success_count = len([seg for seg in audio_segments if seg.get('audio_data') is not None])
        logger.info(f"并发音频生成完成: {success_count}/{len(segments)} 成功")
        
        return audio_segments
    
    def _generate_single_audio(self, text: str, voice_name: str, 
                              speech_rate: Optional[float] = None, 
                              target_duration: Optional[float] = None) -> AudioSegment:
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
                
                # 跟踪API调用
                self._track_api_call(text)
                
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
                
                if result is None:
                    raise Exception("语音合成返回空结果")
                
                if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
                    # 成功，重置错误计数
                    self.consecutive_errors = 0
                    self.last_error_time = None
                    
                    # 释放并发计数
                    self._release_rate_limit()
                    
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
                        
                        # 超时错误和解码器启动错误
                        elif 'timeout' in error_str or 'codec decoding' in error_str:
                            self._handle_decoder_timeout_error(attempt, max_retries)
                            if attempt < max_retries - 1:
                                continue
                    
                    self._record_error()
                    # 释放并发计数
                    self._release_rate_limit()
                    raise Exception(error_msg)
                    
            except Exception as e:
                self._record_error()
                # 释放并发计数
                self._release_rate_limit()
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
                
                # 处理超时错误和解码器启动错误
                elif 'timeout' in error_str or 'codec decoding' in error_str:
                    self._handle_decoder_timeout_error(attempt, max_retries)
                    if attempt < max_retries - 1:
                        continue
                
                # 如果是最后一次尝试，抛出异常
                if attempt == max_retries - 1:
                    # 释放并发计数
                    self._release_rate_limit()
                    raise Exception(f"所有重试都失败: {error_msg}")
        
        # 释放并发计数
        self._release_rate_limit()        
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
    
    def estimate_audio_duration_optimized(self, text: str, language: str, speech_rate: float = 1.0) -> float:
        """
        优化的语音时长估算 - 基于单词数和语言特性的精确算法
        用于减少API调用，特别是在循环逼近算法中
        
        Args:
            text: 文本内容
            language: 语言代码
            speech_rate: 语速倍率
            
        Returns:
            估算的时长（秒）
        """
        # 基于实际Azure TTS的语音特性优化的估算参数（基于单词数）
        language_params = {
            'en': {
                'words_per_second': 2.4,  # 英语的实际语速（单词/秒）
                'pause_weight': 1.0,
                'ssml_overhead': 0.15  # SSML处理开销
            },
            'es': {
                'words_per_second': 2.2,
                'pause_weight': 1.1,
                'ssml_overhead': 0.16
            },
            'fr': {
                'words_per_second': 2.3,
                'pause_weight': 1.0,
                'ssml_overhead': 0.15
            },
            'de': {
                'words_per_second': 2.1,
                'pause_weight': 1.2,
                'ssml_overhead': 0.18
            },
            'ja': {
                'words_per_second': 1.8,
                'pause_weight': 0.9,
                'ssml_overhead': 0.12
            },
            'ko': {
                'words_per_second': 1.9,
                'pause_weight': 0.95,
                'ssml_overhead': 0.14
            },
            'zh': {
                'words_per_second': 1.6,
                'pause_weight': 0.85,
                'ssml_overhead': 0.13
            }
        }
        
        # 获取语言参数，默认使用英语
        lang_params = language_params.get(language, language_params['en'])
        
        # 计算单词数（更准确的时长估算）
        words = text.split()
        word_count = len(words)
        char_count = len(text)
        
        # 计算基础时长（基于单词数）
        base_time = word_count / lang_params['words_per_second']
        
        # 计算标点符号造成的停顿时间
        major_pauses = text.count('.') + text.count('!') + text.count('?') + \
                      text.count('。') + text.count('！') + text.count('？')
        minor_pauses = text.count(',') + text.count(';') + text.count(':') + \
                      text.count('，') + text.count('；') + text.count('：')
        
        pause_time = (major_pauses * 0.35 + minor_pauses * 0.18) * lang_params['pause_weight']
        
        # 应用语速调整
        adjusted_time = (base_time + pause_time) / speech_rate
        
        # 添加SSML处理开销
        total_time = adjusted_time + lang_params['ssml_overhead']
        
        # 添加起始缓冲时间
        buffer_time = 0.2
        
        estimated_duration = total_time + buffer_time

        # === 应用动态校准因子 ===
        calibration = self._calibration_factors.get(language, {}).get('factor', 1.0)
        estimated_duration *= calibration

        logger.debug(f"时长估算: 文本={word_count}单词({char_count}字符), 基础={base_time:.2f}s, "
                    f"停顿={pause_time:.2f}s, 语速={speech_rate:.2f}, "
                    f"校准因子={calibration:.3f}, 预估={estimated_duration:.2f}s")
        
        return estimated_duration
    
    def estimate_optimal_speech_rate(self, text: str, language: str, target_duration: float, 
                                   min_rate: float = 0.95, max_rate: float = 1.15) -> float:
        """
        估算达到目标时长所需的最优语速
        
        Args:
            text: 文本内容
            language: 语言代码
            target_duration: 目标时长（秒）
            min_rate: 最小语速
            max_rate: 最大语速
            
        Returns:
            最优语速倍率
        """
        # 使用标准语速估算基础时长
        base_duration = self.estimate_audio_duration_optimized(text, language, 1.0)
        
        # 计算所需语速
        required_rate = base_duration / target_duration
        
        # 限制在允许范围内
        optimal_rate = max(min_rate, min(required_rate, max_rate))
        
        logger.debug(f"语速估算: 基础时长={base_duration:.2f}s, 目标时长={target_duration:.2f}s, "
                    f"所需语速={required_rate:.3f}, 最优语速={optimal_rate:.3f}")
        
        return optimal_rate
    
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
    
    def test_voice_synthesis(self, text: str = "这是一个测试", voice_name: Optional[str] = None) -> bool:
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
            if voice_name is None:
                voice_name = list(self.voice_map.values())[0]
            test_audio = self._generate_single_audio(text, voice_name, 1.0)  # type: ignore
            
            logger.info(f"语音合成测试成功 - 时长: {len(test_audio)/1000:.2f}s")
            return True
                
        except Exception as e:
            logger.error(f"语音合成测试失败: {str(e)}")
            return False
    
    def get_available_voices(self, language: Optional[str] = None) -> List[str]:
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

    def _track_api_call(self, text: str):
        """
        跟踪API调用次数和成本
        
        Args:
            text: 合成的文本
        """
        self.api_call_count += 1
        self.total_characters += len(text)
        logger.debug(f"API调用统计: 第{self.api_call_count}次调用, 累计字符数: {self.total_characters}")
    
    def get_cost_summary(self) -> Dict[str, Any]:
        """
        获取成本摘要
        
        Returns:
            包含成本信息的字典
        """
        elapsed_time = (datetime.now() - self.session_start_time).total_seconds()
        estimated_cost = self.total_characters * self.cost_per_character
        
        return {
            'api_calls': self.api_call_count,
            'total_characters': self.total_characters,
            'estimated_cost_usd': estimated_cost,
            'session_duration_seconds': elapsed_time,
            'avg_calls_per_minute': (self.api_call_count / elapsed_time * 60) if elapsed_time > 0 else 0,
            'avg_characters_per_call': (self.total_characters / self.api_call_count) if self.api_call_count > 0 else 0
        }
    
    def print_cost_report(self):
        """
        打印成本报告
        """
        summary = self.get_cost_summary()
        
        print("\n" + "="*60)
        print("🔥 AZURE TTS 成本报告")
        print("="*60)
        print(f"📊 API调用次数: {summary['api_calls']}")
        print(f"📝 总字符数: {summary['total_characters']:,}")
        print(f"💰 估计成本: ${summary['estimated_cost_usd']:.4f}")
        print(f"⏱️  会话时长: {summary['session_duration_seconds']:.1f}秒")
        print(f"📈 平均调用频率: {summary['avg_calls_per_minute']:.1f}次/分钟")
        print(f"📋 平均字符数/调用: {summary['avg_characters_per_call']:.1f}")
        print("="*60)
        
        # 成本优化建议
        if summary['api_calls'] > 50:
            print("💡 成本优化建议:")
            print("  • 启用成本优化模式可减少60-80%的API调用")
            print("  • 使用估算方法预筛选可避免不必要的API调用")
            print("  • 考虑批量处理较短的文本片段")
        print("="*60 + "\n")

    def _wait_for_rate_limit(self):
        """
        等待满足请求频率限制 - 支持并发控制
        """
        with self.request_lock:
            current_time = datetime.now()
            
            # 检查并发数限制
            while self.concurrent_requests >= self.max_concurrent_requests:
                logger.debug(f"达到最大并发数({self.max_concurrent_requests})，等待...")
                time.sleep(0.05)  # 短暂等待
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
            
            # 检查请求间隔（对并发请求稍微放宽）
            time_since_last = (current_time - self.last_request_time).total_seconds()
            min_interval = self.min_request_interval / max(1, self.concurrent_requests)
            if time_since_last < min_interval:
                wait_time = min_interval - time_since_last
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
            
            # 更新计数器
            self.concurrent_requests += 1
            self.last_request_time = datetime.now()
            self.request_count += 1
    
    def _release_rate_limit(self):
        """
        释放并发计数
        """
        with self.request_lock:
            self.concurrent_requests = max(0, self.concurrent_requests - 1)
    
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
    
    def _handle_decoder_timeout_error(self, attempt: int, max_retries: int):
        """
        处理解码器启动超时错误 - 增强版本
        """
        # 对于解码器启动超时，使用更长的等待时间和更保守的策略
        if attempt == 0:
            # 第一次遇到解码器超时，等待较长时间
            base_wait = 5.0
        elif attempt == 1:
            # 第二次，等待更长时间
            base_wait = 8.0
        else:
            # 后续尝试，使用指数退避
            base_wait = 10.0 + (attempt * 2.0)
        
        jitter = 0.3 * base_wait  # 30%的随机延迟
        wait_time = base_wait + jitter
        
        logger.warning(f"遇到解码器启动超时错误，等待 {wait_time:.1f} 秒后重试 (第{attempt + 1}/{max_retries}次)")
        
        # 在等待期间，尝试清理可能的资源
        try:
            import gc
            gc.collect()  # 强制垃圾回收
        except:
            pass
        
        time.sleep(wait_time) 

    def update_calibration(self, language: str, estimated_duration: float, actual_duration: float):
        """根据一次真实合成结果更新指定语言的校准因子

        Args:
            language: 语言代码 (如 'en')
            estimated_duration: 本次估算的时长（秒）
            actual_duration: 实际合成后的时长（秒）
        """
        try:
            if estimated_duration <= 0 or actual_duration <= 0:
                return

            factor = actual_duration / estimated_duration
            entry = self._calibration_factors.get(language)

            if entry is None:
                entry = {'factor': factor, 'samples': 1}
            else:
                # 指数滑动平均，最近样本权重更高 (alpha = 0.3)
                alpha = 0.3
                entry['factor'] = entry['factor'] * (1 - alpha) + factor * alpha
                entry['samples'] += 1

            self._calibration_factors[language] = entry
            logger.debug(f"更新校准因子: {language} -> {entry['factor']:.3f} (samples={entry['samples']})")
        except Exception as e:
            logger.warning(f"更新校准因子失败: {str(e)}")

    def get_calibration_factor(self, language: str) -> float:
        """获取指定语言的当前校准因子"""
        return self._calibration_factors.get(language, {}).get('factor', 1.0) 

    def synthesize_speech_optimized(self, text: str, language: str, speech_rate: float, file_prefix: str = "tts_segment") -> str:
        """
        兼容sync_manager的音频合成方法，自动选择voice并保存为wav文件，返回文件路径
        Args:
            text: 合成文本
            language: 目标语言代码
            speech_rate: 语速倍率
            file_prefix: 文件名前缀
        Returns:
            生成的音频文件路径
        """
        voice_name = self.voice_map.get(language)
        if not voice_name:
            raise ValueError(f"未配置语言 {language} 的voice")
        audio_segment = self._generate_single_audio(text, voice_name, speech_rate)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav", prefix=file_prefix + "_") as f:
            audio_segment.export(f.name, format="wav")
            file_path = f.name
        return file_path 

    def get_audio_duration(self, audio_file_path: str) -> float:
        """
        获取音频文件的时长
        
        Args:
            audio_file_path: 音频文件路径
            
        Returns:
            音频时长（秒）
        """
        try:
            from pydub import AudioSegment
            audio = AudioSegment.from_wav(audio_file_path)
            duration_seconds = len(audio) / 1000.0
            return duration_seconds
        except Exception as e:
            logger.error(f"获取音频时长失败: {e}")
            return 0.0 