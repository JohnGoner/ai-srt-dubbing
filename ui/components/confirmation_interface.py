"""
用户确认界面模块
提供片段确认、文本编辑和音频预览功能
"""

import streamlit as st
from typing import List, Dict, Any, Optional
from loguru import logger
import tempfile
import os


class ConfirmationInterface:
    """用户确认界面管理器"""
    
    def __init__(self):
        """初始化确认界面"""
        self.confirmation_data = []
        self.current_segment_index = 0
    
    def display_confirmation_interface(self, confirmation_segments: List[Dict], 
                                     audio_synthesizer, tts, target_language: str) -> List[Dict]:
        """
        显示用户确认界面
        
        Args:
            confirmation_segments: 确认片段列表
            audio_synthesizer: 音频合成器实例
            tts: TTS实例
            target_language: 目标语言
            
        Returns:
            用户确认后的片段列表
        """
        self.confirmation_data = confirmation_segments
        
        st.header("🎵 片段确认与编辑")
        st.write("请确认每个片段的翻译和音频效果，可以修改文本并重新生成音频。")
        
        # 显示总体统计
        self._display_overall_stats()
        
        # 片段导航
        self._display_segment_navigation()
        
        # 当前片段详情
        if self.confirmation_data:
            self._display_current_segment(audio_synthesizer, tts, target_language)
        
        # 批量操作
        self._display_batch_operations()
        
        # 确认完成按钮
        if st.button("✅ 确认完成并生成最终音频", type="primary"):
            return self._process_final_confirmation()
        
        return self.confirmation_data
    
    def _display_overall_stats(self):
        """显示总体统计信息"""
        if not self.confirmation_data:
            return
        
        total = len(self.confirmation_data)
        confirmed = sum(1 for seg in self.confirmation_data if seg.get('confirmed', False))
        modified = sum(1 for seg in self.confirmation_data if seg.get('text_modified', False))
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("总片段数", total)
        
        with col2:
            st.metric("已确认", f"{confirmed}/{total}")
        
        with col3:
            st.metric("已修改", modified)
        
        with col4:
            avg_error = sum(seg.get('timing_error_ms', 0) for seg in self.confirmation_data) / total
            st.metric("平均误差", f"{avg_error:.0f}ms")
    
    def _display_segment_navigation(self):
        """显示片段导航"""
        if not self.confirmation_data:
            return
        
        st.subheader("📋 片段导航")
        
        # 创建片段列表
        segment_info = []
        for i, seg in enumerate(self.confirmation_data):
            status = "✅" if seg.get('confirmed', False) else "⏳"
            quality_icon = self._get_quality_icon(seg.get('quality', 'unknown'))
            error_ms = seg.get('timing_error_ms', 0)
            
            segment_info.append({
                'index': i,
                'id': seg['segment_id'],
                'status': status,
                'quality': quality_icon,
                'error': f"{error_ms:.0f}ms",
                'text': seg['final_text'][:50] + "..." if len(seg['final_text']) > 50 else seg['final_text']
            })
        
        # 显示片段表格
        for info in segment_info:
            col1, col2, col3, col4, col5, col6 = st.columns([0.5, 0.5, 0.5, 1, 2, 1])
            
            with col1:
                if st.button(f"查看", key=f"view_{info['index']}"):
                    self.current_segment_index = info['index']
            
            with col2:
                st.write(info['status'])
            
            with col3:
                st.write(info['quality'])
            
            with col4:
                st.write(f"#{info['id']}")
            
            with col5:
                st.write(info['text'])
            
            with col6:
                st.write(info['error'])
    
    def _display_current_segment(self, audio_synthesizer, tts, target_language: str):
        """显示当前片段详情"""
        if not self.confirmation_data:
            return
        
        segment = self.confirmation_data[self.current_segment_index]
        
        st.subheader(f"🎯 片段 #{segment['segment_id']} 详情")
        
        # 基本信息
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric("目标时长", f"{segment['target_duration']:.2f}s")
        
        with col2:
            st.metric("实际时长", f"{segment['actual_duration']:.2f}s")
        
        with col3:
            st.metric("时长误差", f"{segment['timing_error_ms']:.0f}ms")
        
        # 质量评级
        quality = segment.get('quality', 'unknown')
        quality_icon = self._get_quality_icon(quality)
        st.write(f"**质量评级:** {quality_icon} {quality.upper()}")
        
        # 原始文本
        st.write("**原始文本:**")
        st.text_area("", segment['original_text'], height=100, key=f"original_{self.current_segment_index}", disabled=True)
        
        # 当前文本（可编辑）
        st.write("**当前文本:**")
        current_text = st.text_area("", segment['final_text'], height=100, key=f"current_{self.current_segment_index}")
        
        # 检查文本是否被修改
        if current_text != segment['final_text']:
            segment['user_modified_text'] = current_text
            segment['text_modified'] = True
        
        # 语速信息
        st.write(f"**语速:** {segment['speech_rate']:.2f}")
        
        # 音频预览
        self._display_audio_preview(segment)
        
        # 操作按钮
        col1, col2, col3 = st.columns(3)
        
        with col1:
            if st.button("🔄 重新生成音频", key=f"regenerate_{self.current_segment_index}"):
                if segment.get('text_modified'):
                    # 重新生成音频
                    updated_segment = audio_synthesizer.regenerate_audio_with_modified_text(
                        segment, tts, target_language
                    )
                    self.confirmation_data[self.current_segment_index] = updated_segment
                    st.success("音频重新生成成功！")
                    st.rerun()
                else:
                    st.warning("请先修改文本")
        
        with col2:
            if st.button("✅ 确认此片段", key=f"confirm_{self.current_segment_index}"):
                segment['confirmed'] = True
                st.success("片段已确认！")
        
        with col3:
            if st.button("❌ 取消确认", key=f"unconfirm_{self.current_segment_index}"):
                segment['confirmed'] = False
                st.info("已取消确认")
    
    def _display_audio_preview(self, segment: Dict):
        """显示音频预览"""
        st.write("**音频预览:**")
        
        if segment.get('audio_data') is not None:
            # 保存临时音频文件
            with tempfile.NamedTemporaryFile(delete=False, suffix='.wav') as tmp_file:
                segment['audio_data'].export(tmp_file.name, format='wav')
                tmp_path = tmp_file.name
            
            # 显示音频播放器
            with open(tmp_path, 'rb') as audio_file:
                st.audio(audio_file.read(), format='audio/wav')
            
            # 清理临时文件
            os.unlink(tmp_path)
        else:
            st.error("音频生成失败")
    
    
    def _process_final_confirmation(self) -> List[Dict]:
        """处理最终确认"""
        confirmed_count = sum(1 for seg in self.confirmation_data if seg.get('confirmed', False))
        total_count = len(self.confirmation_data)
        
        if confirmed_count == 0:
            st.error("请至少确认一个片段！")
            return self.confirmation_data
        
        if confirmed_count < total_count:
            st.warning(f"只确认了 {confirmed_count}/{total_count} 个片段，未确认的片段将被跳过")
        
        st.success(f"确认完成！将生成包含 {confirmed_count} 个片段的最终音频")
        return self.confirmation_data
    
    def _get_quality_icon(self, quality: str) -> str:
        """获取质量评级图标"""
        icons = {
            'excellent': '🟢',
            'good': '🟡',
            'fair': '🟠',
            'poor': '🔴',
            'error': '❌',
            'unknown': '⚪'
        }
        return icons.get(quality, '⚪')


