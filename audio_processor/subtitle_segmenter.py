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
    """字幕分段器（当前为规则模式）"""
    
    def __init__(self, config: dict, progress_callback=None):
        """
        初始化字幕分段器
        
        Args:
            config: 配置字典
            progress_callback: 进度回调函数，格式为 callback(current, total, message)
        """
        self.config = config
        self.progress_callback = progress_callback
        
        # # AI功能已禁用 - Kimi/OpenAI客户端配置
        # self.translation_config = config.get('translation', {})
        # self.use_kimi = self.translation_config.get('use_kimi', False)
        
        # # 根据配置选择API
        # if self.use_kimi:
        #     self.api_key = config.get('api_keys', {}).get('kimi_api_key')
        #     self.base_url = config.get('api_keys', {}).get('kimi_base_url', 'https://api.moonshot.cn/v1')
        #     self.model = self.translation_config.get('model', 'kimi-k2-0711-preview')
        #     self.max_tokens = self.translation_config.get('max_tokens', 8000)
        #     logger.info(f"字幕分段器使用Kimi API，模型: {self.model}")
        # else:
        #     self.api_key = config.get('api_keys', {}).get('openai_api_key')
        #     self.base_url = None
        #     self.model = self.translation_config.get('model', 'gpt-4o')
        #     self.max_tokens = self.translation_config.get('max_tokens', 4000)
        #     logger.info(f"字幕分段器使用OpenAI API，模型: {self.model}")
        
        # self.temperature = 0.3
        
        # # 创建客户端
        # if self.use_kimi:
        #     self.client = OpenAI(
        #         api_key=self.api_key,
        #         base_url=self.base_url
        #     )
        # else:
        #     self.client = OpenAI(api_key=self.api_key)
        
        # 理想的分段参数
        self.ideal_segment_duration = 12.0  # 理想时长12秒
        self.min_segment_duration = 8.0   # 最短8秒
        self.max_segment_duration = 16.0  # 最长16秒
        
        # 动态字符数参数（根据语言调整）
        self.ideal_chars = 120             # 理想字符数（约40个汉字）
        self.min_chars = 80               # 最少字符数（约27个汉字）
        self.max_chars = 160              # 最多字符数（约53个汉字）
        
        # 英文优化参数
        self.english_ideal_chars = 200     # 英文理想字符数（约30-40个单词）
        self.english_min_chars = 120       # 英文最少字符数（约20个单词）
        self.english_max_chars = 280       # 英文最多字符数（约50个单词）
    
    def _report_progress(self, current: int, total: int, message: str):
        """报告进度"""
        if self.progress_callback:
            try:
                self.progress_callback(current, total, message)
            except Exception as e:
                logger.warning(f"进度回调失败: {str(e)}")
    
    def segment_subtitles(self, segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        基于规则的字幕分段
        
        Args:
            segments: 原始字幕片段列表
            
        Returns:
            重新分段后的字幕片段列表
        """
        try:
            logger.info(f"开始规则分段处理，原始片段数: {len(segments)}")
            self._report_progress(0, 100, "开始规则分段分析...")
            
            # 0. 检测语言并调整参数
            self._report_progress(5, 100, "检测字幕语言...")
            detected_language = self._detect_subtitle_language(segments)
            self.current_language = detected_language  # 保存检测到的语言
            self._adjust_parameters_for_language(detected_language)
            logger.info(f"检测到字幕语言: {detected_language}，已调整分段参数")
            
            # 1. 快速质量评估 - 如果原始分段已经很好，直接跳过
            self._report_progress(10, 100, "评估原始分段质量...")
            if self._is_original_segments_good(segments):
                logger.info("原始分段质量良好，跳过分段")
                self._report_progress(100, 100, "原始分段质量良好，无需优化")
                return segments
            
            # 2. 规则预分段
            self._report_progress(20, 100, "执行规则分段...")
            final_segments = self._rule_based_pre_segmentation(segments)
            
            if not final_segments:
                logger.warning("规则分段结果为空，将使用原始分段")
                self._report_progress(100, 100, "规则分段失败，使用原始分段")
                return segments

            logger.info(f"规则分段完成，新段落数: {len(final_segments)}")
            if len(final_segments) > 0:
                logger.info(f"平均字符数: {sum(len(s['text']) for s in final_segments) / len(final_segments):.1f}")
                logger.info(f"平均时长: {sum(s['duration'] for s in final_segments) / len(final_segments):.1f}秒")
            
            self._report_progress(100, 100, "规则分段完成！")
            return final_segments
            
        except Exception as e:
            logger.error(f"规则分段失败: {str(e)}")
            self._report_progress(100, 100, f"规则分段失败: {str(e)}")
            logger.warning("使用原始分段")
            return segments
    
    def _is_original_segments_good(self, segments: List[Dict[str, Any]]) -> bool:
        """
        快速评估原始分段质量，如果已经很好就直接跳过
        
        Args:
            segments: 原始片段列表
            
        Returns:
            是否需要进一步优化
        """
        if len(segments) <= 10:  # 片段数很少，不需要优化
            return True
        
        # 计算质量指标
        total_chars = sum(len(s['text']) for s in segments)
        avg_chars = total_chars / len(segments)
        avg_duration = sum(s['duration'] for s in segments) / len(segments)
        
        # 检查是否大部分片段都在理想范围内
        good_segments = 0
        for seg in segments:
            char_count = len(seg['text'])
            duration = seg['duration']
            
            # 字符数和时长都在合理范围内
            if (self.current_min_chars <= char_count <= self.current_max_chars and 
                self.min_segment_duration <= duration <= self.max_segment_duration):
                good_segments += 1
        
        quality_ratio = good_segments / len(segments)
        
        # 如果80%以上的片段质量都很好，就跳过优化
        if quality_ratio >= 0.8:
            logger.info(f"原始分段质量良好 ({quality_ratio:.1%} 优质片段)，跳过智能分段")
            return True
        
        logger.info(f"原始分段需要优化 (质量比例: {quality_ratio:.1%})")
        return False
    
    def _detect_subtitle_language(self, segments: List[Dict[str, Any]]) -> str:
        """
        检测字幕语言
        
        Args:
            segments: 字幕片段列表
            
        Returns:
            检测到的语言代码 ('zh', 'en', 'ja', 'ko', 等)
        """
        if not segments:
            return 'zh'  # 默认中文
        
        # 取前几个片段的文本进行分析
        sample_texts = []
        for i, seg in enumerate(segments[:10]):  # 只分析前10个片段
            text = seg.get('text', '').strip()
            if text:
                sample_texts.append(text)
        
        if not sample_texts:
            return 'zh'
        
        combined_text = ' '.join(sample_texts)
        
        # 简单的语言检测逻辑
        # 检测中文字符
        chinese_chars = sum(1 for char in combined_text if '\u4e00' <= char <= '\u9fff')
        
        # 检测英文单词
        english_words = len([word for word in combined_text.split() if word.isalpha() and all(ord(c) < 128 for c in word)])
        
        # 检测日文字符（平假名、片假名）
        japanese_chars = sum(1 for char in combined_text if '\u3040' <= char <= '\u309f' or '\u30a0' <= char <= '\u30ff')
        
        # 检测韩文字符
        korean_chars = sum(1 for char in combined_text if '\uac00' <= char <= '\ud7af')
        
        total_chars = len(combined_text.replace(' ', ''))
        
        # 判断主要语言
        if chinese_chars > total_chars * 0.3:
            return 'zh'
        elif english_words > 5 and english_words > chinese_chars:
            return 'en'
        elif japanese_chars > total_chars * 0.2:
            return 'ja'
        elif korean_chars > total_chars * 0.2:
            return 'ko'
        else:
            # 如果都不明显，通过其他特征判断
            if '.' in combined_text and combined_text.count('.') > combined_text.count('。'):
                return 'en'  # 英文标点更多
            else:
                return 'zh'  # 默认中文
    
    def _adjust_parameters_for_language(self, language: str):
        """
        根据检测到的语言调整分段参数
        
        Args:
            language: 语言代码
        """
        if language == 'en':
            # 英文参数
            self.current_ideal_chars = self.english_ideal_chars
            self.current_min_chars = self.english_min_chars
            self.current_max_chars = self.english_max_chars
            logger.info(f"使用英文分段参数: {self.current_min_chars}-{self.current_max_chars} 字符")
        elif language in ['ja', 'ko']:
            # 日韩文参数（介于中英文之间）
            self.current_ideal_chars = int(self.ideal_chars * 1.3)
            self.current_min_chars = int(self.min_chars * 1.2)
            self.current_max_chars = int(self.max_chars * 1.3)
            logger.info(f"使用日韩文分段参数: {self.current_min_chars}-{self.current_max_chars} 字符")
        else:
            # 中文或其他语言使用默认参数
            self.current_ideal_chars = self.ideal_chars
            self.current_min_chars = self.min_chars
            self.current_max_chars = self.max_chars
            logger.info(f"使用中文分段参数: {self.current_min_chars}-{self.current_max_chars} 字符")
    
    def _rule_based_pre_segmentation(self, segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        基于规则的预分段，大幅减少需要LLM处理的片段数量
        
        Args:
            segments: 原始片段列表
            
        Returns:
            预分段后的片段列表
        """
        logger.info("开始规则预分段...")
        
        pre_segments = []
        current_group = []
        current_text = ""
        current_start = 0
        
        for i, seg in enumerate(segments):
            current_group.append(i + 1)  # 原始片段编号从1开始
            current_text += seg['text']
            
            # 检查是否需要分段
            should_split = False
            
            # 1. 基于字符数 - 超过最大字符数强制分段
            if len(current_text) > self.current_max_chars:
                should_split = True
            
            # 2. 基于时长 - 超过最大时长强制分段
            if seg['end'] - current_start > self.max_segment_duration:
                should_split = True
            
            # 3. 基于标点符号 - 在句子结束处分段
            if seg['text'].strip().endswith(('。', '！', '？', '.', '!', '?')):
                should_split = True
            
            # 4. 基于语义停顿 - 检测明显的语义边界
            if self._is_semantic_boundary(seg, segments, i):
                should_split = True
            
            # 5. 如果是最后一个片段，强制分段
            if i == len(segments) - 1:
                should_split = True
            
            if should_split and current_group:
                # 创建预分段
                pre_segment = {
                    'text': current_text,
                    'start': current_start,
                    'end': seg['end'],
                    'duration': seg['end'] - current_start,
                    'original_indices': current_group,
                    'original_count': len(current_group),
                    'needs_llm_optimization': False # 预分段不进行LLM优化
                }
                
                pre_segments.append(pre_segment)
                
                # 重置
                current_group = []
                current_text = ""
                current_start = seg['end']
        
        logger.info(f"规则预分段完成，从 {len(segments)} 个片段减少到 {len(pre_segments)} 个预分段")
        return pre_segments
    
    def _is_semantic_boundary(self, current_seg: Dict, all_segments: List[Dict], current_index: int) -> bool:
        """
        检测语义边界
        
        Args:
            current_seg: 当前片段
            all_segments: 所有片段列表
            current_index: 当前索引
            
        Returns:
            是否为语义边界
        """
        # 简单的语义边界检测
        text = current_seg['text'].strip()
        
        # 1. 明显的段落结束标记
        if text.endswith(('。', '！', '？', '.', '!', '?')):
            return True

        # 2. 原始字幕中的换行（强烈的语义边界信号）
        if '\n' in current_seg.get('original_raw_text', ''):
            return True
        
        # 3. 英文特有的语义边界检测
        if hasattr(self, 'current_language') and self.current_language == 'en':
            # 检测英文句子结构
            if self._is_english_sentence_boundary(text, all_segments, current_index):
                return True
        
        # 4. 检测话题转换（简单实现）
        if current_index > 0:
            prev_text = all_segments[current_index - 1]['text'].strip()
            
            # 如果前后文本差异很大，可能是话题转换
            if len(text) > 20 and len(prev_text) > 20:
                # 简单的关键词差异检测
                current_words = set(text[:20].split())
                prev_words = set(prev_text[-20:].split())
                if len(current_words & prev_words) < 2:  # 几乎没有共同词
                    return True
        
        return False
    
    def _is_english_sentence_boundary(self, text: str, all_segments: List[Dict], current_index: int) -> bool:
        """
        检测英文特有的语义边界
        
        Args:
            text: 当前文本
            all_segments: 所有片段
            current_index: 当前索引
            
        Returns:
            是否为英文语义边界
        """
        # 1. 检测完整句子结束
        if text.endswith(('.', '!', '?', '...', '."', '!"', '?"')):
            return True
        
        # 2. 检测对话结束
        if text.endswith(('."', '!"', '?"', ".'", "!'", "?'")):
            return True
        
        # 3. 检测段落标记词
        paragraph_markers = ['however', 'meanwhile', 'furthermore', 'moreover', 'therefore', 'consequently', 'nevertheless']
        words = text.lower().split()
        if words and words[0] in paragraph_markers:
            return True
        
        # 4. 检测时间或场景转换
        time_markers = ['later', 'earlier', 'meanwhile', 'suddenly', 'then', 'next', 'finally']
        if words and words[0] in time_markers:
            return True
        
        # 5. 检测对话开始
        if text.startswith(('"', "'")) and current_index > 0:
            prev_text = all_segments[current_index - 1]['text'].strip()
            if not prev_text.startswith(('"', "'")):
                return True
        
        return False
    
    # def _needs_llm_optimization(self, text: str, duration: float) -> bool:
    #     """
    #     判断是否需要LLM优化
        
    #     Args:
    #         text: 文本内容
    #         duration: 时长
            
    #     Returns:
    #         是否需要LLM优化
    #     """
    #     char_count = len(text)
        
    #     # 如果字符数和时长都在理想范围内，不需要LLM优化
    #     if (self.min_chars <= char_count <= self.max_chars and 
    #         self.min_segment_duration <= duration <= self.max_segment_duration):
    #         return False
        
    #     # 任何超出理想范围的都进行优化
    #     return True
    
    # def _create_optimal_batches(self, pre_segments: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    #     """
    #     创建最优处理批次，控制每个批次的token数量
        
    #     Args:
    #         pre_segments: pre_segments
            
    #     Returns:
    #         批次列表
    #     """
    #     batches = []
    #     current_batch = []
    #     current_chars = 0
    #     max_chars_per_batch = 2500  # 控制每个批次的字符数
        
    #     for seg in pre_segments:
    #         seg_chars = len(seg['text'])
            
    #         # 如果当前批次加上新片段会超出限制，且当前批次不为空，则开始新批次
    #         if current_chars + seg_chars > max_chars_per_batch and current_batch:
    #             batches.append(current_batch)
    #             current_batch = []
    #             current_chars = 0
            
    #         current_batch.append(seg)
    #         current_chars += seg_chars
        
    #     # 添加最后一个批次
    #     if current_batch:
    #         batches.append(current_batch)
        
    #     logger.info(f"创建了 {len(batches)} 个处理批次，平均每批次 {sum(len(batch) for batch in batches) / len(batches):.1f} 个片段")
    #     return batches
    
    # def _parallel_llm_segmentation(self, batches: List[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    #     """
    #     并行LLM处理多个批次
        
    #     Args:
    #         batches: 批次列表
            
    #     Returns:
    #         所有处理结果
    #     """
    #     from concurrent.futures import ThreadPoolExecutor, as_completed
    #     import threading
        
    #     all_results = []
    #     results_lock = threading.Lock()
        
    #     def process_batch(batch: List[Dict[str, Any]], batch_index: int) -> List[Dict[str, Any]]:
    #         """处理单个批次"""
    #         try:
    #             # 检查批次中是否有任何片段需要优化
    #             needs_optimization = any(seg.get('needs_llm_optimization', True) for seg in batch)
                
    #             if not needs_optimization:
    #                 logger.info(f"批次 {batch_index + 1} 无需LLM优化")
    #                 return batch

    #             # 如果需要，则对整个批次进行优化
    #             api_name = "Kimi" if self.use_kimi else "OpenAI"
    #             logger.info(f"批次 {batch_index + 1} 使用{api_name}优化 {len(batch)} 个片段")
                
    #             batch_content = self._build_batch_content(batch)
    #             result = self._analyze_batch_with_ai(batch_content, batch)
    #             optimized_segments = self._parse_batch_result(result)
                
    #             # 如果AI优化失败或返回空，则返回原始批次
    #             if not optimized_segments:
    #                 logger.warning(f"批次 {batch_index + 1} AI优化失败或返回空结果，使用预分段批次")
    #                 return batch
                
    #             return optimized_segments
                
    #         except Exception as e:
    #             logger.error(f"批次 {batch_index + 1} 处理失败: {str(e)}")
    #             return batch  # 在任何异常情况下都返回原始批次
        
    #     # 并行处理所有批次
    #     with ThreadPoolExecutor(max_workers=min(4, len(batches))) as executor:
    #         future_to_batch = {
    #             executor.submit(process_batch, batch, i): i 
    #             for i, batch in enumerate(batches)
    #         }
            
    #         for future in as_completed(future_to_batch):
    #             batch_index = future_to_batch[future]
    #             try:
    #                 batch_results = future.result()
    #                 with results_lock:
    #                     all_results.extend(batch_results)
    #                 logger.info(f"批次 {batch_index + 1} 处理完成")
    #             except Exception as e:
    #                 logger.error(f"批次 {batch_index + 1} 处理异常: {str(e)}")
        
    #     return all_results
    
    # def _build_batch_content(self, segments: List[Dict[str, Any]]) -> str:
    #     """
    #     构建批次内容
        
    #     Args:
    #         segments: 片段列表
            
    #     Returns:
    #         批次内容字符串
    #     """
    #     lines = []
    #     for i, seg in enumerate(segments):
    #         lines.append(f"[{i+1}] {seg['start']:.2f}s-{seg['end']:.2f}s ({seg['duration']:.2f}s)")
    #         lines.append(f"    {seg['text']}")
    #         lines.append("")
        
    #     return "\n".join(lines)
    
    # def _analyze_batch_with_ai(self, batch_content: str, segments: List[Dict[str, Any]]) -> str:
    #     """
    #     使用AI分析单个批次
        
    #     Args:
    #         batch_content: 批次内容
    #         segments: 原始片段列表
            
    #     Returns:
    #         分析结果
    #     """
    #     system_prompt = f"""你是一个专业的字幕分段专家。请优化给定的字幕片段，使其更符合以下标准：

    # 优化目标：
    # 1. **字符数控制**：
    #    - 理想字符数：{self.ideal_chars}个字符（约40个汉字）
    #    - 最少：{self.min_chars}个字符（约27个汉字），最多：{self.max_chars}个字符（约53个汉字）
    # 2. **时长控制**：
    #    - 理想时长：{self.ideal_segment_duration}秒
    #    - 最短：{self.min_segment_duration}秒，最长：{self.max_segment_duration}秒
    # 3. **语义完整性**：确保每个段落表达完整的意思

    # 请以JSON格式返回优化结果，格式：
    # {{
    #   "segments": [
    #     {{
    #       "original_indices": [1, 2, 3],
    #       "text": "优化后的文本",
    #       "start_time": 0.0,
    #       "end_time": 8.5,
    #       "duration": 8.5
    #     }}
    #   ]
    # }}

    # 如果当前片段已经很好，可以保持不变。"""

    #     user_prompt = f"""请优化以下字幕片段：

    # {batch_content}

    # 请返回JSON格式的优化结果。"""

    #     try:
    #         response = self.client.chat.completions.create(
    #             model=self.model,
    #             messages=[
    #                 {"role": "system", "content": system_prompt},
    #                 {"role": "user", "content": user_prompt}
    #             ],
    #             temperature=self.temperature,
    #             max_tokens=min(self.max_tokens, 2000)  # 减少token使用
    #         )
            
    #         result = response.choices[0].message.content.strip()
    #         logger.debug(f"AI Raw Response (Batch): {result}")
    #         return result
            
    #     except Exception as e:
    #         logger.error(f"批次AI分析失败: {str(e)}")
    #         raise e
    
    # def _parse_batch_result(self, result: str) -> List[Dict[str, Any]]:
    #     """
    #     解析批次处理结果
        
    #     Args:
    #         result: AI返回的结果
            
    #     Returns:
    #         解析后的片段列表，如果失败则为空列表
    #     """
    #     try:
    #         data = json.loads(result)
            
    #         if 'segments' not in data or not isinstance(data['segments'], list):
    #             logger.warning("批次结果格式不正确（缺少segments列表），使用原始片段")
    #             return []
            
    #         parsed_segments = []
            
    #         for seg_data in data['segments']:
    #             if not all(key in seg_data for key in ['original_indices', 'text', 'start_time', 'end_time', 'duration']):
    #                 continue
                
    #             new_segment = {
    #                 'text': seg_data['text'],
    #                 'start': seg_data['start_time'],
    #                 'end': seg_data['end_time'],
    #                 'duration': seg_data['duration'],
    #                 'original_indices': seg_data['original_indices'],
    #                 'original_count': len(seg_data['original_indices'])
    #             }
                
    #             parsed_segments.append(new_segment)
            
    #         return parsed_segments
            
    #     except json.JSONDecodeError as e:
    #         logger.warning(f"批次结果JSON解析失败: {str(e)}")
    #         return []
    #     except Exception as e:
    #         logger.error(f"解析批次结果失败: {str(e)}")
    #         return []
    
    def _merge_and_optimize_results(self, all_results: List[Dict[str, Any]], original_segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        合并和优化所有处理结果
        
        Args:
            all_results: 所有处理结果
            original_segments: 原始片段列表
            
        Returns:
            最终优化的片段列表
        """
        # 简单的合并，按时间排序
        merged_segments = sorted(all_results, key=lambda x: x['start'])
        
        # 移除重复或重叠的片段
        final_segments = []
        for seg in merged_segments:
            # 检查是否与前面的片段重叠
            is_duplicate = False
            for prev_seg in final_segments:
                if (abs(seg['start'] - prev_seg['start']) < 0.1 and 
                    abs(seg['end'] - prev_seg['end']) < 0.1):
                    is_duplicate = True
                    break
            
            if not is_duplicate:
                final_segments.append(seg)
        
        logger.info(f"合并完成，最终片段数: {len(final_segments)}")
        return final_segments
    
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
    
    # def _analyze_with_ai(self, srt_content: str, original_segments: List[Dict[str, Any]]) -> str:
    #     """
    #     使用AI分析整个SRT文档进行智能分段
        
    #     Args:
    #         srt_content: SRT文档内容
    #         original_segments: 原始片段列表
            
    #     Returns:
    #         分段结果JSON字符串
    #     """
    #     system_prompt = f"""你是一个专业的字幕分段专家。请分析给定的SRT字幕文档，将零散的字幕片段重新组织成逻辑完整的段落。

    # 分段原则：
    # 1. **语义完整性**：确保每个段落表达完整的意思，不要在句子中间断开
    # 2. **时间合理性**：
    #    - 理想时长：{self.ideal_segment_duration}秒
    #    - 最短时长：{self.min_segment_duration}秒，最长时长：{self.max_segment_duration}秒
    # 3. **字符数控制**：
    #    - 理想字符数：{self.ideal_chars}个字符（约40个汉字）
    #    - 最少：{self.min_chars}个字符（约27个汉字），最多：{self.max_chars}个字符（约53个汉字）
    # 4. **上下文连贯**：合并相关的语句，保持话题的连续性
    # 5. **标点符号**：在自然的标点符号处分段

    # 请以JSON格式返回分段结果，包含每个新段落的：
    # - segments: 包含的原始片段编号列表（从1开始）
    # - text: 合并后的文本内容
    # - start_time: 开始时间（秒）
    # - end_time: 结束时间（秒）
    # - duration: 持续时间（秒）

    # 示例格式：
    # {{
    #   "segments": [
    #     {{
    #       "segments": [1, 2, 3],
    #       "text": "合并后的完整句子内容",
    #       "start_time": 0.0,
    #       "end_time": 8.5,
    #       "duration": 8.5
    #     }}
    #   ]
    # }}

    # 请确保：
    # 1. 所有原始片段都被包含在新段落中
    # 2. 时间码准确对应原始片段的时间范围
    # 3. 文本内容完整且逻辑连贯
    # 4. 每个新段落的时长在合理范围内
    # """

    #     user_prompt = f"""请分析以下SRT字幕文档并进行智能分段：

    # {srt_content}

    # 请返回JSON格式的分段结果。"""

    #     try:
    #         response = self.client.chat.completions.create(
    #             model=self.model,
    #             messages=[
    #                 {"role": "system", "content": system_prompt},
    #                 {"role": "user", "content": user_prompt}
    #             ],
    #             temperature=self.temperature,
    #             max_tokens=self.max_tokens
    #         )
            
    #         result = response.choices[0].message.content.strip()
    #         logger.info("AI分段分析完成")
    #         return result
            
    #     except Exception as e:
    #         logger.error(f"AI分段分析失败: {str(e)}")
    #         raise e
    
    # def _parse_segmentation_result(self, result: str, original_segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    #     """
    #     解析AI返回的分段结果
        
    #     Args:
    #         result: AI返回的JSON字符串
    #         original_segments: 原始片段列表
            
    #     Returns:
    #         解析后的新片段列表
    #     """
    #     try:
    #         # 尝试解析JSON
    #         data = json.loads(result)
            
    #         if 'segments' not in data:
    #             logger.warning("AI返回结果格式不正确，尝试其他解析方式")
    #             return self._fallback_parse(result, original_segments)
            
    #         new_segments = []
            
    #         for seg_data in data['segments']:
    #             # 验证必要字段
    #             if not all(key in seg_data for key in ['segments', 'text', 'start_time', 'end_time', 'duration']):
    #                 logger.warning(f"段落数据缺少必要字段: {seg_data}")
    #                 continue
                
    #             # 验证原始片段索引
    #             original_indices = seg_data['segments']
    #             if not all(1 <= idx <= len(original_segments) for idx in original_indices):
    #                 logger.warning(f"原始片段索引超出范围: {original_indices}")
    #                 continue
                
    #             # 创建新片段（不生成ID，等用户确认后再生成）
    #             new_segment = {
    #                 'text': seg_data['text'],
    #                 'start': seg_data['start_time'],
    #                 'end': seg_data['end_time'],
    #                 'duration': seg_data['duration'],
    #                 'original_indices': original_indices,
    #                 'original_count': len(original_indices)
    #             }
                
    #             new_segments.append(new_segment)
            
    #         logger.info(f"成功解析 {len(new_segments)} 个新段落")
    #         return new_segments
            
    #     except json.JSONDecodeError as e:
    #         logger.warning(f"JSON解析失败: {str(e)}")
    #         return self._fallback_parse(result, original_segments)
    #     except Exception as e:
    #         logger.error(f"解析分段结果失败: {str(e)}")
    #         return original_segments
    
    # def _fallback_parse(self, result: str, original_segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    #     """
    #     备用解析方法，当JSON解析失败时使用
        
    #     Args:
    #         result: AI返回的文本
    #         original_segments: 原始片段列表
            
    #     Returns:
    #         解析后的新片段列表
    #     """
    #     logger.info("使用备用解析方法")
        
    #     # 简单的基于字符数的分段
    #     new_segments = []
    #     current_group = []
    #     current_text = ""
    #     current_start = 0
        
    #     for i, seg in enumerate(original_segments):
    #         current_group.append(i + 1)  # 原始片段编号从1开始
    #         current_text += seg['text']
            
    #         # 检查是否需要分段
    #         should_split = False
            
    #         # 基于字符数
    #         if len(current_text) > self.max_chars:
    #             should_split = True
            
    #         # 基于时长
    #         if seg['end'] - current_start > self.max_segment_duration:
    #             should_split = True
            
    #         # 基于标点符号
    #         if seg['text'].strip().endswith(('。', '！', '？', '.', '!', '?')):
    #             should_split = True
            
    #         # 如果是最后一个片段，强制分段
    #         if i == len(original_segments) - 1:
    #             should_split = True
            
    #         if should_split and current_group:
    #             new_segment = {
    #                 'text': current_text,
    #                 'start': current_start,
    #                 'end': seg['end'],
    #                 'duration': seg['end'] - current_start,
    #                 'original_indices': current_group,
    #                 'original_count': len(current_group)
    #             }
                
    #             new_segments.append(new_segment)
                
    #             # 重置
    #             current_group = []
    #             current_text = ""
    #             current_start = seg['end']
        
    #     return new_segments
    
    def _evaluate_segments(self, segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        评估分段质量并优化
        
        Args:
            segments: 分段后的片段列表
            
        Returns:
            优化后的片段列表
        """
        evaluated_segments = []
        
        for seg in segments:
            # 计算质量分数
            quality_score = self._calculate_quality_score(seg)
            seg['quality_score'] = quality_score
            
            # 处理过长片段
            if len(seg['text']) > self.max_chars * 1.5:
                logger.info(f"分段 {seg['id']} 过长，进行拆分")
                split_segments = self._split_long_segment(seg)
                evaluated_segments.extend(split_segments)
            else:
                evaluated_segments.append(seg)
        
        return evaluated_segments
    
    def _calculate_quality_score(self, segment: Dict[str, Any]) -> float:
        """
        计算分段质量分数
        
        Args:
            segment: 片段字典
            
        Returns:
            质量分数 (0-1)
        """
        score = 1.0
        
        # 字符数评分
        char_count = len(segment.get('text', ''))
        if char_count < self.min_chars:
            score *= 0.7
        elif char_count > self.max_chars:
            score *= 0.8
        else:
            # 理想字符数附近得分最高
            ideal_diff = abs(char_count - self.ideal_chars)
            score *= max(0.9, 1.0 - ideal_diff / self.ideal_chars * 0.2)
        
        # 时长评分
        duration = segment.get('duration', 0.0)
        if duration < self.min_segment_duration:
            score *= 0.7
        elif duration > self.max_segment_duration:
            score *= 0.8
        else:
            # 理想时长附近得分最高
            ideal_diff = abs(duration - self.ideal_segment_duration)
            score *= max(0.9, 1.0 - ideal_diff / self.ideal_segment_duration * 0.2)
        
        # 文本完整性评分
        text = segment['text']
        if text.endswith(('。', '！', '？', '.', '!', '?')):
            score *= 1.1  # 完整句子加分
        elif text.endswith(('，', '；', ',', ';')):
            score *= 0.9  # 不完整句子减分
        
        return min(1.0, score)
    
    def _split_long_segment(self, segment: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        拆分过长的片段
        
        Args:
            segment: 要拆分的片段
            
        Returns:
            拆分后的片段列表
        """
        text = segment.get('text', '')
        duration = segment.get('duration', 0.0)
        
        # 简单的按标点符号拆分
        split_points = []
        for i, char in enumerate(text):
            if char in '。！？；，':
                split_points.append(i + 1)
        
        if not split_points:
            # 如果没有标点符号，按字符数拆分
            mid_point = len(text) // 2
            split_points = [mid_point]
        
        # 创建拆分后的片段
        split_segments = []
        start_pos = 0
        start_time = segment['start']
        
        for split_point in split_points:
            if split_point >= len(text):
                break
                
            # 计算时间比例
            text_ratio = split_point / len(text)
            end_time = segment['start'] + duration * text_ratio
            
            split_text = text[start_pos:split_point].strip()
            if split_text:
                split_segment = segment.copy()
                split_segment['text'] = split_text
                split_segment['start'] = start_time
                split_segment['end'] = end_time
                split_segment['duration'] = end_time - start_time
                # 移除ID字段，等用户确认后再生成
                if 'id' in split_segment:
                    del split_segment['id']
                split_segments.append(split_segment)
            
            start_pos = split_point
            start_time = end_time
        
        # 处理最后一部分
        if start_pos < len(text):
            split_text = text[start_pos:].strip()
            if split_text:
                split_segment = segment.copy()
                split_segment['text'] = split_text
                split_segment['start'] = start_time
                split_segment['end'] = segment['end']
                split_segment['duration'] = segment['end'] - start_time
                # 移除ID字段，等用户确认后再生成
                if 'id' in split_segment:
                    del split_segment['id']
                split_segments.append(split_segment)
        
        return split_segments
    
    def create_segmentation_report(self, original_segments: List[Dict[str, Any]], 
                                 new_segments: List[Dict[str, Any]]) -> str:
        """
        创建分段报告
        
        Args:
            original_segments: 原始片段列表
            new_segments: 新片段列表
            
        Returns:
            报告字符串
        """
        report_lines = []
        report_lines.append("=== 智能分段报告 ===")
        report_lines.append(f"原始片段数: {len(original_segments)}")
        report_lines.append(f"新片段数: {len(new_segments)}")
        report_lines.append(f"优化比例: {len(new_segments) / len(original_segments):.2f}")
        
        # 统计信息
        original_avg_chars = sum(len(s['text']) for s in original_segments) / len(original_segments)
        new_avg_chars = sum(len(s['text']) for s in new_segments) / len(new_segments)
        original_avg_duration = sum(s['duration'] for s in original_segments) / len(original_segments)
        new_avg_duration = sum(s['duration'] for s in new_segments) / len(new_segments)
        
        report_lines.append(f"平均字符数: {original_avg_chars:.1f} -> {new_avg_chars:.1f}")
        report_lines.append(f"平均时长: {original_avg_duration:.1f}s -> {new_avg_duration:.1f}s")
        
        # 质量评分
        avg_quality = sum(s.get('quality_score', 0.5) for s in new_segments) / len(new_segments)
        report_lines.append(f"平均质量评分: {avg_quality:.2f}")
        
        return "\n".join(report_lines) 