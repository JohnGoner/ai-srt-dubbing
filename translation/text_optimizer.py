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
        original_language: str = 'zh',
        force: bool = False
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
            force: 是否强制优化（忽略阈值检查）
            
        Returns:
            优化后的文本，如果失败返回None
        """
        try:
            # 计算时长差距
            duration_diff = actual_duration - target_duration
            duration_diff_ms = duration_diff * 1000
            
            # 如果差距很小（<50ms）且非强制模式，不需要优化
            if abs(duration_diff_ms) < 50 and not force:
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
                adjustment_type,
                force=force
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
        adjustment_type: str,
        force: bool = False
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
            force: 是否强制激进优化
            
        Returns:
            优化后的文本
        """
        # 计算当前文本词数
        current_word_count = len(current_text.split())
        
        # 根据时长差距估算需要调整的比例和词数
        adjustment_percentage, estimated_words = self._estimate_adjustment_ratio(
            abs(duration_diff_ms), 
            current_text, 
            target_language
        )
        
        # 根据时长差距决定修改力度（越大越激进）
        diff_ms = abs(duration_diff_ms)
        
        # 对于极小的调整（<400ms），优先尝试标点符号调整
        if diff_ms < 400 and not force:
            punctuation_result = self._try_punctuation_only_adjustment(
                current_text, action, diff_ms, target_language
            )
            if punctuation_result and punctuation_result != current_text:
                logger.info(f"标点微调: 需要{action}{diff_ms:.0f}ms, 仅通过标点符号调整")
                return punctuation_result
        
        if diff_ms > 5000:  # >5秒：非常激进
            discount = 0.9
            max_change = 10
        elif diff_ms > 3000:  # 3-5秒：较激进  
            discount = 0.8
            max_change = 8
        elif diff_ms > 1500:  # 1.5-3秒：中等
            discount = 0.6
            max_change = 5
        else:  # <1.5秒：保守
            discount = 0.4
            max_change = 3
        
        llm_percentage = adjustment_percentage * discount
        llm_estimated_words = max(1, int(current_word_count * llm_percentage / 100 + 0.5))
        target_change_words = max(1, min(llm_estimated_words, max_change))
        
        # 统计当前标点符号
        comma_count = current_text.count(',')
        logger.info(f"渐进式优化: 需要{action}{diff_ms:.0f}ms, "
                   f"当前{current_word_count}词/{comma_count}逗号, 本轮目标{action}{target_change_words}词")
        
        # 传入target_change_words（已经限制过的词数）
        optimized_text = self._call_llm_with_ratio_control(
            original_text,
            current_text,
            target_language,
            action, 
            adjustment_type,
            llm_percentage,
            target_change_words,  # 修复：传入限制后的词数
            duration_diff_ms,
            actual_percentage=adjustment_percentage,
            actual_estimated_words=estimated_words
        )
        
        return optimized_text
    
    def _estimate_adjustment_ratio(self, duration_diff_ms: float, current_text: str, target_language: str) -> tuple:
        """
        根据时长差距估算需要调整的比例和词数
        
        Args:
            duration_diff_ms: 时长差距(ms)
            current_text: 当前文本
            target_language: 目标语言
            
        Returns:
            (调整比例%, 估算词数)
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
        current_word_count = len(current_text.split())
        
        # 估算当前文本总时长
        estimated_current_duration = current_word_count * avg_ms
        
        # 计算需要调整的比例（基于时长）
        if estimated_current_duration > 0:
            adjustment_percentage = (duration_diff_ms / estimated_current_duration) * 100
        else:
            adjustment_percentage = 20  # 默认20%
        
        # 限制调整比例范围：5% ~ 50%
        adjustment_percentage = max(5, min(50, abs(adjustment_percentage)))
        
        # 根据比例计算词数
        estimated_words = max(1, int(current_word_count * adjustment_percentage / 100 + 0.5))
        
        return adjustment_percentage, estimated_words
    
    def _try_punctuation_only_adjustment(
        self,
        text: str,
        action: str,
        diff_ms: float,
        target_language: str
    ) -> Optional[str]:
        """
        尝试仅通过标点符号调整来匹配时长（不调用LLM，快速且免费）
        
        Args:
            text: 当前文本
            action: 动作（缩短/延长）
            diff_ms: 时长差距(ms)
            target_language: 目标语言
            
        Returns:
            调整后的文本，如果无法调整返回None
        """
        import re
        
        # 每个逗号约产生250-350ms停顿
        MS_PER_COMMA = 300
        
        if action == "缩短":
            # 需要缩短时间，尝试删除不必要的逗号
            comma_count = text.count(',')
            if comma_count == 0:
                return None
            
            # 计算需要删除几个逗号
            commas_to_remove = min(comma_count, int(diff_ms / MS_PER_COMMA) + 1)
            if commas_to_remove == 0:
                return None
            
            # 找到可以安全删除的逗号位置（优先删除连接词前后的逗号）
            # 安全删除模式：", and" ", but" ", so" ", or" 等前的逗号
            safe_patterns = [
                (r',\s+(and|but|so|or|yet)\s+', r' \1 '),  # ", and X" -> " and X"
                (r',\s+(which|who|that)\s+', r' \1 '),      # 非限定性从句的逗号
            ]
            
            result = text
            removed = 0
            
            # 先尝试安全删除
            for pattern, replacement in safe_patterns:
                if removed >= commas_to_remove:
                    break
                match = re.search(pattern, result, re.IGNORECASE)
                if match:
                    result = re.sub(pattern, replacement, result, count=1, flags=re.IGNORECASE)
                    removed += 1
            
            # 如果还需要删除更多，从后往前删除普通逗号
            while removed < commas_to_remove and ',' in result:
                # 找到最后一个逗号（通常是最不重要的）
                last_comma = result.rfind(',')
                if last_comma > 0:
                    result = result[:last_comma] + result[last_comma+1:]
                    removed += 1
                else:
                    break
            
            if removed > 0:
                logger.debug(f"标点微调：删除了{removed}个逗号")
                return result.strip()
            
        else:  # 延长
            # 需要延长时间，尝试在适当位置添加逗号
            commas_to_add = min(2, int(diff_ms / MS_PER_COMMA) + 1)
            
            # 寻找适合添加逗号的位置
            # 1. 连接词前（and, but, so, or, yet, however）
            # 2. 副词短语后（however, therefore, moreover, indeed）
            # 3. 介词短语后
            
            add_patterns = [
                (r'\s+(and|but|so|or|yet)\s+', r', \1 '),         # "X and Y" -> "X, and Y"
                (r'^(However|Therefore|Moreover|Indeed|Furthermore)\s+', r'\1, '),  # 句首副词
                (r'\s+(however|therefore|moreover|indeed)\s+', r', \1, '),  # 句中副词
            ]
            
            result = text
            added = 0
            
            for pattern, replacement in add_patterns:
                if added >= commas_to_add:
                    break
                # 检查是否已经有逗号在这个位置
                if re.search(pattern, result, re.IGNORECASE):
                    # 确保不会重复添加
                    test_result = re.sub(pattern, replacement, result, count=1, flags=re.IGNORECASE)
                    if test_result.count(',') > result.count(','):
                        result = test_result
                        added += 1
            
            if added > 0:
                logger.debug(f"标点微调：添加了{added}个逗号")
                return result.strip()
        
        return None
    
    def _call_llm_with_ratio_control(
        self,
        original_text: str,
        current_text: str,
        target_language: str,
        action: str,
        adjustment_type: str,
        llm_percentage: float,
        llm_estimated_words: int,
        duration_diff_ms: float,
        actual_percentage: float = None,
        actual_estimated_words: int = None
    ) -> Optional[str]:
        """
        使用精确词数控制的LLM调用（改进版）
        
        Args:
            original_text: 原始文本
            current_text: 当前翻译文本
            target_language: 目标语言
            action: 动作（缩短/延长）
            adjustment_type: 调整类型（删减/增加）
            llm_percentage: [已弃用] 原百分比参数
            llm_estimated_words: 告诉LLM的估算词数
            duration_diff_ms: 时长差距
            actual_percentage: 实际需要的调整比例(%)（用于验证）
            actual_estimated_words: 实际需要的词数（用于验证）
            
        Returns:
            优化后的文本
        """
        # 如果没传验证参数，使用LLM参数
        if actual_percentage is None:
            actual_percentage = llm_percentage
        if actual_estimated_words is None:
            actual_estimated_words = llm_estimated_words
        
        language_name = self.language_names.get(target_language, target_language.upper())
        current_word_count = len(current_text.split())
        
        # 使用上层传入的词数（不再重新计算，避免覆盖）
        target_change_words = llm_estimated_words
        
        # 分析当前标点符号情况
        current_comma_count = current_text.count(',')
        diff_ms = abs(duration_diff_ms)
        
        # 标点符号调整策略：每个逗号约影响200-400ms
        # 对于小幅度调整，优先考虑标点符号
        punctuation_hint = ""
        if diff_ms < 800:  # 小于800ms的调整，可以优先用标点
            if action == "缩短" and current_comma_count > 0:
                commas_to_remove = min(2, current_comma_count, int(diff_ms / 300) + 1)
                punctuation_hint = f"\n【标点优化】可删除 {commas_to_remove} 个逗号来缩短停顿（每个逗号约300ms）"
            elif action == "延长":
                commas_to_add = min(2, int(diff_ms / 300) + 1)
                punctuation_hint = f"\n【标点优化】可在适当位置添加 {commas_to_add} 个逗号来增加停顿（每个逗号约300ms）"
        elif diff_ms < 1500:  # 中等调整，词数+标点配合
            if action == "缩短" and current_comma_count > 1:
                punctuation_hint = f"\n【辅助】可同时删除1-2个不必要的逗号"
            elif action == "延长":
                punctuation_hint = f"\n【辅助】可在从句连接处添加逗号"
        
        # 构建严格词数控制的prompt（核心：精确控制修改幅度）
        if action == "缩短":
            target_word_count = max(1, current_word_count - target_change_words)
            
            system_prompt = f"""你是精确的{language_name}微编辑器。严格遵守词数限制！

