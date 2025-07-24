"""
翻译验证视图组件
纯组件，不直接操作session_state
"""

import streamlit as st
from typing import List, Dict, Any
from models.segment_dto import SegmentDTO


class TranslationValidationView:
    """翻译验证视图组件"""
    
    def render(self, translated_segments: List[SegmentDTO], 
               config: Dict[str, Any], target_lang: str) -> Dict[str, Any]:
        """
        渲染翻译验证界面
        
        Args:
            translated_segments: 已翻译的片段列表
            config: 配置信息
            target_lang: 目标语言
            
        Returns:
            包含action和数据的结果字典
        """
        st.markdown("## 🔍 Step 3.5: 翻译结果验证")
        st.markdown("请查看翻译结果和时长分析，选择是否需要调整。")
        
        # 显示翻译统计
        self._show_translation_statistics(translated_segments)
        
        # 显示翻译结果预览
        self._show_translation_preview(translated_segments)
        
        # 快速验证界面
        validated_segments = self._show_quick_validation(translated_segments)
        
        # 操作按钮
        return self._render_action_buttons(validated_segments, target_lang)
    
    def _show_translation_statistics(self, segments: List[SegmentDTO]):
        """显示翻译统计信息"""
        total_segments = len(segments)
        total_chars = sum(len(seg.translated_text) for seg in segments)
        avg_chars = total_chars / total_segments if total_segments > 0 else 0
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("翻译片段", total_segments)
        with col2:
            st.metric("总字符数", total_chars)
        with col3:
            st.metric("平均字符", f"{avg_chars:.0f}")
    
    def _show_translation_preview(self, segments: List[SegmentDTO]):
        """显示翻译预览"""
        st.subheader("📝 翻译预览")
        
        # 显示前几个片段的翻译对比
        preview_count = min(5, len(segments))
        
        for i, seg in enumerate(segments[:preview_count]):
            with st.expander(f"片段 {seg.id} ({seg.start:.1f}s - {seg.end:.1f}s)"):
                col1, col2 = st.columns(2)
                
                with col1:
                    st.markdown("**原文:**")
                    st.text_area(
                        "原文",
                        value=seg.original_text,
                        height=100,
                        disabled=True,
                        key=f"preview_original_{i}",
                        label_visibility="collapsed"
                    )
                
                with col2:
                    st.markdown("**译文:**")
                    st.text_area(
                        "译文",
                        value=seg.translated_text,
                        height=100,
                        disabled=True,
                        key=f"preview_translated_{i}",
                        label_visibility="collapsed"
                    )
        
        if len(segments) > preview_count:
            st.info(f"... 还有 {len(segments) - preview_count} 个片段")
    
    def _show_quick_validation(self, segments: List[SegmentDTO]) -> List[SegmentDTO]:
        """显示快速验证选项"""
        st.subheader("⚡ 快速验证")
        
        validation_mode = st.radio(
            "选择验证模式",
            ["自动确认所有翻译", "手动调整翻译"],
            help="自动确认将直接使用所有翻译结果，手动调整允许您修改具体翻译"
        )
        
        validated_segments = segments.copy()
        
        if validation_mode == "手动调整翻译":
            st.info("💡 手动调整模式暂时简化，直接进入优化阶段")
            # 这里可以添加详细的手动调整界面
            # 为了简化，暂时跳过
        
        # 标记所有片段为已验证
        for seg in validated_segments:
            seg.optimized_text = seg.translated_text  # 使用翻译文本作为优化文本
            seg.final_text = seg.translated_text  # 使用翻译文本作为最终文本
        
        return validated_segments
    
    def _render_action_buttons(self, validated_segments: List[SegmentDTO], 
                              target_lang: str) -> Dict[str, Any]:
        """渲染操作按钮"""
        st.markdown("---")
        col1, col2, col3 = st.columns([1, 1, 1])
        
        with col1:
            if st.button("🔙 返回语言选择", use_container_width=True):
                return {'action': 'back_to_language'}
        
        with col2:
            if st.button("📊 查看详细报告", use_container_width=True):
                self._show_validation_report(validated_segments)
                return {'action': 'none'}
        
        with col3:
            if st.button("✅ 确认并优化", type="primary", use_container_width=True):
                return {
                    'action': 'confirm_and_optimize',
                    'validated_segments': validated_segments,
                    'user_choices': {}  # 简化的用户选择
                }
        
        return {'action': 'none'}
    
    def _show_validation_report(self, segments: List[SegmentDTO]):
        """显示验证报告"""
        st.subheader("📊 验证报告")
        
        # 文本长度分析
        text_lengths = [len(seg.translated_text) for seg in segments]
        avg_length = sum(text_lengths) / len(text_lengths)
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.write("**文本长度分析:**")
            st.write(f"- 平均长度: {avg_length:.1f} 字符")
            st.write(f"- 最短: {min(text_lengths)} 字符")
            st.write(f"- 最长: {max(text_lengths)} 字符")
        
        with col2:
            st.write("**时长分析:**")
            durations = [seg.target_duration for seg in segments]
            avg_duration = sum(durations) / len(durations)
            st.write(f"- 平均时长: {avg_duration:.1f} 秒")
            st.write(f"- 最短: {min(durations):.1f} 秒")
            st.write(f"- 最长: {max(durations):.1f} 秒")
        
        # 潜在问题检测
        issues = []
        for seg in segments:
            if len(seg.translated_text) < 5:
                issues.append(f"片段 {seg.id}: 翻译过短")
            elif len(seg.translated_text) > 200:
                issues.append(f"片段 {seg.id}: 翻译过长")
        
        if issues:
            st.warning("⚠️ 发现潜在问题:")
            for issue in issues:
                st.write(f"- {issue}")
        else:
            st.success("✅ 翻译质量检查通过") 