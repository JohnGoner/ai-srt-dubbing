"""
翻译验证界面模块
提供翻译结果验证、时长分析和用户确认功能
"""

import streamlit as st
from typing import List, Dict, Any, Callable
from loguru import logger
import tempfile
import os


class TranslationValidationInterface:
    """
    一个Streamlit界面，用于让用户审校和调整需要人工干预的翻译片段。
    """
    
    def __init__(self, segments_to_validate: List[Dict], callback: Callable[[Dict], None]):
        """
        初始化翻译验证界面。
        
        Args:
            segments_to_validate: 需要用户审校的片段列表。
            callback: 用户确认所有修改后要调用的回调函数。
                      回调函数将接收一个字典，包含所有片段的最终调整选择。
        """
        self.segments = segments_to_validate
        self.callback = callback
        
        if 'user_adjustments' not in st.session_state:
            st.session_state.user_adjustments = {}
        
        # 为每个片段的UI组件生成唯一的key
        self._keys = {
            seg['id']: {
                "text_area": f"text_area_{seg['id']}",
                "speed_slider": f"speed_slider_{seg['id']}",
                "form": f"form_{seg['id']}"
            }
            for seg in self.segments
        }

    def display(self):
        """
        渲染整个验证界面。
        """
        st.header("翻译结果人工审校")
        st.info(
            "以下片段的预估时长与目标差异较大，可能影响最终配音效果。"
            "请根据建议审校并调整，或直接确认以使用优化后的最佳参数。"
        )
        
        # 添加操作按钮区域
        st.markdown("---")
        col1, col2, col3 = st.columns([1, 1, 1])
        
        with col1:
            if st.button("🔙 返回上一步", use_container_width=True, key="back_to_previous"):
                # 返回到语言选择阶段
                st.session_state.processing_stage = 'language_selection'
                st.rerun()
        
        with col2:
            if st.button("🔄 重新LLM翻译", use_container_width=True, key="retranslate"):
                # 清除翻译缓存，重新进行翻译
                self._retranslate_segments()
        
        with col3:
            if st.button("📊 查看验证报告", use_container_width=True, key="view_validation_report"):
                self._show_validation_report()
        
        st.markdown("---")
        
        if not self.segments:
            st.success("所有片段均已自动通过验证，无需人工干预。")
            return
        
        for segment in self.segments:
            self._display_segment_editor(segment)

        if st.button("全部确认，生成最终音频", key="confirm_all_button"):
            self._finalize_and_callback()
            
    def _display_segment_editor(self, segment: Dict[str, Any]):
        """
        为单个片段渲染一个编辑区域。
        """
        seg_id = segment['id']
        keys = self._keys[seg_id]

        with st.form(key=keys['form']):
            st.subheader(f"片段 #{seg_id}")

            col1, col2, col3 = st.columns(3)
            col1.metric("目标时长", f"{segment['target_duration']:.2f}s")
            col2.metric("实际时长", f"{segment['actual_duration']:.2f}s", delta=f"{segment['timing_analysis']['timing_error_ms']/1000:.2f}s")
            col3.metric("当前语速", f"{segment['speech_rate']:.2f}x")
            
            st.markdown("**调整建议:**")
            for suggestion in segment['adjustment_suggestions']:
                st.warning(f"- {suggestion['description']}")
            
            # 从session_state或原始数据初始化
            initial_text = st.session_state.user_adjustments.get(seg_id, {}).get('text', segment['optimized_text'])
            initial_speed = st.session_state.user_adjustments.get(seg_id, {}).get('speed', segment['speech_rate'])

            edited_text = st.text_area(
                "编辑译文:",
                value=initial_text,
                key=keys['text_area'],
                height=100
            )

            speech_rate = st.slider(
                "调整语速:",
                min_value=0.85,
                max_value=1.15,
                value=initial_speed,
                step=0.01,
                key=keys['speed_slider']
            )
            
            submitted = st.form_submit_button("确认此片段的修改")
            if submitted and edited_text is not None:
                self._save_adjustment(seg_id, edited_text, speech_rate)
                st.success(f"片段 #{seg_id} 的修改已保存。")

    def _save_adjustment(self, seg_id: int, text: str, speed: float):
        """
        将单一片段的修改保存到 session_state。
        """
        st.session_state.user_adjustments[seg_id] = {
            'type': 'manual_adjustment',
            'final_text': text,
            'speech_rate': speed
        }
        logger.info(f"用户保存了片段 #{seg_id} 的调整: 语速={speed:.2f}, 文本='{text[:50]}...'")

    def _finalize_and_callback(self):
        """
        处理所有片段的最终确认并触发回调。
        """
        final_choices = {}
        for segment in self.segments:
            seg_id = segment['id']
            if seg_id in st.session_state.user_adjustments:
                final_choices[seg_id] = st.session_state.user_adjustments[seg_id]
            else:
                # 如果用户未动过此片段，则使用默认的最佳参数
                final_choices[seg_id] = {
                    'type': 'auto_adjustment',
                    'final_text': segment['optimized_text'],
                    'speech_rate': segment['speech_rate']
                }
        
        st.success("所有修改已确认！正在进入下一步...")
        logger.info("用户已完成所有片段的审校。")
        self.callback(final_choices)

    def _retranslate_segments(self):
        """
        重新进行LLM翻译
        """
        try:
            st.info("🔄 正在重新翻译...")
            
            # 清除翻译缓存
            from utils.cache_manager import get_cache_manager
            cache_manager = get_cache_manager()
            
            # 清除翻译相关的缓存
            cache_manager.clear_cache("translation")
            cache_manager.clear_cache("translation_confirmed")
            st.success("✅ 翻译缓存已清除")
            
            # 清除相关的session state数据
            if 'translated_segments' in st.session_state:
                del st.session_state.translated_segments
            if 'validated_segments' in st.session_state:
                del st.session_state.validated_segments
            if 'segments_for_review' in st.session_state:
                del st.session_state.segments_for_review
            if 'user_adjustments' in st.session_state:
                del st.session_state.user_adjustments
            if 'final_segments_for_tts' in st.session_state:
                del st.session_state.final_segments_for_tts
            if 'optimized_segments' in st.session_state:
                del st.session_state.optimized_segments
            if 'confirmation_segments' in st.session_state:
                del st.session_state.confirmation_segments
            if 'translated_original_segments' in st.session_state:
                del st.session_state.translated_original_segments
            
            # 返回到翻译阶段
            st.session_state.processing_stage = 'translating'
            st.rerun()
            
        except Exception as e:
            st.error(f"重新翻译失败: {str(e)}")
            logger.error(f"重新翻译时发生错误: {e}")
    
    def _show_validation_report(self):
        """
        显示验证报告
        """
        try:
            from timing.sync_manager import PreciseSyncManager
            
            # 获取所有验证片段（包括自动通过的和需要人工确认的）
            all_validated_segments = st.session_state.get('validated_segments', [])
            
            if all_validated_segments:
                sync_manager = PreciseSyncManager({})
                report = sync_manager.create_final_report(all_validated_segments)
                
                st.markdown("### 📊 翻译验证报告")
                st.text(report)
                
                # 显示问题片段
                problematic_segments = [seg for seg in all_validated_segments if seg.get('needs_user_confirmation', False)]
                if problematic_segments:
                    st.markdown("#### ⚠️ 需要确认的片段")
                    for segment in problematic_segments:
                        st.warning(f"片段 {segment.get('id', 'unknown')}: {segment.get('optimized_text', '')[:50]}...")
                        if segment.get('timing_analysis'):
                            analysis = segment['timing_analysis']
                            st.caption(f"质量: {segment.get('quality', 'unknown')}, 误差: {analysis.get('timing_error_ms', 0):.0f}ms, 语速: {segment.get('speech_rate', 1.0):.2f}")
            else:
                st.warning("暂无验证数据")
                
        except Exception as e:
            st.error(f"生成验证报告失败: {str(e)}")
            logger.error(f"生成验证报告时发生错误: {e}")


def create_validation_workflow(validated_segments: List[Dict], config: dict, 
                             tts, target_language: str, progress_callback=None):
    """
    创建验证工作流
    
    Args:
        validated_segments: 验证后的片段列表
        config: 配置字典
        tts: TTS实例
        target_language: 目标语言
        progress_callback: 进度回调函数
        
    Returns:
        用户确认后的片段列表和调整选择
    """
    interface = TranslationValidationInterface(validated_segments, progress_callback if progress_callback else lambda x: None)
    
    if progress_callback:
        progress_callback(0, 1, "显示验证界面")
    
    # 显示验证界面
    interface.display()
    
    if progress_callback:
        progress_callback(1, 1, "验证完成")
    
    return validated_segments, st.session_state.user_adjustments 