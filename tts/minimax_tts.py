"""
MiniMax TTS模块 - 支持循环逼近算法的精确语速控制
使用MiniMax Speech Services进行多语言语音合成，支持语速微调
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
import base64
import json


class MinimaxTTS:
    """MiniMax TTS语音合成器 - 支持精确语速控制"""
    
    def __init__(self, config: dict):
        """
        初始化MiniMax TTS
        
        Args:
            config: 配置字典
        """
        self.config = config
        api_keys = config.get('api_keys', {})
        
        # 获取MiniMax API配置
        self.api_key = api_keys.get('minimax_api_key')
        self.group_id = api_keys.get('minimax_group_id')
        self.base_url = api_keys.get('minimax_base_url', 'https://api.minimax.chat/v1')
        
        if not self.api_key:
            raise ValueError("未配置MiniMax API密钥")
        
        self.tts_config = config.get('tts', {})
        minimax_config = self.tts_config.get('minimax', {})
        
        # 音色映射 - 从配置文件获取，格式与ElevenLabs保持一致
        # 结构: {language: {voice_id: voice_name}}
        self.voice_map = minimax_config.get('voices', {
            'en': {
                "moss_audio_ef01c4ea-ce7f-11f0-825a-da3ca3ba36b8": "Moss - 英语男声"
            }
        })
        
        # 默认音色ID（每个语言的第一个音色）
        self.default_voice_ids = {}
        for lang, voices in self.voice_map.items():
            if isinstance(voices, dict) and voices:
                self.default_voice_ids[lang] = list(voices.keys())[0]
        
        # 当前选择的音色（可通过UI更新）
        self.current_voice_id = None
        
        # 基础语音参数
        self.base_speech_rate = self.tts_config.get('speech_rate', 1.0)
        self.pitch = self.tts_config.get('pitch', 0)
        # 优先使用 minimax 专属音量配置，否则使用通用音量配置
        self.volume = minimax_config.get('volume', self.tts_config.get('volume', 1.0))
        
        # 停顿时长配置（可在config.yaml中调整）
        pause_config = self.tts_config.get('minimax', {}).get('pause_settings', {})
        self.major_pause_duration = pause_config.get('major_pause_duration', 0.35)  # 句号、问号、感叹号停顿（秒）
        self.minor_pause_duration = pause_config.get('minor_pause_duration', 0.18)  # 逗号、分号、冒号停顿（秒）
        self.custom_pause_multiplier = pause_config.get('pause_multiplier', 1.0)    # 整体停顿倍率调节
        
        # 请求频率控制 - 更保守的设置
        self.request_lock = threading.Lock()
        self.last_request_time = datetime.now()
        self.min_request_interval = 0.5  # 每个请求之间最小间隔500ms（更保守）
        self.request_count = 0
        self.rate_limit_reset_time = datetime.now()
        self.max_requests_per_minute = 40  # 每分钟最大请求数（更保守）
        
        # 并发控制相关 - 降低并发数避免429错误
        self.concurrent_requests = 0  # 当前并发请求数
        self.max_concurrent_requests = 3  # 最大并发请求数（更保守）
        
        # 错误恢复相关
        self.consecutive_errors = 0
        self.max_consecutive_errors = 3
        self.error_cooldown_time = 5  # 连续错误后的冷却时间（秒）
        self.last_error_time = None
        
        # 成本跟踪
        self.api_call_count = 0
        self.total_characters = 0
        self.cost_per_character = 0.00002  # MiniMax TTS定价估算
        self.session_start_time = datetime.now()
        
        # 循环逼近相关参数
        self.language_specific_adjustments = {
            'en': {'rate_offset': 0.08},    # 英语稍快
            'es': {'rate_offset': 0.06},    # 西班牙语中等调整
            'fr': {'rate_offset': 0.10},    # 法语快一点
            'de': {'rate_offset': 0.05},    # 德语较稳重
            'ja': {'rate_offset': 0.02},    # 日语较慢
            'ko': {'rate_offset': 0.04},    # 韩语中等调整
            'zh': {'rate_offset': 0.00}     # 中文标准
        }

        # 动态校准相关
        self._calibration_factors: Dict[str, Dict[str, float]] = {}
        
        logger.info(f"MiniMax TTS初始化完成，基础语速: {self.base_speech_rate}")
    
    def set_voice(self, voice_id: str):
        """
        设置当前使用的音色
        
        Args:
            voice_id: 音色ID
        """
        self.current_voice_id = voice_id
        logger.debug(f"已设置MiniMax音色: {voice_id}")
    
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
        return self.default_voice_ids.get(language, "moss_audio_ef01c4ea-ce7f-11f0-825a-da3ca3ba36b8")
    
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
            logger.info(f"MiniMax开始并发生成 {len(segments)} 个音频片段")
            
            # 获取对应语言的语音
            voice_id = self.get_voice_id(target_language)
            if not voice_id:
                raise ValueError(f"未找到语言 {target_language} 的音色配置")
            
            return self._generate_audio_segments_concurrent(segments, voice_id)
            
        except Exception as e:
            logger.error(f"生成音频片段失败: {str(e)}")
            raise
    
    def _generate_audio_segments_concurrent(self, segments: List[Dict[str, Any]], voice_id: str, use_multi_candidate: bool = False) -> List[Dict[str, Any]]:
        """
        并发生成音频片段
        
        Args:
            segments: 片段列表
            voice_id: 语音ID
            use_multi_candidate: 是否使用多候选策略（首次批量生成默认关闭以节省API调用）
            
        Returns:
            音频片段列表
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import threading
        
        # 控制并发数，考虑API限制 - 更保守的设置
        max_workers = min(self.max_concurrent_requests, len(segments), max(1, len(segments) // 6))
        
        results_lock = threading.Lock()
        completed_count = 0
        
        multi_candidate_info = "（多候选模式）" if use_multi_candidate else "（单次生成）"
        logger.info(f"启动并发音频生成{multi_candidate_info}: {max_workers}个worker处理{len(segments)}个片段")
        
        def generate_single_segment(segment: Dict, index: int) -> Tuple[int, Dict]:
            """生成单个片段的音频"""
            try:
                target_duration = segment.get('duration', 0)
                text = segment['translated_text']
                
                # 如果启用多候选且目标时长>8秒，使用多候选策略
                if use_multi_candidate and target_duration > 8.0:
                    audio_data = self._generate_audio_with_best_match(
                        text,
                        voice_id,
                        self.base_speech_rate,
                        target_duration,
                        num_candidates=3
                    )
                else:
                    # 使用默认语速生成
                    audio_data = self._generate_single_audio(
                        text,
                        voice_id,
                        self.base_speech_rate,
                        target_duration
                    )
                
                # 创建音频片段对象
                audio_segment = {
                    'id': segment['id'],
                    'start': segment['start'],
                    'end': segment['end'],
                    'original_text': segment.get('original_text', ''),
                    'translated_text': segment['translated_text'],
                    'audio_data': audio_data,
                    'duration': segment.get('duration', 0),
                    'multi_candidate_used': use_multi_candidate and target_duration > 1.0
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
    
    def _generate_single_audio(self, text: str, voice_id: str, 
                              speech_rate: Optional[float] = None, 
                              target_duration: Optional[float] = None) -> AudioSegment:
        """
        生成单个音频片段 - 支持精确语速控制
        
        Args:
            text: 文本内容
            voice_id: 语音ID
            speech_rate: 语速倍率 (0.5-2.0)
            target_duration: 目标时长（用于记录，不影响生成）
            
        Returns:
            音频片段对象
        """
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                # 应用请求频率控制
                self._wait_for_rate_limit()
                
                # 跟踪API调用
                self._track_api_call(text)
                
                # 使用传入的语速，或默认语速
                effective_rate = speech_rate if speech_rate is not None else self.base_speech_rate
                
                # 构建请求payload
                payload = self._build_payload(text, voice_id, effective_rate)
                
                # 发送请求
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                }
                
                # 根据官方文档，API端点格式应该是带GroupId参数的
                if not self.group_id:
                    raise ValueError("MiniMax API需要group_id参数")
                url = f"{self.base_url}/t2a_v2?GroupId={self.group_id}"
                
                response = requests.post(url, headers=headers, json=payload, timeout=30)
                
                if response.status_code == 200:
                    # 成功，重置错误计数
                    self.consecutive_errors = 0
                    self.last_error_time = None
                    
                    # 释放并发计数
                    self._release_rate_limit()
                    
                    # 处理响应
                    try:
                        result = response.json()
                        logger.debug(f"MiniMax API响应结构: {list(result.keys())}")
                        
                        # 根据官方示例，检查响应格式
                        # 官方示例直接打印response.text，说明可能有不同的响应格式
                        
                        # 尝试多种可能的响应结构
                        audio_hex = None
                        
                        # 方式1: data.audio 结构
                        if 'data' in result and isinstance(result['data'], dict) and 'audio' in result['data']:
                            audio_hex = result['data']['audio']
                            logger.debug("使用data.audio结构解析音频数据")
                        
                        # 方式2: 直接audio字段
                        elif 'audio' in result:
                            audio_hex = result['audio']
                            logger.debug("使用直接audio字段解析音频数据")
                        
                        # 方式3: base64编码的音频数据
                        elif 'data' in result and 'audio_data' in result['data']:
                            audio_hex = result['data']['audio_data']
                            logger.debug("使用data.audio_data结构解析音频数据")
                        
                        # 如果都没找到，记录完整响应结构用于调试
                        if not audio_hex:
                            logger.error(f"无法找到音频数据，完整响应结构: {result}")
                            raise Exception(f"响应中未找到音频数据，响应结构: {list(result.keys())}")
                        
                        if not audio_hex:
                            raise Exception("音频数据为空")
                        
                        logger.debug(f"收到音频数据长度: {len(audio_hex)} 字符")
                        
                        # 尝试解析音频数据 - 支持十六进制和base64两种格式
                        audio_data = None
                        
                        # 尝试十六进制解码
                        try:
                            audio_data = bytes.fromhex(audio_hex)
                            logger.debug(f"十六进制解码成功，音频数据长度: {len(audio_data)} 字节")
                        except ValueError:
                            logger.debug("十六进制解码失败，尝试base64解码")
                            # 尝试base64解码
                            try:
                                audio_data = base64.b64decode(audio_hex)
                                logger.debug(f"base64解码成功，音频数据长度: {len(audio_data)} 字节")
                            except Exception as e:
                                raise Exception(f"音频数据解码失败（尝试了十六进制和base64）: {str(e)}")
                        
                        if not audio_data or len(audio_data) == 0:
                            raise Exception("解码后的音频数据为空")
                            
                    except json.JSONDecodeError as e:
                        raise Exception(f"JSON解析失败: {str(e)}")
                    except Exception as e:
                        if "响应中缺少" in str(e) or "JSON解析失败" in str(e):
                            raise e
                        else:
                            raise Exception(f"处理响应数据失败: {str(e)}")
                    
                    # 转换为AudioSegment - 尝试多种音频格式
                    audio_segment = None
                    audio_io = io.BytesIO(audio_data)
                    
                    # 尝试不同的音频格式
                    formats_to_try = ['mp3', 'wav', 'raw']
                    
                    for fmt in formats_to_try:
                        try:
                            audio_io.seek(0)  # 重置流位置
                            
                            if fmt == 'mp3':
                                audio_segment = AudioSegment.from_mp3(audio_io)
                            elif fmt == 'wav':
                                audio_segment = AudioSegment.from_wav(audio_io)
                            elif fmt == 'raw':
                                # 尝试作为原始PCM数据（32kHz, 16-bit, mono）
                                audio_segment = AudioSegment(
                                    data=audio_data,
                                    sample_width=2,  # 16-bit = 2 bytes
                                    frame_rate=32000,  # MiniMax默认32kHz
                                    channels=1
                                )
                            
                            if audio_segment:
                                actual_duration = len(audio_segment) / 1000.0
                                logger.debug(f"音频生成成功 ({fmt}格式) - 语速: {effective_rate:.3f}, 时长: {actual_duration:.2f}s")
                                return audio_segment
                                
                        except Exception as e:
                            logger.debug(f"尝试{fmt}格式失败: {str(e)}")
                            continue
                    
                    # 如果所有格式都失败，抛出异常
                    logger.error(f"所有音频格式都无法解码，数据长度: {len(audio_data)}")
                    raise Exception(f"音频格式转换失败: 尝试了{formats_to_try}格式都无法解码")
                    
                else:
                    error_msg = f"MiniMax TTS请求失败: {response.status_code} - {response.text}"
                    logger.error(error_msg)
                    
                    # 处理特定错误类型
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
                error_msg = f"生成单个音频失败 (第{attempt + 1}次尝试): {str(e)}"
                logger.error(error_msg)
                
                # 处理429错误
                error_str = str(e).lower()
                if '429' in error_str or 'too many requests' in error_str:
                    self._handle_rate_limit_error(attempt, max_retries)
                    if attempt < max_retries - 1:
                        continue
                
                # 如果是最后一次尝试，抛出异常
                if attempt == max_retries - 1:
                    self._release_rate_limit()
                    raise Exception(f"所有重试都失败: {error_msg}")
        
        self._release_rate_limit()        
        raise Exception("MiniMax TTS音频生成失败")
    
    def _build_payload(self, text: str, voice_id: str, speech_rate: float) -> dict:
        """
        构建MiniMax TTS请求payload
        
        Args:
            text: 文本内容
            voice_id: 语音ID
            speech_rate: 语速倍率
            
        Returns:
            请求payload字典
        """
        # 确保语速在合理范围内（0.5-2.0）
        rate = max(0.5, min(2.0, speech_rate))
        
        payload = {
            "model": "speech-2.5-hd-preview",
            "text": text,
            "timbre_weights": [
                {
                    "voice_id": voice_id,
                    "weight": 100  # 官方示例使用100而不是1
                }
            ],
            "voice_setting": {
                "voice_id": "",  # 保持空字符串，语音通过timbre_weights指定
                "speed": rate,
                "pitch": self.pitch,
                "vol": self.volume,
                "latex_read": False
            },
            "audio_setting": {
                "sample_rate": 32000,
                "bitrate": 128000,
                "format": "mp3"
            },
            "language_boost": "auto"
        }
        
        logger.debug(f"生成MiniMax payload - 语速: {rate}, 音调: {self.pitch}, 音量: {self.volume}")
        return payload
    
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
        
        pause_time = (major_pause_count * self.major_pause_duration + 
                      minor_pause_count * self.minor_pause_duration) * self.custom_pause_multiplier
        
        # 应用语速调整
        total_time = (base_time + pause_time) / speech_rate
        
        # 添加起始和结束缓冲
        buffer_time = 0.2
        
        return total_time + buffer_time
    
    def estimate_audio_duration_optimized(self, text: str, language: str, speech_rate: float = 1.0) -> float:
        """
        优化的语音时长估算 - 基于单词数和语言特性的精确算法
        
        Args:
            text: 文本内容
            language: 语言代码
            speech_rate: 语速倍率
            
        Returns:
            估算的时长（秒）
        """
        # 基于MiniMax TTS的语音特性优化的估算参数
        language_params = {
            'en': {
                'words_per_second': 2.4,
                'pause_weight': 1.0,
                'overhead': 0.15
            },
            'zh': {
                'words_per_second': 2.0,
                'pause_weight': 0.9,
                'overhead': 0.13
            },
            'ja': {
                'words_per_second': 1.8,
                'pause_weight': 0.9,
                'overhead': 0.12
            },
            'ko': {
                'words_per_second': 1.9,
                'pause_weight': 0.95,
                'overhead': 0.14
            },
            'es': {
                'words_per_second': 2.2,
                'pause_weight': 1.1,
                'overhead': 0.16
            },
            'fr': {
                'words_per_second': 2.3,
                'pause_weight': 1.0,
                'overhead': 0.15
            },
            'de': {
                'words_per_second': 2.1,
                'pause_weight': 1.2,
                'overhead': 0.18
            }
        }
        
        # 获取语言参数，默认使用英语
        lang_params = language_params.get(language, language_params['en'])
        
        # 计算单词数
        words = text.split()
        word_count = len(words)
        
        # 计算基础时长
        base_time = word_count / lang_params['words_per_second']
        
        # 计算标点符号造成的停顿时间
        major_pauses = text.count('.') + text.count('!') + text.count('?') + \
                      text.count('。') + text.count('！') + text.count('？')
        minor_pauses = text.count(',') + text.count(';') + text.count(':') + \
                      text.count('，') + text.count('；') + text.count('：')
        
        pause_time = ((major_pauses * self.major_pause_duration + 
                       minor_pauses * self.minor_pause_duration) * 
                      self.custom_pause_multiplier * lang_params['pause_weight'])
        
        # 应用语速调整
        adjusted_time = (base_time + pause_time) / speech_rate
        
        # 添加处理开销
        total_time = adjusted_time + lang_params['overhead']
        
        # 添加起始缓冲时间
        buffer_time = 0.2
        
        estimated_duration = total_time + buffer_time

        # 应用动态校准因子
        calibration = self._calibration_factors.get(language, {}).get('factor', 1.0)
        estimated_duration *= calibration

        logger.debug(f"时长估算: 文本={word_count}单词, 基础={base_time:.2f}s, "
                    f"停顿={pause_time:.2f}s, 语速={speech_rate:.2f}, "
                    f"校准因子={calibration:.3f}, 预估={estimated_duration:.2f}s")
        
        return estimated_duration
    
    def estimate_optimal_speech_rate(self, text: str, language: str, target_duration: float, 
                                   min_rate: float = 0.5, max_rate: float = 2.0) -> float:
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
    
    def test_voice_synthesis(self, text: str = "Hello, this is a test.", voice_id: Optional[str] = None) -> bool:
        """
        测试语音合成功能
        
        Args:
            text: 测试文本
            voice_id: 语音ID
            
        Returns:
            测试是否成功
        """
        try:
            if not voice_id:
                voice_id = self.default_voice_ids.get('en', "moss_audio_ef01c4ea-ce7f-11f0-825a-da3ca3ba36b8")
            
            logger.info(f"开始测试MiniMax TTS - 语音ID: {voice_id}")
            
            test_audio = self._generate_single_audio(text, voice_id, 1.0)
            
            logger.info(f"语音合成测试成功 - 时长: {len(test_audio)/1000:.2f}s")
            return True
                
        except Exception as e:
            logger.error(f"语音合成测试失败: {str(e)}")
            return False
    
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
    
    def get_optimal_rate_for_language(self, language: str, base_rate: float = 1.0) -> float:
        """
        获取语言的最优语速
        
        Args:
            language: 语言代码
            base_rate: 基础语速
            
        Returns:
            最优语速
        """
        rate_offset = self.language_specific_adjustments.get(language, {}).get('rate_offset', 0)
        optimal_rate = base_rate + rate_offset
        # MiniMax支持更宽的语速范围：0.5 - 2.0
        return max(0.5, min(2.0, optimal_rate))
    
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
        
        # 统计语速分布
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
        
        # 语速分布统计（MiniMax范围：0.5-2.0）
        speed_distribution = {
            '0.5-1.0': sum(1 for s in speeds if 0.5 <= s < 1.0),
            '1.0-1.5': sum(1 for s in speeds if 1.0 <= s < 1.5),
            '1.5-2.0': sum(1 for s in speeds if 1.5 <= s <= 2.0)
        }
        
        report = f"""MiniMax TTS语音合成报告
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
  - 0.5-1.0: {speed_distribution['0.5-1.0']} 片段
  - 1.0-1.5: {speed_distribution['1.0-1.5']} 片段
  - 1.5-2.0: {speed_distribution['1.5-2.0']} 片段
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
        print("🔥 MINIMAX TTS 成本报告")
        print("="*60)
        print(f"📊 API调用次数: {summary['api_calls']}")
        print(f"📝 总字符数: {summary['total_characters']:,}")
        print(f"💰 估计成本: ${summary['estimated_cost_usd']:.4f}")
        print(f"⏱️  会话时长: {summary['session_duration_seconds']:.1f}秒")
        print(f"📈 平均调用频率: {summary['avg_calls_per_minute']:.1f}次/分钟")
        print(f"📋 平均字符数/调用: {summary['avg_characters_per_call']:.1f}")
        print("="*60)
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
                time.sleep(0.1)
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

    def synthesize_speech_optimized(self, text: str, language: str, speech_rate: float, file_prefix: str = "tts_segment", target_duration: Optional[float] = None, num_candidates: int = 1) -> str:
        """
        兼容sync_manager的音频合成方法，自动选择voice并保存为wav文件，返回文件路径
        
        Args:
            text: 合成文本
            language: 目标语言代码
            speech_rate: 语速倍率
            file_prefix: 文件名前缀
            target_duration: 目标时长（秒），如果提供则从多候选中选择最接近的
            num_candidates: 候选数量，默认1（不使用多候选策略）
            
        Returns:
            生成的音频文件路径
        """
        voice_id = self.get_voice_id(language)
        if not voice_id:
            raise ValueError(f"未配置语言 {language} 的voice")
        
        # 如果需要多候选选优
        if target_duration and num_candidates > 1:
            audio_segment = self._generate_audio_with_best_match(
                text, voice_id, speech_rate, target_duration, num_candidates
            )
        else:
            audio_segment = self._generate_single_audio(text, voice_id, speech_rate)
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3", prefix=file_prefix + "_") as f:
            audio_segment.export(f.name, format="mp3", bitrate="128k")
            file_path = f.name
        return file_path
    
    def _generate_audio_with_best_match(
        self, 
        text: str, 
        voice_id: str, 
        speech_rate: float, 
        target_duration: float,
        num_candidates: int = 3
    ) -> AudioSegment:
        """
        生成多个音频候选，选择时长最接近目标的
        
        Args:
            text: 文本内容
            voice_id: 语音ID
            speech_rate: 语速倍率
            target_duration: 目标时长（秒）
            num_candidates: 候选数量
            
        Returns:
            最佳匹配的音频片段
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed
        
        candidates = []
        target_ms = target_duration * 1000
        overflow_threshold_ms = 100  # 超时阈值：超过目标100ms视为"超时"
        
        logger.info(f"🎯 多候选TTS: {num_candidates}候选, 目标={target_duration:.2f}s")
        
        def generate_candidate(idx: int) -> Tuple[int, Optional[AudioSegment], float, bool]:
            """生成单个候选，返回(索引, 音频, 误差, 是否超时)"""
            try:
                audio = self._generate_single_audio(text, voice_id, speech_rate)
                duration_ms = len(audio)
                error = abs(duration_ms - target_ms)
                is_overflow = duration_ms > target_ms + overflow_threshold_ms  # 超过目标+100ms
                status = "⚠️超时" if is_overflow else "✓"
                logger.debug(f"  候选#{idx+1}: {duration_ms/1000:.2f}s, 误差{error:.0f}ms {status}")
                return idx, audio, error, is_overflow
            except Exception as e:
                logger.warning(f"  候选#{idx+1}失败: {e}")
                return idx, None, float('inf'), True
        
        # 并发生成候选（控制并发数，避免API限制）
        max_workers = min(num_candidates, 2)
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(generate_candidate, i) for i in range(num_candidates)]
            
            for future in as_completed(futures):
                idx, audio, error, is_overflow = future.result()
                if audio is not None:
                    candidates.append((audio, error, idx, is_overflow))
        
        if not candidates:
            logger.error("多候选全部失败，使用静音")
            return AudioSegment.silent(duration=int(target_ms))
        
        # 选优策略：优先选择"不超时"的候选，在不超时的候选中选误差最小的
        non_overflow = [(a, e, i, o) for a, e, i, o in candidates if not o]
        
        if non_overflow:
            # 有不超时的候选，从中选误差最小的
            best_audio, best_error, best_idx, _ = min(non_overflow, key=lambda x: x[1])
            logger.info(f"✅ 选中#{best_idx+1}(安全), 误差={best_error:.0f}ms, 时长={len(best_audio)/1000:.2f}s")
        else:
            # 全部超时，选择超时最少的（误差最小的）
            best_audio, best_error, best_idx, _ = min(candidates, key=lambda x: x[1])
            logger.warning(f"⚠️ 全部超时，选中#{best_idx+1}, 误差={best_error:.0f}ms, 时长={len(best_audio)/1000:.2f}s")
        
        return best_audio

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

    def test_pause_duration_settings(self, test_texts: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        测试停顿时长设置的效果
        
        Args:
            test_texts: 测试文本列表，如果不提供则使用默认测试文本
            
        Returns:
            测试结果字典
        """
        if test_texts is None:
            test_texts = [
                "这是一个测试。包含句号的停顿。",
                "测试逗号，分号；还有冒号：的停顿效果。",
                "问号停顿测试？感叹号停顿测试！",
                "综合测试：句号。逗号，问号？感叹号！分号；冒号：的停顿。"
            ]
        
        results = {
            'pause_config': {
                'major_pause_duration': self.major_pause_duration,
                'minor_pause_duration': self.minor_pause_duration,
                'pause_multiplier': self.custom_pause_multiplier
            },
            'test_results': []
        }
        
        logger.info(f"开始测试停顿时长设置 - 句号停顿: {self.major_pause_duration}s, 逗号停顿: {self.minor_pause_duration}s, 倍率: {self.custom_pause_multiplier}")
        
        for i, text in enumerate(test_texts):
            try:
                # 统计标点符号数量
                major_count = sum(1 for char in text if char in '.!?。！？')
                minor_count = sum(1 for char in text if char in ',;，；:')
                
                # 估算时长
                estimated_duration = self.estimate_audio_duration_optimized(text, 'zh', 1.0)
                
                # 计算预期停顿时间
                expected_pause_time = ((major_count * self.major_pause_duration + 
                                      minor_count * self.minor_pause_duration) * 
                                     self.custom_pause_multiplier)
                
                test_result = {
                    'text': text,
                    'text_length': len(text),
                    'major_pauses': major_count,
                    'minor_pauses': minor_count,
                    'expected_pause_time': expected_pause_time,
                    'estimated_total_duration': estimated_duration,
                    'pause_ratio': expected_pause_time / estimated_duration if estimated_duration > 0 else 0
                }
                
                results['test_results'].append(test_result)
                
                logger.info(f"测试文本{i+1}: {text[:20]}... - 预期停顿: {expected_pause_time:.2f}s, 总时长: {estimated_duration:.2f}s")
                
            except Exception as e:
                logger.error(f"测试文本{i+1}失败: {str(e)}")
                results['test_results'].append({
                    'text': text,
                    'error': str(e)
                })
        
        # 计算平均停顿比例
        successful_tests = [r for r in results['test_results'] if 'error' not in r]
        if successful_tests:
            avg_pause_ratio = sum(r['pause_ratio'] for r in successful_tests) / len(successful_tests)
            results['summary'] = {
                'total_tests': len(test_texts),
                'successful_tests': len(successful_tests),
                'average_pause_ratio': avg_pause_ratio,
                'pause_impact': '高' if avg_pause_ratio > 0.3 else '中' if avg_pause_ratio > 0.15 else '低'
            }
            
            logger.info(f"停顿测试完成 - 平均停顿占比: {avg_pause_ratio:.1%}, 停顿影响: {results['summary']['pause_impact']}")
        
        return results
