"""
缓存选择视图组件
纯组件，不直接操作session_state
"""

import streamlit as st
from typing import Dict, Any


class CacheSelectionView:
    """缓存选择视图组件"""
    
    def render(self, input_file_path: str) -> Dict[str, Any]:
        """
        渲染缓存选择界面
        
        Args:
            input_file_path: 输入文件路径
            
        Returns:
            包含action和数据的结果字典
        """
        st.header("💾 检查缓存数据")
        
        try:
            from utils.cache_integration import get_cache_integration
            cache_integration = get_cache_integration()
            
            # 计算文件内容的哈希值用于缓存匹配
            with open(input_file_path, 'rb') as f:
                file_content = f.read()
            
            import hashlib
            content_hash = hashlib.md5(file_content).hexdigest()
            
            # 检查是否有相关缓存
            related_caches = cache_integration.get_all_related_caches(content_hash, skip_validation=True)
            
            if related_caches:
                # 将字典转换为列表
                cache_list = []
                for cache_type, cache_entries in related_caches.items():
                    cache_list.extend(cache_entries)
                
                st.success(f"✅ 发现 {len(cache_list)} 个相关缓存")
                
                # 显示缓存选项
                cache_options = ["开始新处理"]
                cache_descriptions = ["从头开始处理，不使用缓存"]
                
                for i, cache in enumerate(cache_list):
                    cache_type = self._determine_cache_type(cache)
                    cache_options.append(f"使用缓存 {i+1}: {cache_type}")
                    cache_descriptions.append(self._get_cache_description(cache))
                
                selected_index = st.radio(
                    "选择处理方式",
                    range(len(cache_options)),
                    format_func=lambda x: cache_options[x],
                    help="选择是开始新处理还是使用已有缓存"
                )
                
                # 显示选择的描述
                st.info(cache_descriptions[selected_index])
                
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("✅ 确认选择", type="primary", use_container_width=True):
                        if selected_index == 0:
                            return {'action': 'new_processing'}
                        else:
                            cache_data = cache_list[selected_index - 1]
                            return {
                                'action': 'use_cache',
                                'cache_data': cache_data
                            }
                
                with col2:
                    if st.button("🔙 返回", use_container_width=True):
                        return {'action': 'back'}
            else:
                st.info("💡 未发现相关缓存，将开始新处理")
                if st.button("🚀 开始新处理", type="primary", use_container_width=True):
                    return {'action': 'new_processing'}
                
                if st.button("🔙 返回", use_container_width=True):
                    return {'action': 'back'}
            
        except Exception as e:
            st.error(f"❌ 检查缓存时发生错误: {str(e)}")
            if st.button("🚀 开始新处理", type="primary", use_container_width=True):
                return {'action': 'new_processing'}
        
        # 默认返回（无操作）
        return {'action': 'none'}
    
    def _determine_cache_type(self, cache_data: Dict[str, Any]) -> str:
        """确定缓存类型"""
        if "confirmation" in cache_data and cache_data.get("confirmation"):
            return "完整处理结果"
        elif "translation" in cache_data and cache_data.get("translation"):
            return "翻译结果"
        elif "segmentation" in cache_data and cache_data.get("segmentation"):
            return "分段结果"
        else:
            return "未知类型"
    
    def _get_cache_description(self, cache_data: Dict[str, Any]) -> str:
        """获取缓存描述"""
        descriptions = []
        
        if "segmentation" in cache_data:
            seg_data = cache_data["segmentation"]
            if "confirmed_segments" in seg_data:
                count = len(seg_data["confirmed_segments"])
                descriptions.append(f"分段结果: {count} 个片段")
        
        if "translation" in cache_data:
            trans_data = cache_data["translation"]
            target_lang = cache_data.get("target_lang", "未知")
            descriptions.append(f"翻译结果: {target_lang}")
        
        if "confirmation" in cache_data:
            descriptions.append("音频确认结果")
        
        return " | ".join(descriptions) if descriptions else "详细信息不可用" 