规则：
1. 只能删除 {target_change_words} 个词，不能多删
2. 保持句子主体结构完全不变
3. 可以删除不必要的逗号来缩短停顿
4. 直接输出结果，无解释"""

            user_prompt = f"""输入（{current_word_count}词，{current_comma_count}个逗号）: "{current_text}"

任务：删除恰好 {target_change_words} 个词
目标：{target_word_count} 词

删除优先级：副词 > 形容词 > 介词短语{punctuation_hint}
禁止：重写句子、改变句式、删除主语谓语宾语

输出（必须 {target_word_count} 词）:"""
        else:
            target_word_count = current_word_count + target_change_words
            
            system_prompt = f"""你是精确的{language_name}微编辑器。严格遵守词数限制！

规则：
1. 只能添加 {target_change_words} 个词，不能多加
2. 保持句子主体结构完全不变
3. 可以在适当位置添加逗号来增加停顿
4. 直接输出结果，无解释"""

            user_prompt = f"""输入（{current_word_count}词，{current_comma_count}个逗号）: "{current_text}"
参考原意: "{original_text}"

任务：添加恰好 {target_change_words} 个词
目标：{target_word_count} 词

添加方式：插入副词/形容词修饰现有词{punctuation_hint}
禁止：重写句子、改变句式

