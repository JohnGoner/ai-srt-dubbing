"""
分段视图组件
纯组件，不直接操作session_state
"""

import streamlit as st
from typing import List, Dict, Any
from loguru import logger
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
        渲染分段确认界面 (极简设计)
        
        Args:
            segments: 原始片段列表
            segmented_segments: 智能分段结果
            config: 配置信息
            
        Returns:
            包含action和数据的结果字典
        """
        st.markdown('<div class="main-header"><h1>分段确认</h1></div>', unsafe_allow_html=True)
        
        # 使用session_state管理编辑状态，避免状态丢失
        if 'segmentation_edited_segments' not in st.session_state:
            st.session_state.segmentation_edited_segments = segmented_segments.copy()
            logger.debug(f"🔄 初始化编辑状态，共 {len(segmented_segments)} 个段落")
        
        # 保存原始segments的引用，用于准确的时间码计算
        if 'segmentation_original_segments' not in st.session_state:
            st.session_state.segmentation_original_segments = segments.copy()
            logger.debug(f"💾 保存原始segments引用，共 {len(segments)} 个片段")
        
        # 使用session_state中的编辑状态
        self.edited_segments = st.session_state.segmentation_edited_segments
        self.original_segments = st.session_state.segmentation_original_segments
        
        # 确保所有编辑中的段落都有original_indices属性
        self._ensure_original_indices_compatibility()
        
        # 使用session_state管理当前页码
        if 'segmentation_current_page' not in st.session_state:
            st.session_state.segmentation_current_page = 1
            
        self.current_page = st.session_state.segmentation_current_page
        
        # 分页设置
        segments_per_page = 8
        total_segments = len(self.edited_segments)
        total_pages = (total_segments + segments_per_page - 1) // segments_per_page
        
        # 统计概览 (极简版)
        avg_duration = sum(seg.target_duration for seg in self.edited_segments) / len(self.edited_segments)
        st.caption(f"总段落: {total_segments} | 平均时长: {avg_duration:.1f}秒 | 页面: {self.current_page}/{total_pages}")
        
        st.markdown("---")
        
        # 显示当前页的分段
        self._render_segments_page(segments_per_page, True)
        
        # 分页控制
        col1, col2 = st.columns(2)
        with col1:
            if st.button("⬅️ 上一页", disabled=self.current_page <= 1, key="seg_prev_page", use_container_width=True):
                self.current_page -= 1
                st.session_state.segmentation_current_page = self.current_page
                st.rerun()
        with col2:
            if st.button("➡️ 下一页", disabled=self.current_page >= total_pages, key="seg_next_page", use_container_width=True):
                self.current_page += 1
                st.session_state.segmentation_current_page = self.current_page
                st.rerun()

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
                    # 安全获取original_indices
                    seg_original_indices = getattr(seg, 'original_indices', [])
                    original_info = f" [原始片段: {seg_original_indices}]" if seg_original_indices else ""
                    st.markdown(f"**段落 {temp_id}** `{seg.start:.1f}s - {seg.end:.1f}s` *({seg.target_duration:.1f}秒)*{original_info}")
                with col2:
                    if edit_mode:
                        if actual_idx > 0 and st.button("⬆️ 合并", key=f"merge_up_{actual_idx}_{temp_id}", help="与上一个段落合并，使用原始SRT时间码"):
                            self._merge_segments(actual_idx-1, actual_idx)
                            st.rerun()
                        if st.button("🗑️ 删除", key=f"delete_{actual_idx}_{temp_id}", help="删除此段落"):
                            self._delete_segment(actual_idx)
                            st.rerun()
                
                # 如果包含多个原始片段，显示capsule形式的拆分界面
                seg_original_indices = getattr(seg, 'original_indices', [])
                if len(seg_original_indices) > 1:
                    self._render_multi_segment_capsules(seg, actual_idx, temp_id, edit_mode)
                else:
                    # 单个片段或普通文本编辑
                    if edit_mode:
                        text_key = f"edit_text_{actual_idx}_{temp_id}"
                        edited_text = st.text_area(
                            f"编辑段落 {temp_id}",
                            value=seg.get_current_text(),
                            height=100,
                            key=text_key,
                            label_visibility="collapsed"
                        )
                        
                        # 检查文本是否被修改
                        if edited_text != seg.get_current_text():
                            seg.update_final_text(edited_text)
                            # 同步到session_state
                            st.session_state.segmentation_edited_segments = self.edited_segments.copy()
                            logger.debug(f"📝 文本修改已同步到session_state")
                    else:
                        st.markdown(f"📖 {seg.get_current_text()}")
                
                if seg_idx < len(page_segments) - 1:
                    st.divider()
    
    def _render_multi_segment_capsules(self, segment: SegmentDTO, segment_idx: int, temp_id: str, edit_mode: bool):
        """渲染包含多个原始片段的capsule界面，支持精确拆分"""
        seg_original_indices = getattr(segment, 'original_indices', [])
        
        if not seg_original_indices:
            # 如果没有original_indices，回退到普通编辑模式
            if edit_mode:
                text_key = f"edit_text_{segment_idx}_{temp_id}"
                edited_text = st.text_area(
                    f"编辑段落 {temp_id}",
                    value=segment.get_current_text(),
                    height=100,
                    key=text_key,
                    label_visibility="collapsed"
                )
                
                if edited_text != segment.get_current_text():
                    segment.update_final_text(edited_text)
                    st.session_state.segmentation_edited_segments = self.edited_segments.copy()
            else:
                st.markdown(f"📖 {segment.get_current_text()}")
            return
        
        # 显示capsule界面
        st.markdown("##### 📦 智能合并片段 - 可选择拆分位置")
        
        # 为每个原始片段创建capsule
        capsule_container = st.container()
        
        with capsule_container:
            # 创建capsule布局
            for i, original_idx in enumerate(seg_original_indices):
                # 获取原始片段数据
                if original_idx <= len(self.original_segments):
                    original_seg = self.original_segments[original_idx - 1]
                    
                    # 创建capsule容器
                    col1, col2 = st.columns([4, 1])
                    
                    with col1:
                        # Capsule样式的片段显示
                        capsule_text = original_seg.get_current_text()[:80] + "..." if len(original_seg.get_current_text()) > 80 else original_seg.get_current_text()
                        
                        st.markdown(f"""
                        <div style="
                            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                            color: white;
                            padding: 12px 16px;
                            border-radius: 20px;
                            margin: 4px 0;
                            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
                            font-size: 14px;
                            line-height: 1.4;
                        ">
                            <strong>片段 {original_idx}</strong> 
                            <span style="opacity: 0.8;">({original_seg.start:.1f}s - {original_seg.end:.1f}s)</span><br/>
                            {capsule_text}
                        </div>
                        """, unsafe_allow_html=True)
                    
                    with col2:
                        # 显示时长信息
                        st.markdown(f"<div style='text-align: center; padding: 20px 0; color: #666;'>{original_seg.target_duration:.1f}s</div>", unsafe_allow_html=True)
                    
                    # 在capsule之间添加拆分按钮（除了最后一个）
                    if i < len(seg_original_indices) - 1:
                        col_split = st.columns([2, 1, 2])
                        with col_split[1]:
                            split_key = f"split_after_{segment_idx}_{original_idx}_{temp_id}"
                            if st.button("✂️ 拆分", key=split_key, help=f"在片段{original_idx}之后拆分", use_container_width=True):
                                self._split_segment_at_position(segment_idx, i + 1)  # i+1表示在第i+1个位置拆分
                                st.rerun()
                        
                        # 添加分隔线
                        st.markdown("<hr style='margin: 8px 0; border: 1px dashed #ccc;'>", unsafe_allow_html=True)
        
        # 整体编辑区域
        if edit_mode:
            st.markdown("##### ✏️ 整体编辑")
            text_key = f"edit_combined_text_{segment_idx}_{temp_id}"
            edited_text = st.text_area(
                "编辑整个段落内容",
                value=segment.get_current_text(),
                height=80,
                key=text_key,
                help="在这里可以编辑整个段落的文本内容"
            )
            
            # 检查文本是否被修改
            if edited_text != segment.get_current_text():
                segment.update_final_text(edited_text)
                st.session_state.segmentation_edited_segments = self.edited_segments.copy()
                logger.debug(f"📝 整体文本修改已同步到session_state")
        
        # 操作按钮区域
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🔄 按原始片段拆分", key=f"split_all_{segment_idx}_{temp_id}", help="将此段落完全按原始片段边界拆分"):
                self._split_segment_by_original_boundaries(segment_idx)
                st.rerun()
        with col2:
            st.markdown(f"<div style='text-align: center; padding: 8px; color: #666; font-size: 12px;'>包含 {len(seg_original_indices)} 个原始片段</div>", unsafe_allow_html=True)
    
    def _split_segment_at_position(self, segment_index: int, split_position: int):
        """在指定位置拆分段落
        
        Args:
            segment_index: 要拆分的段落索引
            split_position: 拆分位置（在第几个原始片段之后拆分，从1开始）
        """
        if segment_index >= len(self.edited_segments) or segment_index < 0:
            st.error("❌ 拆分失败：段落索引无效")
            return
        
        segment = self.edited_segments[segment_index]
        seg_original_indices = getattr(segment, 'original_indices', [])
        
        if len(seg_original_indices) <= 1:
            st.warning("⚠️ 此段落只包含一个原始片段，无法拆分")
            return
        
        if split_position <= 0 or split_position >= len(seg_original_indices):
            st.error("❌ 拆分位置无效")
            return
        
        try:
            # 删除原始段落
            original_segment = self.edited_segments.pop(segment_index)
            
            # 分成两部分
            first_part_indices = seg_original_indices[:split_position]
            second_part_indices = seg_original_indices[split_position:]
            
            # 创建第一部分段落
            first_part = self._create_segment_from_indices(first_part_indices, f"seg_{segment_index}_1")
            
            # 创建第二部分段落
            second_part = self._create_segment_from_indices(second_part_indices, f"seg_{segment_index}_2")
            
            # 插入新段落
            self.edited_segments.insert(segment_index, first_part)
            self.edited_segments.insert(segment_index + 1, second_part)
            
            # 重新组织ID
            self._reorganize_segment_ids()
            
            # 同步到session_state
            st.session_state.segmentation_edited_segments = self.edited_segments.copy()
            logger.debug(f"🔄 精确拆分后同步状态，当前共 {len(self.edited_segments)} 个段落")
            
            # 调整当前页码，确保能看到拆分后的段落
            self._adjust_current_page_for_split(segment_index, 2)
            
            st.success(f"✅ 段落已在位置 {split_position} 拆分为2个部分")
            
            # 显示拆分详情
            with st.expander("📋 拆分详情", expanded=True):
                st.info(f"原段落包含原始片段 {seg_original_indices}")
                st.write(f"**第一部分 {first_part.id}:** 包含原始片段 {first_part_indices}")
                st.write(f"   - 时间: `{first_part.start:.1f}s - {first_part.end:.1f}s`")
                st.write(f"   - 内容: {first_part.get_current_text()[:50]}...")
                st.write(f"**第二部分 {second_part.id}:** 包含原始片段 {second_part_indices}")
                st.write(f"   - 时间: `{second_part.start:.1f}s - {second_part.end:.1f}s`")
                st.write(f"   - 内容: {second_part.get_current_text()[:50]}...")
                st.write(f"当前总段落数：{len(self.edited_segments)}，当前页码：{self.current_page}")
                
        except Exception as e:
            # 如果拆分失败，恢复原始段落
            if 'original_segment' in locals():
                self.edited_segments.insert(segment_index, original_segment)
            st.error(f"❌ 拆分失败：{str(e)}")
            logger.error(f"精确拆分段落时发生错误: {e}", exc_info=True)
    
    def _create_segment_from_indices(self, original_indices: List[int], segment_id: str) -> SegmentDTO:
        """根据原始片段索引创建新的段落"""
        if not original_indices:
            raise ValueError("原始片段索引列表不能为空")
        
        # 获取对应的原始片段
        original_segments = []
        for idx in original_indices:
            if idx <= len(self.original_segments):
                original_segments.append(self.original_segments[idx - 1])
        
        if not original_segments:
            raise ValueError("未找到对应的原始片段")
        
        # 计算时间范围
        start_time = min(seg.start for seg in original_segments)
        end_time = max(seg.end for seg in original_segments)
        
        # 合并文本内容
        combined_text = " ".join(seg.get_current_text() for seg in original_segments if seg.get_current_text().strip())
        
        # 创建新段落
        new_segment = SegmentDTO(
            id=segment_id,
            start=start_time,
            end=end_time,
            original_text=combined_text,
            translated_text="",  # 拆分后需要重新翻译
            optimized_text="",   # 拆分后需要重新优化  
            final_text=combined_text,
            target_duration=end_time - start_time,
            original_indices=original_indices.copy()
        )
        
        return new_segment
    
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
    
    def _ensure_original_indices_compatibility(self):
        """确保所有段落都有original_indices属性，兼容旧数据"""
        for i, seg in enumerate(self.edited_segments):
            if not hasattr(seg, 'original_indices') or not isinstance(getattr(seg, 'original_indices', None), list):
                # 为旧的SegmentDTO实例添加missing的属性
                seg.original_indices = []
                logger.debug(f"为段落 {i+1} 添加了original_indices属性")
        
        # 同步回session_state
        st.session_state.segmentation_edited_segments = self.edited_segments
    
    def _merge_segments(self, index1: int, index2: int):
        """合并两个相邻段落"""
        if index1 >= len(self.edited_segments) or index2 >= len(self.edited_segments):
            st.error("❌ 合并失败：段落索引无效")
            return
        
        if index1 < 0 or index2 < 0:
            st.error("❌ 合并失败：段落索引无效")
            return
        
        seg1 = self.edited_segments[index1]
        seg2 = self.edited_segments[index2]
        
        # 安全地连接文本，确保有适当的分隔
        def safe_join(text1: str, text2: str) -> str:
            """安全地连接两个文本，确保有适当的分隔符"""
            if not text1 and not text2:
                return ""
            if not text1:
                return text2.strip()
            if not text2:
                return text1.strip()
            
            text1 = text1.strip()
            text2 = text2.strip()
            
            # 检查是否需要添加分隔符
            if text1 and text2:
                # 如果第一个文本不以标点符号结尾，添加一个空格
                if text1[-1] not in '。！？.,!?;:':
                    return f"{text1} {text2}"
                else:
                    return f"{text1} {text2}"
            
            return f"{text1}{text2}".strip()
        
        # 合并original_indices（安全获取）
        seg1_indices = getattr(seg1, 'original_indices', [])
        seg2_indices = getattr(seg2, 'original_indices', [])
        merged_original_indices = seg1_indices + seg2_indices
        merged_original_indices.sort()  # 确保顺序正确
        
        # 计算准确的时间码：使用第一个和最后一个原始片段的时间
        if merged_original_indices:
            first_original_idx = merged_original_indices[0]
            last_original_idx = merged_original_indices[-1]
            
            # 获取准确的开始和结束时间
            if (first_original_idx <= len(self.original_segments) and 
                last_original_idx <= len(self.original_segments)):
                accurate_start = self.original_segments[first_original_idx - 1].start
                accurate_end = self.original_segments[last_original_idx - 1].end
            else:
                # 如果索引有问题，使用现有的时间
                accurate_start = seg1.start
                accurate_end = seg2.end
        else:
            # 如果没有original_indices，使用现有的时间
            accurate_start = seg1.start
            accurate_end = seg2.end
        
        # 创建合并后的段落
        merged_seg = SegmentDTO(
            id=seg1.id,
            start=accurate_start,
            end=accurate_end,
            original_text=safe_join(seg1.original_text, seg2.original_text),
            translated_text=safe_join(seg1.translated_text, seg2.translated_text) if seg1.translated_text or seg2.translated_text else "",
            optimized_text=safe_join(seg1.optimized_text, seg2.optimized_text) if seg1.optimized_text or seg2.optimized_text else "",
            final_text=safe_join(seg1.get_current_text(), seg2.get_current_text()),
            target_duration=accurate_end - accurate_start,
            original_indices=merged_original_indices
        )
        
        # 更新段落列表
        self.edited_segments[index1] = merged_seg
        self.edited_segments.pop(index2)
        
        # 重新组织ID
        self._reorganize_segment_ids()
        
        # 同步到session_state
        st.session_state.segmentation_edited_segments = self.edited_segments.copy()
        
        # 调整当前页码，确保能看到合并后的段落
        self._adjust_current_page_for_merge(index1)
        
        st.success(f"✅ 段落已合并：{merged_seg.id} - {merged_seg.get_current_text()[:50]}...")
        
        # 显示合并详情
        with st.expander("📋 合并详情", expanded=True):
            st.info(f"位置 {index1+1} 的段落与位置 {index2+1} 的段落已合并")
            st.write(f"**合并后段落 {merged_seg.id}:** `{merged_seg.start:.1f}s - {merged_seg.end:.1f}s` {merged_seg.get_current_text()[:50]}...")
            # 安全显示original_indices
            merged_indices = getattr(merged_seg, 'original_indices', [])
            st.write(f"包含原始片段: {merged_indices}")
            st.write(f"时长: {merged_seg.target_duration:.2f}秒")
            st.write(f"当前总段落数：{len(self.edited_segments)}，当前页码：{self.current_page}")
    
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
        
        # 同步到session_state
        st.session_state.segmentation_edited_segments = self.edited_segments.copy()
        
        # 调整当前页
        self._adjust_current_page()
        
        st.success(f"✅ 段落已删除: {deleted_seg.id} - {deleted_seg.get_current_text()[:30]}...")
        
        # 显示删除详情
        with st.expander("📋 删除详情", expanded=True):
            st.info(f"位置 {segment_index+1} 的段落已删除")
            st.write(f"当前总段落数：{len(self.edited_segments)}，当前页码：{self.current_page}")
    
    def _can_split_segment(self, segment: SegmentDTO) -> bool:
        """检查段落是否可以拆分（包含多个原始片段）"""
        # 安全获取original_indices属性
        original_indices = getattr(segment, 'original_indices', [])
        return len(original_indices) > 1
    
    def _split_segment_by_original_boundaries(self, segment_index: int):
        """按原始SRT片段边界拆分段落"""
        if segment_index >= len(self.edited_segments) or segment_index < 0:
            st.error("❌ 拆分失败：段落索引无效")
            return
        
        segment = self.edited_segments[segment_index]
        
        # 安全获取original_indices属性
        original_indices = getattr(segment, 'original_indices', [])
        if len(original_indices) <= 1:
            st.warning("⚠️ 此段落只包含一个原始片段，无法拆分")
            return
        
        try:
            # 删除原始段落
            original_segment = self.edited_segments.pop(segment_index)
            
            # 为每个原始片段创建新的段落
            new_segments = []
            for original_idx in original_indices:
                # 找到对应的原始片段（original_indices是从1开始的）
                if original_idx <= len(self.original_segments):
                    original_seg = self.original_segments[original_idx - 1]
                    
                    # 创建新段落，使用原始片段的准确时间码
                    new_seg = SegmentDTO(
                        id=f"seg_{original_idx}",
                        start=original_seg.start,
                        end=original_seg.end,
                        original_text=original_seg.original_text,
                        translated_text="",  # 拆分后需要重新翻译
                        optimized_text="",   # 拆分后需要重新优化
                        final_text=original_seg.original_text,
                        target_duration=original_seg.target_duration,
                        original_indices=[original_idx]  # 只包含自己
                    )
                    
                    new_segments.append(new_seg)
            
            # 插入新段落
            for i, new_seg in enumerate(new_segments):
                self.edited_segments.insert(segment_index + i, new_seg)
            
            # 重新组织ID
            self._reorganize_segment_ids()
            
            # 同步到session_state
            st.session_state.segmentation_edited_segments = self.edited_segments.copy()
            logger.debug(f"🔄 拆分后同步状态，当前共 {len(self.edited_segments)} 个段落")
            
            # 调整当前页码，确保能看到拆分后的段落
            self._adjust_current_page_for_split(segment_index, len(new_segments))
            
            st.success(f"✅ 段落已按原始片段边界拆分为 {len(new_segments)} 个部分")
            
            # 显示拆分详情
            with st.expander("📋 拆分详情", expanded=True):
                split_segments = self.edited_segments[segment_index:segment_index + len(new_segments)]
                st.info(f"原段落包含 {len(original_indices)} 个原始片段，已拆分为：")
                for i, seg in enumerate(split_segments):
                    st.write(f"**{seg.id}:** `{seg.start:.1f}s - {seg.end:.1f}s` {seg.get_current_text()[:50]}...")
                
                # 显示当前总段落数和页面信息
                st.write(f"当前总段落数：{len(self.edited_segments)}，当前页码：{self.current_page}")
        
        except Exception as e:
            # 如果拆分失败，恢复原始段落
            if 'original_segment' in locals():
                self.edited_segments.insert(segment_index, original_segment)
            st.error(f"❌ 拆分失败：{str(e)}")
            logger.error(f"拆分段落时发生错误: {e}", exc_info=True)
    

    
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
            st.session_state.segmentation_current_page = self.current_page
    
    def _adjust_current_page_for_split(self, split_index: int, new_segments_count: int):
        """拆分后调整页码，确保用户能看到拆分的结果"""
        segments_per_page = 8
        total_segments = len(self.edited_segments)
        total_pages = (total_segments + segments_per_page - 1) // segments_per_page
        
        # 计算拆分位置应该在哪一页
        target_page = (split_index // segments_per_page) + 1
        
        # 确保页码在有效范围内
        target_page = max(1, min(target_page, total_pages))
        
        # 更新当前页码
        self.current_page = target_page
        st.session_state.segmentation_current_page = self.current_page
    
    def _adjust_current_page_for_merge(self, merge_index: int):
        """合并后调整页码，确保用户能看到合并的结果"""
        segments_per_page = 8
        total_segments = len(self.edited_segments)
        total_pages = (total_segments + segments_per_page - 1) // segments_per_page
        
        # 计算合并位置应该在哪一页
        target_page = (merge_index // segments_per_page) + 1
        
        # 确保页码在有效范围内
        target_page = max(1, min(target_page, total_pages))
        
        # 更新当前页码
        self.current_page = target_page
        st.session_state.segmentation_current_page = self.current_page
    
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