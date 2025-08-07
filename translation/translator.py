"""
翻译模块
使用大语言模型进行智能翻译，考虑时间约束和上下文连贯性
支持高性能并发翻译
"""

from openai import OpenAI, AzureOpenAI
from typing import List, Dict, Any, Optional
from loguru import logger
import re
import time
import json
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

from utils.cache_manager import get_cache_manager


class Translator:
    """智能翻译器 - 支持高性能并发"""
    
    def __init__(self, config: dict, progress_callback=None):
        """
        初始化翻译器
        
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
            logger.info(f"使用Kimi API，模型: {self.model}")
        else:
            self.api_key = config.get('api_keys', {}).get('openai_api_key')
            self.base_url = None
            self.model = self.translation_config.get('model', 'gpt-4o')
            self.max_tokens = self.translation_config.get('max_tokens', 3000)
            logger.info(f"使用OpenAI API，模型: {self.model}")
        
        self.temperature = self.translation_config.get('temperature', 0.3)
        self.system_prompt = self.translation_config.get('system_prompt', '你是一个专业的翻译专家，擅长将中文文本翻译为其他语言。')
        
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
        
        # 语言映射
        self.language_names = {
            'en': 'English',
            'es': 'Spanish',
            'fr': 'French',
            'de': 'German',
            'ja': 'Japanese',
            'ko': 'Korean'
        }
        
        # 并发优化参数 - 根据Kimi API限制优化
        if self.use_kimi:
            # Kimi API限制：并发50，RPM 200，TPM 128000
            self.max_concurrent_requests = 12  # 适中的并发数，避免过度并发
            self.batch_size = 6  # 减少批次大小，增加并发度
            self.request_delay = 0.3  # 控制请求频率，避免超过RPM限制(200/min = 3.33/s)
        else:
            # OpenAI API保守设置
            self.max_concurrent_requests = 8
            self.batch_size = 5  # 同样减少批次大小
            self.request_delay = 0.05
        
        # 简单缓存机制
        self.translation_cache = {}
        self.max_cache_size = 1000
        self.cache_lock = threading.Lock()
        
        # Token使用统计
        self.token_stats = {
            'total_prompt_tokens': 0,
            'total_completion_tokens': 0,
            'total_requests': 0,
            'cache_hits': 0,
            'session_start_time': time.time()
        }

        # 获取全局缓存实例
        self.cache_manager = get_cache_manager()

        # API调用统计
        self.api_call_stats = {
            'total_calls': 0,
            'total_tokens': 0,
            'session_start_time': time.time()
        }
    
    def _report_progress(self, current: int, total: int, message: str):
        """报告进度"""
        if self.progress_callback:
            try:
                self.progress_callback(current, total, message)
            except Exception as e:
                logger.warning(f"翻译进度回调失败: {str(e)}")
    
    def translate_segments_with_cache(self, segments: List[Dict], target_language: str, progress_callback=None) -> List[Dict]:
        """
        使用缓存批量翻译字幕片段。

        Args:
            segments: 待翻译的片段列表。
            target_language: 目标语言代码。
            progress_callback: 进度回调函数。

        Returns:
            翻译后的片段列表。
        """
        if progress_callback is None:
            progress_callback = self.progress_callback

        processed_segments = []
        segments_to_translate_map = {} # 使用字典来保留原始索引
        cache_hits = 0
        
        # 1. 检查缓存
        for i, segment in enumerate(segments):
            # 优先使用 confirmed_text, 其次是 text
            text_to_translate = segment.get('confirmed_text', segment.get('text', ''))
            
            # 创建不同的缓存键，区分初次翻译和用户确认后的翻译
            is_user_confirmed = 'confirmed_text' in segment
            cache_type = 'translation_confirmed' if is_user_confirmed else 'translation'
            
            cache_key = self.cache_manager.get_cache_key_for_text(
                cache_type, text_to_translate, target_language=target_language
            )
            cached_result = self.cache_manager.get(cache_key)
            
            if cached_result:
                segment['translated_text'] = cached_result
                processed_segments.append(segment)
                cache_hits += 1
            else:
                # 存储需要翻译的文本和它的原始位置
                segments_to_translate_map[i] = {
                    'text': text_to_translate,
                    'is_user_confirmed': is_user_confirmed
                }
            
            if progress_callback:
                progress_callback(i + 1, len(segments), "检查翻译缓存")

        logger.info(f"翻译缓存命中: {cache_hits}/{len(segments)}")

        # 2. 对未命中缓存的片段进行批量翻译
        if segments_to_translate_map:
            original_indices = list(segments_to_translate_map.keys())
            texts_to_translate = [segments_to_translate_map[idx]['text'] for idx in original_indices]
            
            try:
                # 调用批量翻译方法
                translated_texts = self.translate_segments(texts_to_translate, target_language, progress_callback)
                
                # 3. 合并结果并更新缓存
                for i, translated_text in enumerate(translated_texts):
                    original_index = original_indices[i]
                    segment = segments[original_index]
                    
                    segment['translated_text'] = translated_text
                    processed_segments.append(segment)
                    
                    # 更新缓存
                    text_info = segments_to_translate_map[original_index]
                    text_to_translate = text_info['text']
                    is_user_confirmed = text_info['is_user_confirmed']
                    
                    # 根据是否为用户确认的文本选择不同的缓存类型
                    cache_type = 'translation_confirmed' if is_user_confirmed else 'translation'
                    
                    cache_key = self.cache_manager.get_cache_key_for_text(
                        cache_type, text_to_translate, target_language=target_language
                    )
                    self.cache_manager.set(
                        key=cache_key,
                        data=translated_text,
                        cache_type=cache_type,
                        target_language=target_language
                    )
            except Exception as e:
                logger.error(f"批量翻译失败: {e}")
                raise  # 翻译失败时直接抛出异常，不使用降级方案
        
        # 按原始顺序重新排序
        processed_segments.sort(key=lambda x: x['id'])
        return processed_segments

    def translate_segments(self, texts: List[str], target_language: str, progress_callback=None) -> List[str]:
        """
        批量翻译文本列表。
        (此方法现在只接收文本列表)
        """
        if not texts:
            return []
        
        # 为了让内部函数正常工作，将List[str]转换为List[Dict]，并使用索引作为临时ID
        segments_with_meta = [{'id': i, 'text': text} for i, text in enumerate(texts)]

        try:
            logger.info(f"开始并发翻译 {len(texts)} 个片段到 {target_language}")
            self._report_progress(0, 100, f"开始翻译到{target_language}...")
            
            # 检查缓存
            self._report_progress(5, 100, "检查翻译缓存...")
            # 使用转换后的segments_with_meta
            segments_to_translate, cached_translations = self._separate_cached_segments(segments_with_meta, target_language)
            
            if not segments_to_translate:
                logger.info("所有片段都有缓存，直接返回")
                self._report_progress(100, 100, "所有片段已有缓存，翻译完成！")
                all_translations_dicts = self._merge_cached_results(segments_with_meta, cached_translations)
            else:
                if cached_translations:
                    logger.info(f"从缓存中找到 {len(cached_translations)} 个翻译，需要翻译 {len(segments_to_translate)} 个新片段")
                    self._report_progress(10, 100, f"缓存命中{len(cached_translations)}个，翻译{len(segments_to_translate)}个新片段...")
                else:
                    self._report_progress(10, 100, f"开始并发翻译{len(segments_to_translate)}个片段...")
                
                # 并发翻译
                new_translations = self._concurrent_translate(segments_to_translate, target_language)
                
                # 合并缓存和新翻译的结果
                self._report_progress(95, 100, "合并翻译结果...")
                all_translations_dicts = self._merge_all_results(segments_with_meta, cached_translations, new_translations)
            
            logger.info("并发翻译完成")
            self._report_progress(100, 100, "翻译完成！")

            # 将List[Dict]转回List[str]
            all_translations_texts = [d.get('translated_text', d.get('text', '')) for d in all_translations_dicts]
            return all_translations_texts
            
        except Exception as e:
            logger.error(f"翻译失败: {str(e)}")
            self._report_progress(100, 100, f"翻译失败: {str(e)}")
            raise  # 直接抛出异常，不使用降级方案
    
    def _concurrent_translate(self, segments: List[Dict[str, Any]], target_language: str) -> List[Dict[str, Any]]:
        """
        并发翻译片段 - 优化版，动态调整批次大小
        
        Args:
            segments: 需要翻译的片段列表
            target_language: 目标语言代码
            
        Returns:
            翻译后的片段列表
        """
        if not segments:
            return []
        
        # 动态调整批次大小，充分利用更高的并发能力
        # 提高并发数：将最大并发数提升一倍，但不超过批次数
        optimal_batch_size = self._calculate_optimal_batch_size(len(segments))
        batches = [segments[i:i + optimal_batch_size] for i in range(0, len(segments), optimal_batch_size)]
        
        # 提高并发数，最大为原设定的2倍，但不超过批次数
        increased_concurrent = min(len(batches), self.max_concurrent_requests * 2)
        
        logger.info(f"并发翻译策略：{len(segments)} 个片段 -> {len(batches)} 个批次（每批 {optimal_batch_size} 个）")
        logger.info(f"并发执行：{increased_concurrent} 个并发任务（最大限制 {self.max_concurrent_requests * 2}）")
        
        self._report_progress(15, 100, f"创建{len(batches)}个并发翻译任务（{increased_concurrent}个并发执行）...")
        
        # 使用线程池并发处理
        translated_segments = []
        completed_batches = 0
        
        with ThreadPoolExecutor(max_workers=self.max_concurrent_requests) as executor:
            # 提交所有翻译任务
            future_to_batch = {
                executor.submit(self._translate_batch_thread_safe, batch, target_language, i + 1): batch 
                for i, batch in enumerate(batches)
            }
            
            # 收集结果
            for future in as_completed(future_to_batch):
                try:
                    batch_result = future.result()
                    translated_segments.extend(batch_result)
                    
                    # 缓存结果
                    batch = future_to_batch[future]
                    for original, translated in zip(batch, batch_result):
                        text = original.get('text')
                        if text:
                            self._cache_translation(text, target_language, translated)
                    
                    # 更新进度
                    completed_batches += 1
                    progress = 15 + int((completed_batches / len(batches)) * 75)  # 15-90%
                    self._report_progress(progress, 100, f"完成翻译批次 {completed_batches}/{len(batches)}...")
                        
                except Exception as e:
                    logger.error(f"批次翻译失败: {str(e)}")
                    # 中断整个翻译过程
                    raise ValueError(f"翻译过程中发生错误: {str(e)}")
        
        # 按原始顺序排序
        translated_segments.sort(key=lambda x: x['id'])
        
        logger.info(f"并发翻译完成，处理了 {len(translated_segments)} 个片段")
        self._report_progress(90, 100, "并发翻译完成，正在整理结果...")
        return translated_segments

    def _calculate_optimal_batch_size(self, total_segments: int) -> int:
        """
        计算最优批次大小，充分利用并发能力
        
        Args:
            total_segments: 总片段数
            
        Returns:
            最优批次大小
        """
        # 基础批次大小
        base_batch_size = self.batch_size
        
        # 根据片段数量动态调整
        if total_segments <= 10:
            # 小任务：每批2-3个片段，确保有足够的并发
            return min(3, max(1, total_segments // 3))
        elif total_segments <= 30:
            # 中等任务：每批3-5个片段
            return min(5, max(3, total_segments // 8))
        else:
            # 大任务：每批5-8个片段，但确保批次数不少于并发数
            optimal_size = max(base_batch_size, total_segments // (self.max_concurrent_requests * 2))
            return min(8, optimal_size)
    
    def _get_concurrency_info(self, segments_count: int) -> Dict[str, Any]:
        """
        获取并发信息
        
        Args:
            segments_count: 片段数量
            
        Returns:
            并发信息字典
        """
        optimal_batch_size = self._calculate_optimal_batch_size(segments_count)
        batch_count = (segments_count + optimal_batch_size - 1) // optimal_batch_size
        actual_concurrent = min(batch_count, self.max_concurrent_requests)
        
        return {
            'total_segments': segments_count,
            'batch_size': optimal_batch_size,
            'batch_count': batch_count,
            'max_concurrent': self.max_concurrent_requests,
            'actual_concurrent': actual_concurrent,
            'utilization': actual_concurrent / self.max_concurrent_requests
        }
    
    def _translate_batch_thread_safe(self, batch: List[Dict[str, Any]], target_language: str, batch_num: int) -> List[Dict[str, Any]]:
        """
        线程安全的批量翻译
        
        Args:
            batch: 片段批次
            target_language: 目标语言
            batch_num: 批次编号
            
        Returns:
            翻译后的片段列表
        """
        try:
            logger.debug(f"处理并发批次 {batch_num} - {len(batch)} 个片段")
            
            # 添加小延迟避免过快请求
            time.sleep(self.request_delay * (batch_num - 1))
            
            return self._translate_batch(batch, target_language)
            
        except Exception as e:
            logger.error(f"并发批次 {batch_num} 翻译失败: {e}")
            raise  # 直接抛出异常

    def _create_fallback_translations(self, batch: List[Dict[str, Any]], target_language: str) -> List[Dict[str, Any]]:
        """
        创建降级翻译结果（此方法已不再用于降级，保留为向后兼容）
        
        Args:
            batch: 片段批次
            target_language: 目标语言
            
        Returns:
            降级的翻译结果
        """
        logger.error("翻译失败，无法继续执行")
        raise ValueError("翻译失败，系统无法继续处理，请检查API设置和网络连接")
    
    def _separate_cached_segments(self, segments: List[Dict[str, Any]], target_language: str) -> tuple:
        """
        分离有缓存和需要翻译的片段
        
        Args:
            segments: 所有片段
            target_language: 目标语言
            
        Returns:
            (需要翻译的片段, 缓存的翻译结果)
        """
        segments_to_translate = []
        cached_translations = {}
        
        with self.cache_lock:
            for segment in segments:
                cache_key = self._get_cache_key(segment.get('text', ''), target_language)
                if cache_key in self.translation_cache:
                    # 确保缓存数据包含完整的字段
                    cached_data = self.translation_cache[cache_key].copy()
                    # 如果缓存中没有original_text，从segment中获取
                    if 'original_text' not in cached_data:
                        cached_data['original_text'] = segment.get('text', '')
                    cached_translations[segment.get('id')] = cached_data
                else:
                    segments_to_translate.append(segment)
        
        return segments_to_translate, cached_translations
    
    def _merge_cached_results(self, original_segments: List[Dict[str, Any]], cached_translations: Dict) -> List[Dict[str, Any]]:
        """
        合并缓存的翻译结果
        
        Args:
            original_segments: 原始片段
            cached_translations: 缓存的翻译
            
        Returns:
            完整的翻译结果
        """
        result = []
        for segment in original_segments:
            if segment.get('id') in cached_translations:
                translated_segment = segment.copy()
                cached_data = cached_translations[segment.get('id')].copy()
                # 确保缓存数据包含完整的字段
                if 'original_text' not in cached_data:
                    cached_data['original_text'] = segment.get('text', '')
                translated_segment.update(cached_data)
                result.append(translated_segment)
            else:
                # 这种情况不应该出现，如果出现则说明缓存管理出现问题
                logger.error(f"严重错误：声称有缓存但找不到片段ID {segment.get('id', '')} 的翻译")
                raise ValueError(f"缓存管理错误：找不到片段 {segment.get('id', '')} 的翻译缓存")
        
        return result
    
    def _merge_all_results(self, original_segments: List[Dict[str, Any]], 
                          cached_translations: Dict, 
                          new_translations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        合并所有翻译结果
        
        Args:
            original_segments: 原始片段
            cached_translations: 缓存的翻译
            new_translations: 新翻译的结果
            
        Returns:
            完整的翻译结果
        """
        # 创建新翻译的索引
        new_translation_dict = {seg['id']: seg for seg in new_translations}
        
        result = []
        for segment in original_segments:
            if segment.get('id') in cached_translations:
                # 使用缓存
                translated_segment = segment.copy()
                cached_data = cached_translations[segment.get('id')].copy()
                # 确保缓存数据包含完整的字段
                if 'original_text' not in cached_data:
                    cached_data['original_text'] = segment.get('text', '')
                translated_segment.update(cached_data)
                result.append(translated_segment)
            elif segment.get('id') in new_translation_dict:
                # 使用新翻译
                result.append(new_translation_dict[segment.get('id')])
            else:
                # 这种情况不应该出现，如果出现则说明有严重错误
                logger.error(f"严重错误：片段ID {segment.get('id', '')} 既不在缓存中也不在新翻译中")
                raise ValueError(f"翻译过程中出现严重错误：无法找到片段 {segment.get('id', '')} 的翻译结果")
        
        return result
    
    def _translate_batch(self, segments: List[Dict[str, Any]], target_language: str) -> List[Dict[str, Any]]:
        """
        批量翻译片段（线程安全版本）
        
        Args:
            segments: 片段列表
            target_language: 目标语言代码
            
        Returns:
            翻译后的片段列表
        """
        try:
            # 构建翻译请求
            source_texts = []
            for segment in segments:
                duration = segment.get('end', 0.0) - segment.get('start', 0.0)
                source_texts.append({
                    'id': segment.get('id', ''),
                    'text': segment.get('text', ''),
                    'duration': duration,
                    'start': segment.get('start', 0.0),
                    'end': segment.get('end', 0.0)
                })
            
            # 构建提示词
            prompt = self._build_translation_prompt(source_texts, target_language)
            
            # 调用LLM进行翻译 - 使用新版本API
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                top_p=1.0,
                frequency_penalty=0.0,
                presence_penalty=0.0
            )
            
            # 统计token使用情况
            if hasattr(response, 'usage') and response.usage:
                self.token_stats['total_prompt_tokens'] += response.usage.prompt_tokens
                self.token_stats['total_completion_tokens'] += response.usage.completion_tokens
                self.token_stats['total_requests'] += 1
                
                logger.debug(f"Token使用: prompt={response.usage.prompt_tokens}, "
                           f"completion={response.usage.completion_tokens}, "
                           f"total={response.usage.total_tokens}")
            
            # 解析翻译结果
            translation_result = response.choices[0].message.content
            if not translation_result:
                raise ValueError("翻译API返回空结果")
            translated_segments = self._parse_translation_result(segments, translation_result)
            
            return translated_segments
            
        except Exception as e:
            logger.error(f"批量翻译失败: {str(e)}")
            # 如果批量翻译失败，尝试单个翻译
            return self._translate_segments_individually(segments, target_language)
    
    def _build_translation_prompt(self, source_texts: List[Dict], target_language: str) -> str:
        """
        构建翻译提示词 - 简化版本，专注于翻译质量
        
        Args:
            source_texts: 源文本列表
            target_language: 目标语言代码
            
        Returns:
            翻译提示词
        """
        language_name = self.language_names.get(target_language, target_language)
        
        # 构建适合短视频口播的prompt，专注于日常化表达
        prompt = f"""你是一个短视频配音翻译师，将以下中文文本翻译为{language_name}：

**翻译要求：**
1. 使用日常口语化的表达，就像朋友间聊天一样自然
2. 避免书面语和学术词汇，多用简单直白的词汇
3. 语调轻松活泼，适合短视频观众的接受习惯
4. 保持内容的准确性，但表达方式要接地气

**语言风格：**
- 就像本地人在跟朋友介绍有趣事物
- 用词简单易懂，避免复杂术语
- 语气自然亲切，有感染力
- 符合短视频平台的表达习惯

**返回格式：**
{{
  "1": "翻译文本1",
  "2": "翻译文本2"
}}

**待翻译内容：**
"""
        
        for i, text_info in enumerate(source_texts, 1):
            prompt += f"{i}. {text_info['text']}\n"
        
        prompt += f"""
**翻译要点：**
- 准确传达原文含义，但用最简单的话说出来
- 就像{language_name}当地人在日常对话中会用的表达
- 让观众一听就懂，不需要思考
- 语气要有趣生动，能抓住注意力
"""
        
        return prompt
    
    def _parse_translation_result(self, original_segments: List[Dict], translation_result: str) -> List[Dict]:
        """
        解析翻译结果
        
        Args:
            original_segments: 原始片段列表
            translation_result: LLM翻译结果
            
        Returns:
            解析后的翻译片段列表
        """
        try:
            # 尝试解析简洁的JSON格式
            json_match = re.search(r'\{[^}]*\}', translation_result, re.DOTALL)
            if json_match:
                translations_dict = json.loads(json_match.group(0))
                
                # 构建翻译后的片段
                translated_segments = []
                for i, segment in enumerate(original_segments):
                    index_key = str(i + 1)
                    translated_text = translations_dict.get(index_key, segment.get('text', ''))
                    
                    translated_segment = {
                        'id': segment.get('id', ''),
                        'start': segment.get('start', 0.0),
                        'end': segment.get('end', 0.0),
                        'original_text': segment.get('text', ''),
                        'translated_text': translated_text,
                        'confidence': segment.get('confidence', 0),
                        'duration': segment.get('end', 0.0) - segment.get('start', 0.0)
                    }
                    
                    translated_segments.append(translated_segment)
                
                return translated_segments
            else:
                # 如果解析失败，使用原始片段
                logger.warning("无法解析翻译结果，使用原文")
                return original_segments
            
        except Exception as e:
            logger.error(f"解析翻译结果失败: {str(e)}")
            # 如果解析失败，返回原始片段
            return original_segments
    
    def _simple_parse_translation(self, translation_result: str) -> List[Dict]:
        """
        简单解析翻译结果
        
        Args:
            translation_result: 翻译结果字符串
            
        Returns:
            解析后的翻译列表
        """
        translations = []
        lines = translation_result.strip().split('\n')
        
        current_translation = {}
        for line in lines:
            line = line.strip()
            if line.startswith('ID:'):
                if current_translation:
                    translations.append(current_translation)
                current_translation = {'id': line.split(':', 1)[1].strip()}
            elif line.startswith('翻译:') or line.startswith('Translation:'):
                current_translation['translated_text'] = line.split(':', 1)[1].strip()
        
        if current_translation:
            translations.append(current_translation)
        
        return translations
    
    def _translate_segments_individually(self, segments: List[Dict], target_language: str) -> List[Dict]:
        """
        单独翻译每个片段（备选方案）
        
        Args:
            segments: 片段列表
            target_language: 目标语言代码
            
        Returns:
            翻译后的片段列表
        """
        translated_segments = []
        
        for segment in segments:
            try:
                translated_text = self._translate_single_text(
                    segment.get('text', ''), 
                    target_language, 
                    segment.get('end', 0.0) - segment.get('start', 0.0)
                )
                
                translated_segment = {
                    'id': segment.get('id', ''),
                    'start': segment.get('start', 0.0),
                    'end': segment.get('end', 0.0),
                    'original_text': segment.get('text', ''),
                    'translated_text': translated_text,
                    'confidence': segment.get('confidence', 0),
                    'duration': segment.get('end', 0.0) - segment.get('start', 0.0)
                }
                
                translated_segments.append(translated_segment)
                
            except Exception as e:
                logger.error(f"翻译片段 {segment.get('id', 'unknown')} 失败: {str(e)}")
                # 使用原文作为备选
                translated_segment = segment.copy()
                translated_segment['translated_text'] = segment.get('text', '')
                translated_segments.append(translated_segment)
        
        return translated_segments
    
    def _translate_single_text(self, text: str, target_language: str, duration: float) -> str:
        """
        翻译单个文本
        
        Args:
            text: 待翻译文本
            target_language: 目标语言代码
            duration: 时长约束
            
        Returns:
            翻译后的文本
        """
        language_name = self.language_names.get(target_language, target_language)
        
        prompt = f"""请将以下中文文本翻译成{language_name}，要求：
1. 用最日常、最口语化的表达方式
2. 就像{language_name}当地人平时聊天时会说的话
3. 考虑时间约束({duration:.2f}秒)，用简洁有力的表达
4. 避免复杂词汇，让观众一听就懂

原文: {text}

请直接返回翻译结果，语气要自然亲切，适合短视频配音。"""
        
        # 使用新版本API
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "你是一个短视频配音翻译师，擅长将内容转化为日常口语化的表达。"},
                {"role": "user", "content": prompt}
            ],
            max_tokens=500,
            temperature=self.temperature
        )
        
        content = response.choices[0].message.content
        return content.strip() if content else ""
    
    def estimate_speech_time(self, text: str, language: str) -> float:
        """
        估算语音时间
        
        Args:
            text: 文本内容
            language: 语言代码
            
        Returns:
            预估的语音时间（秒）
        """
        # 基于不同语言的语速特性估算
        language_factors = {
            'en': 2.5,  # 英语：每秒约2.5个单词
            'es': 2.2,  # 西班牙语：每秒约2.2个单词
            'fr': 2.0,  # 法语：每秒约2.0个单词
            'de': 1.8,  # 德语：每秒约1.8个单词
            'ja': 3.0,  # 日语：每秒约3.0个字符
            'ko': 2.8,  # 韩语：每秒约2.8个字符
            'zh': 3.5   # 中文：每秒约3.5个字符
        }
        
        factor = language_factors.get(language, 2.0)
        
        if language in ['ja', 'ko', 'zh']:
            # 对于字符计数的语言
            char_count = len(text)
            return char_count / factor
        else:
            # 对于单词计数的语言
            word_count = len(text.split())
            return word_count / factor
    
    def _get_cache_key(self, text: str, target_language: str) -> str:
        """
        生成缓存键
        
        Args:
            text: 待翻译文本
            target_language: 目标语言
            
        Returns:
            缓存键
        """
        content = f"{text}_{target_language}"
        return hashlib.md5(content.encode('utf-8')).hexdigest()
    
    def _cache_translation(self, text: str, target_language: str, translated_segment: Dict[str, Any]):
        """
        缓存翻译结果
        
        Args:
            text: 原文
            target_language: 目标语言
            translated_segment: 翻译后的片段
        """
        try:
            # 如果缓存过大，清理旧的条目
            if len(self.translation_cache) >= self.max_cache_size:
                # 简单的LRU清理：删除一半的条目
                keys_to_remove = list(self.translation_cache.keys())[:self.max_cache_size // 2]
                for key in keys_to_remove:
                    del self.translation_cache[key]
                logger.debug(f"清理翻译缓存，删除了 {len(keys_to_remove)} 个条目")
            
            cache_key = self._get_cache_key(text, target_language)
            # 只缓存翻译相关的字段
            cache_data = {
                'translated_text': translated_segment.get('translated_text'),
                'original_text': translated_segment.get('original_text'),
                'confidence': translated_segment.get('confidence', 1.0)
            }
            self.translation_cache[cache_key] = cache_data
            
        except Exception as e:
            logger.error(f"缓存翻译结果失败: {str(e)}")
    
    def _check_cache(self, segments: List[Dict[str, Any]], target_language: str) -> bool:
        """
        检查是否有缓存的翻译结果
        
        Args:
            segments: 片段列表
            target_language: 目标语言
            
        Returns:
            是否有缓存结果
        """
        cached_count = 0
        for segment in segments:
            cache_key = self._get_cache_key(segment.get('text', ''), target_language)
            if cache_key in self.translation_cache:
                cached_count += 1
        
        # 如果超过20%的内容有缓存，就值得使用缓存逻辑
        return cached_count > len(segments) * 0.2
    
    def clear_cache(self):
        """清空翻译缓存"""
        self.translation_cache.clear()
        logger.info("翻译缓存已清空")
    
    def get_cache_info(self) -> Dict[str, Any]:
        """
        获取缓存信息
        
        Returns:
            缓存信息字典
        """
        with self.cache_lock:
            return {
                'cache_size': len(self.translation_cache),
                'max_cache_size': self.max_cache_size,
                'cache_usage': len(self.translation_cache) / self.max_cache_size * 100
            }
    
    def get_token_stats(self) -> Dict[str, Any]:
        """
        获取Token使用统计
        
        Returns:
            Token使用统计信息
        """
        total_tokens = self.token_stats['total_prompt_tokens'] + self.token_stats['total_completion_tokens']
        avg_tokens_per_request = total_tokens / max(1, self.token_stats['total_requests'])
        session_duration = time.time() - self.token_stats['session_start_time']
        
        stats = {
            'total_prompt_tokens': self.token_stats['total_prompt_tokens'],
            'total_completion_tokens': self.token_stats['total_completion_tokens'],
            'total_tokens': total_tokens,
            'total_requests': self.token_stats['total_requests'],
            'cache_hits': self.token_stats['cache_hits'],
            'avg_tokens_per_request': round(avg_tokens_per_request, 2),
            'cache_hit_rate': round(self.token_stats['cache_hits'] / max(1, self.token_stats['total_requests']) * 100, 2),
            'session_duration_minutes': round(session_duration / 60, 2),
            'tokens_per_minute': round(total_tokens / max(1, session_duration / 60), 2),
            'requests_per_minute': round(self.token_stats['total_requests'] / max(1, session_duration / 60), 2)
        }
        
        # 如果使用Kimi API，添加限制比较
        if self.use_kimi:
            stats['kimi_limits'] = {
                'tpm_limit': 128000,
                'rpm_limit': 200,
                'tpm_usage_percent': round((stats['tokens_per_minute'] / 128000) * 100, 1),
                'rpm_usage_percent': round((stats['requests_per_minute'] / 200) * 100, 1),
                'tpm_remaining': 128000 - stats['tokens_per_minute'],
                'rpm_remaining': 200 - stats['requests_per_minute']
            }
            
            # 如果接近限制，记录警告
            if stats['kimi_limits']['tpm_usage_percent'] > 80:
                logger.warning(f"⚠️  TPM使用率过高: {stats['kimi_limits']['tpm_usage_percent']}%")
            if stats['kimi_limits']['rpm_usage_percent'] > 80:
                logger.warning(f"⚠️  RPM使用率过高: {stats['kimi_limits']['rpm_usage_percent']}%")
        
        return stats
    
    def reset_token_stats(self):
        """重置Token使用统计"""
        self.token_stats = {
            'total_prompt_tokens': 0,
            'total_completion_tokens': 0,
            'total_requests': 0,
            'cache_hits': 0,
            'session_start_time': time.time()
        } 

    def get_embedding(self, text: str) -> Optional[List[float]]:
        """
        获取单个文本的 embedding 向量。

        Args:
            text: 输入文本。

        Returns:
            浮点数列表形式的 embedding，失败则返回 None。
        """
        if not text:
            return None
        
        try:
            # 确保 client 已经初始化
            if self.client is None:
                if self.use_kimi:
                    self.client = OpenAI(
                        api_key=self.api_key,
                        base_url=self.base_url
                    )
                else:
                    self.client = OpenAI(api_key=self.api_key)

            response = self.client.embeddings.create(
                input=[text],
                model="text-embedding-3-small" # 推荐使用小模型以提高效率和降低成本
            )
            return response.data[0].embedding
        except Exception as e:
            logger.error(f"获取 embedding 失败: {e}")
            return None

    def get_embeddings(self, texts: List[str]) -> List[Optional[List[float]]]:
        """
        批量获取文本的 embedding 向量。
        """
        if not texts:
            return []
        
        embeddings = []
        for text in texts:
            embedding = self.get_embedding(text)
            embeddings.append(embedding)
        
        return embeddings 