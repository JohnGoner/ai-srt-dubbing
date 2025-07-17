"""
时间同步管理模块 - 并发循环逼近算法
通过LLM文本精简 + Azure API微调语速实现精确时间同步
支持高性能并发处理
"""

from typing import List, Dict, Any, Optional, Tuple
from loguru import logger
from pydub import AudioSegment
import time
from concurrent.futures import ThreadPoolExecutor, as_completed


class AdvancedSyncManager:
    """高级时间同步管理器 - 并发循环逼近算法"""
    
    def __init__(self, config: dict, progress_callback=None):
        """
        初始化时间同步管理器
        
        Args:
            config: 配置字典
            progress_callback: 进度回调函数，格式为 callback(current, total, message)
        """
        self.config = config
        self.timing_config = config.get('timing', {})
        
        # 进度回调
        self.progress_callback = progress_callback
        
        # 语速调整范围（调整为0.95-1.15，保持更自然的语速）
        self.min_speed_ratio = 0.95  # 最小语速 - 避免过慢的不自然语速
        self.max_speed_ratio = 1.15  # 最大语速 - 保持上限
        self.speed_step = 0.01       # 语速调整步长
        
        # 时间同步参数
        self.sync_tolerance = 0.15   # 时间同步容忍度（15%）
        self.max_iterations = 3      # 最大循环次数（从5减少到3）
        self.max_speed_variation = 0.1  # 最大语速波动（整体语速波动不超过0.1）
        
        # 并发处理参数
        self.max_concurrent_workers = 6  # 最大并发工作线程数
        self.enable_concurrent_processing = True  # 启用并发处理
        
        # 成本优化配置
        self.enable_cost_optimization = self.timing_config.get('enable_cost_optimization', True)
        self.use_estimation_first = self.timing_config.get('use_estimation_first', True)
        self.max_api_calls_per_segment = self.timing_config.get('max_api_calls_per_segment', 2)
        
        # 优化模式选择
        self.optimization_mode = self.timing_config.get('optimization_mode', 'balanced')  # 'economic', 'balanced', 'precise'
        
        # 根据模式调整参数
        if self.optimization_mode == 'economic':
            # 经济模式：最大化成本节省
            self.max_iterations = 1
            self.max_api_calls_per_segment = 1
            self.sync_tolerance = 0.2  # 放宽容忍度
            self.use_estimation_first = True
        elif self.optimization_mode == 'balanced':
            # 平衡模式：精度和成本的平衡
            self.max_iterations = 2
            self.max_api_calls_per_segment = 3
            self.sync_tolerance = 0.15
            self.use_estimation_first = True
        elif self.optimization_mode == 'precise':
            # 精确模式：最大化精度（原始算法）
            self.max_iterations = 3
            self.max_api_calls_per_segment = 6
            self.sync_tolerance = 0.1
            self.use_estimation_first = False
        
        logger.info(f"时间同步优化模式: {self.optimization_mode}")
        logger.info(f"最大迭代次数: {self.max_iterations}, 最大API调用: {self.max_api_calls_per_segment}")
        
        # 音频时长控制参数（从配置文件读取）
        self.preferred_breathing_gap = self.timing_config.get('preferred_breathing_gap', 0.3)  # 理想呼吸间隙时间（秒）
        self.min_overlap_buffer = self.timing_config.get('min_overlap_buffer', 0.05)           # 最小缓冲时间（秒）
        
        # 语言特性配置
        self.language_expansion_factors = {
            'en': 1.15,   # 英语比中文长15%
            'es': 1.12,   # 西班牙语比中文长12%
            'fr': 1.18,   # 法语比中文长18%
            'de': 1.10,   # 德语比中文长10%
            'ja': 0.95,   # 日语比中文短5%
            'ko': 1.05    # 韩语比中文长5%
        }
    
    def _report_progress(self, current: int, total: int, message: str):
        """报告进度"""
        if self.progress_callback:
            try:
                self.progress_callback(current, total, message)
            except Exception as e:
                logger.warning(f"同步优化进度回调失败: {str(e)}")
    
    def optimize_timing_with_iteration(self, segments: List[Dict[str, Any]], 
                                     target_language: str, 
                                     translator, tts) -> List[Dict[str, Any]]:
        """
        使用并发循环逼近算法优化时间同步
        
        Args:
            segments: 翻译后的片段列表
            target_language: 目标语言代码
            translator: 翻译器实例
            tts: TTS实例
            
        Returns:
            优化后的片段列表
        """
        logger.info("开始并发循环逼近时间同步优化...")
        self._report_progress(0, 100, "开始时间同步优化...")
        
        if self.enable_concurrent_processing and len(segments) > 3:
            # 并发处理
            optimized_segments = self._concurrent_optimize_segments(
                segments, target_language, translator, tts
            )
        else:
            # 串行处理（小数量片段或禁用并发）
            optimized_segments = self._sequential_optimize_segments(
                segments, target_language, translator, tts
            )
        
        # 语速波动控制 - 确保整体语速波动不超过0.1
        # self._report_progress(90, 100, "优化语速波动控制...")
        # optimized_segments = self._control_speed_variation(optimized_segments)
        
        logger.info("并发循环逼近时间同步优化完成")
        self._report_progress(100, 100, "时间同步优化完成！")
        return optimized_segments
    
    def _concurrent_optimize_segments(self, segments: List[Dict[str, Any]], 
                                    target_language: str, 
                                    translator, tts) -> List[Dict[str, Any]]:
        """
        并发优化片段
        
        Args:
            segments: 片段列表
            target_language: 目标语言
            translator: 翻译器实例
            tts: TTS实例
            
        Returns:
            优化后的片段列表
        """
        logger.info(f"并发优化 {len(segments)} 个片段（{self.max_concurrent_workers} 个工作线程）")
        self._report_progress(10, 100, f"启动{self.max_concurrent_workers}个并发线程优化{len(segments)}个片段...")
        
        optimized_segments = []
        completed_segments = 0
        
        with ThreadPoolExecutor(max_workers=self.max_concurrent_workers) as executor:
            # 提交所有优化任务
            future_to_segment = {
                executor.submit(
                    self._optimize_single_segment_thread_safe, 
                    segment, target_language, translator, tts, segments, i + 1
                ): segment 
                for i, segment in enumerate(segments)
            }
            
            # 收集结果
            for future in as_completed(future_to_segment):
                try:
                    optimized_segment = future.result()
                    optimized_segments.append(optimized_segment)
                    
                    # 更新进度
                    completed_segments += 1
                    progress = 10 + int((completed_segments / len(segments)) * 75)  # 10-85%
                    self._report_progress(progress, 100, f"完成片段优化 {completed_segments}/{len(segments)}...")
                    
                except Exception as e:
                    segment = future_to_segment[future]
                    logger.error(f"片段 {segment['id']} 优化失败: {str(e)}")
                    # 创建降级片段
                    fallback_segment = self._create_fallback_segment(segment, tts, target_language)
                    optimized_segments.append(fallback_segment)
                    
                    completed_segments += 1
                    progress = 10 + int((completed_segments / len(segments)) * 75)
                    self._report_progress(progress, 100, f"片段降级处理 {completed_segments}/{len(segments)}...")
        
        # 按原始顺序排序
        optimized_segments.sort(key=lambda x: x['id'])
        
        logger.info(f"并发优化完成，处理了 {len(optimized_segments)} 个片段")
        self._report_progress(85, 100, "并发优化完成，正在整理结果...")
        return optimized_segments
    
    def _sequential_optimize_segments(self, segments: List[Dict[str, Any]], 
                                    target_language: str, 
                                    translator, tts) -> List[Dict[str, Any]]:
        """
        串行优化片段（保持原有逻辑）
        
        Args:
            segments: 片段列表
            target_language: 目标语言
            translator: 翻译器实例
            tts: TTS实例
            
        Returns:
            优化后的片段列表
        """
        logger.info(f"串行优化 {len(segments)} 个片段")
        self._report_progress(10, 100, f"串行优化{len(segments)}个片段...")
        
        optimized_segments = []
        
        for i, segment in enumerate(segments):
            logger.info(f"优化片段 {i+1}/{len(segments)}: {segment['id']}")
            
            # 更新进度
            progress = 10 + int(((i + 1) / len(segments)) * 75)  # 10-85%
            self._report_progress(progress, 100, f"优化片段 {i+1}/{len(segments)}: {segment['id']}")
            
            optimized_segment = self._optimize_single_segment(
                segment, target_language, translator, tts, segments
            )
            optimized_segments.append(optimized_segment)
        
        self._report_progress(85, 100, "串行优化完成，正在整理结果...")
        return optimized_segments
    
    def _optimize_single_segment_thread_safe(self, segment: Dict[str, Any], 
                                           target_language: str, 
                                           translator, tts, all_segments: List[Dict[str, Any]],
                                           segment_num: int) -> Dict[str, Any]:
        """
        线程安全的单个片段优化
        
        Args:
            segment: 片段数据
            target_language: 目标语言
            translator: 翻译器实例
            tts: TTS实例
            all_segments: 所有片段列表
            segment_num: 片段编号
            
        Returns:
            优化后的片段
        """
        try:
            logger.debug(f"并发优化片段 {segment_num} - {segment['id']}")
            
            # 添加小延迟避免过快请求
            time.sleep(0.02 * (segment_num - 1))  # 每个片段间隔20ms
            
            return self._optimize_single_segment(
                segment, target_language, translator, tts, all_segments
            )
            
        except Exception as e:
            logger.error(f"并发优化片段 {segment['id']} 失败: {str(e)}")
            return self._create_fallback_segment(segment, tts, target_language)
    
    def _create_fallback_segment(self, segment: Dict[str, Any], tts, target_language: str) -> Dict[str, Any]:
        """
        创建降级片段（简单处理）
        
        Args:
            segment: 原始片段
            tts: TTS实例
            target_language: 目标语言
            
        Returns:
            降级处理的片段
        """
        try:
            # 使用默认语速生成音频
            fallback_audio = tts._generate_single_audio(
                segment['translated_text'],
                tts.voice_map.get(target_language),
                1.0,  # 默认语速
                segment['duration']
            )
            
            final_duration = len(fallback_audio) / 1000.0
            final_ratio = final_duration / segment['duration']
            
            return self._create_final_segment(
                segment, segment['translated_text'], 1.0, 
                fallback_audio, final_duration, final_ratio, 0, 'fallback', False, 0
            )
            
        except Exception as e:
            logger.error(f"创建降级片段失败: {str(e)}")
            # 最后的降级：创建静音片段
            silence_duration = int(segment['duration'] * 1000)
            silent_audio = AudioSegment.silent(duration=silence_duration)
            
            return self._create_final_segment(
                segment, segment['translated_text'], 1.0,
                silent_audio, segment['duration'], 1.0, 0, 'silent_fallback', False, 0
            )
    
    def _optimize_single_segment(self, segment: Dict[str, Any], 
                                target_language: str, 
                                translator, tts, all_segments: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        优化单个片段的时间同步 - 成本优化版本，减少API调用
        
        Args:
            segment: 片段数据
            target_language: 目标语言
            translator: 翻译器实例
            tts: TTS实例
            all_segments: 所有片段列表（用于计算最大音频时长）
            
        Returns:
            优化后的片段
        """
        original_duration = segment['duration']
        original_text = segment['translated_text']
        
        # 计算最大允许音频时长
        max_audio_duration = self._calculate_max_audio_duration(segment, all_segments)
        
        logger.debug(f"片段 {segment['id']} 原始时长: {original_duration:.2f}s, "
                    f"最大音频时长: {max_audio_duration:.2f}s (成本优化模式)")
        
        # 步骤1: 使用估算方法快速评估文本长度
        logger.debug(f"使用估算方法评估文本长度: {original_text[:50]}...")
        
        # 估算标准语速下的时长
        estimated_duration = tts.estimate_audio_duration_optimized(original_text, target_language, 1.0)
        estimated_ratio = estimated_duration / original_duration
        
        logger.debug(f"估算时长: {estimated_duration:.2f}s, 估算比例: {estimated_ratio:.3f}")
        
        # 步骤2: 基于估算结果决定策略，尽量避免API调用
        if estimated_ratio < 0.6:
            # 文本过短，需要扩展或慢语速
            logger.info(f"片段 {segment['id']} 估算文本过短 (比例: {estimated_ratio:.3f})，使用智能扩展策略")
            return self._handle_short_text_optimized(segment, original_text, target_language, tts, estimated_ratio, max_audio_duration, translator)
        elif estimated_ratio > 1.4:
            # 文本过长，需要精简
            logger.info(f"片段 {segment['id']} 估算文本过长 (比例: {estimated_ratio:.3f})，使用智能精简策略")
            return self._handle_long_text_optimized(segment, original_text, target_language, tts, estimated_ratio, max_audio_duration, translator)
        else:
            # 长度合理，直接计算最优语速
            logger.info(f"片段 {segment['id']} 估算文本长度合理 (比例: {estimated_ratio:.3f})，计算最优语速")
            return self._direct_speed_optimization(segment, original_text, target_language, tts, estimated_ratio, max_audio_duration)
    
    def _direct_speed_optimization(self, segment: Dict[str, Any], text: str, 
                                 target_language: str, tts, estimated_ratio: float,
                                 max_audio_duration: float) -> Dict[str, Any]:
        """
        直接语速优化 - 基于估算结果计算最优语速，只调用一次API
        
        Args:
            segment: 片段数据
            text: 文本内容
            target_language: 目标语言
            tts: TTS实例
            estimated_ratio: 估算的时长比例
            max_audio_duration: 最大音频时长
            
        Returns:
            优化后的片段
        """
        # 使用估算方法计算最优语速
        optimal_speed = tts.estimate_optimal_speech_rate(
            text, target_language, segment['duration'], 
            self.min_speed_ratio, self.max_speed_ratio
        )
        
        # 检查是否会超过最大音频时长
        estimated_final_duration = tts.estimate_audio_duration_optimized(text, target_language, optimal_speed)
        
        if estimated_final_duration > max_audio_duration:
            # 调整语速以适应最大时长限制
            required_speed = optimal_speed * (estimated_final_duration / max_audio_duration)
            optimal_speed = min(required_speed, self.max_speed_ratio)
            logger.debug(f"调整语速以适应最大时长限制: {optimal_speed:.3f}")
        
        # 只调用一次API生成最终音频
        logger.debug(f"使用最优语速 {optimal_speed:.3f} 生成最终音频（减少API调用）")
        final_audio = tts._generate_single_audio(
            text,
            tts.voice_map.get(target_language),
            optimal_speed,
            segment['duration']
        )
        
        final_duration = len(final_audio) / 1000.0
        final_ratio = final_duration / segment['duration']
        
        # 动态校准：根据实际与预测差异更新估算模型
        try:
            predicted_duration = tts.estimate_audio_duration_optimized(text, target_language, optimal_speed)
            tts.update_calibration(target_language, predicted_duration, final_duration)
        except Exception:
            pass
        
        # 如果仍然超出最大限制，进行音频截断
        if final_duration > max_audio_duration:
            logger.warning(f"音频时长 {final_duration:.2f}s 超过最大限制 {max_audio_duration:.2f}s，进行截断")
            max_duration_ms = int(max_audio_duration * 1000)
            final_audio = final_audio[:max_duration_ms]
            if len(final_audio) > 50:
                final_audio = final_audio.fade_out(50)
            final_duration = len(final_audio) / 1000.0
            final_ratio = final_duration / segment['duration']
        
        # 评估结果质量
        if abs(final_ratio - 1.0) <= 0.05:
            quality = 'excellent'
        elif abs(final_ratio - 1.0) <= 0.15:
            quality = 'good'
        else:
            quality = 'fair'
        
        logger.info(f"直接优化片段 {segment['id']} 完成: 估算比例 {estimated_ratio:.3f}, "
                   f"最终比例 {final_ratio:.3f}, 语速 {optimal_speed:.3f}, 质量: {quality}")
        
        return self._create_final_segment(
            segment, text, optimal_speed, final_audio, final_duration, final_ratio, 
            1, quality, False, abs(final_duration - segment['duration']) * 1000
        )
    
    def _handle_short_text_optimized(self, segment: Dict[str, Any], text: str, 
                                   target_language: str, tts, estimated_ratio: float, 
                                   max_audio_duration: float, translator) -> Dict[str, Any]:
        """
        处理短文本的优化版本 - 减少API调用
        
        Args:
            segment: 片段数据
            text: 当前文本
            target_language: 目标语言
            tts: TTS实例
            estimated_ratio: 估算的时长比例
            max_audio_duration: 最大音频时长
            translator: 翻译器实例
            
        Returns:
            优化后的片段
        """
        current_text = text
        
        # 如果文本过短且有翻译器，尝试扩展
        if estimated_ratio < 0.8 and translator:
            logger.info(f"片段 {segment['id']} 文本过短，尝试GPT扩展")
            
            # 计算目标扩展比例
            target_ratio = min(1.0, estimated_ratio + 0.3)
            
            expanded_text = self._adjust_text_with_gpt(
                current_text, target_language, estimated_ratio, target_ratio, translator
            )
            
            if len(expanded_text) > len(current_text):
                # 估算扩展后的效果
                expanded_estimated_duration = tts.estimate_audio_duration_optimized(
                    expanded_text, target_language, 1.0
                )
                expanded_estimated_ratio = expanded_estimated_duration / segment['duration']
                
                logger.debug(f"扩展后估算时长: {expanded_estimated_duration:.2f}s, 比例: {expanded_estimated_ratio:.3f}")
                
                # 如果扩展后效果更好，使用扩展文本
                if expanded_estimated_ratio > estimated_ratio and expanded_estimated_ratio <= 1.5:
                    current_text = expanded_text
                    estimated_ratio = expanded_estimated_ratio
                    logger.info(f"使用扩展文本，新估算比例: {expanded_estimated_ratio:.3f}")
        
        # 基于当前文本计算最优语速
        if estimated_ratio < 0.9:
            # 使用慢语速
            optimal_speed = max(self.min_speed_ratio, estimated_ratio * 0.9)
            optimal_speed = min(optimal_speed, 1.0)
        else:
            # 使用标准语速
            optimal_speed = min(estimated_ratio, 1.05)
        
        # 检查是否会超过最大音频时长
        estimated_final_duration = tts.estimate_audio_duration_optimized(current_text, target_language, optimal_speed)
        
        if estimated_final_duration > max_audio_duration:
            required_speed = optimal_speed * (estimated_final_duration / max_audio_duration)
            optimal_speed = min(required_speed, self.max_speed_ratio)
        
        # 只调用一次API生成最终音频
        logger.debug(f"短文本优化：使用语速 {optimal_speed:.3f} 生成最终音频")
        final_audio = tts._generate_single_audio(
            current_text,
            tts.voice_map.get(target_language),
            optimal_speed,
            segment['duration']
        )
        
        final_duration = len(final_audio) / 1000.0
        final_ratio = final_duration / segment['duration']
        
        # 动态校准
        try:
            predicted_duration = tts.estimate_audio_duration_optimized(current_text, target_language, optimal_speed)
            tts.update_calibration(target_language, predicted_duration, final_duration)
        except Exception:
            pass
        
        # 处理超出限制的情况
        if final_duration > max_audio_duration:
            max_duration_ms = int(max_audio_duration * 1000)
            final_audio = final_audio[:max_duration_ms]
            if len(final_audio) > 50:
                final_audio = final_audio.fade_out(50)
            final_duration = len(final_audio) / 1000.0
            final_ratio = final_duration / segment['duration']
        
        # 评估质量
        if final_ratio < 0.8:
            quality = 'short_text'
        elif abs(final_ratio - 1.0) <= 0.05:
            quality = 'excellent'
        elif abs(final_ratio - 1.0) <= 0.15:
            quality = 'good'
        else:
            quality = 'fair'
        
        logger.info(f"短文本优化完成: 估算比例 {estimated_ratio:.3f}, "
                   f"最终比例 {final_ratio:.3f}, 语速 {optimal_speed:.3f}, 质量: {quality}")
        
        return self._create_final_segment(
            segment, current_text, optimal_speed, final_audio, final_duration, final_ratio, 
            1, quality, False, abs(final_duration - segment['duration']) * 1000
        )
    
    def _handle_long_text_optimized(self, segment: Dict[str, Any], text: str, 
                                  target_language: str, tts, estimated_ratio: float,
                                  max_audio_duration: float, translator) -> Dict[str, Any]:
        """
        处理长文本的优化版本 - 减少API调用
        
        Args:
            segment: 片段数据
            text: 当前文本
            target_language: 目标语言
            tts: TTS实例
            estimated_ratio: 估算的时长比例
            max_audio_duration: 最大音频时长
            translator: 翻译器实例
            
        Returns:
            优化后的片段
        """
        current_text = text
        
        # 如果文本过长，先尝试GPT精简
        if estimated_ratio > 1.3:
            logger.info(f"片段 {segment['id']} 文本过长，尝试GPT精简")
            
            current_text = self._adjust_text_with_gpt(
                current_text, target_language, estimated_ratio, 1.0, translator
            )
            
            # 重新估算精简后的时长
            estimated_ratio = tts.estimate_audio_duration_optimized(
                current_text, target_language, 1.0
            ) / segment['duration']
            
            logger.debug(f"精简后估算比例: {estimated_ratio:.3f}")
        
        # 计算最优语速
        optimal_speed = tts.estimate_optimal_speech_rate(
            current_text, target_language, segment['duration'], 
            self.min_speed_ratio, self.max_speed_ratio
        )
        
        # 检查是否会超过最大音频时长
        estimated_final_duration = tts.estimate_audio_duration_optimized(current_text, target_language, optimal_speed)
        
        if estimated_final_duration > max_audio_duration:
            # 如果仍然超出，进一步精简文本
            logger.warning(f"估算时长 {estimated_final_duration:.2f}s 仍超过限制，进一步精简文本")
            
            required_compression = max_audio_duration / estimated_final_duration
            reduction_ratio = 1 - required_compression
            reduction_ratio = max(0.1, min(0.3, reduction_ratio))
            
            current_text = self._smart_text_reduction(current_text, reduction_ratio)
            logger.debug(f"进一步精简文本: 减少 {reduction_ratio*100:.1f}%")
            
            # 重新计算最优语速
            optimal_speed = min(self.max_speed_ratio, 
                              tts.estimate_optimal_speech_rate(
                                  current_text, target_language, max_audio_duration, 
                                  self.min_speed_ratio, self.max_speed_ratio
                              ))
        
        # 只调用一次API生成最终音频
        logger.debug(f"长文本优化：使用语速 {optimal_speed:.3f} 生成最终音频")
        final_audio = tts._generate_single_audio(
            current_text,
            tts.voice_map.get(target_language),
            optimal_speed,
            segment['duration']
        )
        
        final_duration = len(final_audio) / 1000.0
        final_ratio = final_duration / segment['duration']
        
        # 动态校准
        try:
            predicted_duration = tts.estimate_audio_duration_optimized(current_text, target_language, optimal_speed)
            tts.update_calibration(target_language, predicted_duration, final_duration)
        except Exception:
            pass
        
        # 处理超出限制的情况
        if final_duration > max_audio_duration:
            logger.warning(f"音频时长 {final_duration:.2f}s 仍超过限制，进行截断")
            max_duration_ms = int(max_audio_duration * 1000)
            final_audio = final_audio[:max_duration_ms]
            if len(final_audio) > 50:
                final_audio = final_audio.fade_out(50)
            final_duration = len(final_audio) / 1000.0
            final_ratio = final_duration / segment['duration']
        
        # 评估质量
        if final_ratio > 1.2:
            quality = 'long_text'
        elif abs(final_ratio - 1.0) <= 0.05:
            quality = 'excellent'
        elif abs(final_ratio - 1.0) <= 0.15:
            quality = 'good'
        else:
            quality = 'fair'
        
        logger.info(f"长文本优化完成: 估算比例 {estimated_ratio:.3f}, "
                   f"最终比例 {final_ratio:.3f}, 语速 {optimal_speed:.3f}, 质量: {quality}")
        
        return self._create_final_segment(
            segment, current_text, optimal_speed, final_audio, final_duration, final_ratio, 
            1, quality, False, abs(final_duration - segment['duration']) * 1000
        )
    
    def _fine_tune_speed(self, segment: Dict[str, Any], text: str, 
                        target_language: str, tts, base_ratio: float,
                        max_audio_duration: float) -> Dict[str, Any]:
        """
        通过语速微调优化时长
        
        Args:
            segment: 片段数据
            text: 当前文本
            target_language: 目标语言
            tts: TTS实例
            base_ratio: 基准时长比例
            max_audio_duration: 最大允许音频时长
            
        Returns:
            优化后的片段
        """
        logger.debug(f"微调片段 {segment['id']} 语速，基准比例: {base_ratio:.3f}")
        
        # 检查时长比例是否合理
        if base_ratio < 0.8:  # 更严格的短文本检查
            logger.warning(f"片段 {segment['id']} 时长比例过小 ({base_ratio:.3f})，需要降低语速延长时长")
            # 对于过短的文本，计算需要的语速来接近目标时长
            # 理想情况下，我们希望 actual_duration / target_duration ≈ 1.0
            # 即 (base_duration / target_speed) / target_duration ≈ 1.0
            # 所以 target_speed ≈ base_ratio
            
            # 但要确保语速在允许范围内
            ideal_speed = base_ratio  # 理想语速
            target_speed = max(self.min_speed_ratio, ideal_speed)
            
            if target_speed > ideal_speed:
                logger.warning(f"理想语速 {ideal_speed:.3f} 低于最小允许语速 {self.min_speed_ratio:.3f}，"
                             f"使用最小语速 {target_speed:.3f}，但音频仍可能过短")
            
            logger.debug(f"短文本处理策略: 理想语速 {ideal_speed:.3f}, 实际语速 {target_speed:.3f}")
        else:
            # 正常的语速调整逻辑
            target_speed = max(self.min_speed_ratio, min(base_ratio, self.max_speed_ratio))
        
        # 在1.0语速下预测最大语速的效果，判断是否需要文本精简
        base_duration_at_1_0 = len(text) / 12.0  # 粗略估算1.0语速下的时长
        predicted_duration_at_max_speed = base_duration_at_1_0 / self.max_speed_ratio
        
        current_text = text
        
        # 如果预测的最大语速下仍会超过最大音频时长，先精简文本
        if predicted_duration_at_max_speed > max_audio_duration and base_ratio >= 0.9:
            logger.warning(f"预测最大语速 {self.max_speed_ratio:.3f} 下仍会超出限制，先精简文本")
            
            # 计算需要的文本精简比例
            required_compression = max_audio_duration / predicted_duration_at_max_speed
            text_reduction_ratio = 1 - required_compression
            text_reduction_ratio = max(0.1, min(0.4, text_reduction_ratio))  # 限制精简比例
            
            current_text = self._smart_text_reduction(text, text_reduction_ratio)
            logger.debug(f"预防性文本精简: {len(text)} -> {len(current_text)} 字符")
            
            # 重新计算base_ratio
            new_base_duration = len(current_text) / 12.0
            base_ratio = new_base_duration / segment['duration']
            target_speed = max(self.min_speed_ratio, min(base_ratio, self.max_speed_ratio))
        
        logger.debug(f"微调片段 {segment['id']} 最终策略: 比例 {base_ratio:.3f}, 目标语速: {target_speed:.3f}")
        
        # 生成音频
        final_audio = tts._generate_single_audio(
            current_text,
            tts.voice_map.get(target_language),
            target_speed,
            segment['duration']
        )
        
        final_duration = len(final_audio) / 1000.0
        final_ratio = final_duration / segment['duration']
        
        # 动态校准
        try:
            predicted_duration = tts.estimate_audio_duration_optimized(current_text, target_language, target_speed)
            tts.update_calibration(target_language, predicted_duration, final_duration)
        except Exception:
            pass
        
        # 最终检查：如果仍然超出最大限制
        if final_duration > max_audio_duration:
            logger.warning(f"最终音频时长 {final_duration:.2f}s 仍超过限制 {max_audio_duration:.2f}s")
            
            # 只进行音频截断，不再调整文本（避免过度精简）
            max_duration_ms = int(max_audio_duration * 1000)
            final_audio = final_audio[:max_duration_ms]
            # 添加淡出效果
            if len(final_audio) > 50:
                final_audio = final_audio.fade_out(50)
            final_duration = len(final_audio) / 1000.0
            final_ratio = final_duration / segment['duration']
            logger.debug(f"音频截断至 {final_duration:.2f}s")
        
        # 评估结果质量（更严格的质量控制）
        duration_diff_ms = abs(final_duration - segment['duration']) * 1000
        
        if final_ratio < 0.8:
            quality = 'poor'  # 时长比例过小
            logger.warning(f"片段 {segment['id']} 时长比例过小: {final_ratio:.3f}")
        elif final_ratio > 1.2:
            quality = 'poor'  # 时长比例过大
            logger.warning(f"片段 {segment['id']} 时长比例过大: {final_ratio:.3f}")
        elif abs(final_ratio - 1.0) <= 0.05:
            quality = 'excellent'
        elif abs(final_ratio - 1.0) <= 0.15:
            quality = 'good'
        else:
            quality = 'fair'
        
        logger.info(f"微调片段 {segment['id']} 完成: 时长比例 {final_ratio:.3f}, 语速 {target_speed:.3f}, 质量: {quality}")
        
        # 记录是否被截断
        was_truncated = final_duration < len(final_audio) / 1000.0 if 'original_audio_duration' in locals() else False
        
        return self._create_final_segment(segment, current_text, target_speed, final_audio, final_duration, final_ratio, 1, quality, was_truncated, duration_diff_ms)
    
    def _create_final_segment(self, segment: Dict[str, Any], text: str, speed: float, 
                             audio: Any, duration: float, ratio: float, 
                             iterations: int, quality: str, was_truncated: bool = False, 
                             duration_diff_ms: float = 0) -> Dict[str, Any]:
        """
        创建最终的优化片段
        
        Args:
            segment: 原始片段
            text: 优化后的文本
            speed: 最终语速
            audio: 音频数据
            duration: 实际时长
            ratio: 时长比例
            iterations: 迭代次数
            quality: 质量评级
            was_truncated: 是否被截断
            duration_diff_ms: 时长差异（毫秒）
            
        Returns:
            优化后的片段
        """
        final_segment = segment.copy()
        final_segment.update({
            'optimized_text': text,
            'final_speed': speed,
            'audio_data': audio,
            'actual_duration': duration,
            'sync_ratio': ratio,
            'iterations': iterations,
            'sync_quality': quality,
            'was_truncated': was_truncated,
            'duration_diff_ms': duration_diff_ms
        })
        
        return final_segment
    
    def _preprocess_text_for_language(self, text: str, language: str, duration: float) -> str:
        """
        基于语言特性进行预处理精简
        
        Args:
            text: 原始翻译文本
            language: 目标语言
            duration: 目标时长
            
        Returns:
            精简后的文本
        """
        expansion_factor = self.language_expansion_factors.get(language, 1.1)
        
        # 基于经验进行初步精简
        if expansion_factor > 1.05:  # 需要精简的语言
            target_reduction = (expansion_factor - 1.0) * 0.8  # 精简80%的预期膨胀
            simplified_text = self._smart_text_reduction(text, target_reduction)
            logger.debug(f"语言 {language} 预精简: {len(text)} -> {len(simplified_text)} 字符")
            return simplified_text
        
        return text
    
    def _control_speed_variation(self, segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        控制语速波动，确保整体语速波动不超过0.1
        
        Args:
            segments: 优化后的片段列表
            
        Returns:
            语速波动控制后的片段列表
        """
        if not segments:
            return segments
        
        # 计算当前语速分布
        speeds = [seg.get('final_speed', 1.0) for seg in segments]
        avg_speed = sum(speeds) / len(speeds)
        speed_range = max(speeds) - min(speeds)
        
        logger.info(f"当前语速分布: 平均 {avg_speed:.3f}, 范围 {speed_range:.3f}")
        
        # 如果语速波动超过阈值，进行调整
        if speed_range > self.max_speed_variation:
            logger.info(f"语速波动 {speed_range:.3f} 超过阈值 {self.max_speed_variation:.3f}，进行调整")
            
            # 计算目标语速范围
            target_min_speed = avg_speed - self.max_speed_variation / 2
            target_max_speed = avg_speed + self.max_speed_variation / 2
            
            # 确保目标范围在允许的语速范围内
            target_min_speed = max(target_min_speed, self.min_speed_ratio)
            target_max_speed = min(target_max_speed, self.max_speed_ratio)
            
            # 调整每个片段的语速
            for segment in segments:
                current_speed = segment.get('final_speed', 1.0)
                
                # 如果当前语速超出目标范围，进行调整
                if current_speed < target_min_speed:
                    new_speed = target_min_speed
                elif current_speed > target_max_speed:
                    new_speed = target_max_speed
                else:
                    continue  # 在范围内，不需要调整
                
                # 重新生成音频
                logger.debug(f"调整片段 {segment['id']} 语速: {current_speed:.3f} -> {new_speed:.3f}")
                segment['final_speed'] = new_speed
                
                # 注意：这里需要传入tts实例，但当前方法没有tts参数
                # 为了简化，我们只更新语速值，音频在后续步骤中重新生成
                segment['speed_adjusted'] = True
        
        return segments
    
    def _calculate_max_audio_duration(self, current_segment: Dict[str, Any], 
                                    all_segments: List[Dict[str, Any]]) -> float:
        """
        计算当前片段的最大允许音频时长
        
        Args:
            current_segment: 当前片段
            all_segments: 所有片段列表
            
        Returns:
            最大允许音频时长（秒）
        """
        try:
            segment_duration = current_segment['duration']
            segment_end = current_segment['end']
            
            # 查找下一个片段的开始时间
            next_segment_start = None
            for seg in all_segments:
                if seg['start'] > segment_end:
                    if next_segment_start is None or seg['start'] < next_segment_start:
                        next_segment_start = seg['start']
            
            if next_segment_start is not None:
                # 计算到下一段的实际间隙
                actual_gap = next_segment_start - segment_end
                
                # 动态计算可用的呼吸间隙和缓冲时间
                if actual_gap >= self.preferred_breathing_gap + self.min_overlap_buffer:
                    # 间隙足够，使用理想设置
                    usable_gap = actual_gap - self.preferred_breathing_gap - self.min_overlap_buffer
                    logger.debug(f"间隙充足 ({actual_gap:.2f}s)，使用理想呼吸间隙")
                elif actual_gap >= self.min_overlap_buffer * 2:
                    # 间隙较小，动态调整呼吸间隙
                    breathing_gap = actual_gap * 0.7  # 70%作为呼吸间隙
                    buffer_time = actual_gap * 0.3    # 30%作为缓冲
                    usable_gap = actual_gap - breathing_gap - buffer_time
                    logger.debug(f"间隙较小 ({actual_gap:.2f}s)，动态调整：呼吸间隙 {breathing_gap:.2f}s，缓冲 {buffer_time:.2f}s")
                elif actual_gap > 0:
                    # 间隙很小，只保留最小缓冲
                    usable_gap = actual_gap - self.min_overlap_buffer
                    logger.debug(f"间隙很小 ({actual_gap:.2f}s)，只保留最小缓冲 {self.min_overlap_buffer:.2f}s")
                else:
                    # 没有间隙或负间隙，音频不能超出片段边界
                    usable_gap = 0
                    logger.debug(f"无间隙或负间隙 ({actual_gap:.2f}s)，音频不能超出片段边界")
                
                # 最大音频时长 = 片段时长 + 可用间隙
                max_duration = segment_duration + max(0, usable_gap)
                
                # 确保不小于片段基本时长的80%（留一点容错空间）
                max_duration = max(max_duration, segment_duration * 0.8)
                
                logger.debug(f"片段 {current_segment['id']} 最大音频时长: {max_duration:.2f}s "
                           f"(原时长: {segment_duration:.2f}s, 实际间隙: {actual_gap:.2f}s, 可用间隙: {max(0, usable_gap):.2f}s)")
                
                return max_duration
            else:
                # 如果是最后一个片段，允许稍微超出
                max_duration = segment_duration * 1.2
                logger.debug(f"最后片段 {current_segment['id']} 最大音频时长: {max_duration:.2f}s")
                return max_duration
                
        except Exception as e:
            logger.error(f"计算最大音频时长失败: {str(e)}")
            return current_segment['duration']  # 返回原始时长作为备选
    
    def _adjust_text_with_gpt(self, text: str, target_language: str, 
                             current_ratio: float, target_ratio: float, 
                             translator) -> str:
        """
        使用GPT调整文本长度
        
        Args:
            text: 原文本
            target_language: 目标语言
            current_ratio: 当前时长比例
            target_ratio: 目标时长比例
            translator: 翻译器实例
            
        Returns:
            调整后的文本
        """
        try:
            # 判断需要压缩还是扩展
            if current_ratio > target_ratio:
                # 需要压缩文本
                compression_ratio = (current_ratio - target_ratio) / current_ratio
                action = "压缩"
                instruction = f"压缩约{compression_ratio*100:.0f}%"
            else:
                # 需要扩展文本
                expansion_ratio = (target_ratio - current_ratio) / current_ratio
                action = "扩展"
                instruction = f"扩展约{expansion_ratio*100:.0f}%"
            
            language_names = {
                'en': '英语', 'es': '西班牙语', 'fr': '法语', 
                'de': '德语', 'ja': '日语', 'ko': '韩语'
            }
            language_name = language_names.get(target_language, target_language)
            
            # 简洁的prompt
            prompt = f"""{action}{language_name}文本{instruction}，保持核心语义。

原文：{text}

调整后："""
            
            # 使用翻译器的GPT接口
            response = translator.client.chat.completions.create(
                model=translator.model,
                messages=[
                    {"role": "system", "content": "你是配音文本调整专家，擅长调整文本长度。"},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=800,  # 减少到800
                temperature=0.3
            )
            
            adjusted_text = response.choices[0].message.content.strip()
            
            # 移除可能的引号
            if adjusted_text.startswith('"') and adjusted_text.endswith('"'):
                adjusted_text = adjusted_text[1:-1]
            
            logger.debug(f"GPT文本调整: {len(text)} -> {len(adjusted_text)} 字符 ({action})")
            return adjusted_text
            
        except Exception as e:
            logger.error(f"GPT文本调整失败: {str(e)}")
            return text  # 返回原文本作为备选
    
    def _smart_text_reduction(self, text: str, reduction_ratio: float) -> str:
        """
        智能文本精简 - 多策略组合
        
        Args:
            text: 原始文本
            reduction_ratio: 精简比例 (0.1 = 精简10%)
            
        Returns:
            精简后的文本
        """
        if reduction_ratio <= 0:
            return text
        
        # 确保精简比例合理
        reduction_ratio = min(0.6, reduction_ratio)  # 最多精简60%
        
        original_length = len(text)
        target_length = int(original_length * (1 - reduction_ratio))
        
        if target_length >= original_length:
            return text
        
        # 策略1: 移除标点符号和多余空格
        import re
        cleaned_text = re.sub(r'\s+', ' ', text.strip())
        cleaned_text = re.sub(r'[,，;；:：]', '', cleaned_text)  # 移除逗号、分号、冒号
        
        if len(cleaned_text) <= target_length:
            return cleaned_text
        
        # 策略2: 移除冗余词汇
        words = cleaned_text.split()
        
        # 英语冗余词汇
        removable_words_en = ['very', 'really', 'quite', 'just', 'actually', 
                             'basically', 'literally', 'obviously', 'certainly',
                             'exactly', 'totally', 'completely', 'absolutely',
                             'definitely', 'probably', 'perhaps', 'maybe']
        
        # 西班牙语冗余词汇
        removable_words_es = ['muy', 'realmente', 'exactamente', 'totalmente',
                             'completamente', 'absolutamente', 'definitivamente',
                             'probablemente', 'quizás', 'tal vez']
        
        # 法语冗余词汇  
        removable_words_fr = ['très', 'vraiment', 'exactement', 'totalement',
                             'complètement', 'absolument', 'définitivement',
                             'probablement', 'peut-être']
        
        all_removable = removable_words_en + removable_words_es + removable_words_fr
        
        # 移除冗余词汇
        filtered_words = []
        for word in words:
            word_clean = re.sub(r'[^\w\s]', '', word.lower())
            if word_clean not in all_removable:
                filtered_words.append(word)
        
        current_text = ' '.join(filtered_words)
        
        if len(current_text) <= target_length:
            return current_text
        
        # 策略3: 保留关键词，移除修饰词
        # 简单的关键词检测（名词、动词通常更重要）
        important_words = []
        less_important = []
        
        for word in filtered_words:
            word_lower = word.lower()
            # 检测是否为连接词、介词等不太重要的词
            if word_lower in ['the', 'a', 'an', 'and', 'or', 'but', 'of', 'in', 'on', 'at', 
                             'to', 'for', 'with', 'by', 'from', 'that', 'this', 'these', 'those',
                             'el', 'la', 'los', 'las', 'un', 'una', 'y', 'o', 'pero', 'de', 'en',
                             'le', 'la', 'les', 'un', 'une', 'et', 'ou', 'mais', 'de', 'dans']:
                less_important.append(word)
            else:
                important_words.append(word)
        
        # 优先保留重要词汇
        combined_words = important_words + less_important
        
        # 策略4: 按字符长度截断，但尽量在句子边界
        current_text = ' '.join(combined_words)
        
        if len(current_text) <= target_length:
            return current_text
        
        # 在句子边界截断
        sentences = re.split(r'[.!?。！？]', current_text)
        result_text = ""
        
        for sentence in sentences:
            sentence = sentence.strip()
            if sentence and len(result_text + sentence) <= target_length:
                if result_text:
                    result_text += ". " + sentence
                else:
                    result_text = sentence
            else:
                break
        
        # 如果仍然太长，进行词汇级别的截断
        if len(result_text) > target_length and result_text:
            words = result_text.split()
            while len(' '.join(words)) > target_length and len(words) > 1:
                words.pop()
            result_text = ' '.join(words)
        
        # 确保至少保留一些内容
        if not result_text.strip():
            words = cleaned_text.split()
            result_text = ' '.join(words[:max(1, len(words) // 3)])
        
        logger.debug(f"文本精简: {original_length} -> {len(result_text)} 字符 "
                    f"(目标: {target_length}, 实际精简: {(1-len(result_text)/original_length)*100:.1f}%)")
        
        return result_text
    
    def _process_overlapping_segments(self, segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        处理重叠的音频片段
        
        Args:
            segments: 已排序的音频片段列表
            
        Returns:
            处理后的音频片段列表
        """
        if not segments:
            return segments
        
        processed_segments = []
        
        for i, segment in enumerate(segments):
            audio_data = segment['audio_data']
            audio_duration = len(audio_data) / 1000.0  # 实际音频时长
            segment_start = segment['start']
            segment_end = segment['end']
            
            # 计算音频结束时间
            audio_end_time = segment_start + audio_duration
            
            # 检查是否与下一个片段重叠
            if i < len(segments) - 1:
                next_segment = segments[i + 1]
                next_start = next_segment['start']
                
                if audio_end_time > next_start:
                    # 存在重叠，需要截断当前音频
                    overlap_duration = audio_end_time - next_start
                    allowed_duration = audio_duration - overlap_duration - self.min_overlap_buffer
                    
                    if allowed_duration > 0:
                        # 截断音频
                        allowed_duration_ms = int(allowed_duration * 1000)
                        truncated_audio = audio_data[:allowed_duration_ms]
                        
                        # 添加淡出效果以避免突然中断
                        fade_duration = min(100, allowed_duration_ms // 10)  # 最多100ms淡出
                        if fade_duration > 0:
                            truncated_audio = truncated_audio.fade_out(fade_duration)
                        
                        logger.debug(f"片段 {segment['id']} 音频截断: "
                                   f"{audio_duration:.2f}s -> {allowed_duration:.2f}s "
                                   f"(重叠: {overlap_duration:.2f}s)")
                        
                        # 更新片段的音频数据
                        processed_segment = segment.copy()
                        processed_segment['audio_data'] = truncated_audio
                        processed_segment['actual_audio_duration'] = len(truncated_audio) / 1000.0
                        processed_segments.append(processed_segment)
                    else:
                        # 重叠太严重，使用极短的音频
                        logger.warning(f"片段 {segment['id']} 重叠过严重，使用极短音频")
                        min_duration_ms = 200  # 最少200ms
                        short_audio = audio_data[:min_duration_ms].fade_out(50)
                        
                        processed_segment = segment.copy()
                        processed_segment['audio_data'] = short_audio
                        processed_segment['actual_audio_duration'] = len(short_audio) / 1000.0
                        processed_segments.append(processed_segment)
                else:
                    # 无重叠，直接使用
                    processed_segment = segment.copy()
                    processed_segment['actual_audio_duration'] = audio_duration
                    processed_segments.append(processed_segment)
            else:
                # 最后一个片段，无需检查重叠
                processed_segment = segment.copy()
                processed_segment['actual_audio_duration'] = audio_duration
                processed_segments.append(processed_segment)
        
        # 统计处理结果
        truncated_count = sum(1 for seg in processed_segments 
                            if seg.get('actual_audio_duration', 0) < len(seg['audio_data'])/1000.0)
        
        if truncated_count > 0:
            logger.info(f"处理音频重叠: {truncated_count}/{len(segments)} 个片段被截断")
        
        return processed_segments
    
    def merge_audio_segments(self, audio_segments: List[Dict[str, Any]]) -> AudioSegment:
        """
        合并优化后的音频片段，智能处理重叠问题
        
        Args:
            audio_segments: 音频片段列表
            
        Returns:
            合并后的音频
        """
        try:
            logger.info("开始合并优化后的音频片段...")
            
            if not audio_segments:
                logger.warning("没有音频片段可合并")
                return AudioSegment.silent(duration=1000)
            
            # 按时间码排序
            sorted_segments = sorted(audio_segments, key=lambda x: x['start'])
            
            # 预处理：检测和处理重叠
            processed_segments = self._process_overlapping_segments(sorted_segments)
            
            # 计算总时长
            total_duration = max(seg['end'] for seg in processed_segments)
            
            # 创建空白音频
            final_audio = AudioSegment.silent(duration=int(total_duration * 1000))
            
            # 逐个插入处理后的音频片段
            for segment in processed_segments:
                try:
                    audio_data = segment['audio_data']
                    start_ms = int(segment['start'] * 1000)
                    
                    # 使用处理后的音频（已经解决重叠问题）
                    final_audio = final_audio.overlay(audio_data, position=start_ms)
                    
                    logger.debug(f"插入片段 {segment['id']} 在 {start_ms}ms 位置，"
                               f"音频长度: {len(audio_data)/1000:.2f}s")
                    
                except Exception as e:
                    logger.error(f"插入片段 {segment['id']} 失败: {str(e)}")
                    continue
            
            logger.info("音频片段合并完成")
            return final_audio
            
        except Exception as e:
            logger.error(f"合并音频片段失败: {str(e)}")
            raise
    
    def create_optimization_report(self, segments: List[Dict[str, Any]]) -> str:
        """
        创建优化报告
        
        Args:
            segments: 优化后的片段列表
            
        Returns:
            报告文本
        """
        if not segments:
            return "无片段数据"
        
        total_segments = len(segments)
        
        # 一次遍历收集所有统计数据
        quality_counts = {'excellent': 0, 'good': 0, 'fair': 0, 'poor': 0, 'short_text': 0, 'long_text': 0, 'fallback': 0}
        speeds = []
        ratios = []
        iterations = []
        
        # 问题片段统计
        truncated_segments = []
        short_segments = []
        long_segments = []
        
        for seg in segments:
            # 质量统计
            quality = seg.get('sync_quality', 'unknown')
            if quality in quality_counts:
                quality_counts[quality] += 1
            
            # 收集数值数据
            speeds.append(seg.get('final_speed', 1.0))
            sync_ratio = seg.get('sync_ratio', 1.0)
            ratios.append(abs(sync_ratio - 1.0))
            iterations.append(seg.get('iterations', 0))
            
            # 收集问题片段
            duration_diff_ms = seg.get('duration_diff_ms', 0)
            
            # 截断的片段
            if seg.get('was_truncated', False):
                truncated_segments.append({
                    'id': seg['id'],
                    'ratio': sync_ratio,
                    'speed': seg.get('final_speed', 1.0),
                    'duration_diff_ms': duration_diff_ms,
                    'text': seg.get('optimized_text', '')[:50] + '...'
                })
            
            # 太短的片段（比例 < 0.8 且时间差异 > 500ms）
            if sync_ratio < 0.8 and duration_diff_ms > 500:
                short_segments.append({
                    'id': seg['id'],
                    'ratio': sync_ratio,
                    'speed': seg.get('final_speed', 1.0),
                    'duration_diff_ms': duration_diff_ms,
                    'text': seg.get('optimized_text', '')[:50] + '...'
                })
            
            # 太长的片段（比例 > 1.2）
            if sync_ratio > 1.2:
                long_segments.append({
                    'id': seg['id'],
                    'ratio': sync_ratio,
                    'speed': seg.get('final_speed', 1.0),
                    'duration_diff_ms': duration_diff_ms,
                    'text': seg.get('optimized_text', '')[:50] + '...'
                })
        
        # 计算平均值
        avg_iterations = sum(iterations) / total_segments
        avg_speed = sum(speeds) / total_segments
        avg_ratio_error = sum(ratios) / total_segments
        
        # 语速分布统计
        speed_distribution = {
            '0.95-1.00': sum(1 for s in speeds if 0.95 <= s < 1.00),
            '1.00-1.05': sum(1 for s in speeds if 1.00 <= s < 1.05),
            '1.05-1.10': sum(1 for s in speeds if 1.05 <= s < 1.10),
            '1.10-1.15': sum(1 for s in speeds if 1.10 <= s <= 1.15)
        }
        
        report = f"""并发循环逼近时间同步优化报告
================================

总体统计:
  - 总片段数: {total_segments}
  - 平均迭代次数: {avg_iterations:.1f}
  - 平均语速: {avg_speed:.3f}
  - 平均时长误差: {avg_ratio_error*100:.1f}%

优化质量分布:
  - 优秀 (误差<5%): {quality_counts['excellent']} 个 ({quality_counts['excellent']/total_segments*100:.1f}%)
  - 良好 (误差<15%): {quality_counts['good']} 个 ({quality_counts['good']/total_segments*100:.1f}%)
  - 一般 (误差<20%): {quality_counts['fair']} 个 ({quality_counts['fair']/total_segments*100:.1f}%)
  - 较差 (误差≥20%): {quality_counts['poor']} 个 ({quality_counts['poor']/total_segments*100:.1f}%)
  - 短文本处理: {quality_counts['short_text']} 个 ({quality_counts['short_text']/total_segments*100:.1f}%)
  - 长文本处理: {quality_counts['long_text']} 个 ({quality_counts['long_text']/total_segments*100:.1f}%)
  - 兜底方案: {quality_counts['fallback']} 个 ({quality_counts['fallback']/total_segments*100:.1f}%)

语速分布:
  - 0.95-1.00: {speed_distribution['0.95-1.00']} 片段
  - 1.00-1.05: {speed_distribution['1.00-1.05']} 片段
  - 1.05-1.10: {speed_distribution['1.05-1.10']} 片段
  - 1.10-1.15: {speed_distribution['1.10-1.15']} 片段

问题片段详情:
"""
        
        # 显示截断的片段
        if truncated_segments:
            report += f"\n📋 截断的片段 ({len(truncated_segments)} 个):\n"
            for seg in truncated_segments:
                report += f"  片段 {seg['id']}: 比例 {seg['ratio']:.3f}, 语速 {seg['speed']:.3f}, 时长差 {seg['duration_diff_ms']:.0f}ms\n"
                report += f"    文本: {seg['text']}\n"
        
        # 显示太短的片段
        if short_segments:
            report += f"\n⚠️ 太短的片段 (比例<0.8且时长差>500ms, {len(short_segments)} 个):\n"
            for seg in short_segments:
                report += f"  片段 {seg['id']}: 比例 {seg['ratio']:.3f}, 语速 {seg['speed']:.3f}, 时长差 {seg['duration_diff_ms']:.0f}ms\n"
                report += f"    文本: {seg['text']}\n"
        
        # 显示太长的片段
        if long_segments:
            report += f"\n⚠️ 太长的片段 (比例>1.2, {len(long_segments)} 个):\n"
            for seg in long_segments:
                report += f"  片段 {seg['id']}: 比例 {seg['ratio']:.3f}, 语速 {seg['speed']:.3f}, 时长差 {seg['duration_diff_ms']:.0f}ms\n"
                report += f"    文本: {seg['text']}\n"
        
        # 按质量分组显示优秀片段示例
        excellent_segments = [seg for seg in segments if seg.get('sync_quality') == 'excellent']
        if excellent_segments:
            report += f"\n✅ 优秀片段示例 ({len(excellent_segments)} 个中的前3个):\n"
            for seg in excellent_segments[:3]:
                sync_ratio = seg.get('sync_ratio', 1.0)
                error_pct = abs(sync_ratio - 1.0) * 100
                report += f"  片段 {seg['id']}: 比例 {sync_ratio:.3f} (误差 {error_pct:.1f}%), 语速 {seg.get('final_speed', 1.0):.3f}\n"
        
        return report

    def create_detailed_analysis(self, segments: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        创建详细的问题分析报告
        
        Args:
            segments: 优化后的片段列表
            
        Returns:
            详细分析数据
        """
        if not segments:
            return {"error": "无片段数据"}
        
        analysis = {
            "total_segments": len(segments),
            "truncated_segments": [],
            "short_segments": [],
            "long_segments": [],
            "extreme_ratio_segments": [],
            "quality_distribution": {},
            "speed_distribution": {},
            "summary": {}
        }
        
        quality_counts = {'excellent': 0, 'good': 0, 'fair': 0, 'poor': 0, 'short_text': 0, 'long_text': 0, 'fallback': 0}
        speeds = []
        ratios = []
        
        for seg in segments:
            quality = seg.get('sync_quality', 'unknown')
            if quality in quality_counts:
                quality_counts[quality] += 1
            
            sync_ratio = seg.get('sync_ratio', 1.0)
            speed = seg.get('final_speed', 1.0)
            duration_diff_ms = seg.get('duration_diff_ms', 0)
            
            speeds.append(speed)
            ratios.append(abs(sync_ratio - 1.0))
            
            segment_info = {
                'id': seg['id'],
                'start': seg.get('start', 0),
                'end': seg.get('end', 0),
                'duration': seg.get('duration', 0),
                'sync_ratio': sync_ratio,
                'speed': speed,
                'duration_diff_ms': duration_diff_ms,
                'text': seg.get('optimized_text', '')[:100] + '...' if len(seg.get('optimized_text', '')) > 100 else seg.get('optimized_text', ''),
                'quality': quality
            }
            
            # 截断的片段
            if seg.get('was_truncated', False):
                analysis["truncated_segments"].append(segment_info)
            
            # 太短的片段（比例 < 0.8 且时间差异 > 500ms）
            if sync_ratio < 0.8 and duration_diff_ms > 500:
                analysis["short_segments"].append(segment_info)
            
            # 太长的片段（比例 > 1.2）
            if sync_ratio > 1.2:
                analysis["long_segments"].append(segment_info)
            
            # 极端比例的片段（比例 > 2.0 或 < 0.5）
            if sync_ratio > 2.0 or sync_ratio < 0.5:
                analysis["extreme_ratio_segments"].append(segment_info)
        
        # 统计信息
        analysis["quality_distribution"] = quality_counts
        analysis["speed_distribution"] = {
            'min': min(speeds),
            'max': max(speeds),
            'avg': sum(speeds) / len(speeds),
            'distribution': {
                '0.95-1.00': sum(1 for s in speeds if 0.95 <= s < 1.00),
                '1.00-1.05': sum(1 for s in speeds if 1.00 <= s < 1.05),
                '1.05-1.10': sum(1 for s in speeds if 1.05 <= s < 1.10),
                '1.10-1.15': sum(1 for s in speeds if 1.10 <= s <= 1.15)
            }
        }
        
        analysis["summary"] = {
            'avg_ratio_error': sum(ratios) / len(ratios),
            'problematic_segments': len(analysis["truncated_segments"]) + len(analysis["short_segments"]) + len(analysis["long_segments"]),
            'quality_score': (quality_counts['excellent'] + quality_counts['good'] * 0.8 + quality_counts['fair'] * 0.6) / len(segments)
        }
        
        return analysis


# 保持原有接口兼容性
class SyncManager(AdvancedSyncManager):
    """时间同步管理器 - 保持向后兼容"""
    
    def optimize_timing(self, translated_segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        兼容原有接口的优化方法 - 现在默认使用循环逼近模式
        
        Args:
            translated_segments: 翻译后的片段列表
            
        Returns:
            优化后的片段列表
        """
        logger.info("使用循环逼近时间同步优化...")
        
        # 由于没有translator和tts实例，这里需要外部传入
        # 这个方法现在主要用于UI界面，实际处理在AdvancedSyncManager中完成
        return translated_segments
    
    def create_timing_report(self, segments: List[Dict[str, Any]]) -> str:
        """创建时间同步报告"""
        if segments and 'sync_quality' in segments[0]:
            return self.create_optimization_report(segments)
        else:
            # 兼容原有报告格式
            return f"""循环逼近时间同步报告
===================

总片段数: {len(segments)}
处理模式: 循环逼近模式
""" 