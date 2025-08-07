"""
时间同步管理模块 - 精确模式
专注于LLM文本精简 + Azure API微调语速实现精确时间同步
"""

from typing import List, Dict, Any, Optional, Tuple
from loguru import logger
import time
import numpy as np


class PreciseSyncManager:
    """精确时间同步管理器 - 专注于时间同步算法"""
    
    def __init__(self, config: dict, progress_callback=None):
        """
        初始化精确时间同步管理器
        
        Args:
            config: 配置字典
            progress_callback: 进度回调函数，格式为 callback(current, total, message)
        """
        self.config = config
        self.timing_config = config.get('timing', {})
        
        # 进度回调
        self.progress_callback = progress_callback
        
        # 精确模式参数
        self.min_speed_ratio = 0.95  # 最小语速
        self.max_speed_ratio = 1.15  # 最大语速
        self.speed_step = 0.01       # 语速调整步长
        
        # 时间同步参数
        self.sync_tolerance = 0.05   # 5%容忍度
        self.max_iterations = 3      # 最大迭代次数
        self.max_api_calls_per_segment = 6  # 每片段最大API调用次数
        
        logger.info("精确时间同步管理器初始化完成")
    
    def _report_progress(self, current: int, total: int, message: str):
        """报告进度"""
        if self.progress_callback:
            self.progress_callback(current, total, message)
        logger.info(f"进度: {current}/{total} - {message}")
    
    def first_round_optimization(self, segments: List[Dict], translator, tts, target_language: str) -> List[Dict]:
        """
        第一轮优化：LLM文本优化 + 语速调整 + TTS生成
        
        Args:
            segments: 字幕片段列表
            translator: 翻译器实例
            tts: TTS实例
            target_language: 目标语言
            
        Returns:
            第一轮优化后的片段列表，每个片段包含：
            - 原始数据
            - optimized_text: 优化后的文本
            - speech_rate: 优化后的语速
            - target_duration: 目标时长
            - estimated_duration: TTS预估时长
            - actual_duration: 实际音频时长（需要TTS生成后填充）
            - audio_file: 音频文件路径
            - quality: 质量评级
        """
        logger.info(f"开始第一轮优化，共 {len(segments)} 个片段")
        
        optimized_segments = []
        total_segments = len(segments)
        
        for i, segment in enumerate(segments):
            self._report_progress(i + 1, total_segments, f"第一轮优化片段 {segment.get('id', i+1)}")
            
            try:
                optimized_segment = self._first_round_optimize_single_segment(
                    segment, translator, tts, target_language
                )
                optimized_segments.append(optimized_segment)
                
            except Exception as e:
                logger.error(f"片段 {segment.get('id', i+1)} 第一轮优化失败: {e}")
                # 使用原始片段作为降级方案
                text_content = segment.get('translated_text') or segment.get('text') or segment.get('original_text', '')
                duration = segment.get('duration', 0.0)
                segment.update({
                    'optimized_text': text_content,
                    'speech_rate': 1.0,
                    'target_duration': duration,
                    'estimated_duration': duration,
                    'actual_duration': duration,
                    'audio_file': None,
                    'quality': 'error'
                })
                optimized_segments.append(segment)
        
        logger.info("第一轮优化完成")
        return optimized_segments

    def concurrent_full_optimization(self, segments: List[Dict], translator, tts, target_language: str) -> List[Dict]:
        """
        分阶段并发优化：避免Streamlit上下文问题
        
        Args:
            segments: 字幕片段列表
            translator: 翻译器实例
            tts: TTS实例
            target_language: 目标语言
            
        Returns:
            完整分析后的片段列表
        """
        logger.info(f"开始分阶段并发优化，共 {len(segments)} 个片段")
        
        # 阶段1: 并发文本优化（不涉及Streamlit上下文）
        self._report_progress(10, 100, "开始并发文本优化...")
        optimized_segments = self._concurrent_text_optimization(segments, translator, tts, target_language)
        
        # 阶段2: 并发音频生成（提高效率）
        self._report_progress(40, 100, "开始并发音频生成...")
        audio_segments = self._concurrent_audio_generation(optimized_segments, tts, target_language)
        
        # 阶段3: 并发时长分析（不涉及Streamlit上下文）
        self._report_progress(80, 100, "开始并发时长分析...")
        analyzed_segments = self._concurrent_timing_analysis(audio_segments)
        
        self._report_progress(100, 100, "优化完成！")
        logger.info("分阶段并发优化完成")
        return analyzed_segments
    
    def _concurrent_text_optimization(self, segments: List[Dict], translator, tts, target_language: str) -> List[Dict]:
        """并发文本优化（安全，不涉及Streamlit上下文）"""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import threading
        
        max_workers = min(10, len(segments))
        results = []
        completed_count = 0
        results_lock = threading.Lock()
        
        def optimize_text_only(segment: Dict, index: int) -> Dict:
            """只进行文本优化，不生成音频"""
            try:
                return self._first_round_optimize_single_segment(
                    segment, translator, tts, target_language
                )
            except Exception as e:
                logger.error(f"文本优化失败 seg_{index}: {e}")
                error_segment = segment.copy()
                error_segment.update({
                    'optimized_text': segment.get('translated_text', ''),
                    'speech_rate': 1.0,
                    'quality': 'error'
                })
                return error_segment
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_index = {
                executor.submit(optimize_text_only, segment, i): i
                for i, segment in enumerate(segments)
            }
            
            indexed_results = {}
            for future in as_completed(future_to_index):
                index = future_to_index[future]
                try:
                    result = future.result()
                    indexed_results[index] = result
                    
                    with results_lock:
                        completed_count += 1
                        self._report_progress(10 + (completed_count * 30 // len(segments)), 100,
                                            f"文本优化: {completed_count}/{len(segments)}")
                except Exception as e:
                    logger.error(f"文本优化异常 {index}: {e}")
                    indexed_results[index] = segments[index]
            
            results = [indexed_results[i] for i in range(len(segments))]
        
        return results
    
    def _concurrent_audio_generation(self, segments: List[Dict], tts, target_language: str) -> List[Dict]:
        """并发音频生成 - 提高效率同时控制API调用频率"""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import threading
        
        # 根据API限制和片段数量确定合适的并发数
        # Azure TTS每分钟150次请求，考虑安全裕度使用较小的并发数
        max_workers = min(8, len(segments), max(2, len(segments) // 5))
        
        audio_segments = []
        completed_count = 0
        results_lock = threading.Lock()
        
        logger.info(f"启动并发音频生成: {len(segments)}个片段, {max_workers}个并发worker")
        
        def generate_audio_worker(segment: Dict, index: int) -> Tuple[int, Dict]:
            """音频生成工作函数"""
            try:
                audio_segment = self._generate_single_audio(segment, tts, target_language)
                return index, audio_segment
            except Exception as e:
                logger.error(f"并发音频生成失败 seg_{index}: {e}")
                # 创建错误音频片段
                error_segment = segment.copy()
                error_segment.update({
                    'actual_duration': segment.get('estimated_duration', 0.0),
                    'audio_file': None,
                    'audio_data': None,
                    'quality': 'error',
                    'error_message': str(e)
                })
                return index, error_segment
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 提交所有任务
            future_to_index = {
                executor.submit(generate_audio_worker, segment, i): i
                for i, segment in enumerate(segments)
            }
            
            # 收集结果（保持原始顺序）
            indexed_results = {}
            for future in as_completed(future_to_index):
                index = future_to_index[future]
                try:
                    result_index, audio_segment = future.result()
                    indexed_results[result_index] = audio_segment
                    
                    # 线程安全的进度更新
                    with results_lock:
                        completed_count += 1
                        progress = 40 + (completed_count * 40 // len(segments))
                        self._report_progress(progress, 100, 
                                            f"音频生成: {completed_count}/{len(segments)} (并发)")
                        
                except Exception as e:
                    logger.error(f"获取并发结果异常 {index}: {e}")
                    # 创建默认错误片段
                    error_segment = segments[index].copy()
                    error_segment.update({
                        'actual_duration': segments[index].get('estimated_duration', 0.0),
                        'audio_file': None,
                        'audio_data': None,
                        'quality': 'error',
                        'error_message': str(e)
                    })
                    indexed_results[index] = error_segment
            
            # 按原始顺序重新组织结果
            audio_segments = [indexed_results[i] for i in range(len(segments))]
        
        # 统计并发生成结果
        success_count = sum(1 for seg in audio_segments if seg.get('quality') != 'error')
        error_count = len(audio_segments) - success_count
        
        logger.info(f"并发音频生成完成: 成功{success_count}个, 失败{error_count}个")
        
        return audio_segments
    
    def _concurrent_timing_analysis(self, segments: List[Dict]) -> List[Dict]:
        """并发时长分析（不涉及Streamlit上下文）"""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import threading
        
        max_workers = min(4, len(segments))
        completed_count = 0
        results_lock = threading.Lock()
        
        def analyze_timing_only(segment: Dict, index: int) -> Dict:
            """只进行时长分析"""
            try:
                return self._analyze_single_segment_timing(segment)
            except Exception as e:
                logger.error(f"时长分析失败 seg_{index}: {e}")
                error_segment = segment.copy()
                error_segment.update({
                    'timing_analysis': {'error': str(e)},
                    'adjustment_suggestions': [],
                    'needs_user_confirmation': False
                })
                return error_segment
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_index = {
                executor.submit(analyze_timing_only, segment, i): i
                for i, segment in enumerate(segments)
            }
            
            indexed_results = {}
            for future in as_completed(future_to_index):
                index = future_to_index[future]
                try:
                    result = future.result()
                    indexed_results[index] = result
                    
                    with results_lock:
                        completed_count += 1
                        self._report_progress(80 + (completed_count * 20 // len(segments)), 100,
                                            f"时长分析: {completed_count}/{len(segments)}")
                except Exception as e:
                    logger.error(f"时长分析异常 {index}: {e}")
                    indexed_results[index] = segments[index]
            
            results = [indexed_results[i] for i in range(len(segments))]
        
        return results
    
    def _first_round_optimize_single_segment(self, segment: Dict, translator, tts, target_language: str) -> Dict:
        """
        第一轮优化单个片段：专注于LLM文本优化，语速保持默认1.0
        
        Args:
            segment: 字幕片段
            translator: 翻译器实例
            tts: TTS实例
            target_language: 目标语言
            
        Returns:
            第一轮优化后的片段
        """
        # 获取文本内容，支持多种字段名
        text = segment.get('translated_text') or segment.get('text') or segment.get('original_text', '')
        target_duration = segment.get('duration', 0.0)
        
        if target_duration <= 0:
            logger.warning(f"片段 {segment.get('id', 'unknown')}: 无效的目标时长 {target_duration}")
            return segment
        
        # 重点：只进行LLM文本优化，进行3轮迭代
        optimized_text = self._optimize_text_iteratively(text, target_duration, translator, tts, target_language)
        
        # 语速固定为1.0，不进行语速优化
        optimal_rate = 1.0
        
        # 预估时长
        estimated_duration = tts.estimate_audio_duration_optimized(optimized_text, target_language, optimal_rate)
        
        # 构建结果
        result = segment.copy()
        result.update({
            'optimized_text': optimized_text,
            'speech_rate': optimal_rate,
            'target_duration': target_duration,
            'estimated_duration': estimated_duration,
            'actual_duration': None,  # 将在TTS生成后填充
            'audio_file': None,       # 将在TTS生成后填充
            'quality': 'pending'      # 将在TTS生成后评估
        })
        
        logger.debug(f"片段 {segment.get('id', 'unknown')} 第一轮优化完成: "
                    f"语速={optimal_rate:.3f}, 预估时长={estimated_duration:.2f}s")
        
        return result
    
    def _optimize_text_iteratively(self, text: str, target_duration: float, translator, tts, target_language: str, max_iterations: int = 3) -> str:
        """
        使用LLM进行多轮迭代文本优化，专注于词数调整
        
        Args:
            text: 原始文本
            target_duration: 目标时长
            translator: 翻译器实例
            tts: TTS实例
            target_language: 目标语言
            max_iterations: 最大迭代次数
            
        Returns:
            优化后的文本
        """
        # 估算目标词数
        current_duration = tts.estimate_audio_duration_optimized(text, target_language, 1.0)
        current_words = len(text.split())
        
        # 计算目标词数
        target_words = int(current_words * (target_duration / current_duration)) if current_duration > 0 else current_words
        
        # 如果目标词数与当前词数相差不大，直接返回
        if abs(target_words - current_words) <= 2:
            return text
        
        best_text = text
        best_score = float('inf')
        
        logger.debug(f"开始文本优化迭代: 当前{current_words}词 -> 目标{target_words}词")
        
        for iteration in range(max_iterations):
            try:
                # 生成优化提示
                if target_words < current_words:
                    # 需要精简
                    reduction_ratio = target_words / current_words
                    prompt = f"""请将以下文本精简，目标是减少到约 {target_words} 个词，使其朗读时长接近 {target_duration:.1f} 秒。

要求:
1. 保留核心意义和关键信息
2. 删除冗余词汇、修饰语和次要细节  
3. 使用最直接、简洁的表达
4. 保持原文的语气和风格

原文 ({current_words}个词): "{text}"

请直接返回精简后的文本，不要包含引号或其他说明。"""
                else:
                    # 需要扩展
                    expansion_ratio = target_words / current_words
                    prompt = f"""请适当扩展以下文本，目标是增加到约 {target_words} 个词，使其朗读时长接近 {target_duration:.1f} 秒。

要求:
1. 忠于原文的核心意义和语气
2. 适当增加细节、解释或使用更丰富的表达方式
3. 避免无意义的填充词
4. 保持自然的语言流畅性

原文 ({current_words}个词): "{text}"

请直接返回扩展后的文本，不要包含引号或其他说明。"""
                
                # 调用LLM优化
                optimized_text = translator._translate_single_text(prompt, target_language, 0.0)
                optimized_text = optimized_text.strip().replace('"', '')
                
                # 评估优化效果
                optimized_words = len(optimized_text.split())
                optimized_duration = tts.estimate_audio_duration_optimized(optimized_text, target_language, 1.0)
                
                # 计算评分（词数误差 + 时长误差）
                word_error = abs(optimized_words - target_words)
                duration_error = abs(optimized_duration - target_duration)
                score = word_error * 0.5 + duration_error * 2.0  # 时长误差权重更高
                
                logger.debug(f"迭代 {iteration + 1}: {optimized_words}词, {optimized_duration:.2f}s, 评分={score:.2f}")
                
                # 更新最佳结果
                if score < best_score:
                    best_text = optimized_text
                    best_score = score
                
                # 更新当前文本用于下一轮迭代
                text = optimized_text
                current_words = optimized_words
                
            except Exception as e:
                logger.error(f"文本优化迭代 {iteration + 1} 失败: {e}")
                break
        
        logger.debug(f"文本优化完成，最佳评分: {best_score:.2f}")
        return best_text
    
    def _validate_text_optimization(self, original_text: str, optimized_text: str, target_duration: float, tts, target_language: str) -> bool:
        """
        验证文本优化效果
        
        Args:
            original_text: 原始文本
            optimized_text: 优化后的文本
            target_duration: 目标时长
            tts: TTS实例
            target_language: 目标语言
            
        Returns:
            优化是否有效
        """
        # 检查文本长度变化
        original_words = len(original_text.split())
        optimized_words = len(optimized_text.split())
        
        if original_words == 0:
            return False
        
        word_change_ratio = abs(optimized_words - original_words) / original_words
        
        # 如果词数变化超过80%，可能过度优化
        if word_change_ratio > 0.8:
            return False
        
        # 检查优化后的时长是否更接近目标
        original_duration = tts.estimate_audio_duration_optimized(original_text, target_language, 1.0)
        optimized_duration = tts.estimate_audio_duration_optimized(optimized_text, target_language, 1.0)
        
        original_error = abs(original_duration - target_duration)
        optimized_error = abs(optimized_duration - target_duration)
        
        # 优化后的误差应该更小
        return optimized_error < original_error
    
    def generate_first_round_audio(self, segments: List[Dict], tts, target_language: str) -> List[Dict]:
        """
        为第一轮优化后的片段生成音频
        
        Args:
            segments: 第一轮优化后的片段列表
            tts: TTS实例
            target_language: 目标语言
            
        Returns:
            包含音频文件的片段列表
        """
        logger.info(f"开始生成第一轮音频，共 {len(segments)} 个片段")
        
        audio_segments = []
        total_segments = len(segments)
        
        for i, segment in enumerate(segments):
            self._report_progress(i + 1, total_segments, f"生成音频片段 {segment.get('id', i+1)}")
            
            try:
                audio_segment = self._generate_single_audio(segment, tts, target_language)
                audio_segments.append(audio_segment)
                
            except Exception as e:
                logger.error(f"片段 {segment.get('id', i+1)} 音频生成失败: {e}")
                # 使用原始片段作为降级方案
                segment.update({
                    'actual_duration': segment.get('estimated_duration', 0.0),
                    'audio_file': None,
                    'quality': 'error'
                })
                audio_segments.append(segment)
        
        logger.info("第一轮音频生成完成")
        return audio_segments
    
    def _generate_single_audio(self, segment: Dict, tts, target_language: str) -> Dict:
        """
        为单个片段生成音频
        
        Args:
            segment: 片段
            tts: TTS实例
            target_language: 目标语言
            
        Returns:
            包含音频文件和音频数据的片段
        """
        text = segment.get('optimized_text', '')
        speech_rate = segment.get('speech_rate', 1.0)
        segment_id = segment.get('id', 'unknown')
        
        # 生成音频文件
        audio_file = tts.synthesize_speech_optimized(text, target_language, speech_rate, f"segment_{segment_id}")
        
        # 加载音频数据
        audio_data = None
        try:
            from pydub import AudioSegment
            audio_data = AudioSegment.from_file(audio_file)
            logger.debug(f"片段 {segment_id} 音频数据加载成功")
        except Exception as e:
            logger.warning(f"片段 {segment_id} 音频数据加载失败: {e}")
        
        # 获取实际音频时长
        actual_duration = tts.get_audio_duration(audio_file)
        
        # 计算时长误差
        target_duration = segment.get('target_duration', 0.0)
        timing_error_ms = abs(actual_duration - target_duration) * 1000
        
        # 评估质量
        quality = self._evaluate_quality(timing_error_ms, target_duration, speech_rate)
        
        result = segment.copy()
        result.update({
            'actual_duration': actual_duration,
            'audio_file': audio_file,
            'audio_data': audio_data,  # 添加音频数据
            'timing_error_ms': timing_error_ms,
            'quality': quality
        })
        
        logger.debug(f"片段 {segment_id} 音频生成完成: "
                    f"实际时长={actual_duration:.2f}s, 目标时长={target_duration:.2f}s, 误差={timing_error_ms:.0f}ms, 质量={quality}")
        
        return result
    
    def analyze_timing_issues(self, segments: List[Dict]) -> List[Dict]:
        """
        分析第一轮音频的时长问题，生成调整建议
        
        Args:
            segments: 包含实际音频时长的片段列表
            
        Returns:
            包含分析结果的片段列表，每个片段增加：
            - timing_analysis: 时长分析
            - adjustment_suggestions: 调整建议
            - needs_user_confirmation: 是否需要用户确认
        """
        logger.info(f"开始分析时长问题，共 {len(segments)} 个片段")
        
        analyzed_segments = []
        total_segments = len(segments)
        
        for i, segment in enumerate(segments):
            self._report_progress(i + 1, total_segments, f"分析片段 {segment.get('id', i+1)}")
            
            try:
                analyzed_segment = self._analyze_single_segment_timing(segment)
                analyzed_segments.append(analyzed_segment)
                
            except Exception as e:
                logger.error(f"片段 {segment.get('id', i+1)} 分析失败: {e}")
                segment.update({
                    'timing_analysis': {'error': str(e)},
                    'adjustment_suggestions': [],
                    'needs_user_confirmation': False
                })
                analyzed_segments.append(segment)
        
        logger.info("时长问题分析完成")
        return analyzed_segments
    
    def _analyze_single_segment_timing(self, segment: Dict) -> Dict:
        """
        分析单个片段的时长问题
        
        Args:
            segment: 片段
            
        Returns:
            包含分析结果的片段
        """
        target_duration = segment.get('target_duration', 0.0)
        actual_duration = segment.get('actual_duration', 0.0)
        estimated_duration = segment.get('estimated_duration', 0.0)
        current_text = segment.get('optimized_text', '')
        current_rate = segment.get('speech_rate', 1.0)
        
        if target_duration <= 0 or actual_duration <= 0:
            return segment
        
        # 计算各种比例和误差
        actual_ratio = actual_duration / target_duration
        estimated_ratio = estimated_duration / target_duration if target_duration > 0 else 1.0
        timing_error_ms = abs(actual_duration - target_duration) * 1000
        error_percentage = (timing_error_ms / (target_duration * 1000)) * 100
        
        # 时长分析
        timing_analysis = {
            'target_duration': target_duration,
            'actual_duration': actual_duration,
            'estimated_duration': estimated_duration,
            'actual_ratio': actual_ratio,
            'estimated_ratio': estimated_ratio,
            'timing_error_ms': timing_error_ms,
            'error_percentage': error_percentage,
            'current_words': len(current_text.split()),
            'current_speech_rate': current_rate
        }
        
        # 生成调整建议
        adjustment_suggestions = self._generate_precise_adjustment_suggestions(
            current_text, target_duration, actual_duration, current_rate, timing_analysis
        )
        
        # 判断是否需要用户确认
        needs_user_confirmation = self._needs_user_confirmation_after_audio(timing_error_ms, error_percentage)
        
        result = segment.copy()
        result.update({
            'timing_analysis': timing_analysis,
            'adjustment_suggestions': adjustment_suggestions,
            'needs_user_confirmation': needs_user_confirmation
        })
        
        logger.debug(f"片段 {segment.get('id', 'unknown')} 分析完成: "
                    f"实际比例={actual_ratio:.2f}, 误差={timing_error_ms:.0f}ms, 需要确认={needs_user_confirmation}")
        
        return result
    
    def _generate_precise_adjustment_suggestions(self, text: str, target_duration: float, actual_duration: float, current_rate: float, timing_analysis: Dict) -> List[Dict]:
        """
        基于实际音频时长生成精确的调整建议
        
        Args:
            text: 当前文本
            target_duration: 目标时长
            actual_duration: 实际时长
            current_rate: 当前语速
            timing_analysis: 时长分析数据
            
        Returns:
            调整建议列表
        """
        suggestions = []
        current_words = len(text.split())
        actual_ratio = timing_analysis['actual_ratio']
        error_percentage = timing_analysis['error_percentage']
        
        # 方案1：调整语速（推荐）
        if 0.7 <= actual_ratio <= 1.3:
            # 在合理范围内，优先调整语速
            target_rate = target_duration / actual_duration
            target_rate = max(self.min_speed_ratio, min(self.max_speed_ratio, target_rate))
            
            suggestions.append({
                'type': 'adjust_speed',
                'description': f'调整语速从 {current_rate:.2f} 到 {target_rate:.2f}',
                'current_speed': current_rate,
                'suggested_speed': target_rate,
                'priority': 'high',
                'estimated_improvement': f'预计误差从 {error_percentage:.1f}% 降低到 <5%'
            })
        
        # 方案2：文本调整（当语速调整不够时）
        if actual_ratio < 0.7 or actual_ratio > 1.3:
            if actual_ratio < 0.7:
                # 文本过短，需要扩展
                target_words = int(current_words * (target_duration / actual_duration))
                word_increase = target_words - current_words
                
                suggestions.append({
                    'type': 'expand_text',
                    'description': f'扩展文本，增加约 {word_increase} 个单词',
                    'current_words': current_words,
                    'target_words': target_words,
                    'priority': 'high',
                    'estimated_improvement': f'预计时长从 {actual_duration:.1f}s 增加到 {target_duration:.1f}s'
                })
                
            else:
                # 文本过长，需要精简
                target_words = int(current_words * (target_duration / actual_duration))
                word_decrease = current_words - target_words
                
                suggestions.append({
                    'type': 'condense_text',
                    'description': f'精简文本，减少约 {word_decrease} 个单词',
                    'current_words': current_words,
                    'target_words': target_words,
                    'priority': 'high',
                    'estimated_improvement': f'预计时长从 {actual_duration:.1f}s 减少到 {target_duration:.1f}s'
                })
        
        # 方案3：保持现状（当误差可接受时）
        if error_percentage < 10:
            suggestions.append({
                'type': 'keep_current',
                'description': f'保持现状，当前误差 {error_percentage:.1f}% 在可接受范围内',
                'priority': 'low',
                'reason': '误差较小，无需调整'
            })
        
        return suggestions
    
    def _needs_user_confirmation_after_audio(self, timing_error_ms: float, error_percentage: float) -> bool:
        """
        基于实际音频时长判断是否需要用户确认
        
        Args:
            timing_error_ms: 时长误差（毫秒）
            error_percentage: 误差百分比
            
        Returns:
            是否需要用户确认
        """
        # 阈值驱动的用户确认逻辑
        if error_percentage > 15:  # 误差超过15%
            return True
        elif timing_error_ms > 2000:  # 误差超过2秒
            return True
        elif error_percentage > 10 and timing_error_ms > 1000:  # 误差超过10%且超过1秒
            return True
        
        return False
    
    def apply_user_adjustments(self, segments: List[Dict], adjustment_choices: Dict[int, Dict], translator, tts, target_language: str) -> List[Dict]:
        """
        应用用户选择的调整方案，生成第二轮音频
        
        Args:
            segments: 分析后的片段列表
            adjustment_choices: 用户调整选择 {segment_id: adjustment_choice}
            translator: 翻译器实例
            tts: TTS实例
            target_language: 目标语言
            
        Returns:
            第二轮优化后的片段列表
        """
        logger.info("开始应用用户调整方案，生成第二轮音频")
        
        final_segments = []
        total_segments = len(segments)
        
        for i, segment in enumerate(segments):
            self._report_progress(i + 1, total_segments, f"应用调整片段 {segment.get('id', i+1)}")
            
            segment_id = segment.get('id')
            adjustment_choice = adjustment_choices.get(segment_id) if segment_id is not None else None
            
            try:
                if adjustment_choice:
                    # 应用用户选择的调整
                    final_segment = self._apply_single_user_adjustment(
                        segment, adjustment_choice, translator, tts, target_language
                    )
                else:
                    # 用户选择不调整，保持第一轮结果
                    final_segment = segment.copy()
                    final_segment.update({
                        'final_text': segment.get('optimized_text'),
                        'final_speech_rate': segment.get('speech_rate'),
                        'applied_adjustment': 'none',
                        'final_audio_file': segment.get('audio_file')
                    })
                
                final_segments.append(final_segment)
                
            except Exception as e:
                logger.error(f"片段 {segment_id} 调整应用失败: {e}")
                # 使用第一轮结果作为降级方案
                segment.update({
                    'final_text': segment.get('optimized_text'),
                    'final_speech_rate': segment.get('speech_rate'),
                    'applied_adjustment': 'failed',
                    'final_audio_file': segment.get('audio_file')
                })
                final_segments.append(segment)
        
        logger.info("用户调整方案应用完成")
        return final_segments
    
    def _apply_single_user_adjustment(self, segment: Dict, adjustment_choice: Dict, translator, tts, target_language: str) -> Dict:
        """
        应用单个片段的用户调整
        
        Args:
            segment: 片段
            adjustment_choice: 调整选择
            translator: 翻译器实例
            tts: TTS实例
            target_language: 目标语言
            
        Returns:
            调整后的片段
        """
        adjustment_type = adjustment_choice.get('type')
        current_text = segment.get('optimized_text', '')
        target_duration = segment.get('target_duration', 0.0)
        
        if adjustment_type == 'adjust_speed':
            # 调整语速
            suggested_speed = adjustment_choice.get('suggested_speed', 1.0)
            final_text = current_text
            final_rate = max(self.min_speed_ratio, min(self.max_speed_ratio, suggested_speed))
            applied_adjustment = 'speed_adjustment'
            
        elif adjustment_type == 'expand_text':
            # 扩展文本
            try:
                expanded_text = self._adjust_text_with_gpt(
                    current_text, target_duration, translator, tts, target_language, "expand"
                )
                final_text = expanded_text
                final_rate = 1.0
                applied_adjustment = 'text_expansion'
            except Exception as e:
                logger.error(f"文本扩展失败: {e}")
                final_text = current_text
                final_rate = 1.0
                applied_adjustment = 'failed_expansion'
                
        elif adjustment_type == 'condense_text':
            # 精简文本
            try:
                condensed_text = self._adjust_text_with_gpt(
                    current_text, target_duration, translator, tts, target_language, "condense"
                )
                final_text = condensed_text
                final_rate = 1.0
                applied_adjustment = 'text_condensation'
            except Exception as e:
                logger.error(f"文本精简失败: {e}")
                final_text = current_text
                final_rate = 1.0
                applied_adjustment = 'failed_condensation'
                
        elif adjustment_type == 'keep_current':
            # 保持现状
            final_text = current_text
            final_rate = segment.get('speech_rate', 1.0)
            applied_adjustment = 'keep_current'
            
        else:
            # 默认不调整
            final_text = current_text
            final_rate = segment.get('speech_rate', 1.0)
            applied_adjustment = 'none'
        
        # 生成最终音频
        try:
            final_audio_file = tts.synthesize_speech_optimized(
                final_text, target_language, final_rate, f"final_segment_{segment.get('id', 'unknown')}"
            )
            final_duration = tts.get_audio_duration(final_audio_file)
            final_error_ms = abs(final_duration - target_duration) * 1000
            final_quality = self._evaluate_quality(final_error_ms, target_duration, final_rate)
        except Exception as e:
            logger.error(f"最终音频生成失败: {e}")
            final_audio_file = segment.get('audio_file')  # 使用第一轮音频
            final_duration = segment.get('actual_duration', 0.0)
            final_error_ms = segment.get('timing_error_ms', 0)
            final_quality = 'error'
        
        result = segment.copy()
        result.update({
            'final_text': final_text,
            'final_speech_rate': final_rate,
            'final_duration': final_duration,
            'final_timing_error_ms': final_error_ms,
            'final_quality': final_quality,
            'final_audio_file': final_audio_file,
            'applied_adjustment': applied_adjustment
        })
        
        return result
    
    def _adjust_text_with_gpt(self, text: str, target_duration: float, translator, tts, target_language: str, action: str) -> str:
        """
        使用GPT调整文本长度以匹配目标时长
        """
        current_duration = tts.estimate_audio_duration_optimized(text, target_language, 1.0)
        current_words = len(text.split())

        if action == "expand":
            target_words = int(current_words * 1.2)
            prompt = f"""请扩展以下文本，目标约 {target_words} 个词，使其朗读时长更接近 {target_duration:.1f} 秒。
要求:
1. 忠于原文的核心意义和语气
2. 适当增加细节、解释或使用更丰富的表达方式
3. 避免无意义的填充词

原文 ({current_words}个词): "{text}"
"""
        elif action == "condense":
            percentage = 30
            target_words = int(current_words * (1 - percentage / 100))
            
            prompt = f"""请将以下文本精简约 {percentage}%，目标是减少到 {target_words} 个词左右，使其朗读时长接近 {target_duration:.1f} 秒。
要求:
1. 必须保留核心事实和关键信息
2. 大幅删除冗余词汇、修饰语和次要细节
3. 使用最直接、简洁的表达

原文 ({current_words}个词): "{text}"
"""
        else:
            return text

        try:
            adjusted_text = translator._translate_single_text(prompt, target_language, 0.0)
            adjusted_text = adjusted_text.strip().replace('"', '')
            return adjusted_text

        except Exception as e:
            logger.error(f"GPT文本调整失败: {e}")
            return text

    def _binary_search_speech_rate(self, text: str, target_duration: float, tts, target_language: str) -> float:
        """
        使用二分搜索找到给定文本的最优语速
        """
        low_rate, high_rate = self.min_speed_ratio, self.max_speed_ratio
        
        for _ in range(5):
            if high_rate - low_rate < self.speed_step:
                break
            
            mid_rate = (low_rate + high_rate) / 2
            estimated_duration = tts.estimate_audio_duration_optimized(text, target_language, mid_rate)
            
            if estimated_duration > target_duration:
                low_rate = mid_rate
            else:
                high_rate = mid_rate
        
        duration_at_low = tts.estimate_audio_duration_optimized(text, target_language, low_rate)
        duration_at_high = tts.estimate_audio_duration_optimized(text, target_language, high_rate)
        
        if abs(duration_at_low - target_duration) <= abs(duration_at_high - target_duration):
            return low_rate
        else:
            return high_rate

    def _evaluate_quality(self, timing_error_ms: float, target_duration: float, speech_rate: float) -> str:
        """
        评估质量
        """
        error_percentage = abs(timing_error_ms) / (target_duration * 1000) * 100
        
        rate_penalty = 0
        if speech_rate < 0.85 or speech_rate > 1.15:
            rate_penalty = 5
        
        adjusted_error = error_percentage + rate_penalty
        
        if adjusted_error < 8:
            return 'excellent'
        elif adjusted_error < 15:
            return 'good'
        elif adjusted_error < 25:
            return 'fair'
        else:
            return 'poor'

    def create_final_report(self, segments: List[Dict]) -> str:
        """
        创建最终优化报告
        
        Args:
            segments: 最终优化后的片段列表
            
        Returns:
            报告文本
        """
        if not segments:
            return "无片段数据"
        
        total_segments = len(segments)
        
        # 统计质量分布
        quality_counts = {'excellent': 0, 'good': 0, 'fair': 0, 'poor': 0, 'error': 0}
        final_errors = []
        applied_adjustments = {'speed_adjustment': 0, 'text_expansion': 0, 'text_condensation': 0, 'keep_current': 0, 'none': 0}
        
        for seg in segments:
            # 质量统计
            quality = seg.get('final_quality', seg.get('quality', 'unknown'))
            if quality in quality_counts:
                quality_counts[quality] += 1
            
            # 收集最终误差
            final_error = seg.get('final_timing_error_ms', seg.get('timing_error_ms', 0))
            final_errors.append(abs(final_error))
            
            # 统计调整类型
            adjustment = seg.get('applied_adjustment', 'none')
            if adjustment in applied_adjustments:
                applied_adjustments[adjustment] += 1
        
        # 计算平均值
        avg_final_error = sum(final_errors) / total_segments if final_errors else 0
        
        report = f"""最终时间同步优化报告
======================

总体统计:
  - 总片段数: {total_segments}
  - 平均最终误差: {avg_final_error:.0f}ms

最终质量分布:
  - 优秀 (误差<8%): {quality_counts['excellent']} 个 ({quality_counts['excellent']/total_segments*100:.1f}%)
  - 良好 (误差<15%): {quality_counts['good']} 个 ({quality_counts['good']/total_segments*100:.1f}%)
  - 一般 (误差<25%): {quality_counts['fair']} 个 ({quality_counts['fair']/total_segments*100:.1f}%)
  - 较差 (误差≥25%): {quality_counts['poor']} 个 ({quality_counts['poor']/total_segments*100:.1f}%)
  - 错误: {quality_counts['error']} 个 ({quality_counts['error']/total_segments*100:.1f}%)

调整方案分布:
  - 语速调整: {applied_adjustments['speed_adjustment']} 个
  - 文本扩展: {applied_adjustments['text_expansion']} 个
  - 文本精简: {applied_adjustments['text_condensation']} 个
  - 保持现状: {applied_adjustments['keep_current']} 个
  - 无调整: {applied_adjustments['none']} 个
"""
        
        return report
