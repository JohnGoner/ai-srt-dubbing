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
    
    def __init__(self, config: dict):
        """
        初始化字幕分段器
        
        Args:
            config: 配置字典
        """
        self.config = config
        self.translation_config = config.get('translation', {})
        self.api_key = config.get('api_keys', {}).get('openai_api_key')
        self.model = self.translation_config.get('model', 'gpt-4o')
        self.max_tokens = self.translation_config.get('max_tokens', 4000)
        self.temperature = 0.3  # 使用较低的温度以确保逻辑性
        
        # 创建OpenAI客户端
        self.client = OpenAI(api_key=self.api_key)
        
        # 分段参数
        self.min_segment_duration = 3.0  # 最小段落时长（秒）
        self.max_segment_duration = 15.0  # 最大段落时长（秒）
        self.ideal_segment_duration = 8.0  # 理想段落时长（秒）
        self.max_chars_per_segment = 200  # 每个段落最大字符数
    
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
            
            # 第一步：分析字幕内容和结构
            content_analysis = self._analyze_subtitle_content(segments)
            
            # 第二步：使用LLM进行智能分段
            segmented_groups = self._intelligent_segmentation(segments, content_analysis)
            
            # 第三步：构建新的段落
            new_segments = self._build_new_segments(segmented_groups)
            
            # 第四步：优化和验证
            optimized_segments = self._optimize_segments(new_segments)
            
            logger.info(f"智能分段完成，新段落数: {len(optimized_segments)}")
            logger.info(f"平均段落时长: {sum(s['duration'] for s in optimized_segments) / len(optimized_segments):.2f}秒")
            
            return optimized_segments
            
        except Exception as e:
            logger.error(f"智能分段失败: {str(e)}")
            logger.warning("使用原始分段")
            return segments
    
    def _analyze_subtitle_content(self, segments: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        分析字幕内容和结构
        
        Args:
            segments: 字幕片段列表
            
        Returns:
            内容分析结果
        """
        try:
            # 基本统计信息
            total_segments = len(segments)
            total_duration = max(seg['end'] for seg in segments)
            avg_duration = sum(seg['duration'] for seg in segments) / total_segments
            
            # 文本长度分析
            text_lengths = [len(seg['text']) for seg in segments]
            avg_text_length = sum(text_lengths) / len(text_lengths)
            
            # 短片段统计（可能需要合并）
            short_segments = [seg for seg in segments if seg['duration'] < self.min_segment_duration]
            very_short_segments = [seg for seg in segments if len(seg['text']) < 20]
            
            # 空白间隔分析
            gaps = []
            for i in range(len(segments) - 1):
                gap = segments[i + 1]['start'] - segments[i]['end']
                gaps.append(gap)
            
            avg_gap = sum(gaps) / len(gaps) if gaps else 0
            
            analysis = {
                'total_segments': total_segments,
                'total_duration': total_duration,
                'avg_duration': avg_duration,
                'avg_text_length': avg_text_length,
                'short_segments_count': len(short_segments),
                'very_short_segments_count': len(very_short_segments),
                'avg_gap': avg_gap,
                'needs_segmentation': len(short_segments) > total_segments * 0.3  # 如果超过30%是短片段
            }
            
            logger.info(f"内容分析结果: {analysis}")
            return analysis
            
        except Exception as e:
            logger.error(f"内容分析失败: {str(e)}")
            return {}
    
    def _intelligent_segmentation(self, segments: List[Dict[str, Any]], 
                                content_analysis: Dict[str, Any]) -> List[List[Dict[str, Any]]]:
        """
        使用LLM进行智能分段
        
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
            
            # 分批处理以避免token限制
            batch_size = 20
            all_groups = []
            
            for i in range(0, len(segments), batch_size):
                batch = segments[i:i + batch_size]
                logger.info(f"处理分段批次 {i//batch_size + 1}/{(len(segments)-1)//batch_size + 1}")
                
                batch_groups = self._segment_batch(batch)
                all_groups.extend(batch_groups)
                
                # 避免API限制
                time.sleep(0.5)
            
            return all_groups
            
        except Exception as e:
            logger.error(f"智能分段失败: {str(e)}")
            return [[seg] for seg in segments]
    
    def _segment_batch(self, segments: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
        """
        对一批片段进行智能分段
        
        Args:
            segments: 片段列表
            
        Returns:
            分组后的片段列表
        """
        try:
            # 构建分段请求
            prompt = self._build_segmentation_prompt(segments)
            
            # 调用LLM进行分段分析 - 使用新版本API
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self._get_system_prompt()},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                top_p=1.0,
                frequency_penalty=0.0,
                presence_penalty=0.0
            )
            
            # 解析分段结果
            segmentation_result = response.choices[0].message.content
            groups = self._parse_segmentation_result(segments, segmentation_result)
            
            return groups
            
        except Exception as e:
            logger.error(f"批次分段失败: {str(e)}")
            return [[seg] for seg in segments]
    
    def _build_segmentation_prompt(self, segments: List[Dict[str, Any]]) -> str:
        """
        构建分段分析提示词
        
        Args:
            segments: 片段列表
            
        Returns:
            分段提示词
        """
        prompt = f"""请分析以下字幕片段，将它们重新组织成逻辑完整的段落。

分段原则：
1. 每个段落应该是一个完整的逻辑单元（完整的句子、短语或概念）
2. 避免在句子中间分割
3. 相关的句子应该合并到同一个段落
4. 每个段落的时长应该在3-15秒之间，理想时长是8秒
5. 每个段落的文本长度不应超过200个字符

请按照以下JSON格式返回分段结果：
```json
[
  {{
    "group_id": 1,
    "segments": [1, 2, 3],
    "reason": "合并原因",
    "estimated_duration": 8.5,
    "text_preview": "合并后的文本预览"
  }}
]
```

原始字幕片段：
"""
        
        for segment in segments:
            prompt += f"\n片段 {segment['id']}: [{segment['start']:.2f}s - {segment['end']:.2f}s] ({segment['duration']:.2f}s)\n"
            prompt += f"文本: {segment['text']}\n"
        
        return prompt
    
    def _get_system_prompt(self) -> str:
        """
        获取系统提示词
        
        Returns:
            系统提示词
        """
        return """你是一个专业的字幕编辑专家。你的任务是分析字幕片段，将零碎的小句子重新组织成逻辑完整、结构清晰的段落。

你需要考虑以下因素：
1. 语义连贯性：相关的句子应该归为一组
2. 时间合理性：确保每个段落的时长适中
3. 语言流畅性：避免在重要的语言停顿处分割
4. 逻辑完整性：每个段落应该是一个完整的思想或概念

请仔细分析每个片段的内容和时间信息，做出最佳的分段决策。"""
    
    def _parse_segmentation_result(self, segments: List[Dict[str, Any]], 
                                 segmentation_result: str) -> List[List[Dict[str, Any]]]:
        """
        解析分段结果
        
        Args:
            segments: 原始片段列表
            segmentation_result: LLM分段结果
            
        Returns:
            分组后的片段列表
        """
        try:
            # 尝试解析JSON格式的结果
            json_match = re.search(r'```json\s*(\[.*?\])\s*```', segmentation_result, re.DOTALL)
            if json_match:
                groups_data = json.loads(json_match.group(1))
            else:
                logger.warning("无法解析JSON格式的分段结果，使用默认分组")
                return [[seg] for seg in segments]
            
            # 构建分组
            groups = []
            segment_dict = {seg['id']: seg for seg in segments}
            
            for group_data in groups_data:
                segment_ids = group_data.get('segments', [])
                group_segments = []
                
                for seg_id in segment_ids:
                    if seg_id in segment_dict:
                        group_segments.append(segment_dict[seg_id])
                
                if group_segments:
                    groups.append(group_segments)
            
            # 检查是否有遗漏的片段
            used_ids = set()
            for group in groups:
                for seg in group:
                    used_ids.add(seg['id'])
            
            # 添加遗漏的片段
            for seg in segments:
                if seg['id'] not in used_ids:
                    groups.append([seg])
            
            return groups
            
        except Exception as e:
            logger.error(f"解析分段结果失败: {str(e)}")
            return [[seg] for seg in segments]
    
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
        优化段落
        
        Args:
            segments: 段落列表
            
        Returns:
            优化后的段落列表
        """
        try:
            optimized = []
            
            for segment in segments:
                # 检查段落长度
                if segment['duration'] > self.max_segment_duration:
                    logger.warning(f"段落 {segment['id']} 时长过长 ({segment['duration']:.2f}s)，建议进一步分割")
                
                # 检查文本长度
                if len(segment['text']) > self.max_chars_per_segment:
                    logger.warning(f"段落 {segment['id']} 文本过长 ({len(segment['text'])} 字符)")
                
                # 添加分段质量评分
                quality_score = self._calculate_segment_quality(segment)
                segment['quality_score'] = quality_score
                
                optimized.append(segment)
            
            # 按质量排序并记录
            avg_quality = sum(seg['quality_score'] for seg in optimized) / len(optimized)
            logger.info(f"段落平均质量评分: {avg_quality:.2f}")
            
            return optimized
            
        except Exception as e:
            logger.error(f"优化段落失败: {str(e)}")
            return segments
    
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
            if text_length < 20:
                score -= 0.2
            elif text_length > self.max_chars_per_segment:
                score -= 0.3
            
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