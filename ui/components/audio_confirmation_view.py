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
from translation.text_optimizer import TextOptimizer


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
        渲染音频确认界面 (极简设计)
        
        Args:
            optimized_segments: 优化后的片段
            confirmation_segments: 确认用的片段（包含音频）
            translated_original_segments: 翻译后的原始片段
            target_lang: 目标语言
            config: 配置信息
            
        Returns:
            包含action和数据的结果字典
        """
        # 确保segments按正确顺序排序（按start时间排序）
        if confirmation_segments:
            confirmation_segments.sort(key=lambda seg: (seg.start, seg.id))
            logger.debug(f"已对 {len(confirmation_segments)} 个确认片段按时间排序")
        
        # 显示总体统计 (极简版)
        self._display_overall_stats_minimal(confirmation_segments)
        
        # 当前片段详情
        if confirmation_segments:
            self._display_current_segment(confirmation_segments, target_lang)
        
        # 确认完成按钮
        return self._render_action_buttons(confirmation_segments, translated_original_segments, optimized_segments, target_lang)

    def _display_overall_stats_minimal(self, confirmation_segments: List[SegmentDTO]):
        """显示极简统计信息"""
        if not confirmation_segments:
            return
        
        total = len(confirmation_segments)
        confirmed = sum(1 for seg in confirmation_segments if seg.confirmed)
        avg_error = sum(seg.timing_error_ms or 0 for seg in confirmation_segments) / total
        
        st.caption(f"总片段: {total} | 已确认: {confirmed}/{total} | 平均误差: {avg_error:.0f}ms")
    
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
            # 计算带正负号的时长误差
            if current_segment.actual_duration and current_segment.target_duration:
                error_ms = (current_segment.actual_duration - current_segment.target_duration) * 1000
                if error_ms > 0:
                    error_display = f"+{error_ms:.0f}ms"
                    error_help = "音频比目标时长长（慢了）"
                elif error_ms < 0:
                    error_display = f"{error_ms:.0f}ms"
                    error_help = "音频比目标时长短（快了）"
                else:
                    error_display = "0ms"
                    error_help = "完美匹配目标时长"
            else:
                error_display = "N/A"
                error_help = "缺少时长数据"
            
            st.metric("时长误差", error_display, help=error_help)
        
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
            
            # 使用segment ID作为key，确保文本状态持久化
            text_key = f"text_edit_{current_segment.id}"
            
            # 获取当前应该显示的文本
            current_segment_text = current_segment.get_current_text()
            
            # 检查是否需要重置文本框（比如重新生成音频后）
            reset_key = f"reset_text_{current_segment.id}"
            should_reset = st.session_state.get(reset_key, False)
            
            if should_reset:
                # 清除重置标记和旧的文本状态
                if reset_key in st.session_state:
                    del st.session_state[reset_key]
                manual_text_key = f"manual_text_{current_segment.id}"
                if manual_text_key in st.session_state:
                    del st.session_state[manual_text_key]
                logger.debug(f"重置片段 {current_segment.id} 的文本输入框")
            
            # 使用不同的策略：不使用key参数，而是手动管理状态
            # 这样可以避免Streamlit的value/key冲突
            manual_text_key = f"manual_text_{current_segment.id}"
            
            # 获取当前文本框应该显示的内容
            if manual_text_key in st.session_state:
                display_text = st.session_state[manual_text_key]
            else:
                display_text = current_segment_text
                st.session_state[manual_text_key] = display_text
            
            # 创建文本输入框（不使用key参数）
            new_text = st.text_area(
                "优化翻译", 
                value=display_text,
                height=120, 
                label_visibility="collapsed",
                help="修改文本后点击「重新生成音频」按钮应用更改"
            )
            
            # 手动更新session_state
            if new_text != display_text:
                st.session_state[manual_text_key] = new_text
            
            # 确保new_text不为None
            if new_text is None:
                new_text = ""
            
            # 实时更新segment的final_text（但不影响用户正在编辑的文本）
            if new_text != current_segment.final_text:
                current_segment.update_final_text(new_text)
            
        # 语速控制组件 - 仅对支持语速调整的TTS服务显示（ElevenLabs不支持）
        selected_tts_service = st.session_state.get('selected_tts_service', 'minimax')
        if selected_tts_service != 'elevenlabs':
            self._display_speech_rate_control(current_segment, current_index)
        
        # 音频预览
        self._display_audio_preview(current_segment, current_index)
        
        # 操作按钮
        st.markdown("---")
        
        # 主操作：智能迭代优化
        # ElevenLabs不支持语速调整，按钮提示文字做区分
        selected_tts_for_button = st.session_state.get('selected_tts_service', 'minimax')
        if selected_tts_for_button == 'elevenlabs':
            optimize_help = "三轮迭代自动优化：生成→优化文本→选最优"
        else:
            optimize_help = "三轮迭代自动优化：生成→微调语速/优化文本→选最优"
        
        if st.button(
            "🚀 智能迭代优化",
            key=f"smart_optimize_{current_index}",
            type="primary",
            help=optimize_help,
            use_container_width=True
        ):
            self._smart_iterative_optimization(current_segment, target_lang, current_index)
        
        # 辅助操作
        col1, col2, col3 = st.columns(3)

        with col1:
            if st.button(
                "🔄 重新生成",
                key=f"regenerate_{current_index}",
                type="secondary",
                help="单次重新生成音频",
                use_container_width=True
            ):
                self._regenerate_segment_audio(current_segment, target_lang, current_index)

        with col2:
            if st.button(
                "📝 优化文本",
                key=f"optimize_text_{current_index}",
                type="secondary",
                help="单次优化文本长度",
                use_container_width=True
            ):
                self._optimize_segment_text(current_segment, target_lang, current_index)

        with col3:
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
                    # 重要：确认前检查音频数据
                    if current_segment.audio_data is None:
                        st.warning("⚠️ 该片段缺少音频数据，正在自动生成...")
                        logger.warning(f"片段 {current_segment.id} 缺少音频数据，自动生成中")
                        
                        # 自动生成音频数据
                        try:
                            self._regenerate_segment_audio(current_segment, target_lang, current_index)
                            if current_segment.audio_data is not None:
                                current_segment.confirmed = True
                                # 🔥 Stage 2: 上传确认音频
                                self._upload_confirmed_audio(current_segment)
                                st.success("✅ 音频已生成并确认片段！")
                            else:
                                st.error("❌ 音频生成失败，无法确认片段")
                                return  # 不执行后续的跳转逻辑
                        except Exception as e:
                            logger.error(f"自动生成音频失败: {e}")
                            st.error(f"❌ 自动生成音频失败: {str(e)}")
                            return  # 不执行后续的跳转逻辑
                    else:
                        # 音频数据存在，直接确认
                        current_segment.confirmed = True
                        # 🔥 Stage 2: 上传确认音频
                        self._upload_confirmed_audio(current_segment)
                        st.success("✅ 片段已确认！")
                    
                    # 智能跳转到下一个未确认的片段
                    total_segments = len(confirmation_segments)
                    next_unconfirmed_index = None
                    
                    # 从当前位置开始向后找未确认的片段
                    for i in range(current_index + 1, total_segments):
                        if not confirmation_segments[i].confirmed:
                            next_unconfirmed_index = i
                            break
                    
                    # 如果后面没有未确认的，从头开始找
                    if next_unconfirmed_index is None:
                        for i in range(0, current_index):
                            if not confirmation_segments[i].confirmed:
                                next_unconfirmed_index = i
                                break
                    
                    # 设置跳转目标
                    if next_unconfirmed_index is not None:
                        st.session_state.current_confirmation_index = next_unconfirmed_index
                        st.info(f"🎯 自动跳转到下一个未确认片段 {next_unconfirmed_index + 1}")
                    else:
                        # 所有片段都已确认，显示完成提示
                        st.success("🎉 所有片段都已确认完成！")
                        # 保持在当前位置
                    
                    st.rerun()
        
        # 页面导航控件
        st.markdown("---")
        # 醒目的导航按钮
        st.markdown("""
        <style>
        div[data-testid="stHorizontalBlock"] > div:has(button[key="prev_segment"]) button,
        div[data-testid="stHorizontalBlock"] > div:has(button[key="next_segment"]) button {
            font-size: 1.2rem !important;
            padding: 0.8rem 1.5rem !important;
            font-weight: 600 !important;
        }
        </style>
        """, unsafe_allow_html=True)
        
        nav_col1, nav_col2, nav_col3 = st.columns([1, 1, 1])
        
        with nav_col1:
            if st.button("⬅️ 上一个", disabled=current_index <= 0, key="prev_segment", use_container_width=True):
                st.session_state.current_confirmation_index = max(0, current_index - 1)
                st.rerun()
        
        with nav_col2:
            st.markdown(f"<h3 style='text-align:center; color:#666; margin:0; padding-top:6px;'>{current_index + 1} / {total_segments}</h3>", unsafe_allow_html=True)
        
        with nav_col3:
            if st.button("下一个 ➡️", disabled=current_index >= total_segments - 1, key="next_segment", use_container_width=True):
                st.session_state.current_confirmation_index = min(total_segments - 1, current_index + 1)
                st.rerun()

    
    def _display_speech_rate_control(self, segment: "SegmentDTO", segment_index: int):
        """精简的语速控制UI"""
        
        current_rate: float = segment.speech_rate or 1.0
        slider_key = f"user_speech_rate_{segment_index}"
        
        # 检查是否需要重置语速（智能迭代优化后）
        reset_rate_key = f"reset_rate_{segment_index}"
        suggested_rate_key = f"suggested_rate_{segment_index}"
        
        if st.session_state.get(reset_rate_key, False):
            # 清除重置标记
            del st.session_state[reset_rate_key]
            # 删除旧的slider key让它重新初始化
            if slider_key in st.session_state:
                del st.session_state[slider_key]
            # 获取新语速值
            new_rate = st.session_state.get(suggested_rate_key, current_rate)
            st.session_state[slider_key] = new_rate
            if suggested_rate_key in st.session_state:
                del st.session_state[suggested_rate_key]
        
        # 初始化语速状态
        if slider_key not in st.session_state:
            st.session_state[slider_key] = current_rate
        
        # 单行紧凑布局
        col1, col2 = st.columns([1, 3])

        with col1:
            st.caption(f"当前: {current_rate:.2f}x")

        with col2:
            st.slider(
                "语速调节",
                min_value=0.95,
                max_value=1.15,
                step=0.01,
                key=slider_key,
                label_visibility="collapsed"
            )
    
    
    def _display_audio_preview(self, segment: SegmentDTO, segment_index: int):
        """显示音频预览"""
        st.markdown("### 🎵 音频预览")
        
        # 调试：显示片段的音频状态
        has_audio_data = segment.audio_data is not None
        has_audio_path = bool(segment.audio_path)
        logger.debug(f"_display_audio_preview: 片段 {segment.id}, audio_data={has_audio_data}, audio_path={has_audio_path}, path={segment.audio_path}")
        
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
        
        # 🔥 优先使用内存中的音频数据
        if segment.audio_data is not None:
            try:
                import tempfile
                import os
                from utils.windows_audio_utils import get_windows_audio_utils, is_windows
                
                # 使用Windows音频工具进行优化处理
                if is_windows():
                    # Windows系统使用专用工具
                    windows_utils = get_windows_audio_utils()
                    tmp_path = windows_utils.create_temp_audio_path("preview", segment.id, ext="mp3")
                    
                    # 安全导出音频文件（MP3 格式，体积更小）
                    if windows_utils.safe_export_audio(segment.audio_data, tmp_path, format='mp3'):
                        # 读取音频文件内容
                        with open(tmp_path, 'rb') as audio_file:
                            audio_bytes = audio_file.read()
                        
                        # 显示音频播放器
                        st.audio(audio_bytes, format='audio/mpeg')
                        
                        # 安全清理临时文件
                        windows_utils.safe_cleanup_file(tmp_path)
                        
                    else:
                        raise Exception("Windows音频文件导出失败")
                
                else:
                    # 非Windows系统使用原有逻辑（改用 MP3 格式）
                    with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as tmp_file:
                        # 导出音频到临时文件（MP3 格式，体积更小）
                        segment.audio_data.export(tmp_file.name, format='mp3', bitrate='128k')
                        tmp_path = tmp_file.name
                    
                    # 显示音频播放器
                    with open(tmp_path, 'rb') as audio_file:
                        audio_bytes = audio_file.read()
                        st.audio(audio_bytes, format='audio/mpeg')
                    
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
                    st.write("3. 检查临时目录权限（Windows系统）")
                    st.write("4. 重启应用程序清理文件锁定")
                    st.write("5. 联系技术支持")
                    
        else:
            # 🔥 尝试从 Firebase Storage URL 流式播放（无需下载完整数据）
            audio_url = self._get_audio_stream_url(segment)
            if audio_url:
                st.audio(audio_url, format='audio/mpeg')
                st.caption("🌐 从云端流式播放")
            else:
                st.warning("⚠️ 音频数据不可用，请点击「重新生成」按钮生成音频")
    
    def _get_audio_stream_url(self, segment: SegmentDTO) -> str:
        """
        获取音频流式播放 URL（从 Firebase Storage）
        
        路径来源优先级：
        1. segment.audio_path（在 _restore_audio_from_storage 中设置的）
        2. project.audio_storage_paths 中的已确认路径
        3. project.audio_storage_paths 中的预览路径
        4. 🔥 智能回退：尝试构建预期路径并直接检查 Storage
        
        Args:
            segment: 片段对象
            
        Returns:
            音频 URL，不可用时返回空字符串
        """
        try:
            current_project = st.session_state.get('current_project')
            if not current_project:
                return ""
            
            # 检查是否使用 Firebase 存储后端
            if getattr(current_project, 'storage_backend', 'local') != 'firebase':
                return ""
            
            # 🔥 优先使用 segment 上已设置的 audio_path
            storage_path = segment.audio_path if segment.audio_path else None
            
            # 如果 segment 没有设置路径，从项目的 audio_storage_paths 查找
            if not storage_path:
                audio_paths = getattr(current_project, 'audio_storage_paths', {})
                if audio_paths:
                    # 优先使用已确认的音频路径，其次使用预览路径
                    storage_path = audio_paths.get(segment.id) or audio_paths.get(f"{segment.id}_preview")
            
            # 获取 Firebase Storage 管理器
            from utils.firebase_storage import get_storage_manager
            storage = get_storage_manager()
            if not storage.is_connected:
                return ""
            
            # 🔥 智能回退：如果没有保存的路径，尝试构建预期路径并直接检查
            if not storage_path:
                user_id = getattr(current_project, 'owner_id', '')
                project_id = getattr(current_project, 'id', '')
                if user_id and project_id:
                    # 尝试可能的路径格式（与 _get_staged_audio_path 一致）
                    # 格式: users/{user_id}/projects/{project_id}/audio/{stage}/{segment_id}.mp3
                    possible_paths = [
                        f"users/{user_id}/projects/{project_id}/audio/confirmed/{segment.id}.mp3",
                        f"users/{user_id}/projects/{project_id}/audio/preview/{segment.id}.mp3",
                        f"users/{user_id}/projects/{project_id}/audio/{segment.id}.mp3",
                    ]
                    for path in possible_paths:
                        try:
                            blob = storage.bucket.blob(path)
                            if blob.exists():
                                storage_path = path
                                # 找到了，保存到项目中供下次使用
                                current_project.update_audio_storage_path(segment.id, path)
                                logger.info(f"片段 {segment.id} 智能发现音频: {path}")
                                break
                        except Exception:
                            continue
            
            if not storage_path:
                logger.debug(f"片段 {segment.id} 没有可用的音频路径")
                return ""
            
            # 🔥 兼容性处理：检查文件是否存在，如果不存在尝试转换旧格式路径
            # 旧格式: users/{user_id}/projects/{project_id}/audio/segments/{segment_id}/preview.mp3
            # 新格式: users/{user_id}/projects/{project_id}/audio/preview/{segment_id}.mp3
            if '/audio/segments/' in storage_path:
                # 检查旧格式路径文件是否存在
                blob = storage.bucket.blob(storage_path)
                if not blob.exists():
                    # 尝试转换成新格式
                    import re
                    # 提取路径组件
                    match = re.match(r'(.*/audio)/segments/([^/]+)/(preview|confirmed)\.mp3', storage_path)
                    if match:
                        base_path = match.group(1)  # users/.../audio
                        segment_id = match.group(2)  # seg_1
                        stage = match.group(3)  # preview 或 confirmed
                        new_path = f"{base_path}/{stage}/{segment_id}.mp3"
                        logger.debug(f"片段 {segment.id} 路径兼容转换: {storage_path} -> {new_path}")
                        # 检查新格式路径是否存在
                        new_blob = storage.bucket.blob(new_path)
                        if new_blob.exists():
                            storage_path = new_path
                            # 更新项目中的路径映射为正确格式
                            current_project.update_audio_storage_path(segment.id, new_path)
                            segment.audio_path = new_path
            
            # 获取临时下载 URL（有效期 1 小时）
            url = storage.get_download_url(storage_path, expiration=3600)
            if url:
                logger.debug(f"片段 {segment.id} 音频 URL 获取成功")
            return url or ""
            
        except Exception as e:
            logger.error(f"获取音频 URL 失败 [{segment.id}]: {e}")
            return ""
    
    def _upload_confirmed_audio(self, segment: SegmentDTO):
        """
        Stage 2: 异步上传确认音频到 Firebase Storage，并删除预览音频
        
        当用户点击"确认此片段"后调用，将确认版本的音频异步上传，替换预览版本
        不阻塞主线程，提升用户体验
        
        Args:
            segment: 确认的片段
        """
        try:
            # 获取当前项目信息
            current_project = st.session_state.get('current_project')
            if not current_project:
                logger.debug("无项目信息，跳过确认音频上传")
                return
            
            # 检查是否使用 Firebase 存储后端
            if getattr(current_project, 'storage_backend', 'local') != 'firebase':
                logger.debug("非 Firebase 存储后端，跳过确认音频上传")
                return
            
            user_id = getattr(current_project, 'owner_id', '')
            project_id = getattr(current_project, 'id', '')
            
            if not user_id or not project_id:
                logger.warning("缺少用户 ID 或项目 ID，跳过确认音频上传")
                return
            
            if segment.audio_data is None:
                logger.warning(f"片段 {segment.id} 没有音频数据，跳过上传")
                return
            
            from utils.firebase_storage import get_storage_manager
            from utils.async_upload_manager import get_upload_manager
            
            storage = get_storage_manager()
            if not storage.is_connected:
                logger.warning("Firebase Storage 未连接，跳过确认音频上传")
                return
            
            # 使用异步上传管理器
            upload_manager = get_upload_manager()
            
            # 定义上传完成回调
            segment_id = segment.id
            def on_upload_complete(task_id: str, result_path: str, error: str):
                if error:
                    logger.warning(f"确认音频上传失败 [{segment_id}]: {error}")
                    return
                
                if result_path:
                    logger.info(f"片段 {segment_id} Stage 2 确认音频上传成功: {result_path}")
            
            # 提交异步上传任务（会自动删除预览版本）
            upload_manager.submit_confirmed_upload(
                user_id=user_id,
                project_id=project_id,
                segment_id=segment.id,
                audio_data=segment.audio_data,
                callback=on_upload_complete
            )
            
            # 预先更新项目的音频路径映射（异步上传完成后实际路径一致）
            # 路径格式: users/{user_id}/projects/{project_id}/audio/confirmed/{segment_id}.mp3
            expected_path = f"users/{user_id}/projects/{project_id}/audio/confirmed/{segment.id}.mp3"
            current_project.update_audio_storage_path(segment.id, expected_path)
            
            # 删除预览路径记录
            if hasattr(current_project, 'audio_storage_paths'):
                preview_key = f"{segment.id}_preview"
                if preview_key in current_project.audio_storage_paths:
                    del current_project.audio_storage_paths[preview_key]
            
            logger.debug(f"片段 {segment.id} 确认音频已提交到异步上传队列")
            
            # 🔥 重要：保存项目以持久化 audio_storage_paths
            try:
                from utils.project_integration import get_project_integration
                user_id_for_save = st.session_state.get('auth_username', 'default_user')
                project_integration = get_project_integration(user_id=user_id_for_save)
                project_integration.save_project_state(current_project, st.session_state)
                logger.debug(f"已保存确认音频路径: {segment.id}")
            except Exception as save_err:
                logger.warning(f"保存确认音频路径时出错: {save_err}")
                
        except Exception as e:
            logger.error(f"上传确认音频失败: {e}")

    
    def _regenerate_segment_audio(self, segment: SegmentDTO, target_lang: str, segment_index: int):
        """单次重新生成片段音频"""
        try:
            from tts import create_tts_engine
            
            selected_tts_service = st.session_state.get('selected_tts_service', 'minimax')
            selected_voice_id = st.session_state.get('selected_voice_id')
            config = st.session_state.get('config', {})
            
            tts = st.session_state.get('tts_instance')
            current_service = st.session_state.get('current_tts_service')
            
            if not tts or current_service != selected_tts_service:
                tts = create_tts_engine(config, selected_tts_service)
                st.session_state['tts_instance'] = tts
                st.session_state['current_tts_service'] = selected_tts_service
            
            if selected_voice_id:
                tts.set_voice(selected_voice_id)
            
            manual_text_key = f"manual_text_{segment.id}"
            current_text = st.session_state.get(manual_text_key, segment.get_current_text())
            
            if not current_text.strip():
                st.error("❌ 文本内容为空")
                return
            
            # ElevenLabs不支持语速调整，固定使用1.0
            if selected_tts_service == 'elevenlabs':
                user_rate = 1.0
            else:
                user_rate_key = f"user_speech_rate_{segment_index}"
                user_rate = st.session_state.get(user_rate_key, segment.speech_rate or 1.0)
            
            with st.spinner("🔄 正在生成音频..."):
                if selected_tts_service == 'elevenlabs' and selected_voice_id:
                    voice_name = selected_voice_id
                else:
                    voice_name = tts.voice_map.get(target_lang) if hasattr(tts, 'voice_map') else None
                    if isinstance(voice_name, dict):
                        voice_name = list(voice_name.keys())[0] if voice_name else None
                
                if not voice_name:
                    st.error(f"❌ 未配置语言 {target_lang} 的音色")
                    return
                
                target_duration = segment.target_duration
                new_audio_data = tts._generate_single_audio(
                    current_text, voice_name, user_rate, target_duration
                )
                
                segment.set_audio_data(new_audio_data)
                segment.speech_rate = user_rate
                segment.update_final_text(current_text)
                
                reset_key = f"reset_text_{segment.id}"
                st.session_state[reset_key] = True
                
                if segment.actual_duration:
                    segment.timing_error_ms = abs(segment.actual_duration - segment.target_duration) * 1000
                
                sync_ratio = segment.sync_ratio
                if sync_ratio >= 0.95 and sync_ratio <= 1.05:
                    segment.quality = 'excellent'
                elif sync_ratio >= 0.85 and sync_ratio <= 1.15:
                    segment.quality = 'good'
                elif sync_ratio >= 0.75 and sync_ratio <= 1.25:
                    segment.quality = 'fair'
                else:
                    segment.quality = 'poor'
                
                if current_text != segment.optimized_text:
                    segment.user_modified = True
                
                error_ms = segment.timing_error_ms or 0
                st.success(f"✅ 生成成功！误差: {error_ms:.0f}ms")
                st.rerun()
                
        except Exception as e:
            logger.error(f"重新生成音频失败: {e}")
            st.error(f"❌ 生成失败: {str(e)}")
    
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
    
    def _optimize_segment_text(self, segment: SegmentDTO, target_lang: str, segment_index: int):
        """使用LLM单次优化片段文本以匹配目标时长"""
        try:
            # 检查是否有足够的数据进行优化
            if not segment.actual_duration or not segment.target_duration:
                st.warning("⚠️ 缺少时长数据，无法进行智能优化。请先生成音频。")
                return
            
            # 计算时长差距
            duration_diff = segment.actual_duration - segment.target_duration
            duration_diff_ms = abs(duration_diff) * 1000
            
            # 如果差距很小，不需要优化
            if duration_diff_ms < 100:
                st.info("✅ 当前时长已经很接近目标时长，无需优化")
                return
            
            # 获取配置
            config = st.session_state.get('config', {})
            if not config:
                st.error("❌ 配置信息不可用")
                return
            
            # 显示优化进度
            with st.spinner(f"🎯 正在优化文本（目标{'缩短' if duration_diff > 0 else '延长'}{duration_diff_ms:.0f}ms）..."):
                # 创建文本优化器
                optimizer = TextOptimizer(config)
                
                # 获取当前文本
                manual_text_key = f"manual_text_{segment.id}"
                current_text = st.session_state.get(manual_text_key, segment.get_current_text())
                
                # 获取原始文本
                original_text = segment.original_text or segment.translated_text or current_text
                
                # 单次调用优化器（用户主动点击时强制优化）
                optimized_text = optimizer.optimize_text_for_duration(
                    original_text=original_text,
                    current_text=current_text,
                    target_duration=segment.target_duration,
                    actual_duration=segment.actual_duration,
                    target_language=target_lang,
                    original_language='zh',
                    force=True  # 用户主动点击，强制尝试优化
                )
                
                if optimized_text and optimized_text != current_text:
                    # 更新文本框内容
                    st.session_state[manual_text_key] = optimized_text
                    
                    # 更新segment的文本
                    segment.update_final_text(optimized_text)
                    
                    # 标记为用户修改
                    segment.user_modified = True
                    
                    # 计算文本变化统计
                    original_words = len(current_text.split()) if current_text else 0
                    optimized_words = len(optimized_text.split()) if optimized_text else 0
                    word_diff = optimized_words - original_words
                    
                    action_desc = "增加" if word_diff > 0 else "减少"
                    word_diff_abs = abs(word_diff)
                    
                    st.success(f"✅ 文本优化成功！{action_desc}了{word_diff_abs}个词")
                    st.info("💡 请点击「重新生成音频」应用更改")
                    st.rerun()
                    
                elif optimized_text == current_text:
                    # LLM认为当前文本无需修改
                    duration_diff_ms = (segment.actual_duration - segment.target_duration) * 1000
                    st.warning(f"⚠️ AI未能优化文本（时长差{duration_diff_ms:+.0f}ms），您可尝试手动调整")
                else:
                    st.error("❌ 文本优化失败")
                    
        except Exception as e:
            logger.error(f"文本优化失败: {e}")
            st.error(f"❌ 文本优化失败: {str(e)}")
    
    def _smart_iterative_optimization(self, segment: SegmentDTO, target_lang: str, segment_index: int):
        """
        智能迭代优化：使用公共迭代优化器进行三轮迭代自动优化时长匹配
        """
        from tts import create_tts_engine
        from utils.audio_iteration_optimizer import AudioIterationOptimizer
        
        try:
            # 获取TTS实例
            selected_tts_service = st.session_state.get('selected_tts_service', 'minimax')
            selected_voice_id = st.session_state.get('selected_voice_id')
            config = st.session_state.get('config', {})
            
            tts = st.session_state.get('tts_instance')
            current_service = st.session_state.get('current_tts_service')
            
            if not tts or current_service != selected_tts_service:
                tts = create_tts_engine(config, selected_tts_service)
                st.session_state['tts_instance'] = tts
                st.session_state['current_tts_service'] = selected_tts_service
            
            if selected_voice_id:
                tts.set_voice(selected_voice_id)
            
            # 获取音色
            if selected_tts_service == 'elevenlabs' and selected_voice_id:
                voice_name = selected_voice_id
            else:
                voice_name = tts.voice_map.get(target_lang) if hasattr(tts, 'voice_map') else None
                if isinstance(voice_name, dict):
                    voice_name = list(voice_name.keys())[0] if voice_name else None
            
            if not voice_name:
                st.error(f"❌ 未配置语言 {target_lang} 的音色")
                return
            
            # 获取当前文本和语速
            manual_text_key = f"manual_text_{segment.id}"
            current_text = st.session_state.get(manual_text_key, segment.get_current_text())
            target_duration = segment.target_duration
            
            # ElevenLabs不支持语速调整，固定使用1.0
            supports_speech_rate = selected_tts_service != 'elevenlabs'
            if supports_speech_rate:
                user_rate_key = f"user_speech_rate_{segment_index}"
                initial_rate = st.session_state.get(user_rate_key, segment.speech_rate or 1.0)
            else:
                initial_rate = 1.0
            
            original_text = segment.original_text or segment.translated_text or current_text
            
            progress_container = st.container()
            
            # 检查是否已有音频数据，如果有则检查是否已达标
            if segment.audio_data is not None and segment.actual_duration is not None:
                existing_duration = segment.actual_duration
                existing_error_ms = (existing_duration - target_duration) * 1000
                
                with progress_container:
                    error_sign = "+" if existing_error_ms > 0 else ""
                    if supports_speech_rate:
                        st.markdown(f"""
