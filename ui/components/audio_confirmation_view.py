"""
音频确认视图组件
纯组件，不直接操作session_state
"""

import streamlit as st
import tempfile
import os
from typing import List, Dict, Any
from loguru import logger
from models.segment_dto import SegmentDTO


class AudioConfirmationView:
    """音频确认视图组件"""
    
    def __init__(self):
        self.current_confirmation_index = 0
        self.confirmation_page = 1
    
    def render(self, optimized_segments: List[SegmentDTO], 
               confirmation_segments: List[SegmentDTO],
               translated_original_segments: List[SegmentDTO], 
               target_lang: str, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        渲染音频确认界面
        
        Args:
            optimized_segments: 优化后的片段
            confirmation_segments: 确认用的片段（包含音频）
            translated_original_segments: 翻译后的原始片段
            target_lang: 目标语言
            config: 配置信息
            
        Returns:
            包含action和数据的结果字典
        """
        st.markdown("## 🎵 Step 4: 翻译文本确认与音频预览")
        st.markdown("请确认每个片段的翻译文本和音频效果，可以修改文本并重新生成音频。")
        
        # 当前片段详情
        if confirmation_segments:
            self._display_current_segment(confirmation_segments, target_lang)
        
        # 显示总体统计
        self._display_overall_stats(confirmation_segments)
        
        # 片段导航
        # self._display_segment_navigation(confirmation_segments)
        
        # 确认完成按钮
        return self._render_action_buttons(confirmation_segments, translated_original_segments, optimized_segments, target_lang)
    
    def _display_overall_stats(self, confirmation_segments: List[SegmentDTO]):
        """显示总体统计信息"""
        if not confirmation_segments:
            return
        
        total = len(confirmation_segments)
        confirmed = sum(1 for seg in confirmation_segments if seg.confirmed)
        modified = sum(1 for seg in confirmation_segments if seg.user_modified)
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("总片段数", total)
        
        with col2:
            st.metric("已确认", f"{confirmed}/{total}")
        
        with col3:
            st.metric("已修改", modified)
        
        with col4:
            avg_error = sum(seg.timing_error_ms or 0 for seg in confirmation_segments) / total
            st.metric("平均误差", f"{avg_error:.0f}ms")
    
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
    
    def _display_segment_navigation(self, confirmation_segments: List[SegmentDTO]):
        """显示片段导航"""
        st.subheader("📋 片段导航")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("✅ 快速确认所有", key="nav_confirm_all_segments"):
                for segment in confirmation_segments:
                    segment.confirmed = True
                st.success("所有片段已确认！")
                st.rerun()
        with col2:
            if st.button("❌ 快速取消所有", key="nav_unconfirm_all_segments"):
                for segment in confirmation_segments:
                    segment.confirmed = False
                st.info("已取消所有确认")
                st.rerun()
    
    def _display_current_segment(self, confirmation_segments: List[SegmentDTO], target_lang: str):
        """显示当前确认片段的详情"""
        # st.subheader("🎯 当前片段详情")
        
        if not confirmation_segments:
            st.warning("⚠️ 没有待确认的片段")
            return

        # 使用页面导航
        total_segments = len(confirmation_segments)
        if 'current_confirmation_index' not in st.session_state:
            st.session_state.current_confirmation_index = 0

        current_index = st.session_state.current_confirmation_index

        # 当前片段详情需要 current_index，提前定义
        current_segment = confirmation_segments[current_index]

        # --- 页面导航控件移到后面 ---
        # 片段详情
        st.markdown("---")
        
        # 基本信息
        col1, col2, col3, col4, col5 = st.columns(5)
        
        with col1:
            st.metric("片段ID", current_segment.id)
        
        with col2:
            st.metric("目标时长", f"{current_segment.target_duration:.2f}s")
        
        with col3:
            actual_duration = current_segment.actual_duration or 0.0
            st.metric("实际时长", f"{actual_duration:.2f}s")
        
        with col4:
            error_ms = current_segment.timing_error_ms or 0
            st.metric("时长误差", f"{error_ms:.0f}ms")
        
        with col5:
            sync_ratio = current_segment.sync_ratio
            st.metric(f"同步比例", f"{sync_ratio:.2f}")
        
        # 质量评级
        quality = current_segment.quality or 'unknown'
        quality_icon = self._get_quality_icon(quality)
        st.markdown(f"**质量评级:** {quality_icon} {quality.upper()}")
        
        # 文本对比
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("**原始文本:**")
            st.text_area("原始文本", current_segment.original_text, height=120, 
                        disabled=True, key=f"original_{current_index}", 
                        label_visibility="collapsed")
        
        with col2:
            # 显示文本来源信息
            text_source = "优化后文本"
            if current_segment.optimized_text and current_segment.final_text == current_segment.optimized_text:
                text_source = "🎯 多轮优化后文本"
            elif current_segment.translated_text and current_segment.final_text == current_segment.translated_text:
                text_source = "📝 翻译后文本"
            elif current_segment.final_text == current_segment.original_text:
                text_source = "⚠️ 原始文本（未优化）"
            
            st.markdown(f"**{text_source}:**")
            
            # 获取当前文本
            current_text = current_segment.get_current_text()
            
            # 创建文本输入框
            new_text = st.text_area(
                "优化翻译", 
                current_text, 
                height=120, 
                key=f"optimized_{current_index}",
                label_visibility="collapsed",
                help="修改文本后会自动检测变化，点击「更新音频」按钮重新生成"
            )
            
            # 添加键盘快捷键提示
            st.markdown("""
            <div style="font-size: 0.8em; color: #666; margin-top: -10px; margin-bottom: 10px;">
                💡 <strong>提示:</strong> 修改文本后，统计信息会自动更新，点击下方「更新音频」按钮重新生成音频
            </div>
            """, unsafe_allow_html=True)
            
            # 检查文本是否被修改
            text_changed = new_text != current_text
            if text_changed:
                current_segment.update_final_text(new_text)
                
                # 实时更新统计信息
                word_count = len(new_text.split())
                char_count = len(new_text)
                
                # 显示更新后的统计信息（高亮显示）
                current_rate = current_segment.speech_rate or 1.0
                st.markdown(f"""
                <div style="background-color: #e8f4fd; padding: 8px; border-radius: 4px; border-left: 4px solid #1f77b4;">
                    <small><strong>📊 更新后统计:</strong> 词数: {word_count} | 字符: {char_count} | 当前语速: {current_rate:.2f}x | 时间: {current_segment.start:.1f}s - {current_segment.end:.1f}s</small>
                </div>
                """, unsafe_allow_html=True)
                
                # 计算文本长度变化提示
                original_length = len(current_text)
                new_length = len(new_text)
                length_change = new_length - original_length
                
                if abs(length_change) > 50:  # 如果变化超过50个字符
                    change_type = "增加" if length_change > 0 else "减少"
                    st.warning(f"⚠️ 文本长度{change_type}了 {abs(length_change)} 个字符，可能影响时长匹配。建议重新生成音频检查效果。")
                else:
                    st.info("💡 文本已修改，点击下方「更新音频」按钮更新音频")
            else:
                # 显示原始统计信息
                word_count = len(current_text.split())
                char_count = len(current_text)
                current_rate = current_segment.speech_rate or 1.0
                st.caption(f"词数: {word_count} | 字符: {char_count} | 语速: {current_rate:.2f}x | 时间: {current_segment.start:.1f}s - {current_segment.end:.1f}s")
            
            # 显示优化建议信息
            if not text_changed:
                self._display_optimization_suggestions(current_segment, current_index)
        
        # 语速控制组件
        self._display_speech_rate_control(current_segment, current_index)
        
        # 音频预览
        self._display_audio_preview(current_segment, current_index)
        
        # 操作按钮
        st.markdown("---")
        col1, col2 = st.columns(2)

        with col1:
            # 检查是否有文本修改，调整按钮样式
            text_modified = current_segment.user_modified or (current_segment.get_current_text() != (current_segment.optimized_text or current_segment.translated_text or current_segment.original_text))
            button_type = "primary" if text_modified else "secondary"
            button_text = "🔄 更新音频" if text_modified else "🔄 重新生成音频"
            button_help = "基于修改后的文本重新生成音频" if text_modified else "基于当前文本重新生成音频"

            # 按钮宽度占满col
            if st.button(
                button_text,
                key=f"regenerate_{current_index}",
                type=button_type,
                help=button_help,
                use_container_width=True
            ):
                self._regenerate_segment_audio(current_segment, target_lang)

        with col2:
            # 由于st.button的type只支持primary/secondary/tertiary，使用primary高亮确认按钮
            if current_segment.confirmed:
                if st.button(
                    "❌ 取消确认",
                    key=f"unconfirm_{current_index}",
                    type="secondary",
                    use_container_width=True
                ):
                    current_segment.confirmed = False
                    st.success("已取消确认")
                    st.rerun()
            else:
                if st.button(
                    "✅ 确认此片段",
                    key=f"confirm_{current_index}",
                    type="primary",
                    use_container_width=True
                ):
                    current_segment.confirmed = True
                    st.success("片段已确认！")
                    # 跳转到下一个片段（如有）
                    total_segments = st.session_state.get('total_confirmation_segments', None)
                    if total_segments is None:
                        # 兼容性处理
                        total_segments = st.session_state.get('confirmation_segments_count', None)
                    if total_segments is None:
                        # 兜底方案
                        total_segments = 1
                    next_index = min(current_index + 1, total_segments - 1)
                    st.session_state.current_confirmation_index = next_index
                    st.rerun()
        
        # 页面导航控件
        st.markdown("---")
        nav_col1, nav_col2, nav_col3, nav_col4 = st.columns(4)
        
        with nav_col1:
            if st.button("⬅️ 上一个", disabled=current_index <= 0, key="prev_segment"):
                st.session_state.current_confirmation_index = max(0, current_index - 1)
                st.rerun()
        
        with nav_col2:
            if st.button("➡️ 下一个", disabled=current_index >= total_segments - 1, key="next_segment"):
                st.session_state.current_confirmation_index = min(total_segments - 1, current_index + 1)
                st.rerun()
        
        with nav_col3:
            # 使用不可点击的按钮确保与其他按钮完全对齐
            st.button(
                f"📄 片段 {current_index + 1} / {total_segments}",
                disabled=True,
                key=f"segment_info_{current_index}",
            )
        
        
        with nav_col4:
            if st.button("🔄 刷新", key="refresh_current"):
                st.rerun()

            
    def _display_optimization_suggestions(self, segment: SegmentDTO, segment_index: int):
        """显示优化建议信息"""
        current_text = segment.get_current_text()
        target_duration = segment.target_duration
        current_word_count = len(current_text.split())
        current_char_count = len(current_text)
        
        # 计算理想的词数和字符数（基于目标时长）
        # 假设平均语速为每分钟150词，每秒2.5词
        ideal_word_count = int(target_duration * 2.5)
        word_diff = current_word_count - ideal_word_count
        
        # 计算当前语速和建议语速
        current_rate = segment.speech_rate or 1.0
        if segment.actual_duration and segment.actual_duration > 0:
            current_actual_rate = target_duration / segment.actual_duration
        else:
            current_actual_rate = 1.0
        
        # 显示优化状态
        # if segment.optimized_text and segment.final_text == segment.optimized_text:
            # st.success("✅ 此文本已通过多轮LLM优化，时长匹配度最佳")
        # elif segment.user_modified:
            # st.warning("⚠️ 此文本已被用户修改")
        
        # 显示具体优化建议
        suggestions = []
        
        # 文本长度建议
        if abs(word_diff) > 2:
            if word_diff > 0:
                suggestions.append(f"💡 建议删减 {word_diff} 词以优化时长匹配")
            else:
                suggestions.append(f"💡 建议增加 {abs(word_diff)} 词以优化时长匹配")
        else:
            suggestions.append("✅ 文本长度适中")
        
        # 语速建议
        # if segment.timing_error_ms and abs(segment.timing_error_ms) > 500:
            # 计算理想语速
            # if segment.actual_duration and segment.actual_duration > 0:
                # ideal_rate = segment.actual_duration / segment.target_duration * current_rate
                # 限制在允许范围内
                # suggested_rate = max(0.95, min(1.15, ideal_rate))
                
                #  if abs(suggested_rate - current_rate) > 0.02:
                    # if ideal_rate < 0.95:
                        # suggestions.append(f"⚡ 语速已达下限(0.95x)，建议增加文本")
                    # elif ideal_rate > 1.15:
                        # suggestions.append(f"🐌 语速已达上限(1.15x)，建议删减文本")
                    # else:
                        # suggestions.append(f"🎯 建议语速调整至 {suggested_rate:.2f}x 以优化时长")
            # else:
                # 没有实际时长数据时的建议
                # suggestions.append("🔄 建议重新生成音频以获得准确的时长数据")
        
        # 质量评估建议
        quality = segment.quality or 'unknown'
        if quality == 'poor':
            suggestions.append("⚠️ 当前质量较差，建议重新优化文本或调整语速")
        elif quality == 'fair':
            suggestions.append("📝 质量一般，可通过微调文本或语速进一步优化")
        
        # 显示建议
        if suggestions:
            with st.expander("💡 优化建议", expanded=len(suggestions) > 1 and quality in ['poor', 'fair']):
                for suggestion in suggestions:
                    st.markdown(f"- {suggestion}")
    
    def _display_speech_rate_control(self, segment: "SegmentDTO", segment_index: int):
        """现代化语速控制UI组件"""
        from typing import Any
        
        # 使用自定义CSS美化界面
        st.markdown("""
        <style>
        .speech-rate-container {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            padding: 1.5rem;
            border-radius: 15px;
            margin: 1rem 0;
            box-shadow: 0 8px 32px rgba(0,0,0,0.1);
        }
        .rate-display {
            background: rgba(255,255,255,0.95);
            padding: 1rem;
            border-radius: 10px;
            text-align: center;
            margin: 0.5rem 0;
        }
        .rate-value {
            font-size: 2rem;
            font-weight: bold;
            color: #2c3e50;
        }
        .rate-label {
            color: #7f8c8d;
            font-size: 0.9rem;
        }
        .optimize-button {
            background: linear-gradient(45deg, #ff6b6b, #ee5a24);
            border: none;
            border-radius: 25px;
            padding: 0.5rem 1.5rem;
            color: white;
            font-weight: bold;
            transition: all 0.3s ease;
        }
        .optimize-button:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(0,0,0,0.2);
        }
        .slider-container {
            background: rgba(255,255,255,0.9);
            padding: 1.5rem;
            border-radius: 12px;
            margin: 1rem 0;
        }
        </style>
        """, unsafe_allow_html=True)
        

        # 获取当前语速和时长信息
        current_rate: float = segment.speech_rate or 1.0
        target_duration: float = getattr(segment, "target_duration", 0) or 1.0
        actual_duration: float = getattr(segment, "actual_duration", 0)

        # 计算理想语速（基于当前音频时长）
        if actual_duration > 0 and target_duration > 0:
            raw_optimal_rate: float = actual_duration / target_duration * current_rate
            optimal_rate: float = max(0.95, min(1.15, raw_optimal_rate))
        else:
            raw_optimal_rate = current_rate
            optimal_rate = current_rate

        # 检查是否有待应用的语速设置
        pending_rate_key = f"pending_speech_rate_{segment_index}"
        pending_rate = st.session_state.get(pending_rate_key, None)
        
        # 如果有待应用的语速，显示待应用状态
        if pending_rate is not None:
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(f"""
                <div style="background: linear-gradient(45deg, #f39c12, #e67e22); 
                            color: white; padding: 1rem; border-radius: 10px; 
                            text-align: center; margin: 1rem 0;">
                    <div style="font-size: 1.2rem; margin-bottom: 0.5rem;">
                        ⏳ 待应用语速设置
                    </div>
                    <div style="font-size: 0.9rem;">
                        目标语速: {pending_rate:.2f}x，请点击「更新音频」以应用
                    </div>
                </div>
                """, unsafe_allow_html=True)
            with col2:
                if st.button("❌ 取消", key=f"cancel_pending_rate_{segment_index}", type="secondary"):
                    del st.session_state[pending_rate_key]
                    st.success("✅ 已取消待应用的语速设置")
                    st.rerun()

        # 现代化布局
        col1, col2 = st.columns([3, 2], gap="large")

        with col1:
            # 语速调节滑块区域         
            # 当前语速显示
            st.markdown(f"""
            <div class="rate-display">
                <div class="rate-value">{current_rate:.2f}x</div>
                <div class="rate-label">当前语速</div>
            </div>
            """, unsafe_allow_html=True)
            
            # 语速滑块 - 使用待应用语速或当前语速作为初始值
            slider_value = pending_rate if pending_rate is not None else current_rate
            new_rate: float = st.slider(
                "调整语速倍率",
                min_value=0.95,
                max_value=1.15,
                value=round(slider_value, 2),
                step=0.01,
                key=f"speech_rate_{segment_index}",
                help="拖动滑块调整语音播放速度，1.00为正常语速"
            )
            
            # 手动调整滑块时，立即更新segment（这是用户主动调整）
            if abs(new_rate - current_rate) > 0.01 and pending_rate is None:
                segment.speech_rate = new_rate
                # 重新估算时长误差
                if actual_duration > 0:
                    estimated_new_duration = actual_duration * (current_rate / new_rate)
                    new_error = abs(estimated_new_duration - target_duration) * 1000
                    segment.timing_error_ms = new_error

        with col2:
            # 智能建议区域         
            # 建议语速显示
            if abs(optimal_rate - current_rate) > 0.02:
                delta_val = optimal_rate - current_rate
                delta_icon = "⬆️" if delta_val > 0 else "⬇️"
                delta_color = "#e74c3c" if delta_val > 0 else "#27ae60"
                
                st.markdown(f"""
                <div class="rate-display">
                    <div class="rate-value" style="color: {delta_color};">{optimal_rate:.2f}x</div>
                    <div class="rate-label">建议语速 {delta_icon}</div>
                </div>
                """, unsafe_allow_html=True)
                
                # 建议说明
                if actual_duration > 0 and target_duration > 0:
                    if raw_optimal_rate < 0.95 or raw_optimal_rate > 1.15:
                        st.warning(f"⚠️ 理想语速 {raw_optimal_rate:.2f}x 超出推荐范围")
                    else:
                        st.info(f"💡 根据时长自动推荐，调整幅度: {abs(delta_val):.2f}x")
                else:
                    st.info("💡 缺少时长数据，建议先生成音频")
            else:
                st.success("✅ 当前语速已接近最优，无需调整")

            # 一键优化按钮
            rate_out_of_bounds: bool = raw_optimal_rate < 0.95 or raw_optimal_rate > 1.15
            button_disabled: bool = abs(optimal_rate - current_rate) < 0.02

            if rate_out_of_bounds:
                button_text = "⚠️ 需调文本"
                button_help = "理想语速超出推荐范围，建议优先调整文本长度"
                button_color = "secondary"
            else:
                button_text = "🎯 应用建议"
                button_help = "一键应用推荐语速"
                button_color = "primary"

            if st.button(
                button_text,
                key=f"apply_optimal_rate_{segment_index}",
                disabled=button_disabled,
                help=button_help,
                type=button_color
            ):
                if not rate_out_of_bounds:
                    # 将建议语速存储为待应用状态，而不是立即更新segment
                    st.session_state[pending_rate_key] = optimal_rate
                    st.success(f"✅ 已设置建议语速: {optimal_rate:.2f}x（待应用）")
                    st.rerun()
                else:
                    if raw_optimal_rate < 0.95:
                        st.warning(f"⚠️ 理想语速 {raw_optimal_rate:.2f}x 低于下限，建议增加文本长度")
                    else:
                        st.warning(f"⚠️ 理想语速 {raw_optimal_rate:.2f}x 高于上限，建议减少文本长度")

        # 语速变化提示 - 使用更美观的提示
        if abs(new_rate - current_rate) > 0.01 and pending_rate is None:
            rate_change = new_rate - current_rate
            change_type = "加速" if rate_change > 0 else "减速"
            change_icon = "🚀" if rate_change > 0 else "🐌"
            
            st.markdown(f"""
            <div style="background: linear-gradient(45deg, #3498db, #2980b9); 
                        color: white; padding: 1rem; border-radius: 10px; 
                        text-align: center; margin: 1rem 0;">
                <div style="font-size: 1.2rem; margin-bottom: 0.5rem;">
                    {change_icon} 语速已调整
                </div>
                <div style="font-size: 0.9rem;">
                    {change_type} {abs(rate_change):.2f}x，请点击「更新音频」以应用新语速
                </div>
            </div>
            """, unsafe_allow_html=True)
    
    
    def _display_audio_preview(self, segment: SegmentDTO, segment_index: int):
        """显示音频预览"""
        st.markdown("### 🎵 音频预览")
        
        # 显示音频处理信息
        if hasattr(segment, 'to_legacy_dict'):
            segment_data = segment.to_legacy_dict()
        else:
            segment_data = segment.__dict__ if hasattr(segment, '__dict__') else {}
        
        # 检查是否有截断信息
        is_truncated = segment_data.get('is_truncated', False)
        raw_duration = segment_data.get('raw_audio_duration', 0)
        actual_duration = segment.actual_duration or 0
        
        if is_truncated and raw_duration > 0:
            st.warning(f"⚠️ **音频已智能截断**: 原始时长 {raw_duration:.2f}s → 处理后时长 {actual_duration:.2f}s（已应用淡出效果）")
        elif raw_duration > 0 and raw_duration != actual_duration:
            st.info(f"ℹ️ **音频处理**: 原始时长 {raw_duration:.2f}s → 处理后时长 {actual_duration:.2f}s")
        
        if segment.audio_data is not None:
            try:
                import tempfile
                import os
                
                 
                # 创建临时音频文件
                with tempfile.NamedTemporaryFile(delete=False, suffix='.wav') as tmp_file:
                    # 导出音频到临时文件
                    segment.audio_data.export(tmp_file.name, format='wav')
                    tmp_path = tmp_file.name
                
                # 显示音频播放器
                with open(tmp_path, 'rb') as audio_file:
                    audio_bytes = audio_file.read()
                    st.audio(audio_bytes, format='audio/wav')
                
                
                # 清理临时文件
                try:
                    os.unlink(tmp_path)
                except Exception as e:
                    logger.warning(f"清理临时文件失败: {e}")
                    
            except Exception as e:
                st.error(f"❌ 音频预览失败: {str(e)}")
                logger.error(f"音频预览失败: {e}")
                
                # 提供详细的错误信息
                with st.expander("🔍 错误详情"):
                    st.code(str(e))
                    st.write("**可能的解决方案:**")
                    st.write("1. 重新生成此片段的音频")
                    st.write("2. 检查音频数据是否完整") 
                    st.write("3. 联系技术支持")
                    
        else:
            st.warning("⚠️ 音频数据不可用")

    
    def _regenerate_segment_audio(self, segment: SegmentDTO, target_lang: str):
        """重新生成片段音频"""
        try:
            # 从session_state获取TTS实例
            tts = st.session_state.get('tts')
            if not tts:
                from tts.azure_tts import AzureTTS
                config = st.session_state.get('config', {})
                tts = AzureTTS(config)
                st.session_state['tts'] = tts
            
            # 获取用户修改后的文本
            current_text = segment.get_current_text()
            if not current_text.strip():
                st.error("❌ 文本内容为空，无法生成音频")
                return
            
            # 检查是否有待应用的语速设置
            pending_rate_key = f"pending_speech_rate_{segment.id}"
            pending_rate = st.session_state.get(pending_rate_key, None)
            
            # 显示生成进度
            with st.spinner(f"🔄 正在重新生成片段 {segment.id} 的音频..."):
                # 优先使用待应用的语速设置
                if pending_rate is not None:
                    optimal_rate = pending_rate
                    st.info(f"🎯 应用待设置语速: {optimal_rate:.2f}x")
                    # 清除待应用状态
                    del st.session_state[pending_rate_key]
                elif hasattr(segment, 'speech_rate') and segment.speech_rate:
                    optimal_rate = segment.speech_rate
                    st.info(f"🎛️ 使用用户设定语速: {optimal_rate:.2f}x")
                else:
                    # 估算最优语速以匹配目标时长
                    optimal_rate = tts.estimate_optimal_speech_rate(
                        current_text, target_lang, segment.target_duration
                    )
                    st.info(f"🤖 使用系统估算语速: {optimal_rate:.2f}x")
                
                # 生成新音频
                voice_name = tts.voice_map.get(target_lang)
                if not voice_name:
                    st.error(f"❌ 不支持的语言: {target_lang}")
                    return
                
                new_audio_data = tts._generate_single_audio(
                    current_text,
                    voice_name,
                    optimal_rate,
                    segment.target_duration
                )
                
                # 更新片段信息
                segment.set_audio_data(new_audio_data)
                segment.speech_rate = optimal_rate
                
                # 计算新的时长误差
                if segment.actual_duration:
                    segment.timing_error_ms = abs(segment.actual_duration - segment.target_duration) * 1000
                
                # 计算同步比例并评估质量
                sync_ratio = segment.sync_ratio
                if sync_ratio >= 0.85 and sync_ratio <= 1.15:
                    if sync_ratio >= 0.95 and sync_ratio <= 1.05:
                        segment.quality = 'excellent'
                    else:
                        segment.quality = 'good'
                elif sync_ratio >= 0.75 and sync_ratio <= 1.25:
                    segment.quality = 'fair'
                else:
                    segment.quality = 'poor'
                
                # 更新校准因子（提升未来估算精度）
                estimated_duration = tts.estimate_audio_duration_optimized(
                    current_text, target_lang, optimal_rate
                )
                if segment.actual_duration is not None:
                    tts.update_calibration(target_lang, estimated_duration, segment.actual_duration)
                
                # 标记为用户修改（如果文本不同于优化文本）
                if current_text != segment.optimized_text:
                    segment.user_modified = True
                
                # 确保语速保存到segment中
                segment.speech_rate = optimal_rate
                
                logger.info(f"片段 {segment.id} 音频重新生成成功: "
                          f"时长={segment.actual_duration:.2f}s, 语速={optimal_rate:.3f}, "
                          f"误差={segment.timing_error_ms:.0f}ms, 质量={segment.quality}")
                
                # 根据语速来源显示不同的成功消息
                if pending_rate is not None:
                    st.success(f"✅ 片段 {segment.id} 音频重新生成成功！(已应用建议语速: {optimal_rate:.2f}x)")
                elif hasattr(segment, 'speech_rate') and segment.speech_rate == optimal_rate:
                    st.success(f"✅ 片段 {segment.id} 音频重新生成成功！(使用用户设定语速)")
                else:
                    st.success(f"✅ 片段 {segment.id} 音频重新生成成功！(使用系统估算语速)")
                
                # 显示更新后的统计信息
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("新实际时长", f"{segment.actual_duration:.2f}s")
                with col2:
                    st.metric("使用语速", f"{optimal_rate:.2f}x")
                with col3:
                    st.metric("时长误差", f"{segment.timing_error_ms:.0f}ms")
                with col4:
                    sync_ratio = segment.sync_ratio
                    st.metric("同步比例", f"{sync_ratio:.2f}")
                
                # 自动刷新页面以显示更新后的音频和指标
                st.rerun()
                
        except Exception as e:
            error_msg = f"重新生成音频失败: {str(e)}"
            logger.error(error_msg)
            st.error(f"❌ {error_msg}")
            
            # 如果失败，清除待应用的语速设置
            pending_rate_key = f"pending_speech_rate_{segment.id}"
            if pending_rate_key in st.session_state:
                del st.session_state[pending_rate_key]
            
            # 提供详细的错误信息和解决建议
            with st.expander("🔍 错误详情和解决建议"):
                st.code(str(e))
                st.write("**可能的解决方案:**")
                st.write("1. 检查网络连接和Azure TTS服务状态")
                st.write("2. 验证API密钥是否有效且有足够配额")
                st.write("3. 检查文本长度是否合理（建议少于500字符）")
                st.write("4. 尝试稍后重试，可能是服务临时不可用")
                st.write("5. 如果问题持续，请联系技术支持")
    
    def _show_segment_analysis(self, segment: SegmentDTO):
        """显示片段分析详情"""
        if segment.timing_analysis:
            st.markdown("#### 📊 时长分析详情")
            analysis = segment.timing_analysis
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.write("**时长信息:**")
                st.write(f"- 目标时长: {analysis.get('target_duration', 0):.2f}s")
                st.write(f"- 实际时长: {analysis.get('actual_duration', 0):.2f}s")
                st.write(f"- 预估时长: {analysis.get('estimated_duration', 0):.2f}s")
            
            with col2:
                st.write("**比例分析:**")
                st.write(f"- 实际比例: {analysis.get('actual_ratio', 1):.2f}")
                st.write(f"- 预估比例: {analysis.get('estimated_ratio', 1):.2f}")
                st.write(f"- 误差百分比: {analysis.get('error_percentage', 0):.1f}%")
        else:
            st.info("暂无详细分析数据")
    
    def _show_adjustment_suggestions(self, segment: SegmentDTO):
        """显示调整建议"""
        if segment.adjustment_suggestions:
            st.markdown("#### 🎯 调整建议")
            
            for i, suggestion in enumerate(segment.adjustment_suggestions):
                with st.expander(f"建议 {i+1}: {suggestion.get('type', 'unknown')}"):
                    st.write(f"**描述:** {suggestion.get('description', '无描述')}")
                    st.write(f"**优先级:** {suggestion.get('priority', 'unknown')}")
                    
                    if 'estimated_improvement' in suggestion:
                        st.write(f"**预期改善:** {suggestion['estimated_improvement']}")
                    
                    if suggestion.get('type') == 'adjust_speed':
                        st.write(f"**当前语速:** {suggestion.get('current_speed', 1.0):.2f}")
                        st.write(f"**建议语速:** {suggestion.get('suggested_speed', 1.0):.2f}")
                    
                    elif suggestion.get('type') in ['expand_text', 'condense_text']:
                        st.write(f"**当前词数:** {suggestion.get('current_words', 0)}")
                        st.write(f"**目标词数:** {suggestion.get('target_words', 0)}")
        else:
            st.info("暂无调整建议")
    
    def _render_batch_operations(self, confirmation_segments: List[SegmentDTO]):
        """显示批量操作"""
        st.subheader("🔧 批量操作")
        
        total_segments = len(confirmation_segments)
        confirmed_count = sum(1 for seg in confirmation_segments if seg.confirmed)
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            if st.button("✅ 批量确认全部", key="batch_confirm_all_segments"):
                for segment in confirmation_segments:
                    segment.confirmed = True
                st.success(f"✅ 已确认所有 {total_segments} 个片段！")
                st.rerun()
        
        with col2:
            if st.button("❌ 批量取消全部", key="batch_unconfirm_all_segments"):
                for segment in confirmation_segments:
                    segment.confirmed = False
                st.info("已取消所有确认")
                st.rerun()
        
        with col3:
            quality_filter = st.selectbox(
                "按质量确认",
                ["选择质量等级", "excellent", "good", "fair", "poor"],
                key="batch_quality_filter"
            )
            if quality_filter != "选择质量等级":
                filtered_count = 0
                for segment in confirmation_segments:
                    if segment.quality == quality_filter:
                        segment.confirmed = True
                        filtered_count += 1
                if filtered_count > 0:
                    st.success(f"✅ 已确认 {filtered_count} 个 {quality_filter} 质量的片段")
                    st.rerun()
        
        with col4:
            if st.button("🔄 重置所有修改", key="batch_reset_all_modifications"):
                for segment in confirmation_segments:
                    segment.user_modified = False
                    # 恢复到优化后的文本（优先使用optimized_text）
                    if segment.optimized_text:
                        segment.final_text = segment.optimized_text
                    elif segment.translated_text:
                        segment.final_text = segment.translated_text
                    else:
                        segment.final_text = segment.original_text
                st.info("已重置所有用户修改，恢复到优化后的文本")
                st.rerun()
        
        # 显示统计信息
        st.markdown(f"**状态统计:** {confirmed_count}/{total_segments} 个片段已确认")
        
        if confirmed_count > 0:
            progress = confirmed_count / total_segments
            st.progress(progress)
            
            if confirmed_count == total_segments:
                st.success("🎉 所有片段已确认完成！可以生成最终音频了。")
    
    def _render_action_buttons(self, confirmation_segments: List[SegmentDTO],
                              translated_original_segments: List[SegmentDTO],
                              optimized_segments: List[SegmentDTO],
                              target_lang: str) -> Dict[str, Any]:
        """渲染操作按钮"""
        st.markdown("---")
        st.subheader("🎬 最终操作")
        
        # 统计确认状态
        total_segments = len(confirmation_segments)
        confirmed_count = sum(1 for seg in confirmation_segments if seg.confirmed)
        
        # 显示确认状态
        if confirmed_count == 0:
            st.warning("⚠️ 请至少确认一个片段才能继续")
        elif confirmed_count < total_segments:
            st.info(f"ℹ️ 已确认 {confirmed_count}/{total_segments} 个片段，未确认的片段将被跳过")
        else:
            st.success(f"✅ 所有 {total_segments} 个片段都已确认")
        
        col1, col2 = st.columns(2)
        
        with col1:
            if st.button("🔙 返回语言选择", use_container_width=True, key="back_to_language"):
                return {'action': 'back_to_language'}
        
        
        with col2:
            button_disabled = confirmed_count == 0
            button_text = "✅ 生成最终音频" if confirmed_count == total_segments else f"⚠️ 生成音频（{confirmed_count}个片段）"
            
            if st.button(button_text, type="primary", use_container_width=True, 
                        disabled=button_disabled, key="generate_final_audio"):
                return {
                    'action': 'generate_final',
                    'confirmed_segments': confirmation_segments,
                    'confirmed_count': confirmed_count,
                    'total_count': total_segments
                }
        
        return {'action': 'none'}
    
    def _show_detailed_report(self, confirmation_segments: List[SegmentDTO]):
        """显示详细的确认报告"""
        st.markdown("## 📊 详细确认报告")
        
        total_segments = len(confirmation_segments)
        confirmed_segments = [seg for seg in confirmation_segments if seg.confirmed]
        confirmed_count = len(confirmed_segments)
        
        # 总体统计
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("总片段数", total_segments)
        
        with col2:
            st.metric("已确认", confirmed_count)
        
        with col3:
            if total_segments > 0:
                completion_rate = confirmed_count / total_segments * 100
                st.metric("完成度", f"{completion_rate:.1f}%")
        
        with col4:
            modified_count = sum(1 for seg in confirmation_segments if seg.user_modified)
            st.metric("用户修改", modified_count)
        
        # 质量分布
        if confirmed_segments:
            st.markdown("### 🏆 质量分布")
            quality_counts = {}
            for seg in confirmed_segments:
                quality = seg.quality or 'unknown'
                quality_counts[quality] = quality_counts.get(quality, 0) + 1
            
            quality_cols = st.columns(len(quality_counts))
            for i, (quality, count) in enumerate(quality_counts.items()):
                with quality_cols[i]:
                    icon = self._get_quality_icon(quality)
                    st.metric(f"{icon} {quality.upper()}", count)
        
        # 时长分析
        if confirmed_segments:
            st.markdown("### ⏱️ 时长分析")
            
            total_target_duration = sum(seg.target_duration for seg in confirmed_segments)
            total_actual_duration = sum(seg.actual_duration or 0 for seg in confirmed_segments)
            avg_error = sum(abs(seg.timing_error_ms or 0) for seg in confirmed_segments) / len(confirmed_segments)
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.metric("目标总时长", f"{total_target_duration:.1f}s")
            
            with col2:
                st.metric("实际总时长", f"{total_actual_duration:.1f}s")
            
            with col3:
                st.metric("平均误差", f"{avg_error:.0f}ms")
        
        # 问题片段列表
        problem_segments = [seg for seg in confirmation_segments 
                          if not seg.confirmed or (seg.timing_error_ms and abs(seg.timing_error_ms) > 1000)]
        
        if problem_segments:
            st.markdown("### ⚠️ 需要注意的片段")
            
            for seg in problem_segments:
                with st.expander(f"片段 {seg.id} - {seg.quality or 'unknown'}"):
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.write(f"**状态:** {'✅ 已确认' if seg.confirmed else '❌ 未确认'}")
                        st.write(f"**时长误差:** {seg.timing_error_ms or 0:.0f}ms")
                        st.write(f"**文本:** {seg.get_current_text()[:100]}...")
                    
                    with col2:
                        st.write(f"**质量:** {self._get_quality_icon(seg.quality or 'unknown')} {seg.quality or 'unknown'}")
                        st.write(f"**用户修改:** {'是' if seg.user_modified else '否'}")
                        st.write(f"**时间:** {seg.start:.1f}s - {seg.end:.1f}s")