"""
音频迭代优化器 - 公共迭代优化逻辑
统一处理音频生成的智能迭代优化，供 workflow 和 audio_confirmation_view 复用
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
    target_threshold_ms: float = 150  # 目标误差阈值
    max_iterations: int = 3  # 最大迭代次数
    min_speech_rate: float = 0.95  # 最小语速
    max_speech_rate: float = 1.15  # 最大语速
    text_optimize_threshold_percentage: float = 10  # 触发文本优化的误差百分比
    text_optimize_threshold_ms: float = 2000  # 触发文本优化的误差毫秒


class AudioIterationOptimizer:
    """
    音频迭代优化器
    
    提供统一的三轮迭代优化逻辑：
    1. 生成音频并检查误差
    2. 根据误差大小决定优化策略（微调语速或优化文本）
    3. 选择最优结果
    """
    
    def __init__(self, 
                 tts_engine,
                 text_optimizer,
                 supports_speech_rate: bool = True,
                 config: Optional[OptimizationConfig] = None):
        """
        初始化优化器
        
        Args:
            tts_engine: TTS引擎实例
            text_optimizer: 文本优化器实例
            supports_speech_rate: TTS是否支持语速调整（ElevenLabs不支持）
            config: 优化配置
        """
        self.tts_engine = tts_engine
        self.text_optimizer = text_optimizer
        self.supports_speech_rate = supports_speech_rate
        self.config = config or OptimizationConfig()
    
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
        """
        对单个片段进行迭代优化
        
        Args:
            text: 当前文本
            original_text: 原始文本（用于文本优化参考）
            voice_name: 音色名称
            target_duration: 目标时长（秒）
            target_language: 目标语言
            initial_speech_rate: 初始语速
            source_language: 源语言
            progress_callback: 进度回调函数 (iteration, message)
            
        Returns:
            包含最优结果的字典：
            {
                'success': bool,
                'best_result': IterationResult,
                'all_results': List[IterationResult],
                'final_text': str,
                'final_speech_rate': float,
                'audio_data': AudioSegment
            }
        """
        current_text = text
        current_rate = initial_speech_rate if self.supports_speech_rate else 1.0
        
        iteration_results: List[IterationResult] = []
        best_result: Optional[IterationResult] = None
        
        for iteration in range(self.config.max_iterations):
            # 进度回调
            if progress_callback:
                if self.supports_speech_rate:
                    progress_callback(iteration + 1, f"第{iteration + 1}轮 | 语速: {current_rate:.2f}x")
                else:
                    progress_callback(iteration + 1, f"第{iteration + 1}轮")
            
            # 生成音频
            try:
                audio_data = self.tts_engine._generate_single_audio(
                    current_text,
                    voice_name,
                    current_rate,
                    target_duration
                )
            except Exception as e:
                logger.error(f"迭代{iteration + 1}生成音频失败: {e}")
                break
            
            # 计算误差
            actual_duration = len(audio_data) / 1000.0
            error_ms = (actual_duration - target_duration) * 1000
            error_percentage = abs(error_ms) / (target_duration * 1000) * 100
            
            # 记录结果
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
            
            if self.supports_speech_rate:
                logger.debug(f"迭代{iteration + 1}: 时长={actual_duration:.2f}s, 误差={error_ms:.0f}ms ({error_percentage:.1f}%), 语速={current_rate:.2f}")
            else:
                logger.debug(f"迭代{iteration + 1}: 时长={actual_duration:.2f}s, 误差={error_ms:.0f}ms ({error_percentage:.1f}%)")
            
            # 检查是否达标
            if result.is_valid:
                logger.info(f"✅ 迭代{iteration + 1}达标! 误差={error_ms:.0f}ms")
                best_result = result
                break
            
            # 最后一轮不需要继续优化
            if iteration == self.config.max_iterations - 1:
                break
            
            # 决定下一轮优化策略
            current_text, current_rate = self._decide_next_strategy(
                current_text=current_text,
                original_text=original_text,
                current_rate=current_rate,
                actual_duration=actual_duration,
                target_duration=target_duration,
                error_ms=error_ms,
                error_percentage=error_percentage,
                target_language=target_language,
                source_language=source_language
            )
        
        # 选择最优结果
        if not best_result and iteration_results:
            best_result = self._select_best_result(iteration_results)
        
        if best_result:
            return {
                'success': True,
                'best_result': best_result,
                'all_results': iteration_results,
                'final_text': best_result.text,
                'final_speech_rate': best_result.speech_rate,
                'audio_data': best_result.audio_data
            }
        else:
            return {
                'success': False,
                'best_result': None,
                'all_results': iteration_results,
                'final_text': text,
                'final_speech_rate': initial_speech_rate,
                'audio_data': None
            }
    
    def _decide_next_strategy(self,
                             current_text: str,
                             original_text: str,
                             current_rate: float,
                             actual_duration: float,
                             target_duration: float,
                             error_ms: float,
                             error_percentage: float,
                             target_language: str,
                             source_language: str) -> tuple:
        """
        决定下一轮的优化策略
        
        Returns:
            (new_text, new_rate) 元组
        """
        config = self.config
        
        if self.supports_speech_rate:
            # 支持语速调整的TTS（如MiniMax）
            if error_percentage <= config.text_optimize_threshold_percentage or abs(error_ms) <= config.text_optimize_threshold_ms:
                # 误差小，微调语速
                ideal_rate = actual_duration / target_duration * current_rate
                adjustment = (ideal_rate - current_rate) * 0.5
                new_rate = max(config.min_speech_rate, min(config.max_speech_rate, current_rate + adjustment))
                logger.debug(f"微调语速: {current_rate:.2f}x → {new_rate:.2f}x")
                return current_text, new_rate
            else:
                # 误差大，尝试优化文本
                return self._try_optimize_text(
                    current_text, original_text, current_rate,
                    actual_duration, target_duration, error_ms,
                    target_language, source_language
                )
        else:
            # 不支持语速调整的TTS（如ElevenLabs）
            optimized_text = self._optimize_text(
                current_text, original_text,
                actual_duration, target_duration,
                target_language, source_language
            )
            
            if optimized_text and optimized_text != current_text:
                logger.debug(f"文本已优化 (ElevenLabs)")
                return optimized_text, current_rate
            else:
                logger.debug(f"文本无法进一步优化 (ElevenLabs)")
                return current_text, current_rate
    
    def _try_optimize_text(self,
                          current_text: str,
                          original_text: str,
                          current_rate: float,
                          actual_duration: float,
                          target_duration: float,
                          error_ms: float,
                          target_language: str,
                          source_language: str) -> tuple:
        """尝试优化文本，如果失败则回退到微调语速"""
        config = self.config
        
        try:
            optimized_text = self._optimize_text(
                current_text, original_text,
                actual_duration, target_duration,
                target_language, source_language
            )
            
            if optimized_text and optimized_text != current_text:
                logger.debug(f"文本已优化")
                return optimized_text, current_rate
            else:
                # 文本没变化，微调语速
                if error_ms > 0:
                    new_rate = min(config.max_speech_rate, current_rate + 0.03)
                else:
                    new_rate = max(config.min_speech_rate, current_rate - 0.03)
                logger.debug(f"文本无变化，微调语速至 {new_rate:.2f}x")
                return current_text, new_rate
                
        except Exception as e:
            logger.warning(f"文本优化失败: {e}，回退到微调语速")
            if error_ms > 0:
                new_rate = min(config.max_speech_rate, current_rate + 0.03)
            else:
                new_rate = max(config.min_speech_rate, current_rate - 0.03)
            return current_text, new_rate
    
    def _optimize_text(self,
                      current_text: str,
                      original_text: str,
                      actual_duration: float,
                      target_duration: float,
                      target_language: str,
                      source_language: str) -> Optional[str]:
        """调用文本优化器优化文本"""
        if not self.text_optimizer:
            return None
        
        try:
            return self.text_optimizer.optimize_text_for_duration(
                original_text=original_text,
                current_text=current_text,
                target_duration=target_duration,
                actual_duration=actual_duration,
                target_language=target_language,
                original_language=source_language
            )
        except Exception as e:
            logger.warning(f"文本优化失败: {e}")
            return None
    
    def _select_best_result(self, results: List[IterationResult]) -> Optional[IterationResult]:
        """从所有迭代结果中选择最优的"""
        if not results:
            return None
        
        # 优先选择实际时长 <= 目标时长的结果
        under_target_results = [r for r in results if r.error_ms <= 0]
        
        if under_target_results:
            # 选择最接近目标的（误差绝对值最小）
            return min(under_target_results, key=lambda x: abs(x.error_ms))
        else:
            # 没有<=目标的，选择超出最少的
            return min(results, key=lambda x: x.error_ms)
