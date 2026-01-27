"""
渐进式音频生成器
支持后台生成音频，前端可在部分生成完成后提前进入确认阶段
提高用户体验，减少等待时间
"""

import threading
import queue
from concurrent.futures import ThreadPoolExecutor, Future, as_completed
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from loguru import logger
import time


class SegmentStatus(Enum):
    """片段生成状态"""
    PENDING = "pending"          # 等待生成
    GENERATING = "generating"    # 正在生成
    COMPLETED = "completed"      # 生成完成
    FAILED = "failed"            # 生成失败


@dataclass
class GenerationProgress:
    """生成进度信息"""
    total_segments: int = 0
    completed_segments: int = 0
    failed_segments: int = 0
    generating_segments: int = 0
    current_segment_id: Optional[str] = None
    start_time: Optional[datetime] = None
    estimated_remaining_seconds: float = 0
    
    @property
    def pending_segments(self) -> int:
        return self.total_segments - self.completed_segments - self.failed_segments - self.generating_segments
    
    @property
    def progress_percentage(self) -> float:
        if self.total_segments == 0:
            return 0.0
        return (self.completed_segments / self.total_segments) * 100
    
    @property
    def is_complete(self) -> bool:
        return self.completed_segments + self.failed_segments >= self.total_segments
    
    @property
    def can_start_confirmation(self) -> bool:
        """是否可以开始确认阶段（至少有3个或30%的片段完成）"""
        min_count = min(3, self.total_segments)
        min_percentage = 0.3
        return (self.completed_segments >= min_count or 
                self.completed_segments >= self.total_segments * min_percentage)


