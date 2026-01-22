"""
ElevenLabs TTS模块 - 高品质多语言语音合成
使用ElevenLabs Text-to-Speech API进行语音合成，支持多种音色和语言
"""

import requests
from typing import List, Dict, Any, Optional, Tuple
from loguru import logger
import tempfile
import os
from pydub import AudioSegment
import io
import time
import threading
from datetime import datetime, timedelta


class ElevenLabsTTS:
    """ElevenLabs TTS语音合成器"""
    
    def __init__(self, config: dict):
        """
        初始化ElevenLabs TTS
        
        Args:
            config: 配置字典
        """
        self.config = config
        api_keys = config.get('api_keys', {})
        
        # 获取ElevenLabs API配置
        self.api_key = api_keys.get('elevenlabs_api_key')
        self.base_url = api_keys.get('elevenlabs_base_url', 'https://api.elevenlabs.io/v1')
        
        if not self.api_key:
            raise ValueError("未配置ElevenLabs API密钥，请在config.yaml中设置elevenlabs_api_key")
        
        self.tts_config = config.get('tts', {})
        elevenlabs_config = self.tts_config.get('elevenlabs', {})
        
        # 音色映射 - 从配置文件获取
        self.voice_map = elevenlabs_config.get('voices', {
            'en': {
                "21m00Tcm4TlvDq8ikWAM": "Rachel - 温柔女声",
                "ErXwobaYiN019PkySvjV": "Antoni - 稳重男声",
            },
            'es': {
                "21m00Tcm4TlvDq8ikWAM": "Rachel - Voz femenina suave",
            }
        })
        
        # 默认音色ID（每个语言的第一个音色）
        self.default_voice_ids = {}
        for lang, voices in self.voice_map.items():
            if isinstance(voices, dict) and voices:
                self.default_voice_ids[lang] = list(voices.keys())[0]
        
        # 当前选择的音色（可通过UI更新）
        self.current_voice_id = None
        
        # ElevenLabs特有参数
        self.model_id = elevenlabs_config.get('model_id', 'eleven_multilingual_v2')
        self.stability = elevenlabs_config.get('stability', 0.5)
        self.similarity_boost = elevenlabs_config.get('similarity_boost', 0.75)
        self.style = elevenlabs_config.get('style', 0.0)
        self.use_speaker_boost = elevenlabs_config.get('use_speaker_boost', True)
        
        # 基础语音参数
        self.base_speech_rate = self.tts_config.get('speech_rate', 1.0)
        self.pitch = self.tts_config.get('pitch', 0)
        self.volume = self.tts_config.get('volume', 1.0)
        
        # 停顿时长配置（与MiniMax保持一致）
        pause_config = elevenlabs_config.get('pause_settings', {})
        self.major_pause_duration = pause_config.get('major_pause_duration', 0.35)
        self.minor_pause_duration = pause_config.get('minor_pause_duration', 0.18)
        self.custom_pause_multiplier = pause_config.get('pause_multiplier', 1.0)
        
        # 请求频率控制
        self.request_lock = threading.Lock()
        self.last_request_time = datetime.now()
        self.min_request_interval = 0.3  # ElevenLabs请求间隔
        self.request_count = 0
        self.rate_limit_reset_time = datetime.now()
        self.max_requests_per_minute = 60  # ElevenLabs限制
        
        # 并发控制
        self.concurrent_requests = 0
        self.max_concurrent_requests = 5
        
        # 错误恢复
        self.consecutive_errors = 0
        self.max_consecutive_errors = 3
        self.error_cooldown_time = 5
        self.last_error_time = None
        
        # 成本跟踪
        self.api_call_count = 0
        self.total_characters = 0
        self.cost_per_character = 0.00003  # ElevenLabs定价估算
        self.session_start_time = datetime.now()
        
        # 动态校准
        self._calibration_factors: Dict[str, Dict[str, float]] = {}
        
        logger.info(f"ElevenLabs TTS初始化完成，模型: {self.model_id}")
    
    def set_voice(self, voice_id: str):
        """
        设置当前使用的音色
        
        Args:
            voice_id: 音色ID
        """
        self.current_voice_id = voice_id
        logger.debug(f"已设置ElevenLabs音色: {voice_id}")
    
    def get_voice_id(self, language: str) -> str:
        """
        获取指定语言的音色ID
        
        Args:
            language: 语言代码
            
        Returns:
            音色ID
        """
        # 如果已设置当前音色，优先使用
        if self.current_voice_id:
            return self.current_voice_id
        
        # 否则使用语言的默认音色
        return self.default_voice_ids.get(language, "21m00Tcm4TlvDq8ikWAM")
    
    def get_available_voices(self, language: Optional[str] = None) -> Dict[str, str]:
        """
        获取可用的语音列表
        
        Args:
            language: 语言代码（可选）
            
        Returns:
            音色字典 {voice_id: voice_name}
        """
        if language and language in self.voice_map:
            voices = self.voice_map[language]
            if isinstance(voices, dict):
                return voices
        
        # 返回所有语言的音色
        all_voices = {}
        for lang_voices in self.voice_map.values():
            if isinstance(lang_voices, dict):
                all_voices.update(lang_voices)
        return all_voices
    
    def generate_audio_segments(self, segments: List[Dict[str, Any]], target_language: str) -> List[Dict[str, Any]]:
        """
        生成音频片段（并发版本）
        
        Args:
            segments: 翻译后的片段列表
            target_language: 目标语言代码
            
        Returns:
            包含音频数据的片段列表
        """
        try:
            logger.info(f"ElevenLabs开始并发生成 {len(segments)} 个音频片段")
            
            voice_id = self.get_voice_id(target_language)
            if not voice_id:
                raise ValueError(f"未找到语言 {target_language} 的音色配置")
            
            return self._generate_audio_segments_concurrent(segments, voice_id)
            
        except Exception as e:
            logger.error(f"ElevenLabs生成音频片段失败: {str(e)}")
            raise
    
    def _generate_audio_segments_concurrent(self, segments: List[Dict[str, Any]], voice_id: str) -> List[Dict[str, Any]]:
        """并发生成音频片段"""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        
        max_workers = min(self.max_concurrent_requests, len(segments), 5)
        results_lock = threading.Lock()
        completed_count = 0
        
        logger.info(f"ElevenLabs启动并发音频生成: {max_workers}个worker处理{len(segments)}个片段")
        
        def generate_single_segment(segment: Dict, index: int) -> Tuple[int, Dict]:
            try:
                audio_data = self._generate_single_audio(
                    segment['translated_text'],
                    voice_id,
                    self.base_speech_rate,
                    segment.get('duration', 0)
                )
                
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
                logger.error(f"ElevenLabs生成片段 {segment['id']} 音频失败: {str(e)}")
                audio_segment = self._create_silence_segment(segment)
                return index, audio_segment
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_index = {
                executor.submit(generate_single_segment, segment, i): i
                for i, segment in enumerate(segments)
            }
            
            indexed_results = {}
            for future in as_completed(future_to_index):
                index = future_to_index[future]
                try:
                    result_index, audio_segment = future.result()
                    indexed_results[result_index] = audio_segment
                    
                    with results_lock:
                        completed_count += 1
                        logger.info(f"ElevenLabs音频生成进度: {completed_count}/{len(segments)}")
                        
                except Exception as e:
                    logger.error(f"获取ElevenLabs并发结果异常 {index}: {e}")
                    error_segment = self._create_silence_segment(segments[index])
                    indexed_results[index] = error_segment
            
            audio_segments = [indexed_results[i] for i in range(len(segments))]
        
        success_count = len([seg for seg in audio_segments if seg.get('audio_data') is not None])
        logger.info(f"ElevenLabs并发音频生成完成: {success_count}/{len(segments)} 成功")
        
        return audio_segments
    
    def _generate_single_audio(self, text: str, voice_id: str, 
                              speech_rate: Optional[float] = None,
                              target_duration: Optional[float] = None) -> AudioSegment:
        """
        生成单个音频片段
        
        Args:
            text: 文本内容
            voice_id: 语音ID
            speech_rate: 语速倍率（ElevenLabs不直接支持，通过后处理实现）
            target_duration: 目标时长
            
        Returns:
            音频片段对象
        """
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                self._wait_for_rate_limit()
                self._track_api_call(text)
                
                # 构建请求
                url = f"{self.base_url}/text-to-speech/{voice_id}"
                
                headers = {
                    "Accept": "audio/mpeg",
                    "Content-Type": "application/json",
                    "xi-api-key": self.api_key
                }
                
                payload = {
                    "text": text,
                    "model_id": self.model_id,
                    "voice_settings": {
                        "stability": self.stability,
                        "similarity_boost": self.similarity_boost,
                        "style": self.style,
                        "use_speaker_boost": self.use_speaker_boost
                    }
                }
                
                response = requests.post(url, json=payload, headers=headers, timeout=30)
                
                if response.status_code == 200:
                    self.consecutive_errors = 0
                    self.last_error_time = None
                    self._release_rate_limit()
                    
                    # 直接获取音频数据
                    audio_data = response.content
                    
                    if not audio_data or len(audio_data) == 0:
                        raise Exception("收到的音频数据为空")
                    
                    # 转换为AudioSegment
                    audio_io = io.BytesIO(audio_data)
                    audio_segment = AudioSegment.from_mp3(audio_io)
                    
                    # 如果需要调整语速
                    effective_rate = speech_rate if speech_rate is not None else self.base_speech_rate
                    if effective_rate != 1.0:
                        # 通过改变采样率来调整语速
                        new_frame_rate = int(audio_segment.frame_rate * effective_rate)
                        audio_segment = audio_segment._spawn(
                            audio_segment.raw_data,
                            overrides={'frame_rate': new_frame_rate}
                        ).set_frame_rate(audio_segment.frame_rate)
                    
                    actual_duration = len(audio_segment) / 1000.0
                    logger.debug(f"ElevenLabs音频生成成功 - 语速: {effective_rate:.3f}, 时长: {actual_duration:.2f}s")
                    
                    return audio_segment
                    
                else:
                    error_msg = f"ElevenLabs TTS请求失败: {response.status_code} - {response.text}"
                    logger.error(error_msg)
                    
                    if response.status_code == 429:
                        self._handle_rate_limit_error(attempt, max_retries)
                        if attempt < max_retries - 1:
                            continue
                    
                    self._record_error()
                    self._release_rate_limit()
                    raise Exception(error_msg)
                    
            except Exception as e:
                self._record_error()
                self._release_rate_limit()
                error_msg = f"ElevenLabs生成音频失败 (第{attempt + 1}次尝试): {str(e)}"
                logger.error(error_msg)
                
                error_str = str(e).lower()
                if '429' in error_str or 'too many requests' in error_str:
                    self._handle_rate_limit_error(attempt, max_retries)
                    if attempt < max_retries - 1:
                        continue
                
                if attempt == max_retries - 1:
                    raise Exception(f"所有重试都失败: {error_msg}")
        
        raise Exception("ElevenLabs TTS音频生成失败")
    
    def estimate_speech_duration(self, text: str, language: str, speech_rate: float = 1.0) -> float:
        """估算语音时长"""
        base_rates = {
            'en': 12.5,
            'es': 11.0,
            'fr': 11.8,
            'de': 10.5,
            'ja': 7.5,
            'ko': 8.5,
            'zh': 6.8
        }
        
        base_rate = base_rates.get(language, 11.0)
        char_count = len(text)
        base_time = char_count / base_rate
        
        pause_chars = '.!?。！？'
        major_pause_count = sum(1 for char in text if char in pause_chars)
        minor_pause_chars = ',;，；:'
        minor_pause_count = sum(1 for char in text if char in minor_pause_chars)
        
        pause_time = (major_pause_count * self.major_pause_duration + 
                      minor_pause_count * self.minor_pause_duration) * self.custom_pause_multiplier
        
        total_time = (base_time + pause_time) / speech_rate
        buffer_time = 0.2
        
        return total_time + buffer_time
    
    def estimate_audio_duration_optimized(self, text: str, language: str, speech_rate: float = 1.0) -> float:
        """优化的语音时长估算"""
        language_params = {
            'en': {'words_per_second': 2.5, 'pause_weight': 1.0, 'overhead': 0.15},
            'es': {'words_per_second': 2.3, 'pause_weight': 1.1, 'overhead': 0.16},
            'fr': {'words_per_second': 2.4, 'pause_weight': 1.0, 'overhead': 0.15},
            'de': {'words_per_second': 2.2, 'pause_weight': 1.2, 'overhead': 0.18},
            'zh': {'words_per_second': 2.0, 'pause_weight': 0.9, 'overhead': 0.13},
            'ja': {'words_per_second': 1.8, 'pause_weight': 0.9, 'overhead': 0.12},
            'ko': {'words_per_second': 1.9, 'pause_weight': 0.95, 'overhead': 0.14}
        }
        
        lang_params = language_params.get(language, language_params['en'])
        words = text.split()
        word_count = len(words)
        base_time = word_count / lang_params['words_per_second']
        
        major_pauses = text.count('.') + text.count('!') + text.count('?') + \
                      text.count('。') + text.count('！') + text.count('？')
        minor_pauses = text.count(',') + text.count(';') + text.count(':') + \
                      text.count('，') + text.count('；') + text.count('：')
        
        pause_time = ((major_pauses * self.major_pause_duration + 
                       minor_pauses * self.minor_pause_duration) * 
                      self.custom_pause_multiplier * lang_params['pause_weight'])
        
        adjusted_time = (base_time + pause_time) / speech_rate
        total_time = adjusted_time + lang_params['overhead']
        buffer_time = 0.2
        
        estimated_duration = total_time + buffer_time
        calibration = self._calibration_factors.get(language, {}).get('factor', 1.0)
        estimated_duration *= calibration
        
        return estimated_duration
    
    def estimate_optimal_speech_rate(self, text: str, language: str, target_duration: float,
                                   min_rate: float = 0.5, max_rate: float = 2.0) -> float:
        """估算达到目标时长所需的最优语速"""
        base_duration = self.estimate_audio_duration_optimized(text, language, 1.0)
        required_rate = base_duration / target_duration
        optimal_rate = max(min_rate, min(required_rate, max_rate))
        return optimal_rate
    
    def _create_silence_segment(self, segment: Dict[str, Any]) -> Dict[str, Any]:
        """创建静音片段"""
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
    
    def test_voice_synthesis(self, text: str = "Hello, this is a test.", voice_id: Optional[str] = None) -> bool:
        """测试语音合成功能"""
        try:
            if not voice_id:
                voice_id = self.default_voice_ids.get('en', "21m00Tcm4TlvDq8ikWAM")
            
            logger.info(f"开始测试ElevenLabs TTS - 语音ID: {voice_id}")
            test_audio = self._generate_single_audio(text, voice_id, 1.0)
            logger.info(f"ElevenLabs语音合成测试成功 - 时长: {len(test_audio)/1000:.2f}s")
            return True
                
        except Exception as e:
            logger.error(f"ElevenLabs语音合成测试失败: {str(e)}")
            return False
    
    def synthesize_speech_optimized(self, text: str, language: str, speech_rate: float, file_prefix: str = "tts_segment") -> str:
        """
        兼容sync_manager的音频合成方法
        
        Args:
            text: 合成文本
            language: 目标语言代码
            speech_rate: 语速倍率
            file_prefix: 文件名前缀
            
        Returns:
            生成的音频文件路径
        """
        voice_id = self.get_voice_id(language)
        if not voice_id:
            raise ValueError(f"未配置语言 {language} 的voice")
        
        audio_segment = self._generate_single_audio(text, voice_id, speech_rate)
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3", prefix=file_prefix + "_") as f:
            audio_segment.export(f.name, format="mp3", bitrate="128k")
            file_path = f.name
        
        return file_path
    
    def get_audio_duration(self, audio_file_path: str) -> float:
        """获取音频文件的时长"""
        try:
            # 根据文件扩展名自动选择格式
            if audio_file_path.endswith('.mp3'):
                audio = AudioSegment.from_mp3(audio_file_path)
            elif audio_file_path.endswith('.wav'):
                audio = AudioSegment.from_wav(audio_file_path)
            else:
                audio = AudioSegment.from_file(audio_file_path)
            duration_seconds = len(audio) / 1000.0
            return duration_seconds
        except Exception as e:
            logger.error(f"获取音频时长失败: {e}")
            return 0.0
    
    def _track_api_call(self, text: str):
        """跟踪API调用"""
        self.api_call_count += 1
        self.total_characters += len(text)
        logger.debug(f"ElevenLabs API调用统计: 第{self.api_call_count}次调用, 累计字符数: {self.total_characters}")
    
    def get_cost_summary(self) -> Dict[str, Any]:
        """获取成本摘要"""
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
        """打印成本报告"""
        summary = self.get_cost_summary()
        
        print("\n" + "="*60)
        print("🔥 ELEVENLABS TTS 成本报告")
        print("="*60)
        print(f"📊 API调用次数: {summary['api_calls']}")
        print(f"📝 总字符数: {summary['total_characters']:,}")
        print(f"💰 估计成本: ${summary['estimated_cost_usd']:.4f}")
        print(f"⏱️  会话时长: {summary['session_duration_seconds']:.1f}秒")
        print("="*60 + "\n")
    
    def _wait_for_rate_limit(self):
        """等待满足请求频率限制"""
        with self.request_lock:
            current_time = datetime.now()
            
            while self.concurrent_requests >= self.max_concurrent_requests:
                logger.debug(f"达到最大并发数({self.max_concurrent_requests})，等待...")
                time.sleep(0.1)
                current_time = datetime.now()
            
            if current_time - self.rate_limit_reset_time >= timedelta(minutes=1):
                self.request_count = 0
                self.rate_limit_reset_time = current_time
            
            if self.request_count >= self.max_requests_per_minute:
                wait_time = 60 - (current_time - self.rate_limit_reset_time).seconds
                if wait_time > 0:
                    logger.warning(f"达到每分钟请求限制，等待 {wait_time} 秒...")
                    time.sleep(wait_time)
                    self.request_count = 0
                    self.rate_limit_reset_time = datetime.now()
            
            time_since_last = (current_time - self.last_request_time).total_seconds()
            if time_since_last < self.min_request_interval:
                time.sleep(self.min_request_interval - time_since_last)
            
            if (self.last_error_time and 
                self.consecutive_errors >= self.max_consecutive_errors):
                cooldown_elapsed = (current_time - self.last_error_time).total_seconds()
                if cooldown_elapsed < self.error_cooldown_time:
                    wait_time = self.error_cooldown_time - cooldown_elapsed
                    logger.warning(f"错误冷却期，等待 {wait_time:.1f} 秒...")
                    time.sleep(wait_time)
                    self.consecutive_errors = 0
            
            self.concurrent_requests += 1
            self.last_request_time = datetime.now()
            self.request_count += 1
    
    def _release_rate_limit(self):
        """释放并发计数"""
        with self.request_lock:
            self.concurrent_requests = max(0, self.concurrent_requests - 1)
    
    def _record_error(self):
        """记录错误"""
        self.consecutive_errors += 1
        self.last_error_time = datetime.now()
    
    def _handle_rate_limit_error(self, attempt: int, max_retries: int):
        """处理429限流错误"""
        base_wait = 2 ** attempt
        jitter = 0.1 * base_wait
        wait_time = base_wait + jitter
        logger.warning(f"ElevenLabs遇到429错误，等待 {wait_time:.1f} 秒后重试")
        time.sleep(wait_time)
    
    def update_calibration(self, language: str, estimated_duration: float, actual_duration: float):
        """更新校准因子"""
        try:
            if estimated_duration <= 0 or actual_duration <= 0:
                return
            
            factor = actual_duration / estimated_duration
            entry = self._calibration_factors.get(language)
            
            if entry is None:
                entry = {'factor': factor, 'samples': 1}
            else:
                alpha = 0.3
                entry['factor'] = entry['factor'] * (1 - alpha) + factor * alpha
                entry['samples'] += 1
            
            self._calibration_factors[language] = entry
            logger.debug(f"ElevenLabs更新校准因子: {language} -> {entry['factor']:.3f}")
        except Exception as e:
            logger.warning(f"更新校准因子失败: {str(e)}")
    
    def get_calibration_factor(self, language: str) -> float:
        """获取校准因子"""
        return self._calibration_factors.get(language, {}).get('factor', 1.0)
    
    def create_synthesis_report(self, segments: List[Dict[str, Any]]) -> str:
        """创建语音合成报告"""
        if not segments:
            return "无音频片段数据"
        
        total_segments = len(segments)
        total_duration = sum(seg.get('actual_duration', seg.get('duration', 0)) for seg in segments)
        
        report = f"""ElevenLabs TTS语音合成报告
========================

基本信息:
  - 总片段数: {total_segments}
  - 总音频时长: {total_duration:.1f}秒
  - 使用模型: {self.model_id}
  - 稳定性: {self.stability}
  - 相似度增强: {self.similarity_boost}
"""
        
        return report

