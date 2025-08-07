"""
重构后的Streamlit应用 - 纯状态机调度器
只负责状态管理和session_state存取，不直接画UI
"""

import streamlit as st
import os
import tempfile
from pathlib import Path
import sys
from loguru import logger
from typing import Dict, Any

# 添加项目根目录到Python路径
sys.path.append(str(Path(__file__).parent.parent))

from models.segment_dto import SegmentDTO
from ui.workflow import WorkflowManager
from utils.config_manager import ConfigManager
from utils.file_utils import get_file_info, validate_srt_file
from utils.logger_config import setup_logging


def main():
    """主应用程序 - 纯状态机调度器"""
    st.set_page_config(
        page_title="AI配音系统 - SRT版",
        page_icon="🎬",
        layout="wide"
    )
    
    with st.sidebar:
        st.title("🎬 AI配音系统")
        st.markdown("将中文SRT字幕智能翻译并配音到多种语言")
    
    # 加载配置 - 简化版本，避免循环
    config = load_configuration_simple()
    if not config:
        return
    
    # 检查处理阶段
    processing_stage = st.session_state.get('processing_stage', 'file_upload')
    logger.debug(f"🔄 当前处理阶段: {processing_stage}")
    
    if processing_stage == 'file_upload':
        # 文件上传阶段 - 这是唯一需要在main中处理的UI
        logger.debug("📁 进入文件上传阶段")
        handle_file_upload()
    else:
        # 其他所有阶段都委托给WorkflowManager
        logger.info(f"🚀 处理阶段: {processing_stage}")
        workflow_manager = WorkflowManager(config)
        
        # 获取当前会话数据
        session_data = get_session_data()
        logger.debug(f"📊 会话数据状态: input_file_path={bool(session_data.get('input_file_path'))}, segments={len(session_data.get('segments', []))}, segmented_segments={len(session_data.get('segmented_segments', []))}")
        
        # 渲染当前阶段
        updated_session_data = workflow_manager.render_stage(processing_stage, session_data)
        
        # 更新会话数据
        update_session_data(updated_session_data)
        logger.debug(f"✅ 阶段处理完成，新状态: {updated_session_data.get('processing_stage', 'unknown')}")
        
        # 如果状态发生了变化，需要rerun来显示新的阶段
        if updated_session_data.get('processing_stage') != processing_stage:
            logger.info(f"🔄 状态转换: {processing_stage} → {updated_session_data.get('processing_stage')}")
            st.rerun()


def load_configuration_simple():
    """简化版配置加载 - 避免循环"""
    from utils.config_manager import get_global_config_manager
    config_manager = get_global_config_manager()
    
    try:
        config = config_manager.load_config()
        
        if config is not None:
            # 配置日志系统 - 在配置加载成功后立即设置
            setup_logging(config)
            
            # 验证配置文件
            is_valid, messages = config_manager.validate_config(config)
            
            if is_valid:
                st.sidebar.success("✅ 配置文件加载成功")
            else:
                st.sidebar.warning("⚠️ 配置文件存在问题")
                for message in messages:
                    if message.startswith("警告:"):
                        st.sidebar.warning(message)
                    else:
                        st.sidebar.error(message)
            
            return config
        else:
            # 如果没有配置文件，使用默认的INFO级别
            setup_logging(None, "INFO")
            st.sidebar.error("❌ 未找到配置文件")
            return None
            
    except Exception as e:
        # 如果加载失败，也要设置默认日志级别
        setup_logging(None, "INFO")
        st.sidebar.error(f"❌ 配置加载失败: {str(e)}")
        return None


