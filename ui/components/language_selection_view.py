"""
配音设置确认视图组件
显示侧边栏已选的TTS设置，确认后开始配音
"""

import streamlit as st
from typing import Dict, Any


class LanguageSelectionView:
    """配音设置确认视图组件"""
    
    def render(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        渲染配音设置确认界面 (极简设计)
        
        Args:
            config: 配置信息
            
        Returns:
            包含action和数据的结果字典
        """
        st.markdown('<div class="main-header"><h1>确认配音设置</h1></div>', unsafe_allow_html=True)
        
        # 从session_state获取侧边栏已选的设置
        target_lang = st.session_state.get('target_lang', 'en')
        selected_tts_service = st.session_state.get('selected_tts_service', 'minimax')
        selected_voice_id = st.session_state.get('selected_voice_id')
        
        # 语言和服务显示名称
        language_names = {
            'en': '🇺🇸 英语 (English)',
            'es': '🇪🇸 西班牙语 (Español)',
            'fr': '🇫🇷 法语 (Français)',
            'de': '🇩🇪 德语 (Deutsch)',
            'ja': '🇯🇵 日语 (日本語)',
            'ko': '🇰🇷 韩语 (한국어)'
        }
        
        service_names = {
            'minimax': 'MiniMax (海螺AI)',
            'elevenlabs': 'ElevenLabs'
        }
        
        # 使用原生 st.info 展示设置
        col1, col2 = st.columns(2)
        with col1:
            st.info(f"**目标语言**\n\n{language_names.get(target_lang, target_lang)}")
        with col2:
            st.info(f"**TTS服务**\n\n{service_names.get(selected_tts_service, selected_tts_service)}")
        
        # 音色信息
        if selected_voice_id:
            voice_display = selected_voice_id
            if 'config' in st.session_state:
                tts_config = st.session_state['config'].get('tts', {})
                # 支持 ElevenLabs 和 MiniMax 两种服务的音色名称显示
                if selected_tts_service == 'elevenlabs':
                    voices = tts_config.get('elevenlabs', {}).get('voices', {}).get(target_lang, {})
                    voice_display = voices.get(selected_voice_id, selected_voice_id)
                elif selected_tts_service == 'minimax':
                    voices = tts_config.get('minimax', {}).get('voices', {}).get(target_lang, {})
                    voice_display = voices.get(selected_voice_id, selected_voice_id)
            st.success(f"**选中音色**: {voice_display}")
        else:
            st.warning("⚠️ 未选择音色，将使用默认音色")
        
        # 工程信息摘要
        current_project = st.session_state.get('current_project')
        if current_project:
            st.caption(f"工程: {current_project.name} | 片段: {current_project.total_segments}")
        
        st.markdown("---")
        
        # 操作按钮
        col1, col2 = st.columns(2)
        with col1:
            if st.button("⬅️ 返回分段确认", use_container_width=True, key="back_to_segmentation"):
                return {'action': 'back_to_segmentation'}
        
        with col2:
            if st.button("🚀 开始配音处理", type="primary", use_container_width=True, key="start_dubbing"):
                # 使用侧边栏的设置
                updated_config = config.copy()
                updated_config['tts']['service'] = selected_tts_service
                updated_config['tts']['speech_rate'] = 1.0
                updated_config['tts']['pitch'] = 0
                updated_config['translation']['temperature'] = 0.3
                
                return {
                    'action': 'start_dubbing',
                    'target_lang': target_lang,
                    'updated_config': updated_config
                }
        
        # 默认返回（无操作）
        return {'action': 'none'}
