"""
翻译服务工厂
统一管理不同的翻译实现
"""

from typing import Dict, Any, Optional
from loguru import logger

from .translator import Translator
from .context_translator import ContextTranslator


class TranslationFactory:
    """翻译服务工厂"""
    
    @staticmethod
    def create_translator(config: Dict[str, Any], progress_callback=None):
        """
        创建翻译器实例
        
        Args:
            config: 配置字典
            progress_callback: 进度回调函数
            
        Returns:
            翻译器实例
        """
        translation_config = config.get('translation', {})
        
        # 检查是否使用新的翻译服务
        if 'service' in translation_config:
            service = translation_config.get('service', 'google')
            logger.info(f"使用新的上下文感知翻译器，服务: {service}")
            return ContextTranslator(config, progress_callback)
        else:
            # 兼容旧的GPT翻译配置
            logger.info("使用传统GPT翻译器")
            return Translator(config, progress_callback)
    
    @staticmethod
    def get_available_services() -> Dict[str, Dict[str, Any]]:
        """
        获取可用的翻译服务信息
        
        Returns:
            服务信息字典
        """
        services = {}
        
        # Google Translation
        try:
            from google.cloud import translate_v2 as translate_google
            services['google'] = {
                'name': 'Google Cloud Translation',
                'available': True,
                'features': ['批量翻译', '上下文感知', '高并发'],
                'requirements': ['google-cloud-translate==2.0.1', 'Google Cloud认证']
            }
        except ImportError:
            services['google'] = {
                'name': 'Google Cloud Translation',
                'available': False,
                'error': '需要安装: pip install google-cloud-translate==2.0.1'
            }
        

        
        # GPT翻译（兼容）
        services['gpt'] = {
            'name': 'GPT翻译（传统）',
            'available': True,
            'features': ['多轮优化', '智能调整', '时长控制'],
            'requirements': ['OpenAI API密钥']
        }
        
        return services
    
    @staticmethod
    def validate_service_config(config: Dict[str, Any]) -> Dict[str, Any]:
        """
        验证翻译服务配置
        
        Args:
            config: 配置字典
            
        Returns:
            验证结果
        """
        result = {
            'valid': True,
            'errors': [],
            'warnings': []
        }
        
        translation_config = config.get('translation', {})
        api_keys = config.get('api_keys', {})
        
        if 'service' not in translation_config:
            # 传统GPT模式
            if not api_keys.get('openai_api_key') and not api_keys.get('kimi_api_key'):
                result['errors'].append('GPT翻译需要OpenAI或Kimi API密钥')
                result['valid'] = False
        else:
            service = translation_config.get('service')
            
            if service == 'google':
                if not api_keys.get('google_credentials_path'):
                    result['errors'].append('Google Translation需要认证文件路径')
                    result['valid'] = False
                
                try:
                    from google.cloud import translate_v2 as translate_google
                except ImportError:
                    result['errors'].append('Google Translation客户端未安装')
                    result['valid'] = False
                    

            else:
                result['errors'].append(f'不支持的翻译服务: {service}')
                result['valid'] = False
        
        return result