输出（必须 {target_word_count} 词）:"""

        try:
            logger.debug(f"LLM调用: {action}{target_change_words}词, 目标{target_word_count}词")
            
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
                result_word_count = len(result.split())
                actual_diff = abs(result_word_count - current_word_count)
                
                # 允许±1词的误差
                if abs(actual_diff - target_change_words) <= 1:
                    logger.debug(f"优化成功: {current_word_count}词 → {result_word_count}词 (目标{target_word_count}词)")
                    return result
                elif self._validate_optimization(current_text, result, actual_percentage, actual_estimated_words):
                    logger.debug(f"优化结果词数偏差较大但通过验证: {current_word_count}词 → {result_word_count}词")
                    return result
                else:
                    logger.warning(f"优化结果验证失败: {current_word_count}词 → {result_word_count}词, 期望{target_word_count}词")
                    return result  # 仍然返回结果，让调用方决定
            
            return None
            
        except Exception as e:
            logger.error(f"LLM调用失败: {e}")
            return None
    
    def _validate_optimization(self, original: str, optimized: str, expected_percentage: float, expected_words: int) -> bool:
        """
        验证优化结果是否合理（基于比例）
        
        Args:
            original: 原始文本
            optimized: 优化后文本
            expected_percentage: 预期的调整比例(%)
            expected_words: 预期的词数差异
            
        Returns:
            是否合理
        """
        original_words = len(original.split())
        optimized_words = len(optimized.split())
        actual_diff = abs(original_words - optimized_words)
        
        # 计算实际变化比例
        if original_words > 0:
            actual_percentage = (actual_diff / original_words) * 100
        else:
            actual_percentage = 0
        
        # 允许比预期多调整50%的幅度（更宽松的验证）
        max_allowed_percentage = expected_percentage * 1.5
        max_allowed_words = int(expected_words * 1.5) + 2
        
        if actual_diff > max_allowed_words:
            logger.warning(f"词数变化过大: 预期{expected_words}词({expected_percentage:.0f}%)，实际{actual_diff}词({actual_percentage:.0f}%)")
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
        
        # 限制调整幅度，激进模式允许更多修改
        max_adjustment = 10
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