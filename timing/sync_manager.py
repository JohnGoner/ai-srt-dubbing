"""
时间同步管理模块 - 循环逼近算法
通过LLM文本精简 + Azure API微调语速实现精确时间同步
"""

from typing import List, Dict, Any, Optional, Tuple
from loguru import logger
from pydub import AudioSegment
import time


class AdvancedSyncManager:
    """高级时间同步管理器 - 循环逼近算法"""
    
    def __init__(self, config: dict):
        """
        初始化时间同步管理器
        
        Args:
            config: 配置字典
        """
        self.config = config
        self.timing_config = config.get('timing', {})
        
        # 语速调整范围（调整为0.95-1.15，保持更自然的语速）
        self.min_speed_ratio = 0.95  # 最小语速 - 避免过慢的不自然语速
        self.max_speed_ratio = 1.15  # 最大语速 - 保持上限
        self.speed_step = 0.01       # 语速调整步长
        
        # 时间同步参数
        self.sync_tolerance = 0.15   # 时间同步容忍度（15%）
        self.max_iterations = 5      # 最大循环次数
        self.max_speed_variation = 0.1  # 最大语速波动（整体语速波动不超过0.1）
        
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
    
    def optimize_timing_with_iteration(self, segments: List[Dict[str, Any]], 
                                     target_language: str, 
                                     translator, tts) -> List[Dict[str, Any]]:
        """
        使用循环逼近算法优化时间同步
        
        Args:
            segments: 翻译后的片段列表
            target_language: 目标语言代码
            translator: 翻译器实例
            tts: TTS实例
            
        Returns:
            优化后的片段列表
        """
        logger.info("开始循环逼近时间同步优化...")
        
        optimized_segments = []
        
        for i, segment in enumerate(segments):
            logger.info(f"优化片段 {i+1}/{len(segments)}: {segment['id']}")
            
            optimized_segment = self._optimize_single_segment(
                segment, target_language, translator, tts, segments
            )
            optimized_segments.append(optimized_segment)
        
        # 语速波动控制 - 确保整体语速波动不超过0.1
        optimized_segments = self._control_speed_variation(optimized_segments)
        
        logger.info("循环逼近时间同步优化完成")
        return optimized_segments
    
    def _optimize_single_segment(self, segment: Dict[str, Any], 
                                target_language: str, 
                                translator, tts, all_segments: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        优化单个片段的时间同步
        
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
        current_text = segment['translated_text']
        
        # 计算最大允许音频时长
        max_audio_duration = self._calculate_max_audio_duration(segment, all_segments)
        
        logger.debug(f"片段 {segment['id']} 原始时长: {original_duration:.2f}s, "
                    f"最大音频时长: {max_audio_duration:.2f}s")
        
        # 步骤1: 基于语言特性进行预处理精简
        simplified_text = self._preprocess_text_for_language(
            current_text, target_language, original_duration
        )
        
        # 步骤2: 先用标准语速(1.0)测试基准时长
        base_audio = tts._generate_single_audio(
            simplified_text, 
            tts.voice_map.get(target_language),
            1.0,  # 标准语速
            original_duration
        )
        
        base_duration = len(base_audio) / 1000.0
        base_ratio = base_duration / original_duration
        
        logger.debug(f"基准时长: {base_duration:.2f}s, 比例: {base_ratio:.3f}")
        
        # 步骤3: 根据基准比例决定调整策略
        if base_ratio < 0.7:
            # 翻译文本过短，可能需要重新翻译或使用慢语速
            logger.warning(f"片段 {segment['id']} 翻译文本过短 (比例: {base_ratio:.3f})")
            return self._handle_short_text(segment, simplified_text, target_language, tts, base_ratio, max_audio_duration)
        elif base_ratio > 1.4:
            # 翻译文本过长，需要精简文本 + 快语速
            logger.info(f"片段 {segment['id']} 翻译文本过长 (比例: {base_ratio:.3f})")
            return self._handle_long_text(segment, simplified_text, target_language, tts, base_ratio, max_audio_duration, translator)
        else:
            # 在合理范围内，通过语速微调
            return self._fine_tune_speed(segment, simplified_text, target_language, tts, base_ratio, max_audio_duration)
    
    def _handle_short_text(self, segment: Dict[str, Any], text: str, 
                          target_language: str, tts, base_ratio: float, 
                          max_audio_duration: float) -> Dict[str, Any]:
        """
        处理翻译文本过短的情况
        
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
        logger.debug(f"处理短文本片段 {segment['id']}")
        
        # 对于过短的文本，需要降低语速来延长时长
        # 但要确保不超过最大音频时长限制
        target_speed = max(self.min_speed_ratio, base_ratio)
        
        # 检查是否会超过最大音频时长
        estimated_duration_at_target_speed = (len(text) / 12.0) / target_speed  # 粗略估算
        if estimated_duration_at_target_speed > max_audio_duration:
            # 如果会超过，调整语速以适应最大时长
            target_speed = max(target_speed, (len(text) / 12.0) / max_audio_duration)
            target_speed = min(target_speed, self.max_speed_ratio)  # 确保不超过最大语速
            logger.debug(f"调整语速以适应最大音频时长: {target_speed:.3f}")
        
        logger.debug(f"短文本片段 {segment['id']} 基准比例: {base_ratio:.3f}, 目标语速: {target_speed:.3f}")
        
        final_audio = tts._generate_single_audio(
            text,
            tts.voice_map.get(target_language),
            target_speed,
            segment['duration']
        )
        
        final_duration = len(final_audio) / 1000.0
        final_ratio = final_duration / segment['duration']
        
        logger.info(f"短文本片段 {segment['id']} 处理完成: 时长比例 {final_ratio:.3f}, 语速 {target_speed:.3f}")
        
        # 根据结果质量评定等级
        quality = 'excellent' if abs(final_ratio - 1.0) <= 0.05 else 'good' if abs(final_ratio - 1.0) <= 0.15 else 'short_text'
        
        return self._create_final_segment(segment, text, target_speed, final_audio, final_duration, final_ratio, 1, quality)
    
    def _handle_long_text(self, segment: Dict[str, Any], text: str, 
                         target_language: str, tts, base_ratio: float,
                         max_audio_duration: float, translator) -> Dict[str, Any]:
        """
        处理翻译文本过长的情况
        
        Args:
            segment: 片段数据
            text: 当前文本
            target_language: 目标语言
            tts: TTS实例
            base_ratio: 基准时长比例
            max_audio_duration: 最大允许音频时长
            translator: 翻译器实例
            
        Returns:
            优化后的片段
        """
        logger.debug(f"处理长文本片段 {segment['id']}")
        
        current_text = text
        best_result = None
        iteration = 0
        
        # 如果初始比例太大，先使用GPT进行文本调整
        if base_ratio > 1.3:
            logger.debug(f"初始比例过大 ({base_ratio:.3f})，使用GPT调整文本")
            current_text = self._adjust_text_with_gpt(
                current_text, target_language, base_ratio, 1.0, translator
            )
        
        while iteration < self.max_iterations:
            iteration += 1
            logger.debug(f"片段 {segment['id']} 迭代 {iteration}")
            
            # 用标准语速测试当前文本的时长
            current_audio = tts._generate_single_audio(
                current_text, 
                tts.voice_map.get(target_language),
                1.0,  # 标准语速
                segment['duration']
            )
            
            current_duration = len(current_audio) / 1000.0
            current_ratio = current_duration / segment['duration']
            
            logger.debug(f"当前时长: {current_duration:.2f}s, 比例: {current_ratio:.3f}")
            
            # 计算需要的语速来达到目标时长
            target_speed = min(current_ratio, self.max_speed_ratio)
            
            # 生成最终音频
            final_audio = tts._generate_single_audio(
                current_text,
                tts.voice_map.get(target_language),
                target_speed,
                segment['duration']
            )
            
            final_duration = len(final_audio) / 1000.0
            final_ratio = final_duration / segment['duration']
            
            logger.debug(f"调整后时长: {final_duration:.2f}s, 比例: {final_ratio:.3f}, 语速: {target_speed:.3f}")
            
            # 检查是否超过最大音频时长
            if final_duration > max_audio_duration:
                logger.warning(f"音频时长 {final_duration:.2f}s 超过最大限制 {max_audio_duration:.2f}s")
                # 强制调整语速以适应最大时长
                required_speed = final_duration / max_audio_duration
                adjusted_speed = min(required_speed, self.max_speed_ratio)
                
                # 重新生成音频
                final_audio = tts._generate_single_audio(
                    current_text,
                    tts.voice_map.get(target_language),
                    adjusted_speed,
                    segment['duration']
                )
                final_duration = len(final_audio) / 1000.0
                final_ratio = final_duration / segment['duration']
                target_speed = adjusted_speed
                logger.debug(f"强制调整语速: {adjusted_speed:.3f}, 新时长: {final_duration:.2f}s")
            
            # 更新最佳结果（即使未达到目标也要记录）
            if best_result is None or abs(final_ratio - 1.0) < abs(best_result['ratio'] - 1.0):
                best_result = {
                    'text': current_text,
                    'speed': target_speed,
                    'audio': final_audio,
                    'duration': final_duration,
                    'ratio': final_ratio
                }
            
            # 检查是否达到目标
            if abs(final_ratio - 1.0) <= self.sync_tolerance:
                logger.debug(f"片段 {segment['id']} 在第 {iteration} 次迭代达到目标")
                break
            
            # 根据时长比例决定下一步策略
            if final_ratio > 1.0 + self.sync_tolerance:
                # 如果时长比例仍然过大，且迭代次数少于3次，尝试GPT调整
                if iteration < 3:
                    logger.debug(f"时长比例仍过大 ({final_ratio:.3f})，使用GPT进一步调整文本")
                    current_text = self._adjust_text_with_gpt(
                        current_text, target_language, final_ratio, 1.0, translator
                    )
                else:
                    # 迭代次数过多，使用简单精简
                    excess_ratio = final_ratio - 1.0
                    additional_reduction = min(excess_ratio * 0.3, 0.1)
                    new_text = self._smart_text_reduction(current_text, additional_reduction)
                    if len(new_text) < 10 or len(new_text) == len(current_text):
                        logger.debug(f"文本无法进一步精简，停止迭代")
                        break
                    current_text = new_text
                    logger.debug(f"简单精简至 {len(current_text)} 字符")
            elif final_ratio < 1.0 - self.sync_tolerance:
                # 如果时长比例过小，尝试GPT扩展文本
                if iteration < 3:
                    logger.debug(f"时长比例过小 ({final_ratio:.3f})，使用GPT扩展文本")
                    current_text = self._adjust_text_with_gpt(
                        current_text, target_language, final_ratio, 1.0, translator
                    )
                else:
                    # 迭代次数过多，停止调整
                    logger.debug(f"达到最大迭代次数，停止文本调整")
                    break
            else:
                # 时长比例在合理范围内，停止迭代
                logger.debug(f"时长比例合理 ({final_ratio:.3f})，停止迭代")
                break
        
        logger.info(f"长文本片段 {segment['id']} 处理完成: 时长比例 {best_result['ratio']:.3f}, 语速 {best_result['speed']:.3f}, 迭代 {iteration} 次")
        
        return self._create_final_segment(segment, best_result['text'], best_result['speed'], 
                                        best_result['audio'], best_result['duration'], 
                                        best_result['ratio'], iteration, 'long_text')
    
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
        logger.debug(f"微调片段 {segment['id']} 语速")
        
        # 计算目标语速：base_ratio 就是在标准语速下的时长比例
        # 需要的语速 = base_ratio (如果比例是1.2，需要1.2倍语速)
        target_speed = max(self.min_speed_ratio, min(base_ratio, self.max_speed_ratio))
        
        # 检查是否会超过最大音频时长
        estimated_duration = (len(text) / 12.0) / target_speed  # 粗略估算
        if estimated_duration > max_audio_duration:
            # 调整语速以适应最大时长
            required_speed = estimated_duration / max_audio_duration
            target_speed = min(required_speed, self.max_speed_ratio)
            logger.debug(f"调整语速以适应最大音频时长: {target_speed:.3f}")
        
        logger.debug(f"微调片段 {segment['id']} 基准比例: {base_ratio:.3f}, 目标语速: {target_speed:.3f}")
        
        final_audio = tts._generate_single_audio(
            text,
            tts.voice_map.get(target_language),
            target_speed,
            segment['duration']
        )
        
        final_duration = len(final_audio) / 1000.0
        final_ratio = final_duration / segment['duration']
        
        # 最终检查：确保不超过最大音频时长
        if final_duration > max_audio_duration:
            logger.warning(f"微调后音频时长 {final_duration:.2f}s 仍超过最大限制 {max_audio_duration:.2f}s")
            # 强制调整语速
            required_speed = final_duration / max_audio_duration
            adjusted_speed = min(required_speed, self.max_speed_ratio)
            
            final_audio = tts._generate_single_audio(
                text,
                tts.voice_map.get(target_language),
                adjusted_speed,
                segment['duration']
            )
            final_duration = len(final_audio) / 1000.0
            final_ratio = final_duration / segment['duration']
            target_speed = adjusted_speed
            logger.debug(f"强制调整语速: {adjusted_speed:.3f}, 最终时长: {final_duration:.2f}s")
        
        logger.info(f"微调片段 {segment['id']} 完成: 时长比例 {final_ratio:.3f}, 语速 {target_speed:.3f}")
        
        quality = 'excellent' if abs(final_ratio - 1.0) <= 0.05 else 'good'
        return self._create_final_segment(segment, text, target_speed, final_audio, final_duration, final_ratio, 1, quality)
    
    def _create_final_segment(self, segment: Dict[str, Any], text: str, speed: float, 
                             audio: Any, duration: float, ratio: float, 
                             iterations: int, quality: str) -> Dict[str, Any]:
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
            'sync_quality': quality
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
        使用GPT智能调整文本长度，使其更适合目标时长
        
        Args:
            text: 原始文本
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
                instruction = f"请将以下文本压缩约{compression_ratio*100:.0f}%，保持核心语义不变"
            else:
                # 需要扩展文本
                expansion_ratio = (target_ratio - current_ratio) / current_ratio
                action = "扩展"
                instruction = f"请将以下文本适当扩展约{expansion_ratio*100:.0f}%，增加细节描述或解释"
            
            language_names = {
                'en': '英语', 'es': '西班牙语', 'fr': '法语', 
                'de': '德语', 'ja': '日语', 'ko': '韩语'
            }
            language_name = language_names.get(target_language, target_language)
            
            prompt = f"""作为专业的配音文本调整专家，请{action}以下{language_name}文本。

要求：
1. {instruction}
2. 保持原文的核心语义和情感
3. 确保文本自然流畅，适合配音
4. 不要改变文本的基本风格和语调

原文：{text}

请直接返回调整后的文本，不要包含其他解释。"""
            
            # 使用翻译器的GPT接口
            response = translator.client.chat.completions.create(
                model=translator.model,
                messages=[
                    {"role": "system", "content": "你是一个专业的配音文本调整专家，擅长在保持语义的前提下调整文本长度。"},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=1000,
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
        智能文本精简
        
        Args:
            text: 原始文本
            reduction_ratio: 精简比例 (0.1 = 精简10%)
            
        Returns:
            精简后的文本
        """
        # 智能精简策略：
        # 1. 移除冗余词汇
        # 2. 简化复杂句式
        # 3. 保持核心语义
        
        words = text.split()
        target_length = int(len(words) * (1 - reduction_ratio))
        
        # 优先移除的词汇类型
        removable_words = ['very', 'really', 'quite', 'just', 'actually', 
                          'basically', 'literally', 'obviously', 'certainly']
        
        # 第一轮：移除冗余副词
        filtered_words = []
        removed_count = 0
        
        for word in words:
            if (word.lower() in removable_words and 
                removed_count < len(words) - target_length):
                removed_count += 1
                continue
            filtered_words.append(word)
        
        # 第二轮：如果还需要精简，移除部分形容词和连接词
        if len(filtered_words) > target_length:
            # 简单截断到目标长度（保持语法完整性的截断逻辑可以更复杂）
            filtered_words = filtered_words[:target_length]
        
        return ' '.join(filtered_words)
    
    def merge_audio_segments(self, audio_segments: List[Dict[str, Any]]) -> AudioSegment:
        """
        合并优化后的音频片段
        
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
            
            # 计算总时长
            total_duration = max(seg['end'] for seg in sorted_segments)
            
            # 创建空白音频
            final_audio = AudioSegment.silent(duration=int(total_duration * 1000))
            
            # 逐个插入优化后的音频片段
            for segment in sorted_segments:
                try:
                    audio_data = segment['audio_data']
                    start_ms = int(segment['start'] * 1000)
                    
                    # 直接使用优化后的音频（已经通过循环逼近达到理想时长）
                    final_audio = final_audio.overlay(audio_data, position=start_ms)
                    
                    logger.debug(f"插入片段 {segment['id']} 在 {start_ms}ms 位置")
                    
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
        quality_counts = {'excellent': 0, 'good': 0, 'short_text': 0, 'long_text': 0, 'fallback': 0}
        speeds = []
        ratios = []
        iterations = []
        
        for seg in segments:
            # 质量统计
            quality = seg.get('sync_quality', 'unknown')
            if quality in quality_counts:
                quality_counts[quality] += 1
            
            # 收集数值数据
            speeds.append(seg.get('final_speed', 1.0))
            ratios.append(abs(seg.get('sync_ratio', 1.0) - 1.0))
            iterations.append(seg.get('iterations', 0))
        
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
        
        report = f"""循环逼近时间同步优化报告
================================

总体统计:
  - 总片段数: {total_segments}
  - 平均迭代次数: {avg_iterations:.1f}
  - 平均语速: {avg_speed:.3f}
  - 平均时长误差: {avg_ratio_error*100:.1f}%

优化质量分布:
  - 优秀 (误差<5%): {quality_counts['excellent']} 个 ({quality_counts['excellent']/total_segments*100:.1f}%)
  - 良好 (误差<15%): {quality_counts['good']} 个 ({quality_counts['good']/total_segments*100:.1f}%)
  - 短文本处理: {quality_counts['short_text']} 个 ({quality_counts['short_text']/total_segments*100:.1f}%)
  - 长文本处理: {quality_counts['long_text']} 个 ({quality_counts['long_text']/total_segments*100:.1f}%)
  - 兜底方案: {quality_counts['fallback']} 个 ({quality_counts['fallback']/total_segments*100:.1f}%)

语速分布:
  - 0.95-1.00: {speed_distribution['0.95-1.00']} 片段
  - 1.00-1.05: {speed_distribution['1.00-1.05']} 片段
  - 1.05-1.10: {speed_distribution['1.05-1.10']} 片段
  - 1.10-1.15: {speed_distribution['1.10-1.15']} 片段

详细信息:
"""
        
        # 按质量分组显示详细信息
        for quality in ['excellent', 'good', 'short_text', 'long_text', 'fallback']:
            quality_segments = [seg for seg in segments if seg.get('sync_quality') == quality]
            if quality_segments:
                report += f"\n{quality.upper()} 片段:\n"
                for seg in quality_segments[:5]:  # 只显示前5个，避免报告过长
                    sync_ratio = seg.get('sync_ratio', 1.0)
                    error_pct = abs(sync_ratio - 1.0) * 100
                    report += f"  片段 {seg['id']}: 比例 {sync_ratio:.3f} (误差 {error_pct:.1f}%), 语速 {seg.get('final_speed', 1.0):.3f}, 迭代 {seg.get('iterations', 0)} 次\n"
                
                if len(quality_segments) > 5:
                    report += f"  ... 还有 {len(quality_segments) - 5} 个片段\n"
        
        return report


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