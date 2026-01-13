"""
文本优化器
基于时长差距使用LLM优化翻译文本，调整词数以匹配目标时长
采用"渐进式最小修改"策略，避免过度修改
"""

from typing import Dict, Any, Optional, List, Tuple
from loguru import logger
from openai import OpenAI
import time
import re

from utils.config_manager import get_global_config_manager


class TextOptimizer:
    """基于时长差距的文本优化器 - 渐进式最小修改策略"""
    
    def __init__(self, config: Dict[str, Any]):
        """
        初始化文本优化器
        
        Args:
            config: 配置字典
        """
        self.config = config
        self.translation_config = config.get('translation', {})
        self.use_kimi = self.translation_config.get('use_kimi', False)
        
        # 根据配置选择API
        if self.use_kimi:
            self.api_key = config.get('api_keys', {}).get('kimi_api_key')
            self.base_url = config.get('api_keys', {}).get('kimi_base_url', 'https://api.moonshot.cn/v1')
            self.model = self.translation_config.get('model', 'kimi-k2-0711-preview')
            self.max_tokens = 2000  # 优化任务不需要太多tokens
            logger.info(f"文本优化使用Kimi API，模型: {self.model}")
        else:
            self.api_key = config.get('api_keys', {}).get('openai_api_key')
            self.base_url = None
            self.model = self.translation_config.get('model', 'gpt-5.2')
            self.max_tokens = 1500
            logger.info(f"文本优化使用OpenAI API，模型: {self.model}")
        
        self.temperature = 0.1  # 更低的temperature确保稳定性和一致性
        
        # 创建客户端
        if self.use_kimi:
            self.client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url
            )
        else:
            self.client = OpenAI(api_key=self.api_key)
        
        # 语言映射
        self.language_names = {
            'en': 'English',
            'es': 'Spanish',
            'fr': 'French',
            'de': 'German',
            'ja': 'Japanese',
            'ko': 'Korean'
        }
        
        # 渐进式修改的词数梯度
        self.word_adjustment_tiers = [1, 2, 3, 4, 5]  # 先尝试删1个词，再2个，以此类推
    
    def optimize_text_for_duration(
        self, 
        original_text: str, 
        current_text: str,
        target_duration: float,
        actual_duration: float,
        target_language: str,
        original_language: str = 'zh'
    ) -> Optional[str]:
        """
        基于时长差距优化文本 - 使用渐进式最小修改策略
        
        Args:
            original_text: 原始文本
            current_text: 当前翻译文本
            target_duration: 目标时长（秒）
            actual_duration: 实际音频时长（秒）
            target_language: 目标语言代码
            original_language: 原始语言代码
            
        Returns:
            优化后的文本，如果失败返回None
        """
        try:
            # 计算时长差距
            duration_diff = actual_duration - target_duration
            duration_diff_ms = duration_diff * 1000
            
            # 如果差距很小（<100ms），不需要优化
            if abs(duration_diff_ms) < 100:
                logger.info(f"时长差距很小({duration_diff_ms:.0f}ms)，无需优化")
                return current_text
            
            # 判断需要缩短还是延长
            if duration_diff > 0:
                action = "缩短"
                adjustment_type = "删减"
            else:
                action = "延长"
                adjustment_type = "增加"
            
            # 使用渐进式最小修改策略
            optimized_text = self._progressive_minimal_optimization(
                original_text,
                current_text,
                target_language,
                duration_diff_ms,
                action,
                adjustment_type
            )
            
            if optimized_text and optimized_text != current_text:
                # 验证修改幅度
                change_ratio = self._calculate_text_change_ratio(current_text, optimized_text)
                logger.info(f"文本优化成功：{action}目标{abs(duration_diff_ms):.0f}ms，修改幅度{change_ratio:.1%}")
                return optimized_text
            else:
                logger.warning("文本优化未产生改变，返回原文本")
                return current_text
                
        except Exception as e:
            logger.error(f"文本优化失败: {e}")
            return None
    
    def _progressive_minimal_optimization(
        self,
        original_text: str,
        current_text: str,
        target_language: str,
        duration_diff_ms: float,
        action: str,
        adjustment_type: str
    ) -> Optional[str]:
        """
        渐进式最小修改策略
        从最小的修改开始尝试，逐步增加修改幅度
        
        Args:
            original_text: 原始文本
            current_text: 当前翻译文本
            target_language: 目标语言
            duration_diff_ms: 时长差距(ms)
            action: 动作（缩短/延长）
            adjustment_type: 调整类型（删减/增加）
            
        Returns:
            优化后的文本
        """
        # 根据时长差距估算需要的词数调整
        estimated_words = self._estimate_words_for_duration(abs(duration_diff_ms), target_language)
        
        # 确定尝试的词数范围（从估算值开始，允许±1的浮动）
        min_words = max(1, estimated_words - 1)
        max_words = min(5, estimated_words + 1)  # 最多5个词
        
        logger.info(f"渐进式优化: 需要{action}{abs(duration_diff_ms):.0f}ms, "
                   f"估算需要{adjustment_type}{estimated_words}个词")
        
        # 使用精确词数控制的prompt
        optimized_text = self._call_llm_with_precise_control(
            original_text,
            current_text,
            target_language,
            action,
            adjustment_type,
            estimated_words,
            duration_diff_ms
        )
        
        return optimized_text
    
    def _estimate_words_for_duration(self, duration_ms: float, target_language: str) -> int:
        """
        根据时长差距估算需要调整的词数
        
        Args:
            duration_ms: 时长差距(ms)
            target_language: 目标语言
            
        Returns:
            估算的词数
        """
        # 每个词大约的朗读时长(ms)
        ms_per_word = {
            'en': 350,   # 英语每词约350ms
            'es': 380,   # 西班牙语
            'fr': 360,   # 法语
            'de': 420,   # 德语（词较长）
            'ja': 280,   # 日语（假名较快）
            'ko': 340    # 韩语
        }
        
        avg_ms = ms_per_word.get(target_language, 360)
        
        # 估算词数，向上取整确保足够
        words = max(1, int(duration_ms / avg_ms + 0.5))
        
        return min(words, 5)  # 限制最大5个词
    
    def _call_llm_with_precise_control(
        self,
        original_text: str,
        current_text: str,
        target_language: str,
        action: str,
        adjustment_type: str,
        word_count: int,
        duration_diff_ms: float
    ) -> Optional[str]:
        """
        使用精确词数控制的LLM调用
        
        Args:
            original_text: 原始文本
            current_text: 当前翻译文本
            target_language: 目标语言
            action: 动作
            adjustment_type: 调整类型
            word_count: 需要调整的词数
            duration_diff_ms: 时长差距
            
        Returns:
            优化后的文本
        """
        language_name = self.language_names.get(target_language, target_language.upper())
        
        # 构建精确控制的system prompt
        system_prompt = f"""你是一个精确的{language_name}文本微调专家。你的任务是对翻译文本进行【最小限度】的修改。

核心原则：
1. 只做必要的修改，不改动不需要改的部分
2. 保持原文的语气、风格和核心意思完全不变
3. 优先删除/添加不影响意思的词（如副词、语气词、修饰词）
4. 输出必须是纯{language_name}文本，不包含任何解释"""

        # 根据需要缩短还是延长，使用不同的策略
        if action == "缩短":
            user_prompt = f"""请精确地缩短以下{language_name}文本，只删除{word_count}个词左右。

当前文本: "{current_text}"
原始含义参考: "{original_text}"

删减要求:
- 需要减少约{duration_diff_ms:.0f}毫秒的朗读时间
- 只删除{word_count}个左右的词，不要多删
- 优先删除: 副词(very, really, just)、冗余修饰词、语气词
- 禁止删除: 核心动词、主语、关键名词
- 保持句子语法正确和自然

直接返回修改后的{language_name}文本:"""
        else:
            user_prompt = f"""请精确地延长以下{language_name}文本，只增加{word_count}个词左右。

当前文本: "{current_text}"
原始含义参考: "{original_text}"

增加要求:
- 需要增加约{abs(duration_diff_ms):.0f}毫秒的朗读时间
- 只增加{word_count}个左右的词，不要多加
- 可以添加: 适当的修饰词、连接词、程度副词
- 禁止: 改变原意、添加新信息、过度修饰
- 保持句子语法正确和自然

直接返回修改后的{language_name}文本:"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=self.temperature,
                max_tokens=self.max_tokens
            )
            
            result = response.choices[0].message.content
            if result:
                result = result.strip()
                result = self._clean_response_text(result)
                
                # 验证修改是否合理
                if self._validate_optimization(current_text, result, word_count):
                    return result
                else:
                    logger.warning(f"优化结果验证失败，修改幅度可能过大")
                    return result  # 仍然返回结果，让调用方决定
            
            return None
            
        except Exception as e:
            logger.error(f"精确控制LLM调用失败: {e}")
            return None
    
    def _validate_optimization(self, original: str, optimized: str, expected_word_diff: int) -> bool:
        """
        验证优化结果是否合理
        
        Args:
            original: 原始文本
            optimized: 优化后文本
            expected_word_diff: 预期的词数差异
            
        Returns:
            是否合理
        """
        original_words = len(original.split())
        optimized_words = len(optimized.split())
        actual_diff = abs(original_words - optimized_words)
        
        # 允许±2的误差
        if actual_diff > expected_word_diff + 2:
            logger.warning(f"词数变化过大: 预期{expected_word_diff}词，实际{actual_diff}词")
            return False
        
        return True
    
    def _calculate_text_change_ratio(self, original: str, modified: str) -> float:
        """
        计算文本修改幅度
        
        Args:
            original: 原始文本
            modified: 修改后文本
            
        Returns:
            修改比例 (0-1)
        """
        if not original:
            return 1.0
        
        original_words = set(original.lower().split())
        modified_words = set(modified.lower().split())
        
        # 计算Jaccard相似度的补集
        intersection = len(original_words & modified_words)
        union = len(original_words | modified_words)
        
        if union == 0:
            return 0.0
        
        similarity = intersection / union
        return 1.0 - similarity
    
    def _calculate_word_adjustment(self, duration_diff: float, target_language: str) -> int:
        """
        计算建议的词数调整量
        
        Args:
            duration_diff: 时长差距（秒）
            target_language: 目标语言
            
        Returns:
            建议调整的词数（正数表示增加，负数表示减少）
        """
        # 根据语言特性估算每个词的平均时长
        words_per_second = {
            'en': 2.5,  # 英语大约每秒2.5个词
            'es': 2.2,  # 西班牙语
            'fr': 2.0,  # 法语
            'de': 1.8,  # 德语（词较长）
            'ja': 3.0,  # 日语（假名较快）
            'ko': 2.5   # 韩语
        }
        
        wps = words_per_second.get(target_language, 2.2)  # 默认值
        
        # 计算需要调整的词数（取整）
        word_adjustment = int(duration_diff * wps)
        
        # 限制调整幅度，避免过度修改
        max_adjustment = 5
        word_adjustment = max(-max_adjustment, min(max_adjustment, word_adjustment))
        
        return word_adjustment
    
    def _build_optimization_prompt(
        self,
        original_text: str,
        current_text: str,
        target_language: str,
        action: str,
        adjustment_type: str,
        word_adjustment: int,
        duration_diff_ms: float
    ) -> str:
        """构建优化prompt"""
        
        language_name = self.language_names.get(target_language, target_language.upper())
        
        system_prompt = f"""你是一个专业的文本优化专家，擅长调整{language_name}翻译文本的长度以匹配音频时长要求。

