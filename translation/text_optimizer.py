"""
文本优化器
基于时长差距使用LLM优化翻译文本，调整词数以匹配目标时长
"""

from typing import Dict, Any, Optional
from loguru import logger
from openai import OpenAI
import time

from utils.config_manager import get_global_config_manager


class TextOptimizer:
    """基于时长差距的文本优化器"""
    
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
        
        self.temperature = 0.2  # 较低的temperature确保稳定性
        
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
        基于时长差距优化文本
        
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
            
            # 计算建议的词数调整
            word_adjustment = self._calculate_word_adjustment(duration_diff, target_language)
            
            # 构建优化prompt
            prompt = self._build_optimization_prompt(
                original_text,
                current_text,
                target_language,
                action,
                adjustment_type,
                word_adjustment,
                duration_diff_ms
            )
            
            # 调用LLM进行优化
            optimized_text = self._call_llm_for_optimization(prompt, target_language)
            
            if optimized_text and optimized_text != current_text:
                logger.info(f"文本优化成功：{action}了{abs(duration_diff_ms):.0f}ms的目标时长")
                return optimized_text
            else:
                logger.warning("文本优化未产生改变，返回原文本")
                return current_text
                
        except Exception as e:
            logger.error(f"文本优化失败: {e}")
            return None
    
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