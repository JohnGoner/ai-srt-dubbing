"""
翻译模块
使用大语言模型进行智能翻译，考虑时间约束和上下文连贯性
"""

from openai import OpenAI
from typing import List, Dict, Any, Optional
from loguru import logger
import re
import time
import json


class Translator:
    """智能翻译器"""
    
    def __init__(self, config: dict):
        """
        初始化翻译器
        
        Args:
            config: 配置字典
        """
        self.config = config
        self.translation_config = config.get('translation', {})
        self.api_key = config.get('api_keys', {}).get('openai_api_key')
        self.model = self.translation_config.get('model', 'gpt-4o')
        self.max_tokens = self.translation_config.get('max_tokens', 4000)
        self.temperature = self.translation_config.get('temperature', 0.3)
        self.system_prompt = self.translation_config.get('system_prompt', '')
        
        # 创建OpenAI客户端
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
    
    def translate_segments(self, segments: List[Dict[str, Any]], target_language: str) -> List[Dict[str, Any]]:
        """
        翻译语音片段
        
        Args:
            segments: 原始语音片段列表
            target_language: 目标语言代码
            
        Returns:
            翻译后的片段列表
        """
        try:
            logger.info(f"开始翻译 {len(segments)} 个片段到 {target_language}")
            
            # 批量翻译以保持上下文连贯性
            translated_segments = []
            batch_size = 10  # 每批处理的片段数
            
            for i in range(0, len(segments), batch_size):
                batch = segments[i:i + batch_size]
                logger.info(f"翻译批次 {i//batch_size + 1}/{(len(segments)-1)//batch_size + 1}")
                
                translated_batch = self._translate_batch(batch, target_language)
                translated_segments.extend(translated_batch)
                
                # 避免API限制
                time.sleep(0.5)
            
            logger.info("翻译完成")
            return translated_segments
            
        except Exception as e:
            logger.error(f"翻译失败: {str(e)}")
            raise
    
    def _translate_batch(self, segments: List[Dict[str, Any]], target_language: str) -> List[Dict[str, Any]]:
        """
        批量翻译片段
        
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
                duration = segment['end'] - segment['start']
                source_texts.append({
                    'id': segment['id'],
                    'text': segment['text'],
                    'duration': duration,
                    'start': segment['start'],
                    'end': segment['end']
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
            
            # 解析翻译结果
            translation_result = response.choices[0].message.content
            translated_segments = self._parse_translation_result(segments, translation_result)
            
            return translated_segments
            
        except Exception as e:
            logger.error(f"批量翻译失败: {str(e)}")
            # 如果批量翻译失败，尝试单个翻译
            return self._translate_segments_individually(segments, target_language)
    
    def _build_translation_prompt(self, source_texts: List[Dict], target_language: str) -> str:
        """
        构建翻译提示词
        
        Args:
            source_texts: 源文本列表
            target_language: 目标语言代码
            
        Returns:
            翻译提示词
        """
        language_name = self.language_names.get(target_language, target_language)
        
        prompt = f"""请将以下中文文本翻译成{language_name}，并考虑以下要求：

1. 保持上下文连贯性和语义准确性
2. 考虑时间约束，确保翻译后的文本能在指定的时间范围内正常朗读
3. 使用自然、流畅的表达方式
4. 保持原文的语调和情感

请按照以下JSON格式返回翻译结果：
```json
[
  {{
    "id": "片段ID",
    "original_text": "原文",
    "translated_text": "翻译文本",
    "duration": 时长(秒),
    "estimated_speech_time": 预估朗读时间(秒),
    "adjustment_needed": 是否需要调整(true/false),
    "alternative_translation": "备选翻译(如果需要调整)"
  }}
]
```

待翻译文本：
"""
        
        for i, text_info in enumerate(source_texts, 1):
            prompt += f"\n{i}. ID: {text_info['id']}, 时长: {text_info['duration']:.2f}秒\n"
            prompt += f"   文本: {text_info['text']}\n"
        
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
            # 尝试解析JSON格式的结果
            json_match = re.search(r'```json\s*(\[.*?\])\s*```', translation_result, re.DOTALL)
            if json_match:
                translations = json.loads(json_match.group(1))
            else:
                # 如果不是JSON格式，尝试简单解析
                translations = self._simple_parse_translation(translation_result)
            
            # 构建翻译后的片段
            translated_segments = []
            for i, segment in enumerate(original_segments):
                translation = translations[i] if i < len(translations) else None
                
                if translation:
                    translated_text = translation.get('translated_text', segment['text'])
                    adjustment_needed = translation.get('adjustment_needed', False)
                    alternative = translation.get('alternative_translation', '')
                    
                    # 如果需要调整且有备选翻译，使用备选翻译
                    if adjustment_needed and alternative:
                        translated_text = alternative
                else:
                    translated_text = segment['text']  # 使用原文作为备选
                
                translated_segment = {
                    'id': segment['id'],
                    'start': segment['start'],
                    'end': segment['end'],
                    'original_text': segment['text'],
                    'translated_text': translated_text,
                    'confidence': segment.get('confidence', 0),
                    'duration': segment['end'] - segment['start']
                }
                
                translated_segments.append(translated_segment)
            
            return translated_segments
            
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
                    segment['text'], 
                    target_language, 
                    segment['end'] - segment['start']
                )
                
                translated_segment = {
                    'id': segment['id'],
                    'start': segment['start'],
                    'end': segment['end'],
                    'original_text': segment['text'],
                    'translated_text': translated_text,
                    'confidence': segment.get('confidence', 0),
                    'duration': segment['end'] - segment['start']
                }
                
                translated_segments.append(translated_segment)
                
            except Exception as e:
                logger.error(f"翻译片段 {segment['id']} 失败: {str(e)}")
                # 使用原文作为备选
                translated_segment = segment.copy()
                translated_segment['translated_text'] = segment['text']
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
1. 保持语义准确性
2. 使用自然表达
3. 考虑时间约束({duration:.2f}秒)，确保翻译后的文本能在此时间内正常朗读

原文: {text}

请直接返回翻译结果，不要包含其他内容。"""
        
        # 使用新版本API
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "你是一个专业的翻译专家。"},
                {"role": "user", "content": prompt}
            ],
            max_tokens=500,
            temperature=self.temperature
        )
        
        return response.choices[0].message.content.strip()
    
    def estimate_speech_time(self, text: str, language: str) -> float:
        """
        估算文本的朗读时间
        
        Args:
            text: 文本内容
            language: 语言代码
            
        Returns:
            预估朗读时间（秒）
        """
        # 不同语言的平均朗读速度（字符/秒）
        speech_rates = {
            'en': 14,  # 英语
            'es': 12,  # 西班牙语
            'fr': 13,  # 法语
            'de': 11,  # 德语
            'ja': 8,   # 日语
            'ko': 9,   # 韩语
            'zh': 7    # 中文
        }
        
        rate = speech_rates.get(language, 12)  # 默认速度
        char_count = len(text)
        
        # 基础时间计算
        base_time = char_count / rate
        
        # 考虑标点符号的停顿时间
        pause_chars = '.!?。！？;；,，'
        pause_count = sum(1 for char in text if char in pause_chars)
        pause_time = pause_count * 0.3  # 每个标点0.3秒停顿
        
        return base_time + pause_time 