你的任务是：
1. 保持翻译的准确性和自然度
2. 根据时长要求{action}文本
3. 优先删减/调整不重要的词语或简化句子结构
4. 保持原文的核心意思不变"""

        user_prompt = f"""请优化以下翻译文本以匹配目标时长：

**原文：** {original_text}
**当前翻译：** {current_text}
**目标语言：** {language_name}

**时长调整需求：**
- 当前音频比目标时长{action}了{abs(duration_diff_ms):.0f}毫秒
- 需要{adjustment_type}大约{abs(word_adjustment)}个词

**优化要求：**
1. 如果需要缩短：删减修饰词、副词、重复表达，或简化复杂句型
2. 如果需要延长：适当增加必要的修饰词或连接词，但不改变核心意思
3. 保持翻译的自然流畅
4. 确保语法正确
5. 尽量保持原文的语调和风格

请直接返回优化后的{language_name}文本，不需要解释。"""

        return user_prompt
    
    def _call_llm_for_optimization(self, prompt: str, target_language: str) -> Optional[str]:
        """
        调用LLM进行文本优化
        
        Args:
            prompt: 优化prompt
            target_language: 目标语言
            
        Returns:
            优化后的文本
        """
        try:
            language_name = self.language_names.get(target_language, target_language.upper())
            
            system_prompt = f"""你是一个专业的{language_name}文本优化专家。请根据用户的要求优化文本长度，同时保持翻译质量。直接返回优化后的文本，不要添加任何解释或标记。"""
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                temperature=self.temperature,
                max_tokens=self.max_tokens
            )
            
            optimized_text = response.choices[0].message.content
            if optimized_text:
                optimized_text = optimized_text.strip()
            else:
                optimized_text = ""
            
            # 清理可能的格式标记
            optimized_text = self._clean_response_text(optimized_text)
            
            return optimized_text
            
        except Exception as e:
            logger.error(f"LLM调用失败: {e}")
            return None
    
    def _clean_response_text(self, text: str) -> str:
        """清理LLM响应文本"""
        if not text:
            return text or ""
        
        # 移除可能的引号包围
        text = text.strip()
        if text.startswith('"') and text.endswith('"'):
            text = text[1:-1]
        if text.startswith("'") and text.endswith("'"):
            text = text[1:-1]
        
        # 移除可能的标记
        prefixes_to_remove = [
            "优化后的文本：",
            "优化结果：",
            "Optimized text:",
            "Result:",
            "Translation:",
            "优化后：",
        ]
        
        for prefix in prefixes_to_remove:
            if text.startswith(prefix):
                text = text[len(prefix):].strip()
        
        return text