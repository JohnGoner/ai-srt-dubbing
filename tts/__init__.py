"""
TTS语音合成模块
支持MiniMax TTS和ElevenLabs TTS引擎
"""

from .minimax_tts import MinimaxTTS
from .elevenlabs_tts import ElevenLabsTTS


def create_tts_engine(config: dict, service: str = None):
    """
    根据配置创建TTS引擎
    
    Args:
        config: 配置字典
        service: TTS服务名称，可选 "minimax" 或 "elevenlabs"，如果不指定则从配置读取
        
    Returns:
        TTS引擎实例
    """
    # 从参数或配置中获取服务类型
    if service is None:
        service = config.get('tts', {}).get('service', 'minimax')
    
    service = service.lower()
    
    if service == 'elevenlabs':
        return ElevenLabsTTS(config)
    else:
        # 默认使用MiniMax
        return MinimaxTTS(config)


def get_available_tts_services():
    """
    获取所有可用的TTS服务列表
    
    Returns:
        TTS服务字典 {service_id: display_name}
    """
    return {
        'minimax': 'MiniMax TTS',
        'elevenlabs': 'ElevenLabs TTS'
    }


__all__ = ['MinimaxTTS', 'ElevenLabsTTS', 'create_tts_engine', 'get_available_tts_services'] 