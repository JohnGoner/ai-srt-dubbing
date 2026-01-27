"""
音频迭代优化器 - 公共迭代优化逻辑
统一处理音频生成的智能迭代优化，供 workflow 和 audio_confirmation_view 复用

核心策略：效果验证 + 智能回退
- 每轮优化后验证效果
- 如果没有改善，立即切换策略（文本→语速 或 语速→文本）
"""

from typing import Optional, Dict, Any, Callable, List
from dataclasses import dataclass
from loguru import logger
from pydub import AudioSegment


@dataclass
class IterationResult:
    """单次迭代结果"""
    iteration: int
    text: str
    speech_rate: float
    audio_data: AudioSegment
    actual_duration: float
    error_ms: float
    error_percentage: float
    
    @property
    def is_valid(self) -> bool:
        """是否符合标准（实际时长 <= 目标时长，且差距不超过150ms）"""
        return -150 <= self.error_ms <= 0


@dataclass
class OptimizationConfig:
    """优化配置"""
    target_threshold_ms: float = 150
    max_iterations: int = 3
    min_speech_rate: float = 0.95
    max_speech_rate: float = 1.15
    max_rate_adjustment_per_iter: float = 0.05


class AudioIterationOptimizer:
    """
    音频迭代优化器
    
    核心策略：效果验证 + 智能回退
    1. 先尝试文本优化
    2. 验证效果：如果时长没变短，立即改用语速调整
    3. 语速调整更可控，作为文本优化失败时的fallback
    """
    
    def __init__(self, 
                 tts_engine,
                 text_optimizer,
                 supports_speech_rate: bool = True,
                 config: Optional[OptimizationConfig] = None):
        self.tts_engine = tts_engine
        self.text_optimizer = text_optimizer
        self.supports_speech_rate = supports_speech_rate
        self.config = config or OptimizationConfig()
        
        # 记录文本优化是否有效（用于智能切换策略）
        self._text_opt_failed_count = 0
    
    def optimize_segment(self,
                        text: str,
                        original_text: str,
                        voice_name: str,
                        target_duration: float,
                        target_language: str,
                        initial_speech_rate: float = 1.0,
                        source_language: str = 'zh',
                        progress_callback: Optional[Callable[[int, str], None]] = None
                        ) -> Dict[str, Any]:
        """对单个片段进行迭代优化"""
        
        self._text_opt_failed_count = 0  # 重置
        
        current_text = text
        current_rate = initial_speech_rate if self.supports_speech_rate else 1.0
        
        iteration_results: List[IterationResult] = []
        best_result: Optional[IterationResult] = None
        prev_duration: Optional[float] = None
        
        for iteration in range(self.config.max_iterations):
            if progress_callback:
                if self.supports_speech_rate:
                    progress_callback(iteration + 1, f"第{iteration + 1}轮 | 语速: {current_rate:.2f}x")
                else:
                    progress_callback(iteration + 1, f"第{iteration + 1}轮")
            
            # 生成音频
            try:
                audio_data = self.tts_engine._generate_single_audio(
                    current_text, voice_name, current_rate, target_duration
                )
            except Exception as e:
                logger.error(f"迭代{iteration + 1}生成音频失败: {e}")
                break
            
            actual_duration = len(audio_data) / 1000.0
            error_ms = (actual_duration - target_duration) * 1000
            error_percentage = abs(error_ms) / (target_duration * 1000) * 100
            
            result = IterationResult(
                iteration=iteration + 1,
                text=current_text,
                speech_rate=current_rate,
                audio_data=audio_data,
                actual_duration=actual_duration,
                error_ms=error_ms,
                error_percentage=error_percentage
            )
            iteration_results.append(result)
            
            logger.info(f"🔄 迭代{iteration + 1}: 时长={actual_duration:.2f}s, "
                       f"目标={target_duration:.2f}s, 误差={error_ms:.0f}ms "
                       f"({error_percentage:.1f}%), 语速={current_rate:.2f}x")
            
            # ===== 效果验证 =====
            if prev_duration is not None and error_ms > 0:
                # 检查是否有改善
                improvement = prev_duration - actual_duration
                if improvement < 0.1:  # 改善不到100ms，认为无效
                    self._text_opt_failed_count += 1
                    logger.warning(f"⚠️ 优化无效: 时长从{prev_duration:.2f}s变为{actual_duration:.2f}s "
                                  f"(改善{improvement*1000:.0f}ms)")
            
            prev_duration = actual_duration
            
            # 检查是否达标
            if result.is_valid:
                logger.info(f"✅ 迭代{iteration + 1}达标! 误差={error_ms:.0f}ms")
                best_result = result
                break
            
            if iteration == self.config.max_iterations - 1:
                break
            
            # 决定下一轮策略
            current_text, current_rate = self._decide_next_strategy(
                current_text, original_text, current_rate,
                result, target_duration, target_language, source_language
            )
        
        if not best_result and iteration_results:
            best_result = self._select_best_result(iteration_results)
        
        return {
            'success': best_result is not None,
            'best_result': best_result,
            'all_results': iteration_results,
            'final_text': best_result.text if best_result else text,
            'final_speech_rate': best_result.speech_rate if best_result else initial_speech_rate,
            'audio_data': best_result.audio_data if best_result else None
        }
    
    def _decide_next_strategy(self,
                             current_text: str,
                             original_text: str,
                             current_rate: float,
                             result: IterationResult,
                             target_duration: float,
                             target_language: str,
                             source_language: str) -> tuple:
        """
        决定下一轮策略 - 智能切换
        
        如果文本优化连续失败2次，切换到语速调整
        """
        config = self.config
        error_ms = result.error_ms
        
        # 文本优化已经连续失败，改用语速调整
        use_rate_adjustment = (
            self._text_opt_failed_count >= 2 or 
            not self.text_optimizer
        )
        
        if use_rate_adjustment and self.supports_speech_rate:
            # 使用语速调整
            new_rate = self._calculate_rate_adjustment(
                current_rate, result.actual_duration, target_duration
            )
            if new_rate != current_rate:
                logger.info(f"⚡ 文本优化无效，改用语速调整: {current_rate:.2f}x → {new_rate:.2f}x")
                return current_text, new_rate
        
        # 尝试文本优化
        optimized_text = self._try_text_optimization(
            current_text, original_text, result.actual_duration,
            target_duration, target_language, source_language,
            force=(result.error_percentage > 30)
        )
        
        if optimized_text != current_text:
            logger.info(f"📝 优化文本: {len(current_text.split())}词 → {len(optimized_text.split())}词")
            return optimized_text, current_rate
        
        # 文本无法优化，用语速
        if self.supports_speech_rate:
            new_rate = self._calculate_rate_adjustment(
                current_rate, result.actual_duration, target_duration
            )
            if new_rate != current_rate:
                logger.info(f"⚡ 文本无法优化，调整语速: {current_rate:.2f}x → {new_rate:.2f}x")
                return current_text, new_rate
        
        return current_text, current_rate
    
    def _calculate_rate_adjustment(self, current_rate: float, actual_duration: float, 
                                  target_duration: float) -> float:
        """计算语速调整"""
        config = self.config
        
        ideal_rate = actual_duration / target_duration * current_rate
        rate_diff = ideal_rate - current_rate
        
        # 调整50%的差距
        adjustment = rate_diff * 0.5
        adjustment = max(-config.max_rate_adjustment_per_iter, 
                        min(config.max_rate_adjustment_per_iter, adjustment))
        
        new_rate = current_rate + adjustment
        new_rate = max(config.min_speech_rate, min(config.max_speech_rate, new_rate))
        
        return round(new_rate, 2)
    
    def _try_text_optimization(self, current_text: str, original_text: str,
                              actual_duration: float, target_duration: float,
                              target_language: str, source_language: str,
                              force: bool = False) -> str:
        """尝试优化文本"""
        if not self.text_optimizer:
            return current_text
        
        try:
            optimized = self.text_optimizer.optimize_text_for_duration(
                original_text=original_text,
                current_text=current_text,
                target_duration=target_duration,
                actual_duration=actual_duration,
                target_language=target_language,
                original_language=source_language,
                force=force
            )
            if optimized and optimized != current_text:
                return optimized
        except Exception as e:
            logger.warning(f"文本优化失败: {e}")
        
        return current_text
    
    def _select_best_result(self, results: List[IterationResult]) -> Optional[IterationResult]:
        """选择最优结果"""
        if not results:
            return None
        
        under_target = [r for r in results if r.error_ms <= 0]
        
        if under_target:
            best = min(under_target, key=lambda x: abs(x.error_ms))
            logger.info(f"🏆 选择最优: 迭代{best.iteration}, 误差={best.error_ms:.0f}ms, "
                       f"语速={best.speech_rate:.2f}x (<=目标时长)")
        else:
            best = min(results, key=lambda x: x.error_ms)
            logger.info(f"🏆 选择最优: 迭代{best.iteration}, 误差={best.error_ms:.0f}ms, "
                       f"语速={best.speech_rate:.2f}x (超出最少)")
        
        return best
