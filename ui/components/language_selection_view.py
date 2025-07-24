"""
语言选择视图组件
纯组件，不直接操作session_state
"""

import streamlit as st
from typing import Dict, Any


class LanguageSelectionView:
    """语言选择视图组件"""
    
    def render(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        渲染语言选择界面
        
        Args:
            config: 配置信息
            
        Returns:
            包含action和数据的结果字典
        """
        st.header("🌐 Step 3: 选择目标语言和处理选项")
        
        # 语言选择
        st.subheader("🗣️ 目标语言")
        languages = {
            'en': '英语 (English)',
            'es': '西班牙语 (Español)',
            'fr': '法语 (Français)',
            'de': '德语 (Deutsch)',
            'ja': '日语 (日本語)',
            'ko': '韩语 (한국어)'
        }
        
        target_lang = st.selectbox(
            "选择目标配音语言",
            options=list(languages.keys()),
            format_func=lambda x: languages[x],
            # help="选择您希望将字幕翻译并配音的目标语言"
        )
        
        # 显示选择的语音
        st.subheader("🎤 语音信息")
        selected_voice = config.get('tts', {}).get('azure', {}).get('voices', {}).get(target_lang, 'N/A')
        st.info(f"🎤 将使用语音: {selected_voice}")
        
        # 简化配置：使用默认值
        speech_rate = 1.0
        translation_temp = 0.3
        pitch = 0
        
        # 开始配音处理按钮
        st.markdown("---")
        col1, col2, col3 = st.columns([2, 1, 2])
        with col2:
            if st.button("🎬 开始配音处理", type="primary", use_container_width=True, key="start_dubbing"):
                # 更新配置
                updated_config = config.copy()
                updated_config['tts']['speech_rate'] = speech_rate
                updated_config['tts']['pitch'] = pitch
                updated_config['translation']['temperature'] = translation_temp
                
                return {
                    'action': 'start_dubbing',
                    'target_lang': target_lang,
                    'updated_config': updated_config
                }
        
        # 返回按钮
        col1, col2, col3 = st.columns([2, 1, 2])
        with col2:
            if st.button("🔙 返回分段选择", use_container_width=True, key="back_to_segmentation"):
                return {'action': 'back_to_segmentation'}
        
        # 默认返回（无操作）
        return {'action': 'none'} 