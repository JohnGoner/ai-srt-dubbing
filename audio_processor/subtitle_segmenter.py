"""
智能字幕分段模块
使用大语言模型分析SRT字幕文件，将零碎的小句子重新组织成逻辑完整的段落
"""

from openai import OpenAI
from typing import List, Dict, Any, Optional
from loguru import logger
import json
import re
import time


class SubtitleSegmenter:
    """智能字幕分段器"""
    
    def __init__(self, config: dict, progress_callback=None):
        """
        初始化字幕分段器
        
        Args:
            config: 配置字典
            progress_callback: 进度回调函数，格式为 callback(current, total, message)
        """
        self.config = config
        self.translation_config = config.get('translation', {})
        self.use_kimi = self.translation_config.get('use_kimi', False)
        
        # 根据配置选择API
        if self.use_kimi:
            self.api_key = config.get('api_keys', {}).get('kimi_api_key')
            self.base_url = config.get('api_keys', {}).get('kimi_base_url', 'https://api.moonshot.cn/v1')
            self.model = self.translation_config.get('segmentation_model', 'kimi-k2-0711-preview')
            # 如果没有专门的分段模型配置，使用主模型
            if not self.translation_config.get('segmentation_model'):
                self.model = self.translation_config.get('model', 'kimi-k2-0711-preview')
            self.max_tokens = self.translation_config.get('max_tokens', 8000)
            logger.info(f"字幕分段器使用Kimi API，模型: {self.model}")
        else:
            self.api_key = config.get('api_keys', {}).get('openai_api_key')
            self.base_url = None
            self.model = self.translation_config.get('segmentation_model', 'gpt-3.5-turbo')
            # 如果没有专门的分段模型配置，使用主模型
            if not self.translation_config.get('segmentation_model'):
                self.model = self.translation_config.get('model', 'gpt-4o')
            self.max_tokens = self.translation_config.get('max_tokens', 4000)
            logger.info(f"字幕分段器使用OpenAI API，模型: {self.model}")
        
        self.temperature = 0.3  # 使用较低的温度以确保逻辑性
        
        # 创建客户端
        if self.use_kimi:
            self.client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url
            )
        else:
            self.client = OpenAI(api_key=self.api_key)
        
        # 进度回调
        self.progress_callback = progress_callback
        
        # 基于字符数的分段参数（针对中文）
        self.char_limits = {
            'zh': {
                'min_chars': 15,      # 最少15个字符（约5个汉字）
                'max_chars': 120,     # 最多120个字符（约40个汉字）
                'ideal_chars': 60,    # 理想60个字符（约20个汉字）
                'chars_per_second': 3.5  # 中文朗读速度：每秒3.5个字符
            },
            'en': {
                'min_chars': 30,      # 最少30个字符（约6个单词）
                'max_chars': 200,     # 最多200个字符（约40个单词）
                'ideal_chars': 100,   # 理想100个字符（约20个单词）
                'chars_per_second': 12  # 英文朗读速度：每秒12个字符
            },
            'default': {
                'min_chars': 20,
                'max_chars': 150,
                'ideal_chars': 80,
                'chars_per_second': 8
            }
        }
        
        # 使用中文作为默认语言
        self.current_lang = 'zh'
        self.min_chars = self.char_limits[self.current_lang]['min_chars']
        self.max_chars = self.char_limits[self.current_lang]['max_chars']
        self.ideal_chars = self.char_limits[self.current_lang]['ideal_chars']
        
        # 保留时长参数作为辅助验证
        self.min_segment_duration = 3.0
        self.max_segment_duration = 12.0
        self.ideal_segment_duration = 8.0
        
        # 分段点识别模式
        self.segment_break_patterns = [
            r'[。！？]',      # 句末标点
            r'[，；：]',      # 句中标点
            r'[、]',          # 顿号
            r'[\s]',          # 空格
        ]
        
        # 性能优化参数
        if self.use_kimi:
            self.batch_size = 12
            self.request_delay = 0.3
        else:
            self.batch_size = 10
            self.request_delay = 0.1
    
    def _report_progress(self, current: int, total: int, message: str):
        """报告进度"""
        if self.progress_callback:
            try:
                self.progress_callback(current, total, message)
            except Exception as e:
                logger.warning(f"进度回调失败: {str(e)}")
    
    def segment_subtitles(self, segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        智能分段字幕
        
        Args:
            segments: 原始字幕片段列表
            
        Returns:
            重新分段后的字幕片段列表
        """
        try:
            logger.info(f"开始智能分段处理，原始片段数: {len(segments)}")
            self._report_progress(0, 100, "开始智能分段分析...")
            
            # 第一步：基于字符数的预分段
            self._report_progress(10, 100, "正在进行字符数分段...")
            char_based_segments = self._segment_by_character_count(segments)
            
            # 第二步：分析字幕内容和结构
            self._report_progress(30, 100, "正在分析字幕内容和结构...")
            content_analysis = self._analyze_subtitle_content(char_based_segments)
            
            # 第三步：如果需要，使用LLM进行智能优化
            if content_analysis.get('needs_ai_optimization', False):
                self._report_progress(50, 100, "正在使用AI优化分段...")
                ai_optimized_groups = self._intelligent_segmentation(char_based_segments, content_analysis)
                new_segments = self._build_new_segments(ai_optimized_groups)
            else:
                self._report_progress(50, 100, "字符数分段已满足要求，跳过AI优化...")
                new_segments = char_based_segments
            
            # 第四步：最终优化和验证
            self._report_progress(80, 100, "正在优化和验证分段结果...")
            optimized_segments = self._optimize_segments(new_segments)
            
            # 第五步：字符数验证
            self._report_progress(90, 100, "正在验证字符数限制...")
            final_segments = self._validate_character_limits(optimized_segments)
            
            logger.info(f"智能分段完成，新段落数: {len(final_segments)}")
            logger.info(f"平均字符数: {sum(len(s['text']) for s in final_segments) / len(final_segments):.1f}")
            
            self._report_progress(100, 100, "智能分段完成！")
            return final_segments
            
        except Exception as e:
            logger.error(f"智能分段失败: {str(e)}")
            self._report_progress(100, 100, f"智能分段失败: {str(e)}")
            logger.warning("使用原始分段")
            return segments
    
    def _segment_by_character_count(self, segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        基于字符数的智能分段
        
        Args:
            segments: 原始片段列表
            
        Returns:
            基于字符数分段后的片段列表
        """
        try:
            logger.info(f"开始基于字符数的智能分段，字符限制: {self.min_chars}-{self.max_chars}")
            
            new_segments = []
            current_group = []
            current_chars = 0
            segment_id = 1
            
            for segment in segments:
                text = segment['text']
                text_length = len(text)
                
                # 如果当前片段本身就超过最大字符限制，需要拆分
                if text_length > self.max_chars:
                    # 先保存当前组
                    if current_group:
                        new_segments.append(self._create_segment_from_group(current_group, segment_id))
                        segment_id += 1
                        current_group = []
                        current_chars = 0
                    
                    # 拆分超长片段
                    split_segments = self._split_long_text_segment(segment, segment_id)
                    new_segments.extend(split_segments)
                    segment_id += len(split_segments)
                    continue
                
                # 如果添加当前片段会超过最大字符限制
                if current_chars + text_length > self.max_chars and current_group:
                    # 检查当前组是否满足最小字符要求
                    if current_chars >= self.min_chars:
                        new_segments.append(self._create_segment_from_group(current_group, segment_id))
                        segment_id += 1
                        current_group = []
                        current_chars = 0
                    else:
                        # 如果当前组太短，尝试智能分段点
                        break_point = self._find_best_break_point(current_group + [segment])
                        if break_point > 0:
                            # 在分段点分割
                            new_segments.append(self._create_segment_from_group(current_group[:break_point], segment_id))
                            segment_id += 1
                            current_group = current_group[break_point:]
                            current_chars = sum(len(s['text']) for s in current_group)
                        # 如果找不到合适的分段点，继续添加到当前组
                
                current_group.append(segment)
                current_chars += text_length
            
            # 处理最后一组
            if current_group:
                new_segments.append(self._create_segment_from_group(current_group, segment_id))
            
            logger.info(f"字符数分段完成：{len(segments)} -> {len(new_segments)} 个段落")
            return new_segments
            
        except Exception as e:
            logger.error(f"字符数分段失败: {str(e)}")
            return segments
    
    def _split_long_text_segment(self, segment: Dict[str, Any], start_id: int) -> List[Dict[str, Any]]:
        """
        拆分超长文本片段
        
        Args:
            segment: 超长片段
            start_id: 起始ID
            
        Returns:
            拆分后的片段列表
        """
        text = segment['text']
        duration = segment['end'] - segment['start']
        
        # 根据字符数估算需要分成几段
        target_segments = max(2, (len(text) + self.max_chars - 1) // self.max_chars)
        
        split_segments = []
        current_pos = 0
        
        for i in range(target_segments):
            # 计算这一段的目标长度
            remaining_chars = len(text) - current_pos
            remaining_segments = target_segments - i
            target_length = min(self.max_chars, remaining_chars // remaining_segments)
            
            # 寻找最佳分割点
            end_pos = current_pos + target_length
            if end_pos < len(text):
                end_pos = self._find_text_break_point(text, current_pos, end_pos)
            else:
                end_pos = len(text)
            
            # 创建分段
            segment_text = text[current_pos:end_pos].strip()
            if segment_text:
                # 按比例分配时间
                time_ratio = len(segment_text) / len(text)
                start_time = segment['start'] + (duration * (current_pos / len(text)))
                end_time = segment['start'] + (duration * (end_pos / len(text)))
                
                split_segment = {
                    'id': start_id + i,
                    'start': start_time,
                    'end': end_time,
                    'duration': end_time - start_time,
                    'text': segment_text,
                    'confidence': segment.get('confidence', 1.0),
                    'original_segments': [segment.get('id', 0)],
                    'split_from_long_text': True
                }
                split_segments.append(split_segment)
            
            current_pos = end_pos
            if current_pos >= len(text):
                break
        
        logger.info(f"超长文本拆分：{len(text)}字符 -> {len(split_segments)}个段落")
        return split_segments
    
    def _find_text_break_point(self, text: str, start_pos: int, target_pos: int) -> int:
        """
        在文本中寻找最佳分割点
        
        Args:
            text: 文本内容
            start_pos: 开始位置
            target_pos: 目标位置
            
        Returns:
            最佳分割点位置
        """
        # 在目标位置前后寻找分段点
        search_range = min(20, (target_pos - start_pos) // 4)  # 搜索范围
        
        for pattern in self.segment_break_patterns:
            # 在目标位置往前搜索
            for i in range(target_pos, max(start_pos, target_pos - search_range), -1):
                if i < len(text) and re.search(pattern, text[i]):
                    return i + 1
            
            # 在目标位置往后搜索
            for i in range(target_pos, min(len(text), target_pos + search_range)):
                if re.search(pattern, text[i]):
                    return i + 1
        
        # 如果找不到合适的分段点，返回目标位置
        return min(target_pos, len(text))
    
    def _find_best_break_point(self, segments: List[Dict[str, Any]]) -> int:
        """
        在片段列表中寻找最佳分段点
        
        Args:
            segments: 片段列表
            
        Returns:
            最佳分段点索引
        """
        if len(segments) <= 1:
            return 0
        
        # 计算每个可能分段点的评分
        best_score = -1
        best_point = len(segments) // 2  # 默认中间分割
        
        for i in range(1, len(segments)):
            # 计算前半部分的字符数
            chars_before = sum(len(seg['text']) for seg in segments[:i])
            chars_after = sum(len(seg['text']) for seg in segments[i:])
            
            # 评分标准：
            # 1. 前半部分接近理想字符数
            # 2. 两部分都在合理范围内
            # 3. 在句末标点处分割有额外奖励
            
            score = 0
            
            # 字符数评分
            if self.min_chars <= chars_before <= self.max_chars:
                score += 3
                # 接近理想字符数有奖励
                if abs(chars_before - self.ideal_chars) < 10:
                    score += 2
            
            if self.min_chars <= chars_after <= self.max_chars:
                score += 3
            
            # 标点符号奖励
            prev_text = segments[i-1]['text']
            if re.search(r'[。！？]$', prev_text):
                score += 2
            elif re.search(r'[，；：]$', prev_text):
                score += 1
            
            if score > best_score:
                best_score = score
                best_point = i
        
        return best_point
    
    def _create_segment_from_group(self, group: List[Dict[str, Any]], segment_id: int) -> Dict[str, Any]:
        """
        从片段组创建新的段落
        
        Args:
            group: 片段组
            segment_id: 段落ID
            
        Returns:
            新的段落
        """
        if not group:
            return None
        
        # 计算段落的时间范围
        start_time = min(seg['start'] for seg in group)
        end_time = max(seg['end'] for seg in group)
        duration = end_time - start_time
        
        # 合并文本
        combined_text = ' '.join(seg['text'] for seg in group).strip()
        
        # 计算平均置信度
        avg_confidence = sum(seg.get('confidence', 1.0) for seg in group) / len(group)
        
        # 创建新段落
        new_segment = {
            'id': segment_id,
            'start': start_time,
            'end': end_time,
            'duration': duration,
            'text': combined_text,
            'confidence': avg_confidence,
            'original_segments': [seg.get('id', 0) for seg in group],
            'original_count': len(group),
            'char_count': len(combined_text),
            'created_by': 'character_based_segmentation'
        }
        
        return new_segment
    
    def _validate_character_limits(self, segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        验证并修正字符数限制
        
        Args:
            segments: 段落列表
            
        Returns:
            验证后的段落列表
        """
        validated_segments = []
        
        for segment in segments:
            text_length = len(segment['text'])
            
            # 检查字符数限制
            if text_length > self.max_chars:
                logger.warning(f"段落 {segment['id']} 仍然超过字符限制 ({text_length} > {self.max_chars})，进行最终拆分")
                # 最终拆分
                split_segments = self._split_long_text_segment(segment, segment['id'])
                validated_segments.extend(split_segments)
            elif text_length < self.min_chars:
                logger.info(f"段落 {segment['id']} 字符数过少 ({text_length} < {self.min_chars})，标记为短段落")
                segment['is_short'] = True
                validated_segments.append(segment)
            else:
                validated_segments.append(segment)
        
        # 尝试合并相邻的短段落
        validated_segments = self._merge_short_segments(validated_segments)
        
        return validated_segments
    
    def _merge_short_segments(self, segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        合并相邻的短段落
        
        Args:
            segments: 段落列表
            
        Returns:
            合并后的段落列表
        """
        if not segments:
            return segments
        
        merged_segments = []
        current_group = []
        current_chars = 0
        
        for segment in segments:
            text_length = len(segment['text'])
            
            # 如果当前段落不短，或者添加后会超过限制
            if (not segment.get('is_short', False) or 
                current_chars + text_length > self.max_chars):
                
                # 保存当前组
                if current_group:
                    if len(current_group) > 1:
                        # 合并多个短段落
                        merged_segment = self._create_segment_from_group(current_group, current_group[0]['id'])
                        merged_segment['merged_from_short'] = True
                        merged_segments.append(merged_segment)
                    else:
                        # 单个段落直接添加
                        merged_segments.append(current_group[0])
                    current_group = []
                    current_chars = 0
                
                # 添加当前段落
                merged_segments.append(segment)
            else:
                # 累积短段落
                current_group.append(segment)
                current_chars += text_length
        
        # 处理最后一组
        if current_group:
            if len(current_group) > 1:
                merged_segment = self._create_segment_from_group(current_group, current_group[0]['id'])
                merged_segment['merged_from_short'] = True
                merged_segments.append(merged_segment)
            else:
                merged_segments.append(current_group[0])
        
        return merged_segments
    
    def _analyze_subtitle_content(self, segments: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        分析字幕内容和结构 - 基于字符数分段结果
        
        Args:
            segments: 字幕片段列表（已经过字符数分段）
            
        Returns:
            内容分析结果
        """
        try:
            # 基本统计信息
            total_segments = len(segments)
            total_duration = max(seg['end'] for seg in segments) if segments else 0
            avg_duration = sum(seg['duration'] for seg in segments) / total_segments if total_segments > 0 else 0
            
            # 字符数分析
            char_lengths = [len(seg['text']) for seg in segments]
            avg_char_length = sum(char_lengths) / len(char_lengths) if char_lengths else 0
            
            # 分段质量分析
            good_segments = [seg for seg in segments if self.min_chars <= len(seg['text']) <= self.max_chars]
            good_segment_ratio = len(good_segments) / total_segments if total_segments > 0 else 0
            
            # 超长片段
            long_segments = [seg for seg in segments if len(seg['text']) > self.max_chars]
            long_segment_ratio = len(long_segments) / total_segments if total_segments > 0 else 0
            
            # 短片段
            short_segments = [seg for seg in segments if len(seg['text']) < self.min_chars]
            short_segment_ratio = len(short_segments) / total_segments if total_segments > 0 else 0
            
            # 判断是否需要AI优化
            # 如果字符数分段已经很好，就不需要AI优化
            needs_ai_optimization = (
                good_segment_ratio < 0.8 or     # 好的段落比例少于80%
                long_segment_ratio > 0.1 or     # 超长段落比例大于10%
                short_segment_ratio > 0.3 or    # 短段落比例大于30%
                avg_char_length < 20 or         # 平均字符数太少
                avg_char_length > 100           # 平均字符数太多
            )
            
            # 如果字符数分段质量很好，跳过AI优化
            if (good_segment_ratio > 0.9 and 
                long_segment_ratio < 0.05 and 
                short_segment_ratio < 0.2 and
                40 <= avg_char_length <= 80):
                needs_ai_optimization = False
                logger.info("字符数分段质量良好，跳过AI优化")
            
            analysis = {
                'total_segments': total_segments,
                'total_duration': total_duration,
                'avg_duration': avg_duration,
                'avg_char_length': avg_char_length,
                'good_segments_count': len(good_segments),
                'good_segment_ratio': good_segment_ratio,
                'long_segments_count': len(long_segments),
                'long_segment_ratio': long_segment_ratio,
                'short_segments_count': len(short_segments),
                'short_segment_ratio': short_segment_ratio,
                'needs_ai_optimization': needs_ai_optimization,
                'segmentation_quality': self._calculate_segmentation_quality(segments)
            }
            
            logger.info(f"分段分析结果: 平均字符数={avg_char_length:.1f}, 好段落比例={good_segment_ratio:.2f}, 需要AI优化={needs_ai_optimization}")
            return analysis
            
        except Exception as e:
            logger.error(f"内容分析失败: {str(e)}")
            return {'needs_ai_optimization': False}
    
    def _calculate_segmentation_quality(self, segments: List[Dict[str, Any]]) -> float:
        """
        计算分段质量评分
        
        Args:
            segments: 分段列表
            
        Returns:
            质量评分 (0-1)
        """
        if not segments:
            return 0.0
        
        total_score = 0
        for segment in segments:
            char_count = len(segment['text'])
            
            # 字符数评分
            if self.min_chars <= char_count <= self.max_chars:
                # 在合理范围内
                score = 1.0
                # 接近理想字符数有额外奖励
                if abs(char_count - self.ideal_chars) < 10:
                    score += 0.2
            elif char_count < self.min_chars:
                # 太短，按比例扣分
                score = char_count / self.min_chars * 0.5
            else:
                # 太长，扣分更多
                score = max(0.2, 1.0 - (char_count - self.max_chars) / self.max_chars)
            
            total_score += min(1.2, score)  # 最高分限制为1.2
        
        return min(1.0, total_score / len(segments))
    
    def _intelligent_segmentation(self, segments: List[Dict[str, Any]], 
                                content_analysis: Dict[str, Any]) -> List[List[Dict[str, Any]]]:
        """
        使用LLM进行智能分段 - 优化版本：小批次并发处理
        
        Args:
            segments: 原始片段列表
            content_analysis: 内容分析结果
            
        Returns:
            分组后的片段列表
        """
        try:
            # 如果不需要重新分段，直接返回
            if not content_analysis.get('needs_segmentation', True):
                logger.info("检测到字幕已经有良好的分段结构，跳过重新分段")
                return [[seg] for seg in segments]
            
            logger.info(f"使用智能分段并发处理 {len(segments)} 个片段")
            
            # 优化的分批策略
            optimal_batch_size = self._calculate_optimal_batch_size(segments)
            batches = self._create_smart_batches(segments, optimal_batch_size)
            
            # 获取并发信息
            concurrency_info = self._get_segmentation_concurrency_info(len(segments))
            
            logger.info(f"分段并发策略：{len(segments)} 个片段 -> {len(batches)} 个批次（每批 {optimal_batch_size} 个）")
            logger.info(f"预期并发数：{concurrency_info['expected_concurrency']} 个任务同时执行")
            
            # 并发处理批次
            all_groups = self._process_batches_concurrently(batches)
            
            return all_groups
            
        except Exception as e:
            logger.error(f"智能分段失败: {str(e)}")
            return [[seg] for seg in segments]
    
    def _calculate_optimal_batch_size(self, segments: List[Dict[str, Any]]) -> int:
        """
        计算最优的批次大小 - 优化版，确保合理的并发度
        
        Args:
            segments: 片段列表
            
        Returns:
            最优批次大小
        """
        total_segments = len(segments)
        
        # 根据片段数量动态调整批次大小
        if total_segments <= 20:
            # 小任务：每批3-5个片段，确保有足够的并发
            return min(5, max(3, total_segments // 4))
        elif total_segments <= 50:
            # 中等任务：每批6-10个片段
            return min(10, max(6, total_segments // 8))
        else:
            # 大任务：每批8-15个片段，但确保有足够的并发批次
            base_size = self.batch_size
            # 确保至少有4-6个批次来利用并发
            optimal_size = max(base_size, total_segments // 6)
            return min(15, optimal_size)
    
    def _get_segmentation_concurrency_info(self, segments_count: int) -> Dict[str, Any]:
        """
        获取分段并发信息
        
        Args:
            segments_count: 片段数量
            
        Returns:
            并发信息字典
        """
        optimal_batch_size = self._calculate_optimal_batch_size([{'text': ''} for _ in range(segments_count)])
        batch_count = (segments_count + optimal_batch_size - 1) // optimal_batch_size
        
        return {
            'total_segments': segments_count,
            'batch_size': optimal_batch_size,
            'batch_count': batch_count,
            'expected_concurrency': min(batch_count, 3)  # 分段器使用较少的并发
        }
    
    def _create_smart_batches(self, segments: List[Dict[str, Any]], batch_size: int) -> List[List[Dict[str, Any]]]:
        """
        创建智能批次 - 考虑时间连续性和语义完整性
        增强版：考虑批次间连接和重叠处理
        
        Args:
            segments: 片段列表
            batch_size: 批次大小
            
        Returns:
            批次列表，每个批次包含重叠的上下文片段
        """
        if len(segments) <= batch_size:
            return [segments]
            
        batches = []
        current_batch = []
        current_batch_chars = 0
        max_batch_chars = 2000  # 每批最大字符数
        overlap_size = 2  # 批次间重叠的片段数量
        
        for i, segment in enumerate(segments):
            segment_chars = len(segment['text'])
            
            # 检查是否需要开始新批次
            if (len(current_batch) >= batch_size or 
                current_batch_chars + segment_chars > max_batch_chars):
                
                if current_batch:
                    # 为当前批次添加前后文标记
                    batch_with_context = self._add_batch_context(
                        current_batch, segments, i - len(current_batch), overlap_size
                    )
                    batches.append(batch_with_context)
                    
                    # 新批次从重叠部分开始
                    overlap_start = max(0, len(current_batch) - overlap_size)
                    current_batch = current_batch[overlap_start:]
                    current_batch_chars = sum(len(seg['text']) for seg in current_batch)
            
            current_batch.append(segment)
            current_batch_chars += segment_chars
        
        # 添加最后一个批次
        if current_batch:
            batch_with_context = self._add_batch_context(
                current_batch, segments, len(segments) - len(current_batch), overlap_size
            )
            batches.append(batch_with_context)
        
        logger.info(f"创建智能批次完成，共 {len(batches)} 个批次，平均重叠 {overlap_size} 个片段")
        return batches
    
    def _add_batch_context(self, batch: List[Dict[str, Any]], all_segments: List[Dict[str, Any]], 
                          batch_start_idx: int, overlap_size: int) -> List[Dict[str, Any]]:
        """
        为批次添加上下文信息
        
        Args:
            batch: 当前批次
            all_segments: 所有片段
            batch_start_idx: 批次在全部片段中的起始索引
            overlap_size: 重叠大小
            
        Returns:
            添加上下文信息的批次
        """
        batch_with_context = []
        
        # 添加前置上下文
        prev_context_start = max(0, batch_start_idx - overlap_size)
        prev_context_end = batch_start_idx
        
        for i in range(prev_context_start, prev_context_end):
            if i < len(all_segments):
                context_segment = all_segments[i].copy()
                context_segment['is_context'] = True
                context_segment['context_type'] = 'previous'
                batch_with_context.append(context_segment)
        
        # 添加主要批次内容
        for segment in batch:
            segment_copy = segment.copy()
            segment_copy['is_context'] = False
            batch_with_context.append(segment_copy)
        
        # 添加后置上下文
        next_context_start = batch_start_idx + len(batch)
        next_context_end = min(len(all_segments), next_context_start + overlap_size)
        
        for i in range(next_context_start, next_context_end):
            if i < len(all_segments):
                context_segment = all_segments[i].copy()
                context_segment['is_context'] = True
                context_segment['context_type'] = 'next'
                batch_with_context.append(context_segment)
        
        return batch_with_context
    
    def _process_batches_concurrently(self, batches: List[List[Dict[str, Any]]]) -> List[List[Dict[str, Any]]]:
        """
        并发处理批次
        
        Args:
            batches: 批次列表
            
        Returns:
            所有分组结果
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import time
        
        all_groups = []
        completed_batches = 0
        
        # 使用较少的并发线程以避免API限制
        max_workers = min(3, len(batches))
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 提交所有批次处理任务
            future_to_batch = {
                executor.submit(self._segment_single_batch, batch, i+1): batch 
                for i, batch in enumerate(batches)
            }
            
            # 收集结果
            for future in as_completed(future_to_batch):
                try:
                    batch_groups = future.result()
                    all_groups.extend(batch_groups)
                    
                    completed_batches += 1
                    progress = 30 + int((completed_batches / len(batches)) * 40)  # 30-70%
                    self._report_progress(progress, 100, f"完成批次 {completed_batches}/{len(batches)}")
                    
                    # 为避免API限制，在批次间添加小延迟
                    time.sleep(0.1)
                    
                except Exception as e:
                    batch = future_to_batch[future]
                    logger.error(f"批次处理失败: {str(e)}")
                    # 使用降级策略处理失败的批次
                    main_segments = [seg for seg in batch if not seg.get('is_context', False)]
                    fallback_groups = self._fallback_segmentation(main_segments)
                    all_groups.extend(fallback_groups)
                    
                    completed_batches += 1
                    progress = 30 + int((completed_batches / len(batches)) * 40)
                    self._report_progress(progress, 100, f"批次降级处理 {completed_batches}/{len(batches)}")
        
        # 按时间顺序重新排列
        all_groups.sort(key=lambda group: group[0]['start'])
        
        # 后处理：合并跨批次的连续段落
        optimized_groups = self._merge_cross_batch_segments(all_groups)
        
        logger.info(f"所有批次处理完成，生成 {len(optimized_groups)} 个段落组（原始：{len(all_groups)}）")
        
        return optimized_groups
    
    def _merge_cross_batch_segments(self, groups: List[List[Dict[str, Any]]]) -> List[List[Dict[str, Any]]]:
        """
        合并跨批次的连续段落，解决批次边界问题
        
        Args:
            groups: 分组列表
            
        Returns:
            优化后的分组列表
        """
        if len(groups) <= 1:
            return groups
        
        merged_groups = []
        current_group = groups[0]
        merged_count = 0
        
        for i in range(1, len(groups)):
            next_group = groups[i]
            
            # 检查当前组的最后一个片段和下一组的第一个片段是否应该合并
            if self._should_merge_groups(current_group, next_group):
                # 合并组
                merged_group = current_group + next_group
                
                # 检查合并后的时长是否超过限制
                merged_duration = sum(seg['end'] - seg['start'] for seg in merged_group)
                if merged_duration <= self.max_segment_duration:
                    current_group = merged_group
                    merged_count += 1
                    logger.debug(f"合并跨批次段落：时长 {merged_duration:.1f}s")
                else:
                    # 时长超过限制，不合并
                    merged_groups.append(current_group)
                    current_group = next_group
            else:
                # 不需要合并
                merged_groups.append(current_group)
                current_group = next_group
        
        # 添加最后一组
        merged_groups.append(current_group)
        
        if merged_count > 0:
            logger.info(f"跨批次段落合并：{merged_count} 个段落被合并")
        
        return merged_groups
    
    def _should_merge_groups(self, group1: List[Dict[str, Any]], group2: List[Dict[str, Any]]) -> bool:
        """
        判断两个组是否应该合并
        
        Args:
            group1: 第一组
            group2: 第二组
            
        Returns:
            是否应该合并
        """
        if not group1 or not group2:
            return False
        
        # 获取两组的边界片段
        last_segment = group1[-1]
        first_segment = group2[0]
        
        # 时间间隔检查
        time_gap = first_segment['start'] - last_segment['end']
        if time_gap > 1.0:  # 间隔超过1秒，不合并
            return False
        
        # 文本长度检查
        last_text = last_segment['text'].strip()
        first_text = first_segment['text'].strip()
        
        # 如果第一组以不完整的句子结束，第二组以相关内容开始
        if (len(last_text) < 30 and len(first_text) < 30 and 
            not last_text.endswith('。') and not last_text.endswith('！') and 
            not last_text.endswith('？') and not last_text.endswith('.')):
            return True
        
        # 检查是否是数字、列表等连续内容
        if (last_text.endswith('，') or last_text.endswith(',') or 
            any(last_text.endswith(str(i)) for i in range(10))):
            return True
        
        return False
    
    def _segment_single_batch(self, segments: List[Dict[str, Any]], batch_num: int) -> List[List[Dict[str, Any]]]:
        """
        处理单个批次的智能分段
        
        Args:
            segments: 片段列表
            batch_num: 批次编号
            
        Returns:
            分组后的片段列表
        """
        try:
            logger.debug(f"处理批次 {batch_num}，包含 {len(segments)} 个片段")
            
            # 构建分段请求
            prompt = self._build_batch_segmentation_prompt(segments, batch_num)
            
            # 调用LLM进行分段分析
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self._get_batch_system_prompt()},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=2000,  # 适中的token限制
                temperature=self.temperature,
                top_p=1.0,
                frequency_penalty=0.0,
                presence_penalty=0.0
            )
            
            # 解析分段结果
            segmentation_result = response.choices[0].message.content
            groups = self._parse_batch_segmentation_result(segments, segmentation_result)
            
            logger.debug(f"批次 {batch_num} 分段完成，生成 {len(groups)} 个段落组")
            return groups
            
        except Exception as e:
            logger.error(f"批次 {batch_num} 分段失败: {str(e)}")
            # 如果失败，退回到降级分段
            return self._fallback_segmentation(segments)
    
    def _build_batch_segmentation_prompt(self, segments: List[Dict[str, Any]], batch_num: int) -> str:
        """
        构建批次分段提示词 - 基于字符数的优化版本
        
        Args:
            segments: 片段列表（包含上下文）
            batch_num: 批次编号
            
        Returns:
            分段提示词
        """
        # 分离上下文和主要内容
        context_segments = [seg for seg in segments if seg.get('is_context', False)]
        main_segments = [seg for seg in segments if not seg.get('is_context', False)]
        
        # 构建基于字符数的智能提示词
        prompt = f"""对以下字幕片段进行智能分段优化，批次 {batch_num}：

**核心要求：**
1. 每个段落字符数：{self.min_chars}-{self.max_chars}字符（理想{self.ideal_chars}字符）
2. 保持语义完整性和逻辑连贯性
3. 在合适的语言分界点进行分组（句号、问号、感叹号优先）
4. 避免在句子中间强行分段

**上下文信息：**"""
        
        # 添加前置上下文
        prev_context = [seg for seg in context_segments if seg.get('context_type') == 'previous']
        if prev_context:
            prompt += f"\n[前文参考]:\n"
            for seg in prev_context:
                char_count = len(seg['text'])
                prompt += f"  {seg['id']}: ({char_count}字符) \"{seg['text']}\"\n"
        
        # 添加主要处理内容
        prompt += f"\n**需要优化分组的片段：**\n"
        total_chars = 0
        for segment in main_segments:
            char_count = len(segment['text'])
            total_chars += char_count
            
            # 标记字符数状态
            if char_count > self.max_chars:
                status = "[超长]"
            elif char_count < self.min_chars:
                status = "[过短]"
            else:
                status = "[合适]"
            
            prompt += f"{segment['id']}: {status} ({char_count}字符) \"{segment['text']}\"\n"
        
        # 添加后置上下文
        next_context = [seg for seg in context_segments if seg.get('context_type') == 'next']
        if next_context:
            prompt += f"\n[后文参考]:\n"
            for seg in next_context:
                char_count = len(seg['text'])
                prompt += f"  {seg['id']}: ({char_count}字符) \"{seg['text']}\"\n"
        
        avg_chars = total_chars / len(main_segments) if main_segments else 0
        
        prompt += f"""
**分段统计：**
- 总字符数：{total_chars}
- 平均字符数：{avg_chars:.1f}
- 片段数量：{len(main_segments)}

**返回格式：** [[1,2,3],[4,5],[6]]
（只对主要片段分组，不包括上下文片段）

**分组策略：**
- 优先在句末标点（。！？）处分组
- 其次考虑句中标点（，；：）
- 确保每组字符数在合理范围内
- 保持语义的完整性和连贯性
- 避免将紧密相关的内容分离
"""
        
        return prompt
    
    def _get_batch_system_prompt(self) -> str:
        """
        获取批次处理的系统提示词 - 基于字符数的版本
        
        Returns:
            系统提示词
        """
        return f"""你是专业的字幕分段优化AI。任务是将字幕片段重新分组，确保每个段落的字符数在合理范围内，同时保持语义完整。

分段原则：
1. 字符数控制：每段{self.min_chars}-{self.max_chars}字符，理想{self.ideal_chars}字符
2. 语义完整：保持句子和逻辑的完整性
3. 分段点选择：优先在句末标点处分段，其次是句中标点
4. 上下文连贯：考虑前后文语境，确保自然过渡

当字符数与语义产生冲突时，优先保证语义完整性，然后在下个合适的分段点进行调整。
返回简洁数组格式，确保分段合理。"""
    
    def _parse_batch_segmentation_result(self, segments: List[Dict[str, Any]], 
                                       segmentation_result: str) -> List[List[Dict[str, Any]]]:
        """
        解析批次分段结果 - 增强版，处理上下文片段
        
        Args:
            segments: 原始片段列表（包含上下文）
            segmentation_result: LLM分段结果
            
        Returns:
            分组后的片段列表（只包含主要片段）
        """
        try:
            # 分离主要片段
            main_segments = [seg for seg in segments if not seg.get('is_context', False)]
            
            # 尝试解析简洁的数组格式：[[1,2,3],[4,5],[6]]
            array_match = re.search(r'\[\[.*?\]\]', segmentation_result, re.DOTALL)
            if array_match:
                groups_array = json.loads(array_match.group(0))
                
                # 构建分组
                groups = []
                segment_dict = {seg['id']: seg for seg in main_segments}
                used_ids = set()
                
                for group_array in groups_array:
                    group_segments = []
                    group_duration = 0
                    
                    for seg_id in group_array:
                        if seg_id in segment_dict and seg_id not in used_ids:
                            segment = segment_dict[seg_id]
                            group_segments.append(segment)
                            group_duration += segment['end'] - segment['start']
                            used_ids.add(seg_id)
                    
                    if group_segments:
                        # 验证时长限制
                        if group_duration > 12.0:  # 12秒限制
                            logger.warning(f"检测到过长段落 ({group_duration:.1f}s)，进行拆分")
                            # 拆分过长的段落
                            split_groups = self._split_long_segment(group_segments)
                            groups.extend(split_groups)
                        else:
                            groups.append(group_segments)
                
                # 添加遗漏的片段
                for seg in main_segments:
                    if seg['id'] not in used_ids:
                        logger.warning(f"片段 {seg['id']} 未被分组，单独处理")
                        groups.append([seg])
                
                return groups
            else:
                # 如果解析失败，使用降级策略
                logger.warning("无法解析分段结果，使用降级策略")
                main_segments = [seg for seg in segments if not seg.get('is_context', False)]
                return self._fallback_segmentation(main_segments)
            
        except Exception as e:
            logger.error(f"解析批次分段结果失败: {str(e)}")
            main_segments = [seg for seg in segments if not seg.get('is_context', False)]
            return self._fallback_segmentation(main_segments)
    
    def _split_long_segment(self, segments: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
        """
        拆分过长的段落
        
        Args:
            segments: 需要拆分的片段列表
            
        Returns:
            拆分后的段落列表
        """
        if not segments:
            return []
        
        # 按时间排序
        segments.sort(key=lambda x: x['start'])
        
        groups = []
        current_group = []
        current_duration = 0
        max_duration = 12.0  # 12秒限制
        
        for segment in segments:
            segment_duration = segment['end'] - segment['start']
            
            # 如果添加当前片段会超过限制，则开始新组
            if current_duration + segment_duration > max_duration and current_group:
                groups.append(current_group)
                current_group = []
                current_duration = 0
            
            current_group.append(segment)
            current_duration += segment_duration
        
        # 添加最后一组
        if current_group:
            groups.append(current_group)
        
        logger.info(f"拆分过长段落：{len(segments)} 个片段 -> {len(groups)} 个段落")
        return groups
    
    def _fallback_segmentation(self, segments: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
        """
        降级分段策略 - 基于简单规则合并，遵循严格时长限制
        
        Args:
            segments: 原始片段列表
            
        Returns:
            分组后的片段列表
        """
        logger.info("使用降级分段策略，严格控制时长")
        groups = []
        current_group = []
        current_duration = 0
        max_duration = 12.0  # 使用更严格的12秒限制
        
        for segment in segments:
            segment_duration = segment['end'] - segment['start']
            
            # 如果当前组为空，或者添加这个片段不会超过时长限制
            if (not current_group or 
                (current_duration + segment_duration <= max_duration and
                 len(' '.join(seg['text'] for seg in current_group + [segment])) <= self.max_chars_per_segment)):
                
                current_group.append(segment)
                current_duration += segment_duration
            else:
                # 当前组已满，开始新组
                if current_group:
                    groups.append(current_group)
                current_group = [segment]
                current_duration = segment_duration
        
        # 添加最后一组
        if current_group:
            groups.append(current_group)
        
        # 验证所有组的时长
        for i, group in enumerate(groups):
            group_duration = sum(seg['end'] - seg['start'] for seg in group)
            if group_duration > max_duration:
                logger.warning(f"降级分段第{i+1}组时长过长({group_duration:.1f}s)，需要进一步拆分")
        
        logger.info(f"降级分段完成，生成 {len(groups)} 个段落组（最大时长：{max_duration}s）")
        return groups
    
    def _build_new_segments(self, segmented_groups: List[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        """
        构建新的段落
        
        Args:
            segmented_groups: 分组后的片段列表
            
        Returns:
            新的段落列表
        """
        try:
            new_segments = []
            
            for group_id, group in enumerate(segmented_groups, 1):
                if not group:
                    continue
                
                # 计算段落的时间范围
                start_time = min(seg['start'] for seg in group)
                end_time = max(seg['end'] for seg in group)
                duration = end_time - start_time
                
                # 合并文本
                combined_text = ' '.join(seg['text'] for seg in group)
                
                # 计算平均置信度
                avg_confidence = sum(seg.get('confidence', 1.0) for seg in group) / len(group)
                
                # 创建新段落
                new_segment = {
                    'id': group_id,
                    'start': start_time,
                    'end': end_time,
                    'duration': duration,
                    'text': combined_text,
                    'confidence': avg_confidence,
                    'original_segments': [seg['id'] for seg in group],
                    'original_count': len(group)
                }
                
                new_segments.append(new_segment)
            
            return new_segments
            
        except Exception as e:
            logger.error(f"构建新段落失败: {str(e)}")
            raise
    
    def _optimize_segments(self, segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        优化段落 - 基于字符数的优化版本
        
        Args:
            segments: 段落列表
            
        Returns:
            优化后的段落列表
        """
        try:
            optimized = []
            issues = {
                'long_segments': [],
                'short_segments': [],
                'duration_issues': []
            }
            
            for segment in segments:
                char_count = len(segment['text'])
                duration = segment['duration']
                
                # 检查字符数限制
                if char_count > self.max_chars:
                    logger.warning(f"段落 {segment['id']} 字符数超限 ({char_count} > {self.max_chars})")
                    issues['long_segments'].append(segment['id'])
                    segment['char_too_long'] = True
                elif char_count < self.min_chars:
                    logger.info(f"段落 {segment['id']} 字符数过少 ({char_count} < {self.min_chars})")
                    issues['short_segments'].append(segment['id'])
                    segment['char_too_short'] = True
                
                # 检查时长（作为辅助指标）
                if duration > self.max_segment_duration:
                    logger.warning(f"段落 {segment['id']} 时长过长 ({duration:.2f}s > {self.max_segment_duration}s)")
                    issues['duration_issues'].append(segment['id'])
                    segment['duration_too_long'] = True
                elif duration < self.min_segment_duration:
                    logger.info(f"段落 {segment['id']} 时长过短 ({duration:.2f}s < {self.min_segment_duration}s)")
                    segment['duration_too_short'] = True
                
                # 计算段落质量评分
                quality_score = self._calculate_segment_quality(segment)
                segment['quality_score'] = quality_score
                
                # 估算语音时长
                estimated_speech_time = char_count / self.char_limits[self.current_lang]['chars_per_second']
                segment['estimated_speech_time'] = estimated_speech_time
                
                # 时长与字符数匹配度
                if duration > 0:
                    time_char_ratio = estimated_speech_time / duration
                    segment['time_char_ratio'] = time_char_ratio
                    if time_char_ratio > 1.2:
                        logger.warning(f"段落 {segment['id']} 内容过多，可能难以在时长内朗读完成")
                        segment['content_too_dense'] = True
                
                optimized.append(segment)
            
            # 统计信息
            avg_quality = sum(seg['quality_score'] for seg in optimized) / len(optimized)
            avg_char_count = sum(len(seg['text']) for seg in optimized) / len(optimized)
            avg_duration = sum(seg['duration'] for seg in optimized) / len(optimized)
            
            logger.info(f"段落优化完成：平均质量评分 {avg_quality:.2f}，平均字符数 {avg_char_count:.1f}，平均时长 {avg_duration:.2f}s")
            
            # 生成优化建议
            self._generate_character_optimization_suggestions(optimized, issues)
            
            return optimized
            
        except Exception as e:
            logger.error(f"段落优化失败: {str(e)}")
            return segments
    
    def _generate_character_optimization_suggestions(self, segments: List[Dict[str, Any]], issues: Dict[str, List]):
        """
        生成基于字符数的优化建议
        
        Args:
            segments: 段落列表
            issues: 问题统计
        """
        suggestions = []
        
        if issues['long_segments']:
            suggestions.append(f"需要进一步拆分 {len(issues['long_segments'])} 个超长段落")
        
        if issues['short_segments']:
            suggestions.append(f"可以考虑合并 {len(issues['short_segments'])} 个过短段落")
        
        if issues['duration_issues']:
            suggestions.append(f"需要关注 {len(issues['duration_issues'])} 个时长异常的段落")
        
        # 内容密度问题
        dense_segments = [s for s in segments if s.get('content_too_dense', False)]
        if dense_segments:
            suggestions.append(f"有 {len(dense_segments)} 个段落内容过密，可能需要精简")
        
        # 整体建议
        good_segments = [s for s in segments if self.min_chars <= len(s['text']) <= self.max_chars]
        quality_ratio = len(good_segments) / len(segments)
        
        if quality_ratio > 0.9:
            suggestions.append("✅ 分段质量良好，大部分段落都在合理的字符数范围内")
        elif quality_ratio > 0.8:
            suggestions.append("⚠️ 分段质量一般，建议进一步优化")
        else:
            suggestions.append("❌ 分段质量较差，建议重新分段")
        
        if suggestions:
            logger.info("字符数优化建议：" + "；".join(suggestions))
        else:
            logger.info("所有段落的字符数都在合理范围内")
    
    def _calculate_segment_quality(self, segment: Dict[str, Any]) -> float:
        """
        计算段落质量评分
        
        Args:
            segment: 段落信息
            
        Returns:
            质量评分 (0-1)
        """
        try:
            score = 1.0
            
            # 时长评分
            duration = segment['duration']
            if duration < self.min_segment_duration:
                score -= 0.2
            elif duration > self.max_segment_duration:
                score -= 0.3
            elif abs(duration - self.ideal_segment_duration) < 2.0:
                score += 0.1
            
            # 文本长度评分
            text_length = len(segment['text'])
            if text_length < self.min_chars:
                score -= 0.2
            elif text_length > self.max_chars:
                score -= 0.3
            elif self.min_chars <= text_length <= self.ideal_chars:
                score += 0.1
            
            # 原始片段合并评分
            original_count = segment.get('original_count', 1)
            if original_count > 1:
                score += 0.1  # 成功合并奖励
            
            # 置信度评分
            confidence = segment.get('confidence', 1.0)
            score *= confidence
            
            return max(0.0, min(1.0, score))
            
        except Exception as e:
            logger.error(f"计算质量评分失败: {str(e)}")
            return 0.5
    
    def create_segmentation_report(self, original_segments: List[Dict[str, Any]], 
                                 new_segments: List[Dict[str, Any]]) -> str:
        """
        创建分段报告
        
        Args:
            original_segments: 原始片段列表
            new_segments: 新段落列表
            
        Returns:
            分段报告字符串
        """
        try:
            report = []
            report.append("智能字幕分段报告")
            report.append("=" * 30)
            report.append(f"原始片段数: {len(original_segments)}")
            report.append(f"新段落数: {len(new_segments)}")
            report.append(f"压缩比例: {len(new_segments)/len(original_segments):.2f}")
            
            # 时长统计
            orig_avg_duration = sum(seg['duration'] for seg in original_segments) / len(original_segments)
            new_avg_duration = sum(seg['duration'] for seg in new_segments) / len(new_segments)
            
            report.append(f"\n时长统计:")
            report.append(f"原始平均时长: {orig_avg_duration:.2f}秒")
            report.append(f"新段落平均时长: {new_avg_duration:.2f}秒")
            
            # 质量统计
            if new_segments and 'quality_score' in new_segments[0]:
                avg_quality = sum(seg['quality_score'] for seg in new_segments) / len(new_segments)
                report.append(f"平均质量评分: {avg_quality:.2f}")
            
            # 合并统计
            total_merged = sum(seg.get('original_count', 1) for seg in new_segments)
            report.append(f"总合并片段数: {total_merged}")
            
            report.append(f"\n前5个段落示例:")
            for i, seg in enumerate(new_segments[:5]):
                report.append(f"段落 {seg['id']}: {seg['duration']:.2f}s")
                report.append(f"  文本: {seg['text'][:100]}...")
                report.append(f"  原始片段: {seg.get('original_count', 1)}个")
            
            return "\n".join(report)
            
        except Exception as e:
            logger.error(f"创建分段报告失败: {str(e)}")
            return "分段报告生成失败" 