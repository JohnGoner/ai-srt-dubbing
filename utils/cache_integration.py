"""
缓存集成模块
在各个处理阶段集成缓存功能，提供缓存检查、保存和恢复功能
"""

from typing import Dict, Any, Optional, List, Tuple
from loguru import logger
from .cache_manager import get_cache_manager
from pathlib import Path
import streamlit as st
import time


class CacheIntegration:
    """缓存集成类"""
    
    def __init__(self):
        """初始化缓存集成"""
        self.cache_manager = get_cache_manager()
    
    def check_srt_cache(self, file_path: str) -> Optional[Dict[str, Any]]:
        """
        检查SRT文件信息缓存
        
        Args:
            file_path: SRT文件路径
            
        Returns:
            缓存的SRT信息，如果不存在则返回None
        """
        try:
            cached_data = self.cache_manager.get_cache_entry(file_path, "srt_info")
            if cached_data:
                logger.info(f"找到SRT信息缓存: {Path(file_path).name}")
                return cached_data
            return None
        except Exception as e:
            logger.error(f"检查SRT缓存失败: {e}")
            return None
    
    def save_srt_cache(self, file_path: str, srt_info: Dict[str, Any]) -> bool:
        """
        保存SRT文件信息缓存
        
        Args:
            file_path: SRT文件路径
            srt_info: SRT文件信息
            
        Returns:
            是否成功保存
        """
        try:
            return self.cache_manager.set_cache_entry(file_path, "srt_info", srt_info)
        except Exception as e:
            logger.error(f"保存SRT缓存失败: {e}")
            return False
    
    def check_segmentation_cache(self, file_path: str) -> Optional[Dict[str, Any]]:
        """
        检查分段信息缓存
        
        Args:
            file_path: SRT文件路径
            
        Returns:
            缓存的分段信息，如果不存在则返回None
        """
        try:
            cached_data = self.cache_manager.get_cache_entry(file_path, "segmentation")
            if cached_data:
                logger.info(f"找到分段缓存: {Path(file_path).name}")
                return cached_data
            return None
        except Exception as e:
            logger.error(f"检查分段缓存失败: {e}")
            return None

    def save_confirmed_segmentation_cache(self, file_path: str, confirmed_segments: List[Dict[str, Any]], original_segments: List[Dict[str, Any]]) -> bool:
        """
        保存用户确认后的分段信息缓存
        
        Args:
            file_path: SRT文件路径
            confirmed_segments: 用户确认后的分段数据
            original_segments: 原始片段数据
            
        Returns:
            是否成功保存
        """
        try:
            # 保存segmentation缓存（包含原始和确认数据）
            segmentation_data = {
                "original_segments": original_segments,
                "confirmed_segments": confirmed_segments,
                "confirmation_timestamp": time.time()
            }
            seg_result = self.cache_manager.set_cache_entry(file_path, "segmentation", segmentation_data)
            
            # 同时保存confirmation缓存（仅包含确认数据，用于快速恢复）
            confirmation_data = {
                "original_segments": original_segments,  # 同时保存原始分段
                "confirmed_segments": confirmed_segments,
                "confirmation_timestamp": time.time(),
                "cache_type": "segmentation_confirmation"
            }
            conf_result = self.cache_manager.set_cache_entry(file_path, "confirmation", confirmation_data)
            
            return seg_result and conf_result
        except Exception as e:
            logger.error(f"保存确认分段缓存失败: {e}")
            return False
    
    def check_translation_cache(self, file_path: str, target_lang: str) -> Optional[Dict[str, Any]]:
        """
        检查翻译信息缓存
        
        Args:
            file_path: SRT文件路径
            target_lang: 目标语言
            
        Returns:
            缓存的翻译信息，如果不存在则返回None
        """
        try:
            # 优先检查用户确认后的翻译缓存
            confirmed_cache = self.cache_manager.get_cache_entry(file_path, "translation_confirmed", target_lang=target_lang)
            if confirmed_cache:
                logger.info(f"找到用户确认后的翻译缓存: {Path(file_path).name} -> {target_lang}")
                confirmed_cache['is_user_confirmed'] = True
                return confirmed_cache
            
            # 如果没有用户确认的缓存，则检查初次翻译缓存
            initial_cache = self.cache_manager.get_cache_entry(file_path, "translation", target_lang=target_lang)
            if initial_cache:
                logger.info(f"找到初次翻译缓存: {Path(file_path).name} -> {target_lang}")
                initial_cache['is_user_confirmed'] = False
                return initial_cache
            
            return None
        except Exception as e:
            logger.error(f"检查翻译缓存失败: {e}")
            return None
    
    def save_translation_cache(self, file_path: str, target_lang: str, translation_data: Dict[str, Any]) -> bool:
        """
        保存翻译信息缓存
        
        Args:
            file_path: SRT文件路径
            target_lang: 目标语言
            translation_data: 翻译数据
            
        Returns:
            是否成功保存
        """
        try:
            # 检查是否为用户确认后的翻译
            is_user_confirmed = translation_data.get('is_user_confirmed', False)
            
            # 选择合适的缓存类型
            cache_type = "translation_confirmed" if is_user_confirmed else "translation"
            
            logger.info(f"保存翻译缓存 ({cache_type}): {Path(file_path).name} -> {target_lang}")
            
            result = self.cache_manager.set_cache_entry(file_path, cache_type, translation_data, target_lang=target_lang)
            return result
            
        except Exception as e:
            logger.error(f"保存翻译缓存失败: {e}")
            return False
    
    def check_confirmation_cache(self, file_path: str, target_lang: str) -> Optional[Dict[str, Any]]:
        """
        检查用户确认信息缓存
        
        Args:
            file_path: SRT文件路径
            target_lang: 目标语言
            
        Returns:
            缓存的确认信息，如果不存在则返回None
        """
        try:
            cached_data = self.cache_manager.get_cache_entry(file_path, "confirmation", target_lang=target_lang)
            if cached_data:
                logger.info(f"找到确认信息缓存: {Path(file_path).name} -> {target_lang}")
                return cached_data
            return None
        except Exception as e:
            logger.error(f"检查确认缓存失败: {e}")
            return None
    
    def save_confirmation_cache(self, file_path: str, target_lang: str, confirmation_data: Dict[str, Any]) -> bool:
        """
        保存用户确认信息缓存
        
        Args:
            file_path: SRT文件路径
            target_lang: 目标语言
            confirmation_data: 确认数据
            
        Returns:
            是否成功保存
        """
        try:
            return self.cache_manager.set_cache_entry(file_path, "confirmation", confirmation_data, target_lang=target_lang)
        except Exception as e:
            logger.error(f"保存确认缓存失败: {e}")
            return False
    
    def get_all_related_caches(self, file_path: str, skip_validation: bool = False) -> Dict[str, List[Dict[str, Any]]]:
        """
        获取与文件相关的所有缓存
        
        Args:
            file_path: 文件路径或内容哈希
            skip_validation: 是否跳过文件验证（用于临时文件场景）
            
        Returns:
            按类型分组的缓存信息
        """
        try:
            # 支持使用内容哈希直接匹配
            if len(file_path) == 32 and all(c in '0123456789abcdef' for c in file_path.lower()):
                # 这是一个MD5哈希值
                target_hash = file_path
                related_caches = []
                for entry in self.cache_manager.cache_index["cache_entries"].values():
                    if entry["file_hash"] == target_hash:
                        related_caches.append(entry)
            else:
                # 原始的文件路径匹配
                if skip_validation:
                    # 跳过文件验证，直接返回所有相关缓存
                    related_caches = []
                    for cache_key, entry in self.cache_manager.cache_index["cache_entries"].items():
                        # 检查缓存数据文件是否存在
                        cache_data_path = self.cache_manager.cache_data_dir / f"{cache_key}.pkl"
                        if cache_data_path.exists():
                            related_caches.append(entry)
                else:
                    related_caches = self.cache_manager.find_related_caches(file_path)
            
            # 按类型分组
            grouped_caches = {}
            for cache in related_caches:
                cache_type = cache["cache_type"]
                if cache_type not in grouped_caches:
                    grouped_caches[cache_type] = []
                grouped_caches[cache_type].append(cache)
            
            return grouped_caches
        except Exception as e:
            logger.error(f"获取相关缓存失败: {e}")
            return {}
    
    def show_cache_selection_interface(self, file_path: str) -> Optional[Dict[str, Any]]:
        """
        显示缓存选择界面
        
        Args:
            file_path: 文件路径
            
        Returns:
            用户选择的缓存数据，如果用户选择重新处理则返回None
        """
        try:
            # 对于临时文件，跳过文件验证
            related_caches = self.get_all_related_caches(file_path, skip_validation=True)
            
            if not related_caches:
                # 没有缓存的情况
                st.header("🔍 缓存检查结果")
                st.info(f"文件 `{Path(file_path).name}` 没有发现缓存数据")
                st.markdown("### 选择处理方式:")
                
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("🚀 开始新处理", type="primary", use_container_width=True, key="start_new_processing"):
                        return {"action": "new_processing"}
                
                with col2:
                    if st.button("🔙 返回", use_container_width=True, key="back_to_upload"):
                        return {"action": "back"}
                
                return None
            
            st.header("🔍 发现本地缓存")
            st.info(f"检测到文件 `{Path(file_path).name}` 的本地缓存，您可以选择使用缓存或重新处理")
            
            # 显示缓存统计
            cache_stats = self.cache_manager.get_cache_statistics()
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("总缓存条目", cache_stats.get("total_entries", 0))
            with col2:
                st.metric("缓存大小", f"{cache_stats.get('cache_directory_size_mb', 0):.1f} MB")
            with col3:
                st.metric("相关缓存", len([c for caches in related_caches.values() for c in caches]))
            
            # 显示相关缓存详情
            with st.expander("📋 缓存详情"):
                for cache_type, caches in related_caches.items():
                    st.subheader(f"{self._get_cache_type_name(cache_type)} ({len(caches)} 个)")
                    
                    for i, cache in enumerate(caches):
                        created_time = cache.get("created_at", "")
                        access_count = cache.get("access_count", 0)
                        extra_params = cache.get("extra_params", {})
                        
                        # 格式化时间
                        if created_time:
                            try:
                                from datetime import datetime
                                dt = datetime.fromisoformat(created_time.replace('Z', '+00:00'))
                                formatted_time = dt.strftime("%Y-%m-%d %H:%M:%S")
                            except:
                                formatted_time = created_time
                        else:
                            formatted_time = "未知"
                        
                        # 显示缓存信息
                        cache_info = f"**缓存 {i+1}:** 创建于 {formatted_time}, 访问 {access_count} 次"
                        if extra_params:
                            params_str = ", ".join([f"{k}={v}" for k, v in extra_params.items()])
                            cache_info += f", 参数: {params_str}"
                        
                        st.text(cache_info)
            
            # 缓存选择选项
            st.subheader("🎯 选择处理方式")
            
            # 检查是否有完整的处理流程缓存
            has_complete_flow = (
                "segmentation" in related_caches and
                "translation" in related_caches and
                "confirmation" in related_caches
            )
            
            if has_complete_flow:
                st.success("✅ 发现完整的处理流程缓存")
                
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("🚀 使用完整缓存", type="primary", key="use_complete_cache"):
                        # 返回完整的缓存数据
                        return self._get_complete_cache_data(file_path, related_caches)
                
                with col2:
                    if st.button("🔄 重新处理", key="reprocess_all"):
                        return {"action": "new_processing"}
            
            # 部分缓存选项
            st.subheader("🔧 部分缓存选项")
            
            cache_options = []
            
            if "segmentation" in related_caches:
                cache_options.append(("segmentation", "智能分段结果"))
            
            if "translation" in related_caches:
                cache_options.append(("translation", "翻译结果"))
            
            if "confirmation" in related_caches:
                cache_options.append(("confirmation", "用户确认结果"))
            
            # 显示部分缓存选项
            for cache_type, description in cache_options:
                if st.button(f"📋 使用{description}", key=f"use_{cache_type}_cache"):
                    logger.info(f"[show_cache_selection_interface] 用户选择了 {cache_type} 缓存")
                    return self._get_cache_data_by_type(file_path, cache_type, related_caches)
            
            # 重新处理选项
            st.markdown("---")
            col1, col2 = st.columns(2)
            with col1:
                if st.button("🆕 完全重新处理", key="reprocess_complete", use_container_width=True):
                    return {"action": "new_processing"}
            
            with col2:
                if st.button("🔙 返回", key="back_to_upload", use_container_width=True):
                    return {"action": "back"}
            
            return None
            
        except Exception as e:
            logger.error(f"显示缓存选择界面失败: {e}")
            return None
    
    def _get_cache_type_name(self, cache_type: str) -> str:
        """获取缓存类型的中文名称"""
        type_names = {
            "srt_info": "SRT文件信息",
            "segmentation": "智能分段",
            "translation": "翻译结果",
            "confirmation": "用户确认"
        }
        return type_names.get(cache_type, cache_type)
    
    def _get_complete_cache_data(self, file_path: str, related_caches: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
        """获取完整的缓存数据"""
        try:
            complete_data = {}
            
            # 获取分段缓存
            if "segmentation" in related_caches:
                seg_cache = related_caches["segmentation"][0]  # 使用最新的
                seg_data = self.cache_manager.get_cache_entry(file_path, "segmentation", skip_validation=True)
                if seg_data:
                    complete_data["segmentation"] = seg_data
                    # 如果有用户确认的分段数据，也添加到返回结果中
                    if "confirmed_segments" in seg_data:
                        complete_data["confirmed_segments"] = seg_data["confirmed_segments"]
            
            # 获取翻译缓存
            if "translation" in related_caches:
                trans_cache = related_caches["translation"][0]  # 使用最新的
                target_lang = trans_cache.get("extra_params", {}).get("target_lang", "en")
                trans_data = self.cache_manager.get_cache_entry(file_path, "translation", skip_validation=True, target_lang=target_lang)
                if trans_data:
                    complete_data["translation"] = trans_data
                    complete_data["target_lang"] = target_lang
            
            # 获取确认缓存
            if "confirmation" in related_caches:
                conf_cache = related_caches["confirmation"][0]  # 使用最新的
                target_lang = conf_cache.get("extra_params", {}).get("target_lang", "en")
                conf_data = self.cache_manager.get_cache_entry(file_path, "confirmation", skip_validation=True, target_lang=target_lang)
                if conf_data:
                    complete_data["confirmation"] = conf_data
            
            return complete_data
            
        except Exception as e:
            logger.error(f"获取完整缓存数据失败: {e}")
            return {}
    
    def _get_cache_data_by_type(self, file_path: str, cache_type: str, related_caches: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
        """根据类型获取缓存数据"""
        try:
            if cache_type not in related_caches:
                return {}
            
            cache_entry = related_caches[cache_type][0]  # 使用最新的
            extra_params = cache_entry.get("extra_params", {})
            
            logger.info(f"[_get_cache_data_by_type] 处理 {cache_type} 缓存，extra_params: {extra_params}")
            
            if cache_type == "segmentation":
                seg_data = self.cache_manager.get_cache_entry(file_path, "segmentation", skip_validation=True)
                if seg_data and "confirmed_segments" in seg_data:
                    # 如果有用户确认的数据，同时返回segmentation和confirmation数据
                    result = {"segmentation": seg_data, "confirmed_segments": seg_data["confirmed_segments"]}
                    
                    # 检查是否也有独立的confirmation缓存
                    conf_data = self.cache_manager.get_cache_entry(file_path, "confirmation", skip_validation=True)
                    if conf_data:
                        result["confirmation"] = conf_data
                    
                    return result
                else:
                    # 否则返回原始分段数据
                    return {"segmentation": seg_data}
            
            elif cache_type in ["translation", "translation_confirmed"]:
                target_lang = extra_params.get("target_lang", "en")
                
                # 检查是否有用户确认后的翻译缓存
                confirmed_data = None
                if "translation_confirmed" in related_caches:
                    confirmed_entry = next((entry for entry in related_caches["translation_confirmed"] 
                                          if entry.get("extra_params", {}).get("target_lang") == target_lang), None)
                    if confirmed_entry:
                        confirmed_data = self.cache_manager.get_cache_entry(file_path, "translation_confirmed", 
                                                                         skip_validation=True, target_lang=target_lang)
                
                # 检查初次翻译缓存
                initial_data = None
                if "translation" in related_caches:
                    initial_entry = next((entry for entry in related_caches["translation"] 
                                        if entry.get("extra_params", {}).get("target_lang") == target_lang), None)
                    if initial_entry:
                        initial_data = self.cache_manager.get_cache_entry(file_path, "translation", 
                                                                       skip_validation=True, target_lang=target_lang)
                
                # 优先使用用户确认后的翻译缓存
                result = {}
                if confirmed_data:
                    confirmed_data['is_user_confirmed'] = True
                    result["translation"] = confirmed_data
                elif initial_data:
                    initial_data['is_user_confirmed'] = False
                    result["translation"] = initial_data
                
                result["target_lang"] = target_lang
                return result
            
            elif cache_type == "confirmation":
                # 直接从缓存索引中获取数据，避免键生成问题
                cache_key = cache_entry.get("cache_key")
                if cache_key:
                    # 直接从缓存文件读取数据
                    cache_file = self.cache_manager.cache_data_dir / f"{cache_key}.pkl"
                    if cache_file.exists():
                        import pickle
                        with open(cache_file, 'rb') as f:
                            conf_data = pickle.load(f)
                        
                        logger.info(f"[_get_cache_data_by_type] 直接从文件读取 confirmation 缓存，keys: {list(conf_data.keys())}")
                        
                        result = {
                            "confirmation": conf_data,
                            "target_lang": extra_params.get("target_lang", "en")
                        }
                        
                        # 如果选择confirmation缓存，也需要获取segmentation缓存中的original_segments
                        seg_data = self.cache_manager.get_cache_entry(file_path, "segmentation", skip_validation=True)
                        if seg_data:
                            result["segmentation"] = seg_data
                        
                        return result
                    else:
                        logger.error(f"[_get_cache_data_by_type] confirmation 缓存文件不存在: {cache_file}")
                else:
                    logger.error(f"[_get_cache_data_by_type] confirmation 缓存条目缺少 cache_key")
                
            return {}
            
        except Exception as e:
            logger.error(f"[_get_cache_data_by_type] 获取 {cache_type} 缓存数据失败: {e}")
            return {}
    
    def clear_file_cache(self, file_path: str) -> bool:
        """
        清除指定文件的所有缓存
        
        Args:
            file_path: 文件路径
            
        Returns:
            是否成功清除
        """
        try:
            related_caches = self.get_all_related_caches(file_path, skip_validation=True)
            cleared_count = 0
            
            for cache_type, caches in related_caches.items():
                for cache in caches:
                    cache_key = cache.get("cache_key")
                    if cache_key:
                        self.cache_manager._remove_cache_entry(cache_key)
                        cleared_count += 1
            
            logger.info(f"清除了 {cleared_count} 个缓存条目")
            return True
            
        except Exception as e:
            logger.error(f"清除文件缓存失败: {e}")
            return False


# 全局缓存集成实例
global_cache_integration = CacheIntegration()


def get_cache_integration() -> CacheIntegration:
    """获取全局缓存集成实例"""
    return global_cache_integration 