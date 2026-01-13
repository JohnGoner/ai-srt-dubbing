"""
工程管理视图组件
提供工程列表、选择、创建、分享等功能界面
"""

import streamlit as st
from typing import Dict, Any, Optional, List
from pathlib import Path
from loguru import logger
import tempfile
import json
from datetime import datetime

from utils.project_integration import get_project_integration
from utils.project_manager import get_project_manager
from models.project_dto import ProjectDTO


class ProjectManagementView:
    """工程管理视图组件"""
    
    def __init__(self):
        """初始化工程管理视图"""
        self.project_integration = get_project_integration()
        self.project_manager = get_project_manager()
    
    def render_project_home(self) -> Dict[str, Any]:
        """
        渲染工程管理主页（极简设计）
        
        Returns:
            包含action和数据的结果字典
        """
        st.header("🎬 AI配音工程")
        st.markdown("创建新工程或继续未完成的工作")
        
        # 检查是否需要显示阶段选择界面
        if st.session_state.get('action') == 'show_stage_selection':
            selected_project_id = st.session_state.get('selected_project_id')
            if selected_project_id:
                return self._render_stage_selection(selected_project_id)
        
        # 侧边栏统计信息（简化版）
        self._render_sidebar_statistics()
        
        # 主要内容：创建新工程 + 工程列表
        return self._render_main_content()
    
    def _render_main_content(self) -> Dict[str, Any]:
        """渲染主要内容（极简设计）"""
        projects = self.project_manager.list_projects()
        
        # 创建新工程按钮（始终显示在顶部）
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            if st.button("➕ 创建新工程", type="primary", use_container_width=True, key="main_create_project"):
                return {"action": "create_new_project"}
        
        # 如果没有工程，显示欢迎信息
        if not projects:
            st.markdown("---")
            st.info("🎯 还没有工程，点击上方按钮开始您的第一个配音项目！")
            return {"action": "none"}
        
        # 工程列表（简化搜索）
        st.markdown("---")
        col1, col2 = st.columns([3, 1])
        with col1:
            search_query = st.text_input("🔍 搜索工程", placeholder="输入工程名称...")
        with col2:
            show_advanced = st.checkbox("高级选项", key="show_advanced_options")
        
        # 高级选项（可折叠）
        if show_advanced:
            col1, col2, col3 = st.columns(3)
            with col1:
                status_filter = st.selectbox("状态", ["全部"] + list(set(p.get("processing_stage", "") for p in projects)))
            with col2:
                sort_by = st.selectbox("排序", ["更新时间", "创建时间", "名称", "进度"])
            with col3:
                if st.button("🔄 迁移缓存", help="从旧缓存系统迁移工程"):
                    self._migrate_from_cache()
        else:
            status_filter = "全部"
            sort_by = "更新时间"
        
        # 应用筛选
        filtered_projects = self._filter_projects(projects, search_query, status_filter)
        sorted_projects = self._sort_projects(filtered_projects, sort_by)
        
        if not sorted_projects:
            st.warning("没有找到匹配的工程")
            return {"action": "none"}
        
        st.markdown(f"**找到 {len(sorted_projects)} 个工程**")
        
        # 工程列表（简化卡片）
        for i, project_info in enumerate(sorted_projects):
            project_id = project_info["id"]
            
            # 检查是否需要显示删除确认对话框
            if st.session_state.get(f"show_delete_confirm_{project_id}", False):
                # 显示删除确认对话框
                self._confirm_delete_project(project_id, project_info["name"])
            else:
                # 正常显示工程卡片
                self._render_simple_project_card(project_info, i)
        
        return {"action": "none"}
    
    def _render_simple_project_card(self, project_info: Dict[str, Any], index: int):
        """渲染简化的工程卡片 (极简设计)"""
        try:
            project_id = project_info["id"]
            name = project_info["name"]
            description = project_info.get("description", "")
            status = project_info.get("processing_stage", "unknown")
            progress = project_info.get("completion_percentage", 0)
            target_lang = project_info.get("target_language", "")
            updated_at = project_info.get("updated_at", "").split("T")[0]
            
            with st.container():
                # 标题和基本信息
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.markdown(f"#### 📁 {name}")
                    if description:
                        st.caption(description[:100] + ("..." if len(description) > 100 else ""))
                    st.caption(f"🌍 {target_lang.upper() if target_lang else '未设置'} | 📅 {updated_at}")
                
                with col2:
                    status_name = self._get_stage_display_name(status)
                    if progress >= 100:
                        st.success(f"{status_name}")
                    else:
                        st.info(f"{status_name} ({progress:.0f}%)")
                
                # 操作按钮 (图标化)
                col1, col2, col3, col4, col5, col6 = st.columns([2, 1, 1, 1, 1, 2])
                
                with col1:
                    if st.button("🚀 继续", key=f"continue_{project_id}_{index}", use_container_width=True, type="primary"):
                        st.session_state['selected_project_id'] = project_id
                        st.session_state['action'] = 'show_stage_selection'
                        st.rerun()
                
                with col2:
                    if st.button("📋", key=f"details_{project_id}_{index}", help="详情", use_container_width=True):
                        self._show_project_details(project_id)
                
                with col3:
                    if st.button("📤", key=f"export_{project_id}_{index}", help="导出", use_container_width=True):
                        self._export_project(project_id, name)
                
                with col4:
                    if st.button("📄", key=f"duplicate_{project_id}_{index}", help="复制", use_container_width=True):
                        self._duplicate_project(project_id, name)
                
                with col5:
                    if st.button("🗑️", key=f"delete_{project_id}_{index}", help="删除", use_container_width=True):
                        st.session_state[f"show_delete_confirm_{project_id}"] = True
                        st.rerun()
                
                st.markdown('<div style="margin-bottom: 2rem;"></div>', unsafe_allow_html=True)
                        
        except Exception as e:
            logger.error(f"渲染简化工程卡片失败: {e}")
            st.error(f"显示工程信息时出错: {str(e)}")
    
    def _render_sidebar_statistics(self):
        """渲染侧边栏统计信息（简化版）"""
        with st.sidebar:
            st.header("📊 统计")
            
            try:
                stats = self.project_manager.get_projects_statistics()
                total_projects = stats.get("total_projects", 0)
                total_size_mb = stats.get("total_size_mb", 0)
                
                st.metric("工程数", total_projects)
                if total_size_mb > 0:
                    st.text(f"💾 {total_size_mb:.1f}MB")
                
                # 只显示有意义的语言分布
                language_stats = stats.get("language_statistics", {})
                if language_stats and total_projects > 1:
                    st.markdown("**语言分布:**")
                    for lang, count in sorted(language_stats.items(), key=lambda x: x[1], reverse=True)[:3]:
                        st.text(f"• {lang.upper()}: {count}")
                
            except Exception as e:
                st.text("统计信息不可用")
    
    # 旧的复杂方法已被简化版本替代，保留用于向后兼容
    def _render_projects_list(self) -> Dict[str, Any]:
        """渲染工程列表（向后兼容）"""
        return self._render_main_content()
    
    # 简化版本已取代复杂的tab系统，保留核心功能方法
    def _show_project_details(self, project_id: str):
        """显示工程详情（简化版）"""
        project = self.project_manager.load_project(project_id)
        if project:
            with st.expander(f"📋 工程详情: {project.name}", expanded=True):
                col1, col2 = st.columns(2)
                with col1:
                    st.text(f"ID: {project.id}")
                    st.text(f"创建: {project.created_at.split('T')[0]}")
                    st.text(f"更新: {project.updated_at.split('T')[0]}")
                with col2:
                    st.text(f"语言: {project.target_language or '未设置'}")
                    st.text(f"片段: {project.total_segments}")
                    st.text(f"时长: {project.total_duration:.1f}s")
                
                if project.description:
                    st.text(f"描述: {project.description}")
                if project.tags:
                    st.text(f"标签: {', '.join(project.tags)}")
    
    def _filter_projects(self, projects: List[Dict[str, Any]], search_query: str, status_filter: str) -> List[Dict[str, Any]]:
        """筛选工程"""
        filtered = projects
        
        # 搜索筛选
        if search_query:
            query_lower = search_query.lower()
            filtered = [
                p for p in filtered
                if query_lower in p.get("name", "").lower() or 
                   query_lower in p.get("description", "").lower()
            ]
        
        # 状态筛选
        if status_filter != "全部":
            filtered = [p for p in filtered if p.get("processing_stage") == status_filter]
        
        return filtered
    
    def _sort_projects(self, projects: List[Dict[str, Any]], sort_by: str) -> List[Dict[str, Any]]:
        """排序工程"""
        if sort_by == "更新时间":
            return sorted(projects, key=lambda x: x.get("updated_at", ""), reverse=True)
        elif sort_by == "创建时间":
            return sorted(projects, key=lambda x: x.get("created_at", ""), reverse=True)
        elif sort_by == "名称":
            return sorted(projects, key=lambda x: x.get("name", ""))
        elif sort_by == "进度":
            return sorted(projects, key=lambda x: x.get("completion_percentage", 0), reverse=True)
        else:
            return projects
    

    
    def _duplicate_project(self, project_id: str, project_name: str):
        """复制工程"""
        try:
            new_project = self.project_manager.duplicate_project(project_id, f"{project_name} - 副本")
            if new_project:
                st.success(f"✅ 工程复制成功: {new_project.name}")
                st.rerun()
            else:
                st.error("❌ 工程复制失败")
        except Exception as e:
            st.error(f"❌ 复制过程中发生错误: {str(e)}")
    
    def _export_project(self, project_id: str, project_name: str):
        """导出工程"""
        try:
            export_path = self.project_manager.export_project(project_id)
            if export_path:
                # 创建安全的文件名
                backslash = '\\'
                safe_filename = f"{project_name.replace('<', '_').replace('>', '_').replace(':', '_').replace('/', '_').replace(backslash, '_').replace('|', '_').replace('?', '_').replace('*', '_')}.zip"
                
                # 提供下载链接
                with open(export_path, 'rb') as f:
                    file_data = f.read()
                
                st.download_button(
                    label="📥 下载导出文件",
                    data=file_data,
                    file_name=safe_filename,
                    mime="application/zip"
                )
                st.success("✅ 工程导出成功！")
            else:
                st.error("❌ 工程导出失败")
        except Exception as e:
            st.error(f"❌ 导出过程中发生错误: {str(e)}")
    
    def _confirm_delete_project(self, project_id: str, project_name: str):
        """确认删除工程 - 简化版"""
        # 使用模态对话框样式的确认
        st.markdown("---")
        st.warning(f"⚠️ **确认删除工程**: `{project_name}`")
        st.markdown("**此操作不可撤销！所有相关数据将被永久删除。**")
        
        col1, col2, col3 = st.columns([1, 1, 2])
        
        with col1:
            # 确认删除按钮
            if st.button(
                "🗑️ 确认删除", 
                type="primary", 
                key=f"confirm_delete_{project_id}",
                help="永久删除此工程"
            ):
                try:
                    logger.info(f"用户确认删除工程: {project_name} (ID: {project_id})")
                    
                    # 执行删除
                    success = self.project_manager.delete_project(project_id)
                    
                    if success:
                        st.success(f"✅ 工程 `{project_name}` 删除成功！")
                        logger.info(f"✅ 工程删除成功: {project_name} (ID: {project_id})")
                        
                        # 清理删除确认状态
                        if f"show_delete_confirm_{project_id}" in st.session_state:
                            del st.session_state[f"show_delete_confirm_{project_id}"]
                        
                        # 清理所有相关的session状态
                        keys_to_remove = []
                        for key in st.session_state.keys():
                            if str(project_id) in str(key):
                                keys_to_remove.append(key)
                        
                        for key in keys_to_remove:
                            logger.debug(f"清理session状态: {key}")
                            del st.session_state[key]
                        
                        # 强制刷新页面
                        st.rerun()
                        
                    else:
                        st.error("❌ 删除失败：请检查工程是否正在使用中")
                        logger.error(f"❌ 工程删除返回False: {project_name} (ID: {project_id})")
                        
                except Exception as e:
                    error_msg = f"删除工程时发生错误: {str(e)}"
                    st.error(f"❌ {error_msg}")
                    logger.error(f"❌ 删除工程异常: {project_name} (ID: {project_id}) - {e}", exc_info=True)
        
        with col2:
            # 取消按钮  
            if st.button(
                "❌ 取消", 
                key=f"cancel_delete_{project_id}",
                help="取消删除操作"
            ):
                # 清除删除确认状态
                if f"show_delete_confirm_{project_id}" in st.session_state:
                    del st.session_state[f"show_delete_confirm_{project_id}"]
                st.info("已取消删除操作")
                st.rerun()
        
        with col3:
            st.markdown("")  # 空白列，用于布局
    
    def _batch_export_projects(self, project_ids: List[str]):
        """批量导出工程"""
        try:
            exported_files = []
            for project_id in project_ids:
                export_path = self.project_manager.export_project(project_id)
                if export_path:
                    exported_files.append(export_path)
            
            if exported_files:
                st.success(f"✅ 成功导出 {len(exported_files)} 个工程")
                # 这里可以创建一个包含所有导出文件的ZIP包
            else:
                st.error("❌ 批量导出失败")
        except Exception as e:
            st.error(f"❌ 批量导出过程中发生错误: {str(e)}")
    
    def _migrate_from_cache(self):
        """从缓存系统迁移"""
        try:
            cache_manager = self.project_integration.cache_integration.cache_manager
            migrated_count = self.project_manager.migrate_from_cache(cache_manager)
            
            if migrated_count > 0:
                st.success(f"✅ 成功迁移 {migrated_count} 个工程")
                st.rerun()
            else:
                st.info("💡 没有发现可迁移的缓存数据")
        except Exception as e:
            st.error(f"❌ 迁移过程中发生错误: {str(e)}")
    
    def _get_stage_display_name(self, stage: str) -> str:
        """获取阶段显示名称"""
        stage_names = {
            'file_upload': '文件上传',
            'segmentation': '智能分段',
            'confirm_segmentation': '分段确认',
            'language_selection': '语言选择',
            'translating': '翻译中',
            'user_confirmation': '音频确认',
            'completion': '已完成'
        }
        return stage_names.get(stage, stage)
    
    def _render_stage_selection(self, project_id: str) -> Dict[str, Any]:
        """
        渲染阶段选择界面
        
        Args:
            project_id: 工程ID
            
        Returns:
            包含action和数据的结果字典
        """
        try:
            # 加载工程信息
            project = self.project_manager.load_project(project_id)
            if not project:
                st.error("❌ 工程不存在或已损坏")
                return {"action": "back_to_home"}
            
            st.header(f"🎯 选择继续阶段 - {project.name}")
            st.markdown("选择从哪个阶段继续处理这个工程")
            
            # 分析工程可用的阶段
            available_stages = self._analyze_available_stages(project)
            
            # 显示工程基本信息
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("完成度", f"{project.completion_percentage:.0f}%")
            with col2:
                st.metric("目标语言", project.target_language or "未设置")
            with col3:
                st.metric("片段数量", project.total_segments or 0)
            
            st.markdown("---")
            
            # 阶段选择
            st.subheader("📋 可选择的处理阶段")
            
            for stage_key, stage_info in available_stages.items():
                with st.container():
                    col1, col2 = st.columns([3, 1])
                    
                    with col1:
                        # 显示阶段信息
                        icon = stage_info["icon"]
                        name = stage_info["name"]
                        status = stage_info["status"]
                        
                        if status == "completed":
                            st.success(f"{icon} **{name}** ✅")

                        elif status == "available":
                            st.info(f"{icon} **{name}**")

                        else:
                            st.warning(f"{icon} **{name}** ⚠️")
                            st.text(f"   (需要先完成前置阶段)")
                    
                    with col2:
                        if status in ["completed", "available"]:
                            if st.button(
                                "选择", 
                                key=f"select_stage_{stage_key}",
                                use_container_width=True,
                                type="primary" if status == "available" else "secondary"
                            ):
                                return {
                                    "action": "load_project_stage",
                                    "project_id": project_id,
                                    "target_stage": stage_key
                                }
                        else:
                            st.button(
                                "不可用", 
                                key=f"disabled_stage_{stage_key}",
                                use_container_width=True,
                                disabled=True
                            )
            
            # 底部操作按钮
            st.markdown("---")
            col1, col2 = st.columns(2)
            
            with col1:
                if st.button("🔙 返回工程列表", use_container_width=True):
                    # 清理状态
                    if 'action' in st.session_state:
                        del st.session_state['action']
                    if 'selected_project_id' in st.session_state:
                        del st.session_state['selected_project_id']
                    return {"action": "back_to_home"}
            
            with col2:
                if st.button("🚀 继续当前阶段", type="primary", use_container_width=True):
                    return {
                        "action": "load_project_stage",
                        "project_id": project_id,
                        "target_stage": project.processing_stage
                    }
            
            return {"action": "none"}
            
        except Exception as e:
            logger.error(f"渲染阶段选择界面失败: {e}")
            st.error(f"❌ 显示阶段选择时出错: {str(e)}")
            return {"action": "back_to_home"}
    
    def _analyze_available_stages(self, project: ProjectDTO) -> Dict[str, Dict[str, str]]:
        """
        分析工程可用的阶段
        
        Args:
            project: 工程对象
            
        Returns:
            可用阶段的字典
        """
        stages = {
            "initial": {
                "icon": "📁", 
                "name": "文件分析",

                "status": "hidden"
            },
            "segmentation": {
                "icon": "✂️", 
                "name": "分段编辑",

                "status": "not_available"
            },
            "confirm_segmentation": {
                "icon": "✅", 
                "name": "确认分段",

                "status": "not_available"
            },
            "language_selection": {
                "icon": "🌍", 
                "name": "语言选择",

                "status": "not_available"
            },
            "translating": {
                "icon": "🔄", 
                "name": "翻译进行中",

                "status": "hidden"
            },
            "user_confirmation": {
                "icon": "🎵", 
                "name": "音频确认",

                "status": "not_available"
            },
            "completion": {
                "icon": "🎉", 
                "name": "完成",

                "status": "not_available"
            }
        }
        
        # 根据工程数据判断各阶段状态
        if project.segments:
            stages["initial"]["status"] = "completed"
            stages["segmentation"]["status"] = "available"
        
        if project.segmented_segments:
            stages["segmentation"]["status"] = "completed"
            stages["confirm_segmentation"]["status"] = "available"
        
        if project.confirmed_segments:
            stages["confirm_segmentation"]["status"] = "completed"
            stages["language_selection"]["status"] = "available"
        
        if project.translated_segments:
            stages["language_selection"]["status"] = "completed"
            stages["user_confirmation"]["status"] = "available"
        
        if project.optimized_segments:
            stages["user_confirmation"]["status"] = "available"  # 可以重新确认
        
        if project.final_segments:
            stages["user_confirmation"]["status"] = "completed"
            stages["completion"]["status"] = "available"
        
        # 特殊处理：如果当前阶段是completion，标记为可用
        if project.processing_stage == "completion":
            stages["completion"]["status"] = "available"
        
        return stages
