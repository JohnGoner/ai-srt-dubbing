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
        渲染完成界面 (极简设计)
        
        Args:
            completion_data: 完成数据
            
        Returns:
            包含action和数据的结果字典
        """
        # 成功提示
        st.success("🎉 配音项目已完成！")
        st.markdown('<div class="main-header"><h1>处理完成</h1></div>', unsafe_allow_html=True)
        
        # 下载和试听区域 (极简布局)
        col1, col2 = st.columns([1, 1])
        with col1:
            st.markdown("#### 🎧 在线试听")
            st.audio(completion_data['audio_data'], format='audio/mpeg')
        
        with col2:
            st.markdown("#### 📥 下载文件")
            # 使用工程名作为下载文件名
            project_name = completion_data.get('project_name', f"dubbed_audio_{completion_data['target_lang']}")
            target_lang = completion_data['target_lang']
            
            st.download_button(
                label="下载配音音频 (.mp3)",
                data=completion_data['audio_data'],
                file_name=f"{project_name}_{target_lang}.mp3",
                mime="audio/mpeg",
                use_container_width=True
            )
        
        st.markdown("---")
        
        # 统计和成本 (合并显示)
        col1, col2 = st.columns(2)
        with col1:
            self._show_enhanced_statistics(completion_data)
        with col2:
            self._show_cost_report(completion_data)
        
        # 操作按钮
        return self._render_action_buttons()
    
    def _show_enhanced_statistics(self, completion_data: Dict[str, Any]):
        """显示增强的统计信息 - 从用户确认后的实际数据计算"""
        st.markdown("### 📊 处理统计")
        
        # 从实际的optimized_segments数据中计算统计信息（这些是用户确认后的segments）
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
        
        # 计算总时长 - 使用最后一个片段的结束时间
        total_duration = 0
        for seg in optimized_segments:
            if isinstance(seg, dict):
                end_time = seg.get('end', 0)
            else:
                end_time = getattr(seg, 'end', 0)
            total_duration = max(total_duration, end_time)
        
        # 计算质量分布和时长误差
        quality_stats = {'excellent': 0, 'good': 0, 'fair': 0, 'poor': 0, 'error': 0}
        timing_errors = []
        confirmed_count = 0
        modified_count = 0
        
        for seg in optimized_segments:
            # 统一获取数据的方式
            if isinstance(seg, dict):
                quality = seg.get('quality', 'unknown')
                timing_error = seg.get('timing_error_ms', 0)
                actual_duration = seg.get('actual_duration', 0)
                target_duration = seg.get('target_duration', seg.get('duration', 0))
                confirmed = seg.get('confirmed', False)
                user_modified = seg.get('user_modified', seg.get('text_modified', False))
            else:
                quality = getattr(seg, 'quality', 'unknown')
                timing_error = getattr(seg, 'timing_error_ms', 0)
                actual_duration = getattr(seg, 'actual_duration', 0)
                target_duration = getattr(seg, 'target_duration', 0)
                confirmed = getattr(seg, 'confirmed', False)
                user_modified = getattr(seg, 'user_modified', False)
            
            # 统计确认和修改状态
            if confirmed:
                confirmed_count += 1
            if user_modified:
                modified_count += 1
            
            # 统计质量分布
            if quality and quality != 'unknown' and quality in quality_stats:
                quality_stats[quality] += 1
            else:
                # 如果质量未知，根据同步比例重新计算
                if actual_duration and target_duration and target_duration > 0:
                    sync_ratio = actual_duration / target_duration
                    if 0.95 <= sync_ratio <= 1.05:  # 误差在5%以内
                        quality_stats['excellent'] += 1
                        quality = 'excellent'
                    elif 0.85 <= sync_ratio <= 1.15:  # 误差在15%以内
                        quality_stats['good'] += 1
                        quality = 'good'
                    elif 0.75 <= sync_ratio <= 1.25:  # 误差在25%以内
                        quality_stats['fair'] += 1
                        quality = 'fair'
                    else:
                        quality_stats['poor'] += 1
                        quality = 'poor'
                else:
                    # 没有足够数据，默认为一般
                    quality_stats['fair'] += 1
                    quality = 'fair'
            
            # 收集时长误差（使用实际计算的误差）
            if actual_duration and target_duration and target_duration > 0:
                calculated_error = abs(actual_duration - target_duration) * 1000  # 转换为毫秒
                timing_errors.append(calculated_error)
            elif timing_error:
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
        
        # 显示确认状态统计
        st.markdown("#### ✅ 确认状态统计")
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric("已确认片段", f"{confirmed_count}/{total_segments}")
        
        with col2:
            st.metric("用户修改", modified_count)
        
        with col3:
            completion_rate = (confirmed_count / total_segments * 100) if total_segments > 0 else 0
            st.metric("完成度", f"{completion_rate:.1f}%")
        
        # 显示质量分布
        st.markdown("#### 🎯 时长匹配质量分析")
        
        if sum(quality_stats.values()) > 0:
            col1, col2, col3, col4, col5 = st.columns(5)
            
            with col1:
                excellent_pct = (quality_stats['excellent'] / total_segments) * 100
                st.metric("🟢 优秀", f"{quality_stats['excellent']}", f"↗ {excellent_pct:.1f}%")
            
            with col2:
                good_pct = (quality_stats['good'] / total_segments) * 100
                st.metric("🟡 良好", f"{quality_stats['good']}", f"↗ {good_pct:.1f}%")
            
            with col3:
                fair_pct = (quality_stats['fair'] / total_segments) * 100
                st.metric("🟠 一般", f"{quality_stats['fair']}", f"↗ {fair_pct:.1f}%")
            
            with col4:
                poor_pct = (quality_stats['poor'] / total_segments) * 100
                st.metric("🔴 较差", f"{quality_stats['poor']}", f"↗ {poor_pct:.1f}%")
            
            with col5:
                error_pct = (quality_stats['error'] / total_segments) * 100
                st.metric("❌ 错误", f"{quality_stats['error']}", f"↗ {error_pct:.1f}%")
            
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
        """显示精确的API成本报告 - 使用实际统计数据"""
        # 优先使用新的综合API统计，向后兼容旧的cost_summary
        api_usage_summary = completion_data.get('api_usage_summary', {})
        cost_summary = completion_data.get('cost_summary', {})
        
        # 如果没有API统计数据，不显示成本报告
        if not api_usage_summary and not cost_summary:
            st.info("📊 没有API使用数据 - 可能使用了缓存或本地处理")
            return
        
        if api_usage_summary:
            with st.expander("💰 完整 API 使用报告", expanded=False):
                st.markdown("#### 💰 API调用成本分析")
                
                # TTS API统计
                tts_stats = api_usage_summary.get('tts_api', {})
                translation_stats = api_usage_summary.get('translation_api', {})
                
                # 总体概览
                st.markdown("##### 📊 总体概览")
                col1, col2, col3, col4 = st.columns(4)
                
                with col1:
                    # 修正总API调用数计算
                    tts_calls = tts_stats.get('api_calls', 0) if tts_stats else 0
                    translation_requests = translation_stats.get('total_requests', 0) if translation_stats else 0
                    total_api_calls = tts_calls + translation_requests
                    st.metric("总API调用数", f"{total_api_calls:,}", help="TTS + 翻译API调用总数")
                
                with col2:
                    # 修正会话时长计算
                    tts_duration = tts_stats.get('session_duration_seconds', 0) if tts_stats else 0
                    translation_duration = translation_stats.get('session_duration_minutes', 0) * 60 if translation_stats else 0
                    session_duration = max(tts_duration, translation_duration)
                    st.metric("会话总时长", f"{session_duration:.1f}s", help="从开始到结束的总处理时间")
                    
                    # 计算总成本
                    tts_cost = tts_stats.get('estimated_cost_usd', 0) if tts_stats else 0
                    translation_cost = translation_stats.get('estimated_cost_usd', 0) if translation_stats else 0
                    total_cost = tts_cost + translation_cost
                    st.metric("总估计成本", f"${total_cost:.4f}", help="TTS + 翻译API的总成本")
                
                with col3:
                    st.metric("TTS调用", f"{tts_calls:,}", help="TTS API调用次数")
                
                with col4:
                    st.metric("翻译调用", f"{translation_requests:,}", help="翻译API调用次数")
                
                # TTS详细统计
                if tts_stats and tts_calls > 0:
                    st.markdown("##### 🎵 TTS 统计")
                    col1, col2, col3 = st.columns(3)
                    
                    with col1:
                        total_chars = tts_stats.get('total_characters', 0)
                        estimated_cost = tts_stats.get('estimated_cost_usd', 0)
                        st.metric("TTS字符数", f"{total_chars:,}")
                        st.metric("TTS估计成本", f"${estimated_cost:.4f}")
                    
                    with col2:
                        calls_per_minute = tts_stats.get('avg_calls_per_minute', 0)
                        chars_per_call = tts_stats.get('avg_characters_per_call', 0)
                        st.metric("TTS调用频率", f"{calls_per_minute:.1f}/min")
                        st.metric("平均字符/调用", f"{chars_per_call:.1f}")
                    
                    with col3:
                        if estimated_cost > 0 and session_duration > 0:
                            cost_per_minute = estimated_cost / max(1, session_duration / 60)
                            st.metric("TTS成本/分钟", f"${cost_per_minute:.6f}")
                        
                        # 显示效率指标
                        if total_chars > 0 and tts_calls > 0:
                            efficiency = total_chars / tts_calls
                            st.metric("字符效率", f"{efficiency:.0f}字符/调用")

                # 翻译API详细统计
                if translation_stats and translation_requests > 0:
                    st.markdown("##### 🌐 翻译 API 统计")
                    col1, col2, col3 = st.columns(3)
                    
                    with col1:
                        total_tokens = translation_stats.get('total_tokens', 0)
                        prompt_tokens = translation_stats.get('total_prompt_tokens', 0)
                        completion_tokens = translation_stats.get('total_completion_tokens', 0)
                        total_chars = translation_stats.get('total_characters', 0)
                        estimated_cost = translation_stats.get('estimated_cost_usd', 0)
                        
                        st.metric("总Token数", f"{total_tokens:,}")
                        st.write(f"- 输入Token: {prompt_tokens:,}")
                        st.write(f"- 输出Token: {completion_tokens:,}")
                        st.metric("翻译字符数", f"{total_chars:,}")
                        st.metric("翻译估计成本", f"${estimated_cost:.4f}")
                    
                    with col2:
                        avg_tokens = translation_stats.get('avg_tokens_per_request', 0)
                        tokens_per_minute = translation_stats.get('tokens_per_minute', 0)
                        st.metric("平均Token/请求", f"{avg_tokens:.1f}")
                        st.metric("Token使用率", f"{tokens_per_minute:.1f}/min")
                    
                    with col3:
                        cache_hits = translation_stats.get('cache_hits', 0)
                        cache_hit_rate = translation_stats.get('cache_hit_rate', 0)
                        st.metric("缓存命中", f"{cache_hits}")
                        st.metric("缓存命中率", f"{cache_hit_rate:.1f}%")
                    
                    # 显示效率指标
                    if total_tokens > 0 and translation_requests > 0:
                        efficiency = total_tokens / translation_requests
                        st.write(f"📊 平均效率: {efficiency:.0f} Token/请求")
                    
                    # Kimi API限制信息（如果使用Kimi）
                    kimi_limits = translation_stats.get('kimi_limits', {})
                    if kimi_limits and any(kimi_limits.values()):
                        st.markdown("##### 🚀 Kimi API 使用率")
                        col1, col2 = st.columns(2)
                        
                        with col1:
                            tpm_usage = kimi_limits.get('tpm_usage_percent', 0)
                            tpm_remaining = kimi_limits.get('tpm_remaining', 0)
                            if tpm_usage > 0:  # 只有在有数据时才显示
                                color = "red" if tpm_usage > 80 else "orange" if tpm_usage > 60 else "green"
                                st.markdown(f"**TPM使用率:** <span style='color:{color}'>{tpm_usage:.1f}%</span>", unsafe_allow_html=True)
                                st.write(f"剩余TPM: {tpm_remaining:,}")
                        
                        with col2:
                            rpm_usage = kimi_limits.get('rpm_usage_percent', 0)
                            rpm_remaining = kimi_limits.get('rpm_remaining', 0)
                            if rpm_usage > 0:  # 只有在有数据时才显示
                                color = "red" if rpm_usage > 80 else "orange" if rpm_usage > 60 else "green"
                                st.markdown(f"**RPM使用率:** <span style='color:{color}'>{rpm_usage:.1f}%</span>", unsafe_allow_html=True)
                                st.write(f"剩余RPM: {rpm_remaining}")
                
                # 综合成本效率分析
                tts_cost = tts_stats.get('estimated_cost_usd', 0) if tts_stats else 0
                translation_cost = translation_stats.get('estimated_cost_usd', 0) if translation_stats else 0
                total_cost = tts_cost + translation_cost
                
                if total_cost > 0:
                    st.markdown("##### 📈 成本效率分析")
                    
                    # 计算成本效率指标
                    segments_count = len(completion_data.get('optimized_segments', []))
                    cost_per_minute = total_cost / max(1, session_duration / 60) if session_duration > 0 else 0
                    cost_per_segment = total_cost / max(1, segments_count) if segments_count > 0 else 0
                    
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("总成本/分钟", f"${cost_per_minute:.6f}")
                        if tts_cost > 0:
                            st.write(f"- TTS: ${(tts_cost / max(1, session_duration / 60)):.6f}/min")
                        if translation_cost > 0:
                            st.write(f"- 翻译: ${(translation_cost / max(1, session_duration / 60)):.6f}/min")
                    
                    with col2:
                        st.metric("总成本/片段", f"${cost_per_segment:.6f}")
                        if tts_cost > 0:
                            st.write(f"- TTS: ${(tts_cost / max(1, segments_count)):.6f}/片段")
                        if translation_cost > 0:
                            st.write(f"- 翻译: ${(translation_cost / max(1, segments_count)):.6f}/片段")
                    
                    with col3:
                        # 计算性价比（每美元处理的秒数）
                        total_duration = completion_data.get('stats', {}).get('total_duration', 0)
                        if total_duration > 0:
                            value_ratio = total_duration / total_cost
                            st.metric("性价比", f"{value_ratio:.0f}秒/$")
                        
                        # 成本分布
                        if tts_cost > 0 and translation_cost > 0:
                            tts_percent = (tts_cost / total_cost) * 100
                            st.write(f"📊 成本分布:")
                            st.write(f"- TTS: {tts_percent:.1f}%")
                            st.write(f"- 翻译: {(100-tts_percent):.1f}%")
        
        elif cost_summary and any(cost_summary.values()):
            # 向后兼容：显示旧版本的TTS成本报告
            with st.expander("💰 TTS 成本报告", expanded=False):
                st.markdown("#### 💰 API调用成本分析")
                
                # 核心成本指标
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    api_calls = cost_summary.get('api_calls', 0)
                    total_chars = cost_summary.get('total_characters', 0)
                    
                    st.metric(
                        "API调用次数",
                        f"{api_calls:,}",
                        help="总共调用TTS API的次数"
                    )
                    st.metric(
                        "总字符数",
                        f"{total_chars:,}",
                        help="发送到TTS的总字符数"
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
                    
                    # 显示效率指标
                    if total_chars > 0 and api_calls > 0:
                        efficiency = total_chars / api_calls
                        st.metric("字符效率", f"{efficiency:.0f}字符/调用")
                
                # 成本效率分析
                if api_calls > 0 and estimated_cost > 0:
                    st.markdown("#### 📈 成本效率分析")
                    
                    # 计算成本效率指标
                    segments_count = len(completion_data.get('optimized_segments', []))
                    cost_per_minute = estimated_cost / max(1, session_duration / 60) if session_duration > 0 else 0
                    cost_per_segment = estimated_cost / max(1, segments_count) if segments_count > 0 else 0
                    
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("每分钟成本", f"${cost_per_minute:.6f}")
                    with col2:
                        st.metric("每片段成本", f"${cost_per_segment:.6f}")
                    with col3:
                        # 计算性价比（每美元处理的秒数）
                        total_duration = completion_data.get('stats', {}).get('total_duration', 0)
                        if total_duration > 0 and estimated_cost > 0:
                            value_ratio = total_duration / estimated_cost
                            st.metric("性价比", f"{value_ratio:.0f}秒/$")
                
                # 成本优化建议
                total_calls = api_calls
                if total_calls > 50:
                    st.info("💡 **成本优化建议**：启用成本优化模式可减少60-80%的API调用次数")
                    st.markdown("""
                    **优化方法：**
                    - 在配置中启用 `enable_cost_optimization: true`
                    - 使用 `use_estimation_first: true` 优先使用估算方法
                    - 调整 `max_api_calls_per_segment` 限制每个片段的最大调用次数
                    """)
                elif total_calls <= 10:
                    st.success("💚 **成本控制良好**：API调用次数在合理范围内！")
                else:
                    st.info("💙 **成本使用正常**：API调用次数适中。")
        else:
            # 如果没有新的API统计，显示简化版本
            st.info("💡 成本信息不可用 - 可能是因为使用了缓存或估算模式")
    
    def _render_action_buttons(self) -> Dict[str, Any]:
        """渲染操作按钮"""
        col1, col2 = st.columns(2)
        
        with col1:
            if st.button("🔄 重新开始", key="restart_completed", use_container_width=True):
                return {'action': 'restart'}
        
        with col2:
            if st.button("🔙 返回各分段音频确认", key="back_to_audio_confirmation", use_container_width=True):
                return {'action': 'back_to_audio_confirmation'}
        
        return {'action': 'none'}