class ProgressiveAudioGenerator:
    """
    渐进式音频生成器
    
    特性：
    - 后台线程池处理音频生成
    - 按顺序优先生成（用户更可能先看到前面的片段）
    - 支持随时查询进度
    - 生成完成的片段可立即使用
    - 支持取消和暂停
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance
    
    def __init__(self, max_workers: int = 2):
        if self._initialized:
            return
        
        self._initialized = True
        self._max_workers = max_workers
        self._executor: Optional[ThreadPoolExecutor] = None
        self._generation_lock = threading.Lock()
        
        # 当前生成任务状态
        self._is_running = False
        self._should_stop = False
        self._segments: List[Any] = []
        self._segment_status: Dict[str, SegmentStatus] = {}
        self._progress = GenerationProgress()
        
        # TTS 引擎和配置
        self._tts_engine = None
        self._target_language: str = ""
        self._voice_name: str = ""
        
        # 回调函数
        self._on_segment_complete: Optional[Callable] = None
        self._on_all_complete: Optional[Callable] = None
        self._on_progress_update: Optional[Callable] = None
        
        # 性能统计
        self._segment_times: List[float] = []
        
        logger.info(f"渐进式音频生成器初始化完成，最大工作线程数: {max_workers}")
    
    def start_generation(
        self,
        segments: List[Any],
        tts_engine: Any,
        target_language: str,
        voice_name: str,
        text_optimizer: Any = None,
        supports_speech_rate: bool = True,
        on_segment_complete: Optional[Callable[[str, Any], None]] = None,
        on_all_complete: Optional[Callable[[], None]] = None,
        on_progress_update: Optional[Callable[[GenerationProgress], None]] = None
    ) -> bool:
        """
        开始后台音频生成
        
        Args:
            segments: 需要生成音频的片段列表 (SegmentDTO)
            tts_engine: TTS 引擎实例
            target_language: 目标语言
            voice_name: 音色名称
            text_optimizer: 文本优化器（可选）
            supports_speech_rate: TTS 是否支持语速调整
            on_segment_complete: 单个片段完成回调 (segment_id, segment)
            on_all_complete: 全部完成回调
            on_progress_update: 进度更新回调
            
        Returns:
            是否成功启动
        """
        with self._generation_lock:
            if self._is_running:
                logger.warning("已有生成任务在运行，请先停止")
                return False
            
            # 初始化状态
            self._segments = segments
            self._tts_engine = tts_engine
            self._target_language = target_language
            self._voice_name = voice_name
            self._text_optimizer = text_optimizer
            self._supports_speech_rate = supports_speech_rate
            
            # 初始化片段状态
            self._segment_status = {
                seg.id: SegmentStatus.PENDING for seg in segments
            }
            
            # 初始化进度
            self._progress = GenerationProgress(
                total_segments=len(segments),
                start_time=datetime.now()
            )
            
            # 设置回调
            self._on_segment_complete = on_segment_complete
            self._on_all_complete = on_all_complete
            self._on_progress_update = on_progress_update
            
            # 启动线程池
            self._should_stop = False
            self._is_running = True
            self._segment_times = []
            
            # 创建新的线程池（避免复用可能关闭的线程池）
            self._executor = ThreadPoolExecutor(
                max_workers=self._max_workers,
                thread_name_prefix="audio_gen"
            )
            
            # 启动后台生成线程
            self._generation_thread = threading.Thread(
                target=self._generation_loop,
                daemon=True
            )
            self._generation_thread.start()
            
            logger.info(f"渐进式音频生成已启动，共 {len(segments)} 个片段")
            return True
    
    def _generation_loop(self):
        """后台生成循环"""
        try:
            # 使用迭代优化器处理每个片段
            from utils.audio_iteration_optimizer import AudioIterationOptimizer
            
            iteration_optimizer = AudioIterationOptimizer(
                tts_engine=self._tts_engine,
                text_optimizer=self._text_optimizer,
                supports_speech_rate=self._supports_speech_rate
            )
            
            futures: Dict[Future, Any] = {}
            
            # 按顺序提交任务（但并发执行）
            for seg in self._segments:
                if self._should_stop:
                    break
                
                # 更新状态
                with self._generation_lock:
                    self._segment_status[seg.id] = SegmentStatus.GENERATING
                    self._progress.generating_segments += 1
                    self._progress.current_segment_id = seg.id
                
                # 提交任务
                future = self._executor.submit(
                    self._process_single_segment,
                    seg,
                    iteration_optimizer
                )
                futures[future] = seg
                
                # 控制并发数
                while len([f for f in futures if not f.done()]) >= self._max_workers:
                    # 等待任意一个任务完成
                    time.sleep(0.1)
                    self._collect_completed_futures(futures)
            
            # 等待剩余任务完成
            for future in as_completed(futures):
                if self._should_stop:
                    break
                self._handle_future_result(future, futures[future])
            
            # 通知全部完成
            if self._on_all_complete and not self._should_stop:
                try:
                    self._on_all_complete()
                except Exception as e:
                    logger.warning(f"全部完成回调执行失败: {e}")
            
        except Exception as e:
            logger.error(f"渐进式生成循环出错: {e}")
        finally:
            self._is_running = False
            logger.info(f"渐进式音频生成结束，完成 {self._progress.completed_segments}/{self._progress.total_segments}")
    
    def _collect_completed_futures(self, futures: Dict[Future, Any]):
        """收集已完成的任务"""
        completed = [f for f in futures if f.done()]
        for future in completed:
            seg = futures.pop(future)
            self._handle_future_result(future, seg)
    
    def _handle_future_result(self, future: Future, segment: Any):
        """处理单个任务的结果"""
        start_time = time.time()
        
        try:
            success = future.result()
            
            with self._generation_lock:
                self._progress.generating_segments = max(0, self._progress.generating_segments - 1)
                
                if success:
                    self._segment_status[segment.id] = SegmentStatus.COMPLETED
                    self._progress.completed_segments += 1
                else:
                    self._segment_status[segment.id] = SegmentStatus.FAILED
                    self._progress.failed_segments += 1
                
                # 更新预估剩余时间
                self._update_estimated_time()
            
            # 触发进度回调
            if self._on_progress_update:
                try:
                    self._on_progress_update(self._progress)
                except Exception as e:
                    logger.warning(f"进度回调执行失败: {e}")
            
            # 触发单个完成回调
            if success and self._on_segment_complete:
                try:
                    self._on_segment_complete(segment.id, segment)
                except Exception as e:
                    logger.warning(f"片段完成回调执行失败: {e}")
            
        except Exception as e:
            logger.error(f"处理片段 {segment.id} 结果失败: {e}")
            with self._generation_lock:
                self._segment_status[segment.id] = SegmentStatus.FAILED
                self._progress.failed_segments += 1
                self._progress.generating_segments = max(0, self._progress.generating_segments - 1)
    
    def _process_single_segment(self, segment: Any, optimizer: Any) -> bool:
        """
        处理单个片段的音频生成
        
        Args:
            segment: SegmentDTO 片段
            optimizer: AudioIterationOptimizer 实例
            
        Returns:
            是否成功
        """
        start_time = time.time()
        
        try:
            if not segment.final_text:
                logger.warning(f"片段 {segment.id} 没有文本，跳过")
                return False
            
            current_text = segment.final_text
            original_text = segment.original_text or segment.translated_text or current_text
            target_duration = segment.target_duration
            initial_rate = segment.speech_rate or 1.0 if self._supports_speech_rate else 1.0
            
            # 目标时长太短，简单生成
            if target_duration < 0.5:
                try:
                    audio_data = self._tts_engine._generate_single_audio(
                        current_text, self._voice_name, initial_rate, target_duration
                    )
                    segment.set_audio_data(audio_data)
                    segment.quality = 'good'
                    elapsed = time.time() - start_time
                    self._segment_times.append(elapsed)
                    return True
                except Exception as e:
                    logger.error(f"片段 {segment.id} 简单生成失败: {e}")
                    return False
            
            # 使用迭代优化器进行优化
            result = optimizer.optimize_segment(
                text=current_text,
                original_text=original_text,
                voice_name=self._voice_name,
                target_duration=target_duration,
                target_language=self._target_language,
                initial_speech_rate=initial_rate,
                source_language='zh'
            )
            
            if result.get('success') and result.get('best_result'):
                best = result['best_result']
                segment.set_audio_data(best.audio_data)
                segment.speech_rate = best.speech_rate
                segment.update_final_text(best.text)
                segment.timing_error_ms = abs(best.error_ms)
                
                # 设置质量评级
                if best.is_valid:
                    segment.quality = 'excellent'
                elif best.error_percentage <= 10:
                    segment.quality = 'good'
                elif best.error_percentage <= 20:
                    segment.quality = 'fair'
                else:
                    segment.quality = 'poor'
                
                elapsed = time.time() - start_time
                self._segment_times.append(elapsed)
                logger.debug(f"片段 {segment.id} 生成完成，耗时 {elapsed:.2f}s，质量={segment.quality}")
                return True
            else:
                logger.warning(f"片段 {segment.id} 优化失败")
                return False
                
        except Exception as e:
            logger.error(f"处理片段 {segment.id} 失败: {e}")
            return False
    
    def _update_estimated_time(self):
        """更新预估剩余时间"""
        if not self._segment_times:
            return
        
        avg_time = sum(self._segment_times) / len(self._segment_times)
        remaining = self._progress.pending_segments + self._progress.generating_segments
        self._progress.estimated_remaining_seconds = avg_time * remaining
    
    def stop_generation(self):
        """停止后台生成"""
        logger.info("正在停止渐进式音频生成...")
        self._should_stop = True
        
        if self._executor:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None
        
        self._is_running = False
    
    def get_progress(self) -> GenerationProgress:
        """获取当前进度"""
        with self._generation_lock:
            return GenerationProgress(
                total_segments=self._progress.total_segments,
                completed_segments=self._progress.completed_segments,
                failed_segments=self._progress.failed_segments,
                generating_segments=self._progress.generating_segments,
                current_segment_id=self._progress.current_segment_id,
                start_time=self._progress.start_time,
                estimated_remaining_seconds=self._progress.estimated_remaining_seconds
            )
    
    def get_segment_status(self, segment_id: str) -> SegmentStatus:
        """获取指定片段的状态"""
        with self._generation_lock:
            return self._segment_status.get(segment_id, SegmentStatus.PENDING)
    
    def get_completed_segments(self) -> List[Any]:
        """获取所有已完成的片段"""
        with self._generation_lock:
            completed_ids = {
                sid for sid, status in self._segment_status.items()
                if status == SegmentStatus.COMPLETED
            }
            return [seg for seg in self._segments if seg.id in completed_ids]
    
    def is_running(self) -> bool:
        """是否正在运行"""
        return self._is_running
    
    def can_start_confirmation(self) -> bool:
        """是否可以开始确认阶段"""
        return self._progress.can_start_confirmation
    
    def get_ready_segments_count(self) -> int:
        """获取已就绪（可确认）的片段数量"""
        return self._progress.completed_segments


# 全局单例
_progressive_generator: Optional[ProgressiveAudioGenerator] = None


def get_progressive_generator() -> ProgressiveAudioGenerator:
    """获取渐进式音频生成器单例"""
    global _progressive_generator
    if _progressive_generator is None:
        _progressive_generator = ProgressiveAudioGenerator()
    return _progressive_generator


def reset_progressive_generator():
    """重置渐进式音频生成器（用于新的生成任务）"""
    global _progressive_generator
    if _progressive_generator is not None:
        _progressive_generator.stop_generation()
    _progressive_generator = ProgressiveAudioGenerator()
    return _progressive_generator

