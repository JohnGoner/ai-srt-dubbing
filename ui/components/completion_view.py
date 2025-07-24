"""
完成视图组件
纯组件，不直接操作session_state
"""

import streamlit as st
from typing import Dict, Any, List


class CompletionView:
    """完成视图组件"""
    
    def render(self, completion_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        渲染完成界面
        
        Args:
            completion_data: 完成数据
            
        Returns:
            包含action和数据的结果字典
        """
        # 🎉 成功消息
        st.balloons()
        st.markdown("## 🎉 配音生成成功！")
        
        # 下载区域
        st.markdown("### 📥 下载文件")
        col1, col2 = st.columns(2)
        
        with col1:
            st.download_button(
                label="🎵 下载配音音频",
                data=completion_data['audio_data'],
                file_name=f"dubbed_audio_{completion_data['target_lang']}.wav",
                mime="audio/wav",
                use_container_width=True,
                help="下载生成的配音音频文件"
            )
        
        with col2:
            st.download_button(
                label="📄 下载翻译字幕",
                data=completion_data['subtitle_data'],
                file_name=f"translated_subtitle_{completion_data['target_lang']}.srt",
                mime="text/plain",
                use_container_width=True,
                help="下载翻译后的字幕文件"
            )
        
        # 音频播放器
        st.markdown("### 🎵 在线试听")
        st.audio(completion_data['audio_data'], format='audio/wav')
        
        # 统计信息 - 从实际数据计算
        self._show_enhanced_statistics(completion_data)
        
        # 成本报告
        self._show_cost_report(completion_data)
        
        # 操作按钮
        return self._render_action_buttons()
    
    def _show_enhanced_statistics(self, completion_data: Dict[str, Any]):
        """显示增强的统计信息 - 从实际数据计算"""
        st.markdown("### 📊 处理统计")
        
        # 从实际的optimized_segments数据中计算统计信息
        optimized_segments = completion_data.get('optimized_segments', [])
        
        if not optimized_segments:
            st.warning("⚠️ 没有找到处理数据，显示基础统计信息")
            # 回退到原有的stats数据
            stats = completion_data.get('stats', {})
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.metric("字幕片段", stats.get('total_segments', 0))
            
            with col2:
                st.metric("总时长", f"{stats.get('total_duration', 0):.1f}秒")
            
            with col3:
                st.metric("优秀同步", stats.get('excellent_sync', 0))
            return
        
        # 从实际数据计算详细统计信息
        total_segments = len(optimized_segments)
        
        # 计算总时长
        total_duration = 0
        if isinstance(optimized_segments[0], dict):
            # legacy格式
            total_duration = max((seg.get('end', 0) for seg in optimized_segments), default=0)
        else:
            # 可能是其他格式，尝试不同的字段名
            for seg in optimized_segments:
                if hasattr(seg, 'end'):
                    total_duration = max(total_duration, seg.end)
                elif isinstance(seg, dict) and 'end' in seg:
                    total_duration = max(total_duration, seg['end'])
        
        # 计算质量分布
        quality_stats = {'excellent': 0, 'good': 0, 'fair': 0, 'poor': 0, 'error': 0}
        timing_errors = []
        
        for seg in optimized_segments:
            # 获取质量信息
            quality = None
            timing_error = None
            
            if isinstance(seg, dict):
                quality = seg.get('quality', seg.get('final_quality', 'unknown'))
                timing_error = seg.get('timing_error_ms', seg.get('final_timing_error_ms', 0))
            else:
                # 如果是对象，尝试获取属性
                quality = getattr(seg, 'quality', getattr(seg, 'final_quality', 'unknown'))
                timing_error = getattr(seg, 'timing_error_ms', getattr(seg, 'final_timing_error_ms', 0))
            
            # 统计质量分布
            if quality in quality_stats:
                quality_stats[quality] += 1
            elif quality == 'unknown':
                # 如果质量未知，根据时长误差推算
                if timing_error is not None and timing_error != 0:
                    error_percentage = abs(timing_error) / 1000.0  # 转换为秒
                    target_duration = 5.0  # 假设平均目标时长
                    
                    if isinstance(seg, dict):
                        target_duration = seg.get('target_duration', seg.get('duration', 5.0))
                    else:
                        target_duration = getattr(seg, 'target_duration', getattr(seg, 'duration', 5.0))
                    
                    if target_duration > 0:
                        error_ratio = error_percentage / target_duration
                        if error_ratio < 0.05:  # 误差小于5%
                            quality_stats['excellent'] += 1
                        elif error_ratio < 0.15:  # 误差小于15%
                            quality_stats['good'] += 1
                        elif error_ratio < 0.25:  # 误差小于25%
                            quality_stats['fair'] += 1
                        else:
                            quality_stats['poor'] += 1
                    else:
                        quality_stats['fair'] += 1
                else:
                    quality_stats['fair'] += 1
            
            # 收集时长误差
            if timing_error is not None:
                timing_errors.append(abs(timing_error))
        
        # 计算平均误差
        avg_error = sum(timing_errors) / len(timing_errors) if timing_errors else 0
        
        # 显示核心指标
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("字幕片段", total_segments)
        
        with col2:
            st.metric("总时长", f"{total_duration:.1f}秒")
        
        with col3:
            excellent_count = quality_stats['excellent']
            st.metric("优秀同步", f"{excellent_count}/{total_segments}")
        
        with col4:
            st.metric("平均误差", f"{avg_error:.0f}ms")
        
        # 显示质量分布
        st.markdown("#### 🎯 时长匹配质量分析")
        
        if sum(quality_stats.values()) > 0:
            col1, col2, col3, col4, col5 = st.columns(5)
            
            with col1:
                excellent_pct = (quality_stats['excellent'] / total_segments) * 100
                st.metric("🟢 优秀", f"{quality_stats['excellent']}", f"{excellent_pct:.1f}%")
            
            with col2:
                good_pct = (quality_stats['good'] / total_segments) * 100
                st.metric("🟡 良好", f"{quality_stats['good']}", f"{good_pct:.1f}%")
            
            with col3:
                fair_pct = (quality_stats['fair'] / total_segments) * 100
                st.metric("🟠 一般", f"{quality_stats['fair']}", f"{fair_pct:.1f}%")
            
            with col4:
                poor_pct = (quality_stats['poor'] / total_segments) * 100
                st.metric("🔴 较差", f"{quality_stats['poor']}", f"{poor_pct:.1f}%")
            
            with col5:
                error_pct = (quality_stats['error'] / total_segments) * 100
                st.metric("❌ 错误", f"{quality_stats['error']}", f"{error_pct:.1f}%")
            
            # 质量评价
            if excellent_pct >= 70:
                st.success("🎉 **音频质量优秀**：大部分片段达到了理想的时长匹配效果！")
            elif excellent_pct + good_pct >= 80:
                st.info("✅ **音频质量良好**：整体时长匹配效果不错，可以使用。")
            elif excellent_pct + good_pct + fair_pct >= 90:
                st.warning("⚠️ **音频质量一般**：部分片段时长匹配不够理想，建议检查。")
            else:
                st.error("❌ **音频质量需要改进**：建议重新处理或手动调整部分片段。")
        else:
            st.info("质量分析数据不可用")
    
    def _show_cost_report(self, completion_data: Dict[str, Any]):
        """显示成本报告"""
        cost_summary = completion_data.get('cost_summary', {})
        
        if cost_summary and any(cost_summary.values()):
            with st.expander("💰 Azure TTS 成本报告", expanded=False):
                st.markdown("#### 💰 API调用成本分析")
                
                # 核心成本指标
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    api_calls = cost_summary.get('api_calls', 0)
                    total_chars = cost_summary.get('total_characters', 0)
                    
                    st.metric(
                        "API调用次数",
                        f"{api_calls:,}",
                        help="总共调用Azure TTS API的次数"
                    )
                    st.metric(
                        "总字符数",
                        f"{total_chars:,}",
                        help="发送到Azure TTS的总字符数"
                    )
                
                with col2:
                    estimated_cost = cost_summary.get('estimated_cost_usd', 0)
                    session_duration = cost_summary.get('session_duration_seconds', 0)
                    
                    st.metric(
                        "估计成本",
                        f"${estimated_cost:.4f}",
                        help="基于字符数估算的成本（USD）"
                    )
                    st.metric(
                        "处理时长",
                        f"{session_duration:.1f}s",
                        help="从开始到结束的总处理时间"
                    )
                
                with col3:
                    calls_per_minute = cost_summary.get('avg_calls_per_minute', 0)
                    chars_per_call = cost_summary.get('avg_characters_per_call', 0)
                    
                    st.metric(
                        "调用频率",
                        f"{calls_per_minute:.1f}/min",
                        help="平均每分钟API调用次数"
                    )
                    st.metric(
                        "平均字符/调用",
                        f"{chars_per_call:.1f}",
                        help="平均每次API调用的字符数"
                    )
                
                # 成本效率分析
                if api_calls > 0:
                    st.markdown("#### 📈 成本效率分析")
                    
                    # 计算成本效率指标
                    cost_per_minute = estimated_cost / max(1, session_duration / 60)
                    cost_per_segment = estimated_cost / max(1, len(completion_data.get('optimized_segments', [])))
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        st.metric("每分钟成本", f"${cost_per_minute:.6f}")
                    with col2:
                        st.metric("每片段成本", f"${cost_per_segment:.6f}")
                
                # 成本优化建议
                if api_calls > 50:
                    st.info("💡 **成本优化建议**：启用成本优化模式可减少60-80%的API调用次数")
                    st.markdown("""
                    **优化方法：**
                    - 在配置中启用 `enable_cost_optimization: true`
                    - 使用 `use_estimation_first: true` 优先使用估算方法
                    - 调整 `max_api_calls_per_segment` 限制每个片段的最大调用次数
                    """)
                elif api_calls <= 10:
                    st.success("💚 **成本控制良好**：API调用次数在合理范围内！")
                else:
                    st.info("💙 **成本使用正常**：API调用次数适中。")
        else:
            st.info("💡 成本信息不可用 - 可能是因为使用了缓存或估算模式")
    
    def _render_action_buttons(self) -> Dict[str, Any]:
        """渲染操作按钮"""
        col1, col2 = st.columns(2)
        
        with col1:
            if st.button("🔄 重新开始", key="restart_completed", use_container_width=True):
                return {'action': 'restart'}
        
        with col2:
            if st.button("📊 生成详细报告", key="generate_report", use_container_width=True):
                st.info("详细报告功能已简化")
                return {'action': 'none'}
        
        return {'action': 'none'} 