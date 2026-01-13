"""
音频合成模块
负责根据优化后的片段生成音频，并提供用户确认功能
"""

from typing import List, Dict, Any, Optional, Tuple, Union
from loguru import logger
from pydub import AudioSegment
import time
from models.segment_dto import SegmentDTO


class AudioSynthesizer:
    """音频合成器 - 负责生成音频和用户确认"""
    
    def __init__(self, config: dict, progress_callback=None):
        """
        初始化音频合成器
        
        Args:
            config: 配置字典
            progress_callback: 进度回调函数
        """
        self.config = config
        self.progress_callback = progress_callback
        
        # 音频合成参数
        self.preferred_breathing_gap = config.get('timing', {}).get('preferred_breathing_gap', 0.3)
        self.min_overlap_buffer = config.get('timing', {}).get('min_overlap_buffer', 0.05)
        
        logger.info("音频合成器初始化完成")
    
    def _report_progress(self, current: int, total: int, message: str):
        """报告进度"""
        if self.progress_callback:
            self.progress_callback(current, total, message)
        logger.info(f"进度: {current}/{total} - {message}")
    
    def generate_audio_for_confirmation(self, segments: Union[List[SegmentDTO], List[Dict]], tts, target_language: str) -> List[Dict]:
        """
        为每个优化后的片段并发生成音频，供用户确认
        
        Args:
            segments: 片段列表（支持SegmentDTO或字典格式）
            tts: TTS实例
            target_language: 目标语言
            
        Returns:
            包含音频数据的确认数据列表
        """
        # 转换为统一的SegmentDTO格式
        segment_dtos = self._normalize_segments(segments)
        logger.info(f"开始并发为 {len(segment_dtos)} 个片段生成音频")
        
        return self._generate_confirmation_audio_concurrent(segment_dtos, tts, target_language)
    
    def _normalize_segments(self, segments: Union[List[SegmentDTO], List[Dict]]) -> List[SegmentDTO]:
        """将输入片段标准化为SegmentDTO格式"""
        normalized = []
        
        for segment in segments:
            if isinstance(segment, SegmentDTO):
                normalized.append(segment)
            elif isinstance(segment, dict):
                # 从字典转换为SegmentDTO
                normalized.append(SegmentDTO.from_legacy_segment(segment))
            else:
                logger.warning(f"未知的segment类型: {type(segment)}")
                continue
        
        return normalized
    
    def _generate_confirmation_audio_concurrent(self, segments: List[SegmentDTO], tts, target_language: str) -> List[Dict]:
        """
        并发生成确认音频
        
        Args:
            segments: SegmentDTO片段列表
            tts: TTS实例
            target_language: 目标语言
            
        Returns:
            确认数据列表
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import threading
        
        # 控制并发数
        max_workers = min(6, len(segments), max(2, len(segments) // 4))
        
        results_lock = threading.Lock()
        completed_count = 0
        
        logger.info(f"启动并发确认音频生成: {max_workers}个worker处理{len(segments)}个片段")
        
        def generate_confirmation_segment(segment: SegmentDTO, index: int) -> Tuple[int, Dict]:
            """生成单个确认片段"""
            try:
                # 生成音频
                raw_audio_data = self._generate_single_audio(
                    segment.get_current_text(), 
                    segment.speech_rate, 
                    tts, 
                    target_language
                )
                
                # 在确认阶段就进行音频截断处理
                processed_audio_data = self._process_audio_for_confirmation(raw_audio_data, segment.target_duration)
                
                # 构建确认数据
                confirmation_data = {
                    'segment_id': segment.id,
                    'original_text': segment.original_text,
                    'final_text': segment.get_current_text(),
                    'target_duration': segment.target_duration,
                    'estimated_duration': segment.actual_duration or 0.0,
                    'actual_duration': len(processed_audio_data) / 1000.0,
                    'raw_audio_duration': len(raw_audio_data) / 1000.0,
                    'timing_error_ms': abs(len(processed_audio_data) / 1000.0 - segment.target_duration) * 1000,
                    'speech_rate': segment.speech_rate,
                    'quality': segment.quality or 'unknown',
                    'audio_data': processed_audio_data,
                    'raw_audio_data': raw_audio_data,
                    'segment_data': segment.to_legacy_dict(),
                    'confirmed': segment.confirmed,
                    'text_modified': False,
                    'user_modified_text': None,
                    'is_truncated': len(raw_audio_data) > segment.target_duration * 1000 + 100
                }
                
                return index, confirmation_data
                
            except Exception as e:
                logger.error(f"并发生成片段 {segment.id} 确认音频失败: {e}")
                # 创建错误确认数据
                error_data = {
                    'segment_id': segment.id,
                    'original_text': segment.original_text,
                    'final_text': segment.get_current_text(),
                    'target_duration': segment.target_duration,
                    'estimated_duration': segment.actual_duration or 0.0,
                    'actual_duration': 0,
                    'timing_error_ms': segment.timing_error_ms or 0,
                    'speech_rate': segment.speech_rate,
                    'quality': 'error',
                    'audio_data': None,
                    'segment_data': segment.to_legacy_dict(),
                    'confirmed': False,
                    'text_modified': False,
                    'user_modified_text': None,
                    'error_message': str(e)
                }
                return index, error_data
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 提交所有任务
            future_to_index = {
                executor.submit(generate_confirmation_segment, segment, i): i
                for i, segment in enumerate(segments)
            }
            
            # 收集结果
            indexed_results = {}
            for future in as_completed(future_to_index):
                index = future_to_index[future]
                try:
                    result_index, confirmation_data = future.result()
                    indexed_results[result_index] = confirmation_data
                    
                    # 线程安全的进度报告
                    with results_lock:
                        completed_count += 1
                        self._report_progress(completed_count, len(segments), 
                                            f"生成确认音频: {completed_count}/{len(segments)} (并发)")
                        
                except Exception as e:
                    logger.error(f"获取并发确认结果异常 {index}: {e}")
                    # 创建默认错误数据
                    segment = segments[index]
                    error_data = {
                        'segment_id': segment.id,
                        'original_text': segment.original_text,
                        'final_text': segment.get_current_text(),
                        'target_duration': segment.target_duration,
                        'estimated_duration': segment.actual_duration or 0.0,
                        'actual_duration': 0,
                        'timing_error_ms': segment.timing_error_ms or 0,
                        'speech_rate': segment.speech_rate,
                        'quality': 'error',
                        'audio_data': None,
                        'segment_data': segment.to_legacy_dict(),
                        'confirmed': False,
                        'text_modified': False,
                        'user_modified_text': None,
                        'error_message': str(e)
                    }
                    indexed_results[index] = error_data
            
            # 按原始顺序组织结果
            confirmation_segments = [indexed_results[i] for i in range(len(segments))]
        
        success_count = len([seg for seg in confirmation_segments if seg.get('audio_data') is not None])
        logger.info(f"并发确认音频生成完成: {success_count}/{len(segments)} 成功")
        
        return confirmation_segments
    
    def _generate_single_audio(self, text: str, speech_rate: float, tts, target_language: str) -> AudioSegment:
        """
        生成单个片段的音频
        
        Args:
            text: 文本内容
            speech_rate: 语速
            tts: TTS实例
            target_language: 目标语言
            
        Returns:
            音频数据
        """
        try:
            # 使用TTS生成音频
            audio_data = tts._generate_single_audio(
                text,
                tts.voice_map.get(target_language),
                speech_rate,
                None  # 不指定固定时长，让TTS自然生成
            )
            
            return audio_data
            
        except Exception as e:
            logger.error(f"生成音频失败: {e}")
            # 返回静音音频作为备选
            return AudioSegment.silent(duration=1000)
    
    def _process_audio_for_confirmation(self, audio_segment: AudioSegment, target_duration: float) -> AudioSegment:
        """
        在确认阶段处理音频：包括截断、淡出等处理
        
        Args:
            audio_segment: 原始音频片段
            target_duration: 目标时长（秒）
            
        Returns:
            处理后的音频片段
        """
        try:
            target_duration_ms = int(target_duration * 1000)
            current_duration_ms = len(audio_segment)
            
            if current_duration_ms <= target_duration_ms:
                # 音频时长不超过目标时长，直接返回
                logger.debug(f"音频时长 {current_duration_ms}ms <= 目标时长 {target_duration_ms}ms，无需截断")
                return audio_segment
            
            # 需要截断的情况
            logger.info(f"音频时长 {current_duration_ms}ms > 目标时长 {target_duration_ms}ms，进行智能截断")
            
            # 计算淡出长度（最后100ms进行淡出，避免突然中断）
            fade_out_duration = min(100, target_duration_ms // 10)  # 淡出时长不超过目标时长的10%
            
            # 截断到目标时长 - 使用pydub标准切片方法
            if len(audio_segment) > target_duration_ms:
                # 使用pydub的标准切片方法截断音频
                truncated_audio = audio_segment[:target_duration_ms]  # type: ignore
            else:
                truncated_audio = audio_segment
            
            # 应用淡出效果，让截断更自然
            if fade_out_duration > 0 and len(truncated_audio) > fade_out_duration:  # type: ignore
                # 在最后的淡出区间应用淡出效果
                processed_audio = truncated_audio.fade_out(fade_out_duration)  # type: ignore
            else:
                processed_audio = truncated_audio
            
            logger.debug(f"音频截断完成: {current_duration_ms}ms -> {len(processed_audio)}ms (淡出: {fade_out_duration}ms)")  # type: ignore
            return processed_audio  # type: ignore
            
        except Exception as e:
            logger.error(f"音频处理失败: {e}")
            # 降级方案：返回原音频
            return audio_segment
    
    def regenerate_audio_with_modified_text(self, confirmation_data: Dict, tts, target_language: str, use_multi_candidate: bool = True) -> Dict:
        """
        使用用户修改的文本重新生成音频（支持多候选策略）
        
        Args:
            confirmation_data: 确认数据
            tts: TTS实例
            target_language: 目标语言
            use_multi_candidate: 是否使用多候选策略（默认True）
            
        Returns:
            更新后的确认数据
        """
        if not confirmation_data.get('text_modified'):
            return confirmation_data
        
        modified_text = confirmation_data.get('user_modified_text')
        if not modified_text:
            return confirmation_data
        
        try:
            # 重新计算最优语速
            target_duration = confirmation_data.get('target_duration', 0.0)
            optimal_rate = tts.estimate_optimal_speech_rate(
                modified_text, target_language, target_duration
            )
            
            # 决定候选数量
            num_candidates = 3 if use_multi_candidate and target_duration > 1.0 else 1
            
            # 生成新的原始音频（使用多候选策略）
            raw_new_audio = self._generate_single_audio_with_candidates(
                modified_text, optimal_rate, tts, target_language, target_duration, num_candidates
            )
            
            # 应用音频处理（截断、淡出等）
            processed_new_audio = self._process_audio_for_confirmation(raw_new_audio, target_duration)
            
            # 更新确认数据
            confirmation_data.update({
                'final_text': modified_text,
                'speech_rate': optimal_rate,
                'audio_data': processed_new_audio,  # 使用处理后的音频
                'raw_audio_data': raw_new_audio,  # 保留原始音频
                'actual_duration': len(processed_new_audio) / 1000.0,
                'raw_audio_duration': len(raw_new_audio) / 1000.0,
                'timing_error_ms': abs(len(processed_new_audio) / 1000.0 - target_duration) * 1000,
                'is_truncated': len(raw_new_audio) > target_duration * 1000 + 100,
                'text_modified': False,  # 重置修改标志
                'user_modified_text': None,
                'candidates_used': num_candidates  # 记录使用的候选数
            })
            
            logger.info(f"重新生成片段 {confirmation_data.get('segment_id', 'unknown')} 音频成功 (候选数={num_candidates})：" +
                       f"原始时长 {len(raw_new_audio)/1000:.2f}s -> 处理后时长 {len(processed_new_audio)/1000:.2f}s")
            
        except Exception as e:
            logger.error(f"重新生成音频失败: {e}")
            confirmation_data['error_message'] = str(e)
        
        return confirmation_data
    
    def _generate_single_audio_with_candidates(
        self, 
        text: str, 
        speech_rate: float, 
        tts, 
        target_language: str,
        target_duration: float,
        num_candidates: int = 3
    ) -> AudioSegment:
        """
        生成音频（支持多候选选优）
        
        Args:
            text: 文本内容
            speech_rate: 语速
            tts: TTS实例
            target_language: 目标语言
            target_duration: 目标时长
            num_candidates: 候选数量
            
        Returns:
            最佳匹配的音频数据
        """
        try:
            if num_candidates > 1 and hasattr(tts, '_generate_audio_with_best_match'):
                # 使用多候选策略
                voice_id = tts.get_voice_id(target_language)
                audio_data = tts._generate_audio_with_best_match(
                    text, voice_id, speech_rate, target_duration, num_candidates
                )
                return audio_data
            else:
                # 单次生成
                return self._generate_single_audio(text, speech_rate, tts, target_language)
                
        except Exception as e:
            logger.error(f"多候选音频生成失败: {e}")
            # 回退到单次生成
            return self._generate_single_audio(text, speech_rate, tts, target_language)
    
    def merge_confirmed_audio_segments(self, confirmed_segments: List[Dict]) -> AudioSegment:
        """
        合并用户确认后的音频片段（带安全间隙检查）
        
        Args:
            confirmed_segments: 用户确认后的片段列表
            
        Returns:
            合并后的音频
        """
        try:
            logger.info("开始合并确认后的音频片段...")
            
            if not confirmed_segments:
                logger.warning("没有音频片段可合并")
                return AudioSegment.silent(duration=1000)
            
            # 过滤出已确认且有音频数据的片段
            valid_segments = [
                seg for seg in confirmed_segments 
                if seg.get('confirmed', False) and seg.get('audio_data') is not None
            ]
            
            logger.info(f"有效片段数: {len(valid_segments)}/{len(confirmed_segments)}")
            
            if not valid_segments:
                logger.warning("没有有效的音频片段")
                return AudioSegment.silent(duration=1000)
            
            # 按时间码排序
            def get_start_time(seg):
                if 'segment_data' in seg and seg['segment_data']:
                    return seg['segment_data'].get('start', 0)
                return seg.get('start', seg.get('start_time', 0))
            
            def get_end_time(seg):
                if 'segment_data' in seg and seg['segment_data']:
                    return seg['segment_data'].get('end', 0)
                return seg.get('end', seg.get('end_time', 0))
            
            sorted_segments = sorted(valid_segments, key=get_start_time)
            
            # 安全间隙检查与自动截断
            sorted_segments = self._apply_safety_truncation(sorted_segments, get_start_time, get_end_time)
            
            # 计算总时长
            total_duration = max(get_end_time(seg) for seg in sorted_segments) if sorted_segments else 0
            
            if total_duration <= 0:
                total_duration = sum(len(seg.get('audio_data', AudioSegment.empty())) / 1000.0 for seg in sorted_segments)
            
            # 创建空白音频
            final_audio = AudioSegment.silent(duration=int(total_duration * 1000))
            
            logger.info(f"合并 {len(sorted_segments)} 个片段，总时长: {total_duration:.2f}s")
            
            # 逐个插入音频片段
            for segment in sorted_segments:
                try:
                    audio_data = segment.get('audio_data')
                    if audio_data is None:
                        continue
                    
                    start_time = get_start_time(segment)
                    start_ms = int(start_time * 1000)
                    
                    if start_ms >= len(final_audio):
                        continue
                    
                    final_audio = final_audio.overlay(audio_data, position=start_ms)
                    
                except Exception as e:
                    logger.error(f"插入片段失败: {e}")
                    continue
            
            logger.info(f"合并完成，最终时长: {len(final_audio)/1000:.2f}s")
            return final_audio
            
        except Exception as e:
            logger.error(f"合并音频片段失败: {e}")
            raise
    
    def _apply_safety_truncation(self, sorted_segments: List[Dict], get_start_time, get_end_time) -> List[Dict]:
        """
        应用安全截断：确保每个片段不会侵入下一个片段的时间窗口
        
        Args:
            sorted_segments: 按时间排序的片段列表
            get_start_time: 获取开始时间的函数
            get_end_time: 获取结束时间的函数
            
        Returns:
            处理后的片段列表
        """
        if len(sorted_segments) <= 1:
            return sorted_segments
        
        processed_segments = []
        overlap_warnings = []
        
        for i, segment in enumerate(sorted_segments):
            audio_data = segment.get('audio_data')
            if audio_data is None:
                processed_segments.append(segment)
                continue
            
            seg_id = segment.get('segment_id', segment.get('id', f'seg_{i}'))
            start_time = get_start_time(segment)
            end_time = get_end_time(segment)  # 字幕结束时间（允许的最大时间窗口）
            audio_duration_ms = len(audio_data)
            audio_end_time = start_time + audio_duration_ms / 1000.0
            
            # 计算允许的最大时长（到下一个片段开始前，保留安全间隙）
            if i < len(sorted_segments) - 1:
                next_start = get_start_time(sorted_segments[i + 1])
                max_allowed_end = next_start - self.min_overlap_buffer  # 保留50ms安全间隙
            else:
                max_allowed_end = float('inf')  # 最后一个片段无限制
            
            # 检查是否需要截断
            need_truncate = False
            truncate_reason = ""
            
            # 情况1：音频超出字幕结束时间
            if audio_end_time > end_time + 0.1:  # 允许100ms容差
                need_truncate = True
                truncate_reason = f"超出字幕窗口({audio_end_time:.2f}s > {end_time:.2f}s)"
            
            # 情况2：音频会侵入下一个片段
            if audio_end_time > max_allowed_end:
                need_truncate = True
                truncate_reason = f"侵入下一片段({audio_end_time:.2f}s > {max_allowed_end:.2f}s)"
                overlap_warnings.append(seg_id)
            
            if need_truncate:
                # 计算安全的最大时长
                safe_end = min(end_time, max_allowed_end)
                safe_duration_ms = int((safe_end - start_time) * 1000)
                
                if safe_duration_ms > 0 and safe_duration_ms < audio_duration_ms:
                    # 截断并添加淡出
                    fade_duration = min(100, safe_duration_ms // 10)
                    truncated_audio = audio_data[:safe_duration_ms]
                    if fade_duration > 0:
                        truncated_audio = truncated_audio.fade_out(fade_duration)
                    
                    logger.warning(f"⚠️ 片段{seg_id}安全截断: {audio_duration_ms}ms → {safe_duration_ms}ms ({truncate_reason})")
                    
                    # 更新segment的音频数据
                    segment = segment.copy()
                    segment['audio_data'] = truncated_audio
                    segment['safety_truncated'] = True
                    segment['original_duration_ms'] = audio_duration_ms
            
            processed_segments.append(segment)
        
        if overlap_warnings:
            logger.warning(f"⚠️ {len(overlap_warnings)}个片段因重叠风险被截断: {overlap_warnings[:5]}{'...' if len(overlap_warnings) > 5 else ''}")
        
        return processed_segments
    
    def create_confirmation_report(self, confirmation_segments: List[Dict]) -> str:
        """
        创建用户确认报告
        
        Args:
            confirmation_segments: 确认片段列表
            
        Returns:
            报告文本
        """
        if not confirmation_segments:
            return "无确认数据"
        
        total_segments = len(confirmation_segments)
        confirmed_count = sum(1 for seg in confirmation_segments if seg.get('confirmed', False))
        modified_count = sum(1 for seg in confirmation_segments if seg.get('text_modified', False))
        
        # 统计质量分布
        quality_counts = {'excellent': 0, 'good': 0, 'fair': 0, 'poor': 0, 'error': 0}
        for seg in confirmation_segments:
            quality = seg.get('quality', 'unknown')
            if quality in quality_counts:
                quality_counts[quality] += 1
        
        # 计算平均误差
        errors = [seg.get('timing_error_ms', 0) for seg in confirmation_segments if seg.get('timing_error_ms') is not None]
        avg_error = sum(errors) / len(errors) if errors else 0
        
        report = f"""用户确认报告
================

总体统计:
  - 总片段数: {total_segments}
  - 已确认片段: {confirmed_count} ({confirmed_count/total_segments*100:.1f}%)
  - 文本修改片段: {modified_count} ({modified_count/total_segments*100:.1f}%)
  - 平均时长误差: {avg_error:.0f}ms

质量分布:
  - 优秀 (误差<5%): {quality_counts['excellent']} 个
  - 良好 (误差<15%): {quality_counts['good']} 个
  - 一般 (误差<20%): {quality_counts['fair']} 个
  - 较差 (误差≥20%): {quality_counts['poor']} 个
  - 错误: {quality_counts['error']} 个

确认状态:
  - 待确认: {total_segments - confirmed_count} 个
  - 已确认: {confirmed_count} 个
"""
        
        return report 