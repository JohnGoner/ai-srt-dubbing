"""
上下文感知翻译引擎
使用Google Translation API进行高质量翻译
支持上下文一致性和批量翻译
"""

from typing import List, Dict, Any, Optional, Tuple
from loguru import logger
import time
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import os
import html

# Google Translation imports
try:
    from google.cloud import translate_v2 as translate_google  # type: ignore
    GOOGLE_AVAILABLE = True
except ImportError:
    GOOGLE_AVAILABLE = False
    logger.warning("Google Cloud Translate客户端未安装，请运行: pip install google-cloud-translate==2.0.1")



from utils.cache_manager import get_cache_manager


class ContextTranslator:
    """上下文感知翻译器 - 使用Google Translation API"""
    
    def __init__(self, config: dict, progress_callback=None):
        """
        初始化翻译器
        
        Args:
            config: 配置字典
            progress_callback: 进度回调函数，格式为 callback(current, total, message)
        """
        self.config = config
        self.translation_config = config.get('translation', {})
        self.progress_callback = progress_callback
        
        # 初始化Google翻译客户端
        self._init_translation_client()
        
        # 上下文窗口大小（用于保持翻译一致性）
        self.context_window_size = self.translation_config.get('context_window_size', 5)
        
        # 批处理大小
        self.batch_size = self.translation_config.get('batch_size', 10)
        
        # 并发控制
        self.max_concurrent_requests = self.translation_config.get('max_concurrent_requests', 5)
        
        # 缓存管理
        self.cache_manager = get_cache_manager()
        
        # 语言映射
        self.language_names = {
            'en': 'English',
            'es': 'Spanish', 
            'fr': 'French',
            'de': 'German',
            'ja': 'Japanese',
            'ko': 'Korean'
        }
        
        # 统计信息
        self.translation_stats = {
            'total_characters': 0,
            'cache_hits': 0,
            'api_calls': 0,
            'session_start_time': time.time()
        }

    def _strip_context_markers(self, text: str) -> str:
        """移除可能被意外拼接到文本中的上下文标记或说明。

        处理以下常见形式：
        - 以方括号包裹的前缀，如：[上下文参考：... ]、[Context reference: ...]
        - 直接的前缀：Context reference: / 上下文参考：/ Context: / Later: / Earlier:
        """
        if not text:
            return text

        cleaned = text.strip()

        # 如果以方括号开头，移除首个成对的方括号包裹段
        if cleaned.startswith('['):
            end_idx = cleaned.find(']')
            # 仅当右括号在合理范围内才认为是前缀
            if end_idx != -1 and end_idx < 200:
                cleaned = cleaned[end_idx + 1:].lstrip()

        # 去除常见的说明性前缀
        prefix_candidates = [
            'Context reference:',
            '上下文参考：',
            'Context:',
            'Later:',
            'Earlier:'
        ]
        for prefix in prefix_candidates:
            if cleaned.startswith(prefix):
                cleaned = cleaned[len(prefix):].lstrip()

        return cleaned
    
    def _init_translation_client(self):
        """初始化Google翻译客户端"""
        if not GOOGLE_AVAILABLE:
            raise RuntimeError("Google Cloud Translate客户端未安装")
        
        # 从环境变量或配置中获取认证信息
        credentials_path = self.config.get('api_keys', {}).get('google_credentials_path')
        if credentials_path:
            os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = credentials_path
        
        try:
            self.client = translate_google.Client()
            logger.info("Google Translation客户端初始化成功")
        except Exception as e:
            logger.error(f"Google Translation客户端初始化失败: {e}")
            raise
    
    def translate_segments_with_context(self, segments: List[Dict], target_language: str) -> List[Dict]:
        """
        使用上下文感知进行批量翻译
        
        Args:
            segments: 待翻译的片段列表
            target_language: 目标语言代码
            
        Returns:
            翻译后的片段列表
        """
        if not segments:
            return []
        
        logger.info(f"开始上下文感知翻译 {len(segments)} 个片段到 {target_language}")
        self._report_progress(0, 100, f"开始翻译到{target_language}...")
        
        # 1. 检查缓存
        processed_segments, segments_to_translate = self._check_cache(segments, target_language)
        cache_hits = len(processed_segments)
        
        if not segments_to_translate:
            logger.info("所有片段都有缓存，直接返回")
            self._report_progress(100, 100, "所有片段已有缓存，翻译完成！")
            return self._sort_segments(processed_segments)
        
        logger.info(f"缓存命中: {cache_hits}/{len(segments)}, 需要翻译: {len(segments_to_translate)}")
        self._report_progress(10, 100, f"缓存命中{cache_hits}个，翻译{len(segments_to_translate)}个新片段...")
        
        # 2. 构建上下文批次
        context_batches = self._build_context_batches(segments_to_translate)
        
        # 3. 并发翻译
        translated_segments = self._translate_batches_with_context(context_batches, target_language)
        
        # 4. 合并结果
        all_segments = processed_segments + translated_segments
        result = self._sort_segments(all_segments)
        
        logger.info(f"翻译完成，总共处理 {len(result)} 个片段")
        self._report_progress(100, 100, "翻译完成！")
        
        return result
    
    def _build_context_batches(self, segments: List[Dict]) -> List[Dict]:
        """
        构建包含上下文的翻译批次
        
        Args:
            segments: 需要翻译的片段列表
            
        Returns:
            包含上下文信息的批次列表
        """
        batches = []
        
        for i in range(0, len(segments), self.batch_size):
            batch_segments = segments[i:i + self.batch_size]
            
            # 为每个批次构建上下文
            context_start = max(0, i - self.context_window_size)
            context_end = min(len(segments), i + self.batch_size + self.context_window_size)
            
            # 提取上下文文本
            context_before = []
            context_after = []
            
            # 前置上下文
            for j in range(context_start, i):
                if j < len(segments):
                    context_before.append(segments[j].get('text', ''))
            
            # 后置上下文  
            for j in range(i + self.batch_size, context_end):
                if j < len(segments):
                    context_after.append(segments[j].get('text', ''))
            
            batch = {
                'segments': batch_segments,
                'context_before': context_before,
                'context_after': context_after,
                'batch_index': len(batches)
            }
            
            batches.append(batch)
        
        logger.info(f"构建了 {len(batches)} 个上下文批次")
        return batches
    
    def _translate_batches_with_context(self, batches: List[Dict], target_language: str) -> List[Dict]:
        """
        并发翻译包含上下文的批次
        
        Args:
            batches: 上下文批次列表
            target_language: 目标语言
            
        Returns:
            翻译后的片段列表
        """
        translated_segments = []
        completed_batches = 0
        
        with ThreadPoolExecutor(max_workers=self.max_concurrent_requests) as executor:
            # 提交所有翻译任务
            future_to_batch = {
                executor.submit(self._translate_single_batch, batch, target_language): batch
                for batch in batches
            }
            
            # 收集结果
            for future in as_completed(future_to_batch):
                try:
                    batch_result = future.result()
                    translated_segments.extend(batch_result)
                    
                    # 缓存结果
                    batch = future_to_batch[future]
                    self._cache_batch_results(batch['segments'], batch_result, target_language)
                    
                    # 更新进度
                    completed_batches += 1
                    progress = 15 + int((completed_batches / len(batches)) * 75)
                    self._report_progress(progress, 100, f"完成翻译批次 {completed_batches}/{len(batches)}...")
                    
                except Exception as e:
                    logger.error(f"批次翻译失败: {str(e)}")
                    raise
        
        return translated_segments
    
    def _translate_single_batch(self, batch: Dict, target_language: str) -> List[Dict]:
        """
        翻译单个上下文批次
        
        Args:
            batch: 包含上下文的批次
            target_language: 目标语言
            
        Returns:
            翻译后的片段列表
        """
        segments = batch['segments']
        context_before = batch.get('context_before', [])
        context_after = batch.get('context_after', [])
        
        # 构建包含上下文的翻译文本
        texts_to_translate = []
        for segment in segments:
            texts_to_translate.append(segment.get('text', ''))
        
        # 构建上下文字符串
        context_text = ""
        if context_before:
            context_text += "前文：" + " ".join(context_before[-3:]) + "\n"  # 只取最近3句
        if context_after:
            context_text += "后文：" + " ".join(context_after[:3])  # 只取后面3句
        
        try:
            translated_texts = self._translate_with_google(texts_to_translate, target_language, context_text)
            
            # 构建结果
            result = []
            for i, segment in enumerate(segments):
                translated_segment = segment.copy()
                translated_segment['translated_text'] = translated_texts[i] if i < len(translated_texts) else segment.get('text', '')
                result.append(translated_segment)
            
            return result
            
        except Exception as e:
            logger.error(f"批次翻译失败: {e}")
            # 返回原文作为备选
            result = []
            for segment in segments:
                translated_segment = segment.copy()
                translated_segment['translated_text'] = segment.get('text', '')
                result.append(translated_segment)
            return result
    
    def _translate_with_google(self, texts: List[str], target_language: str, context: str = "") -> List[str]:
        """使用Google Translation API翻译"""
        try:
            # Google Translate不直接支持context，避免将上下文直接拼接到文本以防泄漏
            enhanced_texts = list(texts)
            
            # 批量翻译，指定格式为text以避免HTML实体编码
            results = self.client.translate(
                enhanced_texts,
                target_language=target_language.lower(),
                format_='text'  # 指定为文本格式，避免HTML实体编码
            )
            
            # 提取翻译结果，移除可能的上下文标记
            translated_texts = []
            for result in results:
                translated_text = result['translatedText']
                
                # 解码HTML实体（双重保险，虽然已经指定了format_='text'）
                translated_text = html.unescape(translated_text)
                
                # 强化的上下文前缀清理
                translated_text = self._strip_context_markers(translated_text)
                translated_texts.append(translated_text)
            
            self.translation_stats['api_calls'] += 1
            self.translation_stats['total_characters'] += sum(len(text) for text in texts)
            
            return translated_texts
            
        except Exception as e:
            logger.error(f"Google Translation API调用失败: {e}")
            raise
    

    
    def _check_cache(self, segments: List[Dict], target_language: str) -> Tuple[List[Dict], List[Dict]]:
        """检查缓存并分离已缓存和需要翻译的片段"""
        cached_segments = []
        segments_to_translate = []
        
        for segment in segments:
            text = segment.get('text', '')
            cache_key = self._get_cache_key(text, target_language)
            
            cached_result = self.cache_manager.get(cache_key)
            if cached_result:
                segment_copy = segment.copy()
                segment_copy['translated_text'] = cached_result
                cached_segments.append(segment_copy)
                self.translation_stats['cache_hits'] += 1
            else:
                segments_to_translate.append(segment)
        
        return cached_segments, segments_to_translate
    
    def _cache_batch_results(self, original_segments: List[Dict], translated_segments: List[Dict], target_language: str):
        """缓存批次翻译结果"""
        for original, translated in zip(original_segments, translated_segments):
            text = original.get('text', '')
            translated_text = translated.get('translated_text', '')
            
            if text and translated_text:
                cache_key = self._get_cache_key(text, target_language)
                self.cache_manager.set(
                    key=cache_key,
                    data=translated_text,
                    cache_type='context_translation',
                    target_language=target_language
                )
    
    def _get_cache_key(self, text: str, target_language: str) -> str:
        """生成缓存键"""
        content = f"{text}_{target_language}_google"
        return hashlib.md5(content.encode('utf-8')).hexdigest()
    
    def _sort_segments(self, segments: List[Dict]) -> List[Dict]:
        """按ID排序片段"""
        return sorted(segments, key=lambda x: x.get('id', ''))
    
    def _report_progress(self, current: int, total: int, message: str):
        """报告进度"""
        if self.progress_callback:
            try:
                self.progress_callback(current, total, message)
            except Exception as e:
                logger.warning(f"翻译进度回调失败: {str(e)}")
    
    def get_translation_stats(self) -> Dict[str, Any]:
        """获取翻译统计信息"""
        session_duration = time.time() - self.translation_stats['session_start_time']
        
        return {
            'service': 'google',
            'total_characters': self.translation_stats['total_characters'],
            'cache_hits': self.translation_stats['cache_hits'],
            'api_calls': self.translation_stats['api_calls'],
            'cache_hit_rate': round(
                self.translation_stats['cache_hits'] / 
                max(1, self.translation_stats['cache_hits'] + self.translation_stats['api_calls']) * 100, 2
            ),
            'session_duration_minutes': round(session_duration / 60, 2),
            'characters_per_minute': round(
                self.translation_stats['total_characters'] / max(1, session_duration / 60), 2
            )
        }
    
    def translate_segments(self, texts: List[str], target_language: str, progress_callback=None) -> List[str]:
        """
        兼容性方法：翻译文本列表（不使用上下文）
        
        Args:
            texts: 待翻译的文本列表
            target_language: 目标语言代码
            progress_callback: 进度回调函数
            
        Returns:
            翻译后的文本列表
        """
        # 转换为段落格式
        segments = []
        for i, text in enumerate(texts):
            segments.append({
                'id': f'temp_{i}',
                'text': text,
                'start': 0,
                'end': 1,
                'duration': 1
            })
        
        # 使用上下文翻译方法
        translated_segments = self.translate_segments_with_context(segments, target_language)
        
        # 提取翻译文本
        return [seg.get('translated_text', '') for seg in translated_segments]
    
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