"""
简化智能字幕分段模块
直接使用Kimi处理整个SRT文档进行智能分段，避免复杂的批次处理
"""

from openai import OpenAI
from typing import List, Dict, Any, Optional
from loguru import logger
import json
import re
import time


class SimpleSegmenter:
    """简化的智能字幕分段器"""
    
    def __init__(self, config: dict, progress_callback=None):
        """
        初始化简化分段器
        
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
            self.model = self.translation_config.get('model', 'kimi-k2-0711-preview')
            self.max_tokens = self.translation_config.get('max_tokens', 8000)
            logger.info(f"简化分段器使用Kimi API，模型: {self.model}")
        else:
            self.api_key = config.get('api_keys', {}).get('openai_api_key')
            self.base_url = None
            self.model = self.translation_config.get('model', 'gpt-4o')
            self.max_tokens = self.translation_config.get('max_tokens', 4000)
            logger.info(f"简化分段器使用OpenAI API，模型: {self.model}")
        
        self.temperature = 0.3
        
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
        
        # 理想的分段参数
        self.ideal_segment_duration = 8.0  # 理想时长8秒
        self.min_segment_duration = 3.0   # 最短3秒
        self.max_segment_duration = 15.0  # 最长15秒
        self.ideal_chars = 60             # 理想字符数
        self.min_chars = 15               # 最少字符数
        self.max_chars = 120              # 最多字符数
    
    def _report_progress(self, current: int, total: int, message: str):
        """报告进度"""
        if self.progress_callback:
            try:
                self.progress_callback(current, total, message)
            except Exception as e:
                logger.warning(f"进度回调失败: {str(e)}")
    
    def segment_subtitles(self, segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        简化的智能分段字幕
        
        Args:
            segments: 原始字幕片段列表
            
        Returns:
            重新分段后的字幕片段列表
        """
        try:
            logger.info(f"开始简化智能分段处理，原始片段数: {len(segments)}")
            self._report_progress(0, 100, "开始智能分段分析...")
            
            # 构建SRT文档字符串
            self._report_progress(20, 100, "构建SRT文档...")
            srt_content = self._build_srt_content(segments)
            
            # 直接让Kimi进行分段
            self._report_progress(40, 100, "Kimi正在分析整个文档...")
            segmentation_result = self._analyze_with_kimi(srt_content, segments)
            
            # 解析分段结果
            self._report_progress(80, 100, "解析分段结果...")
            new_segments = self._parse_segmentation_result(segmentation_result, segments)
            
            # 质量评估
            self._report_progress(90, 100, "评估分段质量...")
            final_segments = self._evaluate_segments(new_segments)
            
            logger.info(f"简化智能分段完成，新段落数: {len(final_segments)}")
            logger.info(f"平均字符数: {sum(len(s['text']) for s in final_segments) / len(final_segments):.1f}")
            logger.info(f"平均时长: {sum(s['duration'] for s in final_segments) / len(final_segments):.1f}秒")
            
            self._report_progress(100, 100, "智能分段完成！")
            return final_segments
            
        except Exception as e:
            logger.error(f"简化智能分段失败: {str(e)}")
            self._report_progress(100, 100, f"智能分段失败: {str(e)}")
            logger.warning("使用原始分段")
            return segments
    
    def _build_srt_content(self, segments: List[Dict[str, Any]]) -> str:
        """
        构建SRT文档内容
        
        Args:
            segments: 原始片段列表
            
        Returns:
            SRT文档字符串
        """
        lines = []
        for i, seg in enumerate(segments):
            lines.append(f"[{i+1}] {seg['start']:.2f}s-{seg['end']:.2f}s ({seg['duration']:.2f}s)")
            lines.append(f"    {seg['text']}")
            lines.append("")
        
        return "\n".join(lines)
    
    def _analyze_with_kimi(self, srt_content: str, original_segments: List[Dict[str, Any]]) -> str:
        """
        使用Kimi分析整个SRT文档进行智能分段
        
        Args:
            srt_content: SRT文档内容
            original_segments: 原始片段列表
            
        Returns:
            分段结果JSON字符串
        """
        system_prompt = f"""你是一个专业的字幕分段专家。请分析给定的SRT字幕文档，将零散的字幕片段重新组织成逻辑完整的段落。

分段原则：
1. **语义完整性**：确保每个段落表达完整的意思，不要在句子中间断开
2. **时间合理性**：
   - 理想时长：{self.ideal_segment_duration}秒
   - 最短时长：{self.min_segment_duration}秒，最长时长：{self.max_segment_duration}秒
3. **字符数控制**：
   - 理想字符数：{self.ideal_chars}个字符
   - 最少：{self.min_chars}个字符，最多：{self.max_chars}个字符
4. **上下文连贯**：合并相关的语句，保持话题的连续性
5. **标点符号**：在自然的标点符号处分段

请以JSON格式返回分段结果，包含每个新段落的：
- segments: 包含的原始片段编号列表（从1开始）
- start_time: 开始时间
- end_time: 结束时间
- text: 合并后的文本
- quality_score: 质量评分（0-1）

示例格式：
{{
  "segmented_groups": [
    {{
      "segments": [1, 2, 3],
      "start_time": 0.0,
      "end_time": 8.5,
      "text": "合并后的完整文本",
      "quality_score": 0.9
    }}
  ]
}}"""
        
        user_prompt = f"""请分析以下SRT字幕文档，进行智能分段：

{srt_content}

总共有{len(original_segments)}个原始片段，总时长{original_segments[-1]['end']:.2f}秒。

请将这些片段重新组织成逻辑完整的段落，确保每个段落语义完整且时长合理。"""
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=self.max_tokens,
                temperature=self.temperature
            )
            
            result = response.choices[0].message.content.strip()
            logger.info(f"Kimi分段分析完成，响应长度: {len(result)}")
            return result
            
        except Exception as e:
            logger.error(f"Kimi分段分析失败: {str(e)}")
            raise
    
    def _parse_segmentation_result(self, result: str, original_segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        解析分段结果
        
        Args:
            result: Kimi返回的分段结果
            original_segments: 原始片段列表
            
        Returns:
            新的分段列表
        """
        try:
            # 提取JSON
            json_match = re.search(r'\{.*\}', result, re.DOTALL)
            if not json_match:
                logger.warning("未找到有效的JSON结果，使用原始分段")
                return original_segments
            
            json_str = json_match.group()
            data = json.loads(json_str)
            
            segmented_groups = data.get('segmented_groups', [])
            if not segmented_groups:
                logger.warning("分段结果为空，使用原始分段")
                return original_segments
            
            new_segments = []
            
            for i, group in enumerate(segmented_groups):
                segment_indices = group.get('segments', [])
                if not segment_indices:
                    continue
                
                # 获取对应的原始片段
                original_segs = []
                for idx in segment_indices:
                    if 1 <= idx <= len(original_segments):
                        original_segs.append(original_segments[idx - 1])
                
                if not original_segs:
                    continue
                
                # 创建新段落
                start_time = original_segs[0]['start']
                end_time = original_segs[-1]['end']
                duration = end_time - start_time
                
                # 使用Kimi提供的文本，如果没有则合并原始文本
                merged_text = group.get('text', '')
                if not merged_text.strip():
                    merged_text = ' '.join(seg['text'] for seg in original_segs)
                
                quality_score = group.get('quality_score', 0.8)
                
                new_segment = {
                    'id': f"seg_{i+1}",
                    'start': start_time,
                    'end': end_time,
                    'duration': duration,
                    'text': merged_text.strip(),
                    'original_count': len(original_segs),
                    'original_indices': segment_indices,
                    'quality_score': quality_score,
                    'confidence': 1.0
                }
                
                new_segments.append(new_segment)
            
            logger.info(f"成功解析分段结果：{len(original_segments)} -> {len(new_segments)} 个段落")
            return new_segments
            
        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失败: {str(e)}")
            logger.warning("使用原始分段")
            return original_segments
        except Exception as e:
            logger.error(f"解析分段结果失败: {str(e)}")
            logger.warning("使用原始分段")
            return original_segments
    
    def _evaluate_segments(self, segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        评估分段质量并进行优化
        
        Args:
            segments: 分段列表
            
        Returns:
            优化后的分段列表
        """
        evaluated_segments = []
        
        for segment in segments:
            # 重新计算质量评分
            quality_score = self._calculate_quality_score(segment)
            segment['quality_score'] = quality_score
            
            # 检查是否需要拆分过长的段落
            if segment['duration'] > self.max_segment_duration or len(segment['text']) > self.max_chars:
                split_segments = self._split_long_segment(segment)
                evaluated_segments.extend(split_segments)
            else:
                evaluated_segments.append(segment)
        
        return evaluated_segments
    
    def _calculate_quality_score(self, segment: Dict[str, Any]) -> float:
        """
        计算段落质量评分
        
        Args:
            segment: 段落信息
            
        Returns:
            质量评分 (0-1)
        """
        try:
            score = 0.8  # 基础分
            
            # 时长评分
            duration = segment['duration']
            if self.min_segment_duration <= duration <= self.max_segment_duration:
                score += 0.1
                if abs(duration - self.ideal_segment_duration) < 2.0:
                    score += 0.05
            else:
                score -= 0.1
            
            # 字符数评分
            text_length = len(segment['text'])
            if self.min_chars <= text_length <= self.max_chars:
                score += 0.1
                if abs(text_length - self.ideal_chars) < 20:
                    score += 0.05
            else:
                score -= 0.1
            
            # 合并片段数评分
            original_count = segment.get('original_count', 1)
            if original_count > 1:
                score += 0.05  # 成功合并奖励
            
            return max(0.0, min(1.0, score))
            
        except Exception as e:
            logger.error(f"计算质量评分失败: {str(e)}")
            return 0.5
    
    def _split_long_segment(self, segment: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        拆分过长的段落
        
        Args:
            segment: 过长的段落
            
        Returns:
            拆分后的段落列表
        """
        text = segment['text']
        duration = segment['duration']
        
        # 在标点符号处寻找分割点
        sentences = re.split(r'[。！？；]', text)
        if len(sentences) < 2:
            # 如果没有标点，在空格处分割
            words = text.split()
            mid_point = len(words) // 2
            part1 = ' '.join(words[:mid_point])
            part2 = ' '.join(words[mid_point:])
        else:
            mid_point = len(sentences) // 2
            part1 = ''.join(sentences[:mid_point])
            part2 = ''.join(sentences[mid_point:])
        
        # 按字符比例分配时间
        total_chars = len(text)
        part1_ratio = len(part1) / total_chars if total_chars > 0 else 0.5
        split_time = segment['start'] + duration * part1_ratio
        
        segment1 = segment.copy()
        segment1['text'] = part1.strip()
        segment1['end'] = split_time
        segment1['duration'] = split_time - segment1['start']
        segment1['id'] = f"{segment['id']}_1"
        
        segment2 = segment.copy()
        segment2['text'] = part2.strip()
        segment2['start'] = split_time
        segment2['duration'] = segment2['end'] - split_time
        segment2['id'] = f"{segment['id']}_2"
        
        logger.info(f"拆分过长段落: {segment['id']} -> {segment1['id']}, {segment2['id']}")
        return [segment1, segment2] 