**当前状态** 📊  
- 实际时长: **{existing_duration:.2f}s** | 目标: {target_duration:.2f}s  
- 误差: **{error_sign}{existing_error_ms:.0f}ms** | 语速: {initial_rate:.2f}x
                        """)
                    else:
                        st.markdown(f"""
**当前状态** 📊  
- 实际时长: **{existing_duration:.2f}s** | 目标: {target_duration:.2f}s  
- 误差: **{error_sign}{existing_error_ms:.0f}ms**
                        """)
                
                # 检查现有数据是否已达标
                if -150 <= existing_error_ms <= 0:
                    st.success(f"✅ 当前已达标！实际时长 {existing_duration:.2f}s（短于目标 {abs(existing_error_ms):.0f}ms）")
                    return
            
            # 创建文本优化器和迭代优化器
            text_optimizer = TextOptimizer(config)
            iteration_optimizer = AudioIterationOptimizer(
                tts_engine=tts,
                text_optimizer=text_optimizer,
                supports_speech_rate=supports_speech_rate
            )
            
            # 显示优化进度的回调函数
            def progress_callback(iteration: int, message: str):
                with progress_container:
                    st.info(f"🔄 **第 {iteration}/3 轮** | 目标: {target_duration:.2f}s | {message} | 生成中...")
            
            # 使用迭代优化器进行优化
            with st.spinner("智能优化中..."):
                result = iteration_optimizer.optimize_segment(
                    text=current_text,
                    original_text=original_text,
                    voice_name=voice_name,
                    target_duration=target_duration,
                    target_language=target_lang,
                    initial_speech_rate=initial_rate,
                    source_language='zh',
                    progress_callback=progress_callback
                )
            
            if not result['success'] or not result['best_result']:
                st.error("❌ 优化失败：未能生成有效的音频")
                return
            
            best = result['best_result']
            all_results = result['all_results']
            
            # 应用最优结果
            segment.set_audio_data(best.audio_data)
            segment.speech_rate = best.speech_rate
            segment.update_final_text(best.text)
            
            # 更新UI状态
            st.session_state[manual_text_key] = best.text
            
            # 语速使用重置机制（仅对支持语速的TTS）
            if supports_speech_rate:
                reset_rate_key = f"reset_rate_{segment_index}"
                suggested_rate_key = f"suggested_rate_{segment_index}"
                st.session_state[reset_rate_key] = True
                st.session_state[suggested_rate_key] = best.speech_rate
            
            # 设置文本重置标记
            reset_key = f"reset_text_{segment.id}"
            st.session_state[reset_key] = True
            
            # 更新时长和质量信息
            if segment.actual_duration:
                segment.timing_error_ms = abs(segment.actual_duration - segment.target_duration) * 1000
            
            sync_ratio = segment.sync_ratio
            if sync_ratio >= 0.95 and sync_ratio <= 1.05:
                segment.quality = 'excellent'
            elif sync_ratio >= 0.85 and sync_ratio <= 1.15:
                segment.quality = 'good'
            elif sync_ratio >= 0.75 and sync_ratio <= 1.25:
                segment.quality = 'fair'
            else:
                segment.quality = 'poor'
            
            # 显示结果
            if supports_speech_rate:
                st.success(f"✅ 智能优化完成！第{best.iteration}轮 | 误差: {best.error_ms:.0f}ms | 语速: {best.speech_rate:.2f}x")
            else:
                st.success(f"✅ 智能优化完成！第{best.iteration}轮 | 误差: {best.error_ms:.0f}ms")
            
            # 显示迭代详情
            with st.expander("📊 迭代详情", expanded=False):
                for r in all_results:
                    status = "✅" if r == best else "⚪"
                    if supports_speech_rate:
                        st.caption(f"{status} 第{r.iteration}轮: 误差={r.error_ms:.0f}ms ({r.error_percentage:.1f}%), 语速={r.speech_rate:.2f}x")
                    else:
                        st.caption(f"{status} 第{r.iteration}轮: 误差={r.error_ms:.0f}ms ({r.error_percentage:.1f}%)")
            
            st.rerun()
            
        except Exception as e:
            logger.error(f"智能迭代优化失败: {e}")
            st.error(f"❌ 智能迭代优化失败: {str(e)}")
    
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