def create_confirmation_workflow(optimized_segments: List[Dict], config: dict, 
                               tts, target_language: str, progress_callback=None):
    """
    创建完整的用户确认工作流
    
    Args:
        optimized_segments: 优化后的片段列表
        config: 配置字典
        tts: TTS实例
        target_language: 目标语言
        progress_callback: 进度回调函数
        
    Returns:
        最终音频和确认报告
    """
    from timing.audio_synthesizer import AudioSynthesizer
    
    # 1. 初始化音频合成器
    audio_synthesizer = AudioSynthesizer(config, progress_callback)
    
    # 2. 生成音频供确认
    confirmation_segments = audio_synthesizer.generate_audio_for_confirmation(
        optimized_segments, tts, target_language
    )
    
    # 3. 显示用户确认界面
    confirmation_interface = ConfirmationInterface()
    confirmed_segments = confirmation_interface.display_confirmation_interface(
        confirmation_segments, audio_synthesizer, tts, target_language
    )
    
    # 4. 生成最终音频
    final_audio = audio_synthesizer.merge_confirmed_audio_segments(confirmed_segments)
    
    # 5. 生成确认报告
    confirmation_report = audio_synthesizer.create_confirmation_report(confirmed_segments)
    
    return final_audio, confirmation_report, confirmed_segments 