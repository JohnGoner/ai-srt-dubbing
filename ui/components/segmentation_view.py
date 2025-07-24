"""
分段视图组件
纯组件，不直接操作session_state
"""

import streamlit as st
from typing import List, Dict, Any
from models.segment_dto import SegmentDTO


class SegmentationView:
    """分段确认视图组件"""
    
    def __init__(self):
        # 组件内部状态（不使用session_state）
        self.current_page = 1
        self.edited_segments = []
    
    def render_confirmation(self, segments: List[SegmentDTO], 
                          segmented_segments: List[SegmentDTO], 
                          config: Dict[str, Any]) -> Dict[str, Any]:
        """
        渲染分段确认界面
        
        Args:
            segments: 原始片段列表
            segmented_segments: 智能分段结果
            config: 配置信息
            
        Returns:
            包含action和数据的结果字典
        """
        st.markdown("## 🧠 Step 2: 分段结果确认")
        
        # 初始化编辑状态
        if not self.edited_segments:
            self.edited_segments = segmented_segments.copy()
        
        # 分页设置
        segments_per_page = 8
        total_segments = len(self.edited_segments)
        total_pages = (total_segments + segments_per_page - 1) // segments_per_page
        
        
        # 自动开启编辑模式
        edit_mode = True
        
        
        st.markdown("---")
        
        # 显示当前页的分段
        self._render_segments_page(segments_per_page, edit_mode)
        
        # 编辑工具栏
        # self._render_edit_toolbar(segmented_segments)
        
        # 分页控制
        col1, col2 = st.columns(2)
        with col1:
            if st.button("⬅️ 上一页", disabled=self.current_page <= 1, key="seg_prev_page", use_container_width=True):
                self.current_page -= 1
                st.rerun()
        with col2:
            if st.button("➡️ 下一页", disabled=self.current_page >= total_pages, key="seg_next_page", use_container_width=True):
                self.current_page += 1
                st.rerun()


        # 统计信息
        current_segments = self.edited_segments
        avg_duration = sum(seg.target_duration for seg in current_segments) / len(current_segments)
        
        # 简洁的统计卡片，左右居中显示
        col1, col2, col3 = st.columns([1, 1, 1], gap="large")
        with col1:
            st.markdown(
                f"""
                <div style='display: flex; justify-content: center; align-items: center; flex-direction: column;'>
                    <div style='font-size: 18px;'>📄 总段落数</div>
                    <div style='font-size: 28px; font-weight: bold;'>{len(current_segments)}</div>
                </div>
                """, unsafe_allow_html=True
            )
        with col2:
            st.markdown(
                f"""
                <div style='display: flex; justify-content: center; align-items: center; flex-direction: column;'>
                    <div style='font-size: 18px;'>⏱️ 平均时长</div>
                    <div style='font-size: 28px; font-weight: bold;'>{avg_duration:.1f}秒</div>
                </div>
                """, unsafe_allow_html=True
            )
        with col3:
            st.markdown(
                f"""
                <div style='display: flex; justify-content: center; align-items: center; flex-direction: column;'>
                    <div style='font-size: 18px;'>📊 当前页</div>
                    <div style='font-size: 28px; font-weight: bold;'>{self.current_page}/{total_pages}</div>
                </div>
                """, unsafe_allow_html=True
            )
        # 确认按钮区域
        return self._render_action_buttons(segments)
    
    def _render_segments_page(self, segments_per_page: int, edit_mode: bool):
        """渲染当前页的分段"""
        start_idx = (self.current_page - 1) * segments_per_page
        end_idx = min(start_idx + segments_per_page, len(self.edited_segments))
        page_segments = self.edited_segments[start_idx:end_idx]
        
        for seg_idx, seg in enumerate(page_segments):
            actual_idx = start_idx + seg_idx
            
            with st.container():
                # 段落标题
                col1, col2 = st.columns([3, 1])
                with col1:
                    temp_id = seg.id or f"temp_{actual_idx + 1}"
                    st.markdown(f"**段落 {temp_id}** `{seg.start:.1f}s - {seg.end:.1f}s` *({seg.target_duration:.1f}秒)*")
                with col2:
                    if edit_mode:
                        if actual_idx > 0 and st.button("⬆️ 合并", key=f"merge_up_{actual_idx}_{temp_id}", help="与上一个段落合并"):
                            self._merge_segments(actual_idx-1, actual_idx)
                            st.rerun()
                        if st.button("🗑️ 删除", key=f"delete_{actual_idx}_{temp_id}", help="删除此段落"):
                            self._delete_segment(actual_idx)
                            st.rerun()
                
                # 文本内容
                if edit_mode:
                    text_key = f"edit_text_{actual_idx}_{temp_id}"
                    edited_text = st.text_area(
                        f"编辑段落 {temp_id}",
                        value=seg.get_current_text(),
                        height=100,
                        key=text_key,
                        label_visibility="collapsed",
                        help="💡 在需要拆分的位置按回车，然后点击'应用拆分'按钮"
                    )
                    
                    # 检查是否有换行符（表示用户想要拆分）
                    if '\n' in edited_text:
                        st.info("🔍 检测到换行符，可以在此位置拆分段落")
                        if st.button("✂️ 应用拆分", key=f"apply_split_{actual_idx}_{temp_id}", help="在换行符位置拆分段落"):
                            self._split_segment_at_newline(actual_idx, edited_text)
                            st.rerun()
                    else:
                        # 检查文本是否被修改
                        if edited_text != seg.get_current_text():
                            seg.update_final_text(edited_text)
                else:
                    st.markdown(f"📖 {seg.get_current_text()}")
                
                if seg_idx < len(page_segments) - 1:
                    st.divider()
    
    def _render_edit_toolbar(self, original_segmented_segments: List[SegmentDTO]):
        """渲染编辑工具栏"""
        st.markdown("---")
        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("🔄 重置", help="重置为规则分段的原始结果", key="reset_segments"):
                self.edited_segments = original_segmented_segments.copy()
                self.current_page = 1
                st.success("✅ 已重置为原始规则分段结果")
                st.rerun()
        with col2:
            if st.button("🔍 质量检查", help="检查编辑后的分段质量", key="check_quality"):
                self._check_segment_quality()
        with col3:
            if st.button("📊 统计", help="显示编辑后的统计信息", key="show_statistics"):
                self._show_edit_statistics()
    
    def _render_action_buttons(self, original_segments: List[SegmentDTO]) -> Dict[str, Any]:
        """渲染操作按钮并返回结果"""
        st.markdown("---")
        col1, col2, col3 = st.columns([1, 1, 1])
        
        with col1:
            if st.button(
                "✨ 使用当前分段", 
                type="primary", 
                use_container_width=True,
                key="use_current_segments",
                help="使用当前显示的分段结果（包含您的编辑）"
            ):
                return {
                    'action': 'confirm',
                    'confirmed_segments': self.edited_segments.copy()
                }
        
        with col2:
            if st.button(
                "📋 使用原始片段", 
                type="secondary", 
                use_container_width=True,
                key="use_original_segments",
                help="保持原始SRT文件的分段方式"
            ):
                return {
                    'action': 'confirm',
                    'confirmed_segments': original_segments.copy()
                }
        
        with col3:
            if st.button(
                "🔙 重新开始", 
                use_container_width=True,
                key="restart_upload",
                help="重新上传SRT文件"
            ):
                return {'action': 'restart'}
        
        # 默认返回（无操作）
        return {'action': 'none'}
    
    def _merge_segments(self, index1: int, index2: int):
        """合并两个相邻段落"""
        if index1 >= len(self.edited_segments) or index2 >= len(self.edited_segments):
            return
        
        seg1 = self.edited_segments[index1]
        seg2 = self.edited_segments[index2]
        
        # 创建合并后的段落
        merged_seg = SegmentDTO(
            id=seg1.id,
            start=seg1.start,
            end=seg2.end,
            original_text=f"{seg1.original_text} {seg2.original_text}",
            translated_text=f"{seg1.translated_text} {seg2.translated_text}" if seg1.translated_text else "",
            optimized_text=f"{seg1.optimized_text} {seg2.optimized_text}" if seg1.optimized_text else "",
            final_text=f"{seg1.get_current_text()} {seg2.get_current_text()}",
            target_duration=seg2.end - seg1.start
        )
        
        # 更新段落列表
        self.edited_segments[index1] = merged_seg
        self.edited_segments.pop(index2)
        
        # 重新组织ID
        self._reorganize_segment_ids()
        
        st.success("✅ 段落已合并")
    
    def _delete_segment(self, segment_index: int):
        """删除指定段落"""
        if segment_index >= len(self.edited_segments):
            return
        
        # 至少保留一个段落
        if len(self.edited_segments) <= 1:
            st.warning("⚠️ 不能删除最后一个段落")
            return
        
        deleted_seg = self.edited_segments.pop(segment_index)
        
        # 重新组织ID
        self._reorganize_segment_ids()
        
        # 调整当前页
        self._adjust_current_page()
        
        st.success(f"✅ 段落已删除: {deleted_seg.get_current_text()[:30]}...")
    
    def _split_segment_at_newline(self, segment_index: int, text_with_newlines: str):
        """在换行符位置拆分段落"""
        if segment_index >= len(self.edited_segments):
            return
        
        seg = self.edited_segments[segment_index]
        lines = text_with_newlines.split('\n')
        
        # 如果只有一行或者有空行，不进行拆分
        non_empty_lines = [line.strip() for line in lines if line.strip()]
        if len(non_empty_lines) < 2:
            st.warning("⚠️ 需要至少两个非空段落才能拆分")
            return
        
        # 删除原始段落
        original_seg = self.edited_segments.pop(segment_index)
        
        # 为每个非空行创建新段落
        total_duration = original_seg.target_duration
        duration_per_line = total_duration / len(non_empty_lines)
        
        current_time = original_seg.start
        new_segments = []
        
        for i, line in enumerate(non_empty_lines):
            # 确保最后一个段落的结束时间与原始段落一致
            if i == len(non_empty_lines) - 1:
                line_end_time = original_seg.end
            else:
                line_end_time = current_time + duration_per_line
            
            new_seg = SegmentDTO(
                id=f"{original_seg.id}_{i+1}",
                start=current_time,
                end=line_end_time,
                original_text=line.strip(),
                target_duration=line_end_time - current_time
            )
            
            new_segments.append(new_seg)
            current_time = line_end_time
        
        # 插入新段落
        for i, new_seg in enumerate(new_segments):
            self.edited_segments.insert(segment_index + i, new_seg)
        
        # 重新组织ID
        self._reorganize_segment_ids()
        
        st.success(f"✅ 段落已拆分为 {len(new_segments)} 个部分")
    
    def _reorganize_segment_ids(self):
        """重新组织段落ID，确保连续性"""
        for i, seg in enumerate(self.edited_segments):
            seg.id = f"seg_{i+1}"
    
    def _adjust_current_page(self):
        """调整当前页码"""
        segments_per_page = 8
        total_segments = len(self.edited_segments)
        total_pages = (total_segments + segments_per_page - 1) // segments_per_page
        
        if self.current_page > total_pages:
            self.current_page = max(1, total_pages)
    
    def _check_segment_quality(self):
        """检查分段质量"""
        issues = []
        
        for seg in self.edited_segments:
            current_text = seg.get_current_text()
            
            # 检查文本长度
            if len(current_text) < 10:
                issues.append(f"段落 {seg.id}: 文本过短")
            elif len(current_text) > 200:
                issues.append(f"段落 {seg.id}: 文本过长")
            
            # 检查时长
            if seg.target_duration < 2:
                issues.append(f"段落 {seg.id}: 时长过短")
            elif seg.target_duration > 15:
                issues.append(f"段落 {seg.id}: 时长过长")
        
        if issues:
            st.warning(f"发现 {len(issues)} 个质量问题：")
            for issue in issues:
                st.write(f"⚠️ {issue}")
        else:
            st.success("✅ 分段质量检查通过")
    
    def _show_edit_statistics(self):
        """显示编辑统计信息"""
        total_duration = sum(seg.target_duration for seg in self.edited_segments)
        total_chars = sum(len(seg.get_current_text()) for seg in self.edited_segments)
        avg_duration = total_duration / len(self.edited_segments)
        avg_chars = total_chars / len(self.edited_segments)
        
        st.info(f"""
        📊 编辑统计：
        - 总段落数：{len(self.edited_segments)}
        - 总时长：{total_duration:.1f}秒
        - 总字符数：{total_chars}
        - 平均时长：{avg_duration:.1f}秒
        - 平均字符数：{avg_chars:.0f}
        """) 