def load_configuration():
    """加载配置 - 完整版本（暂时不使用）"""
    with st.sidebar:
        st.header("⚙️ 配置")
        
        from utils.config_manager import get_global_config_manager
        config_manager = get_global_config_manager()
        
        try:
            config = config_manager.load_config()
            
            if config is not None:
                # 验证配置文件
                is_valid, messages = config_manager.validate_config(config)
                
                if is_valid:
                    st.success("✅ 配置文件自动加载成功")
                else:
                    st.warning("⚠️ 配置文件加载成功但存在问题")
                
                # 显示配置信息
                config_info = config_manager.get_config_info()
                with st.expander("📋 配置详情"):
                    st.json({
                        "文件路径": config_info["path"],
                        "文件大小": config_info["size"],
                        "翻译模型": config_info["translation_model"],
                        "语音服务": "Azure Speech Services",
                        "支持语言": config_info["supported_languages"],
                        "语速设置": config_info["speech_rate"],
                        "音量设置": config_info["volume"],
                        "OpenAI密钥": "✅ 已配置" if config_info["has_openai_key"] else "❌ 未配置",
                        "Azure密钥": "✅ 已配置" if config_info["has_azure_key"] else "❌ 未配置",
                        "Azure区域": config_info["azure_region"]
                    })
                
                # 显示验证消息
                if messages:
                    with st.expander("🔍 配置验证"):
                        for message in messages:
                            if message.startswith("警告:"):
                                st.warning(message)
                            else:
                                st.error(message)
                
                st.info(f"📂 配置文件: `{config_info['path']}`")
                
                # 重新加载按钮
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("🔄 重新加载", key="reload_config"):
                        if config_manager.reload_config():
                            st.success("重新加载成功")
                            # st.rerun()  # 注释掉，避免循环
                        else:
                            st.error("重新加载失败")
                
                with col2:
                    if st.button("⚙️ 手动配置", key="manual_config"):
                        config = None
                        # st.rerun()  # 注释掉，避免循环
                
                return config
                
            else:
                st.warning("⚠️ 未找到配置文件")
                
                # 显示搜索路径
                search_paths = config_manager.get_search_paths()
                with st.expander("📍 搜索路径"):
                    for i, path in enumerate(search_paths, 1):
                        path_obj = Path(path)
                        status = "✅ 存在" if path_obj.exists() else "❌ 不存在"
                        st.text(f"{i}. {path} - {status}")
                
                st.info("💡 请确保 config.yaml 文件存在于项目根目录")
                
                # 提供创建配置文件的选项
                if st.button("📝 创建默认配置文件", key="create_default_config"):
                    template = config_manager.get_config_template()
                    project_root = Path(__file__).parent.parent
                    config_path = project_root / "config.yaml"
                    
                    if config_manager.save_config(template, str(config_path)):
                        st.success(f"✅ 默认配置文件已创建: {config_path}")
                        st.info("请编辑配置文件并添加您的API密钥")
                        # st.rerun()  # 注释掉，避免循环
                    else:
                        st.error("❌ 创建配置文件失败")
                
                return None
                
        except Exception as e:
            st.error(f"❌ 配置管理器初始化失败: {str(e)}")
            return None


def handle_file_upload():
    """处理文件上传阶段"""
    st.header("📝 Step 1: 上传SRT字幕文件")
    
    # 文件上传
    uploaded_file = st.file_uploader(
        "选择SRT字幕文件",
        type=['srt'],
        help="请确保SRT文件包含准确的中文字幕和时间码"
    )
    
    if uploaded_file:
        # 清理上一个会话的临时文件
        if 'input_file_path' in st.session_state and os.path.exists(st.session_state.input_file_path):
            try:
                os.unlink(st.session_state.input_file_path)
                logger.debug(f"清理了上一个临时文件: {st.session_state.input_file_path}")
            except Exception as e:
                logger.warning(f"清理旧的临时文件失败: {e}")

        # 验证文件大小
        if uploaded_file.size > 10 * 1024 * 1024:  # 10MB限制
            st.error("文件过大，请选择小于10MB的SRT文件")
            return
        
        # 保存上传的文件
        with tempfile.NamedTemporaryFile(delete=False, suffix='.srt') as tmp:
            tmp.write(uploaded_file.getvalue())
            input_file_path = tmp.name
        
        # 验证SRT文件格式
        if not validate_srt_file(input_file_path):
            st.error("❌ SRT文件格式不正确或文件损坏")
            st.markdown("**请确保文件符合以下要求:**")
            st.markdown("- 文件扩展名为 `.srt`")
            st.markdown("- 包含时间戳格式 (如: `00:00:01,000 --> 00:00:04,000`)")
            st.markdown("- 编码格式为 UTF-8 或 GBK")
            return
        
        # 显示文件信息
        file_info = get_file_info(input_file_path)
        if file_info:
            st.success(f"✅ 文件上传成功: {file_info['name']}")
            
            # 文件信息展示
            col1, col2, col3 = st.columns(3)
            with col1:
                size_kb = file_info.get('size_kb', file_info.get('size', 0) / 1024)
                st.metric("文件大小", f"{size_kb:.2f} KB")
            with col2:
                st.metric("文件类型", "SRT字幕")
            with col3:
                st.metric("状态", "✅ 验证通过")
            
            # 预览字幕内容
            show_subtitle_preview(input_file_path)
            
            # 智能分段分析按钮
            st.markdown("---")
            st.header("🧠 Step 2: 智能分段分析")
            st.markdown("AI将分析您的整个字幕文档，理解上下文进行智能分段，获得更好的翻译和配音效果")
            

            if st.button("🚀 开始智能分段分析", type="primary", use_container_width=True, key="start_analysis"):
                # 保存文件路径到session state并进入下一阶段
                logger.info(f"🎯 开始分段分析，文件: {Path(input_file_path).name}")
                st.session_state.input_file_path = input_file_path
                # st.session_state.processing_stage = 'cache_selection'  # 注释掉cache相关
                st.session_state.processing_stage = 'segmentation'  # 直接进入分段阶段
                logger.debug(f"🔄 状态已设置为: {st.session_state.processing_stage}")
                st.rerun()  # 用户点击后需要刷新页面
                        
            
    else:
        st.info("📁 请上传SRT字幕文件开始处理")
        
        # 帮助信息
        with st.expander("📖 SRT文件格式说明"):
            st.markdown("**标准SRT格式示例:**")
            st.code("""1
00:00:01,000 --> 00:00:04,000
这是第一句中文字幕

2
00:00:05,000 --> 00:00:08,000
这是第二句中文字幕

3
00:00:09,000 --> 00:00:12,000
这是第三句中文字幕""")
            
            st.markdown("**注意事项:**")
            st.markdown("- 每个字幕片段包含序号、时间戳和文本内容")
            st.markdown("- 时间格式: `时:分:秒,毫秒`")
            st.markdown("- 文件编码建议使用 UTF-8")
            st.markdown("- 文件大小限制: 10MB")


def show_subtitle_preview(input_file_path: str):
    """显示字幕预览"""
    with st.expander("👀 预览字幕内容"):
        try:
            from audio_processor.subtitle_processor import SubtitleProcessor
            subtitle_processor = SubtitleProcessor({})
            segments = subtitle_processor.load_subtitle(input_file_path)
            
            if segments:
                # 字幕统计信息
                total_duration = max(seg['end'] for seg in segments)
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("字幕片段数", len(segments))
                with col2:
                    st.metric("总时长", f"{total_duration:.1f}秒")
                with col3:
                    st.metric("平均时长", f"{total_duration/len(segments):.1f}秒/片段")
                
                # 显示前几个片段
                st.markdown("**前5个字幕片段:**")
                for i, seg in enumerate(segments[:5]):
                    with st.container():
                        st.markdown(f"**片段 {i+1}**")
                        st.code(f"时间: {seg['start']:.1f}s - {seg['end']:.1f}s\n内容: {seg['text']}")
                
                if len(segments) > 5:
                    st.info(f"... 还有 {len(segments) - 5} 个片段")
            else:
                st.warning("未能解析到字幕片段")
                
        except Exception as e:
            st.error(f"预览字幕失败: {str(e)}")
            st.markdown("**可能的原因:**")
            st.markdown("- 文件编码格式不支持")
            st.markdown("- SRT格式不规范")
            st.markdown("- 文件内容为空")


def get_session_data():
    """获取当前会话数据"""
    return {
        'processing_stage': st.session_state.get('processing_stage', 'file_upload'),
        'input_file_path': st.session_state.get('input_file_path'),
        'segments': st.session_state.get('segments', []),
        'segmented_segments': st.session_state.get('segmented_segments', []),
        'confirmed_segments': st.session_state.get('confirmed_segments', []),
        'translated_segments': st.session_state.get('translated_segments', []),
        'validated_segments': st.session_state.get('validated_segments', []),
        'optimized_segments': st.session_state.get('optimized_segments', []),
        'confirmation_segments': st.session_state.get('confirmation_segments', []),
        'translated_original_segments': st.session_state.get('translated_original_segments', []),
        'target_lang': st.session_state.get('target_lang'),
        'config': st.session_state.get('config'),
        'completion_results': st.session_state.get('completion_results'),
        'user_adjustment_choices': st.session_state.get('user_adjustment_choices', {}),
        # 'selected_cache': st.session_state.get('selected_cache'),  # 注释掉cache相关
        'current_confirmation_index': st.session_state.get('current_confirmation_index', 0),
        'confirmation_page': st.session_state.get('confirmation_page', 1)
    }


def update_session_data(updated_data: Dict[str, Any]):
    """更新会话数据"""
    logger.debug(f"🔄 开始更新会话数据，收到 {len(updated_data)} 个更新项")
    
    for key, value in updated_data.items():
        st.session_state[key] = value
    
    # 记录状态转换
    old_stage = st.session_state.get('_previous_stage')
    new_stage = updated_data.get('processing_stage')
    if old_stage != new_stage:
        logger.debug(f"🎯 状态转换: {old_stage} → {new_stage}")
        st.session_state['_previous_stage'] = new_stage
    
    logger.debug(f"✅ 会话数据更新完成，当前状态: {new_stage}")


def reset_all_states():
    """重置所有状态"""
    # 清理临时文件
    if 'input_file_path' in st.session_state and os.path.exists(st.session_state.input_file_path):
        try:
            os.unlink(st.session_state.input_file_path)
            logger.debug(f"清理了临时文件: {st.session_state.input_file_path}")
        except Exception as e:
            logger.warning(f"清理临时文件失败: {e}")

    keys_to_reset = [
        'processing_stage', 'segments', 'segmented_segments', 
        'confirmed_segments', 'target_lang', 'config', 'input_file_path',
        'completion_results', 'optimized_segments', 'confirmation_segments',
        'translated_original_segments', 'translated_segments', 'validated_segments',
        'current_confirmation_index', 'confirmation_page', 'user_adjustment_choices',
        # 分段视图的session_state
        'segmentation_edited_segments', 'segmentation_current_page', 'segmentation_original_segments'
        # 'selected_cache'  # 注释掉cache相关
    ]
    
    for key in keys_to_reset:
        if key in st.session_state:
            del st.session_state[key]


def run_streamlit_app(config=None):
    """运行Streamlit应用"""
    if config:
        # 如果提供了配置，将其保存到会话状态
        st.session_state['config'] = config
    
    main()


if __name__ == "__main__":
    main() 