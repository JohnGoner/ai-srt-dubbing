"""
基于Streamlit的AI配音系统用户界面 - SRT字幕配音版
"""

import streamlit as st
import os
import tempfile
from pathlib import Path
import sys

# 添加项目根目录到Python路径
sys.path.append(str(Path(__file__).parent.parent))

from audio_processor.subtitle_processor import SubtitleProcessor
from audio_processor.subtitle_segmenter import SubtitleSegmenter
from translation.translator import Translator
from tts.azure_tts import AzureTTS
from timing.sync_manager import AdvancedSyncManager
from utils.config_manager import ConfigManager
from utils.file_utils import get_file_info, validate_srt_file


def create_default_config(openai_key: str = "", azure_key: str = "", azure_region: str = "eastus") -> dict:
    """
    创建默认配置
    
    Args:
        openai_key: OpenAI API密钥
        azure_key: Azure Speech Services密钥
        azure_region: Azure区域
        
    Returns:
        配置字典
    """
    return {
        "api_keys": {
            "openai_api_key": openai_key,
            "azure_speech_key_1": azure_key,
            "azure_speech_region": azure_region,
            "azure_speech_endpoint": f"https://{azure_region}.api.cognitive.microsoft.com/"
        },
        "translation": {
            "model": "gpt-4o",
            "max_tokens": 4000,
            "temperature": 0.3,
            "system_prompt": """你是一个专业的配音翻译专家。请将中文文本翻译成指定的目标语言，
需要考虑以下要求：
1. 保持语义准确和上下文连贯
2. 考虑时间码约束，确保翻译后的文本能在指定时间内读完
3. 保持自然的语言表达
4. 适合配音的语调和节奏"""
        },
        "tts": {
            "azure": {
                "voices": {
                    "en": "en-US-AndrewMultilingualNeural",
                    "es": "es-MX-JorgeNeural",
                    "fr": "fr-FR-DeniseNeural",
                    "de": "de-DE-KatjaNeural",
                    "ja": "ja-JP-NanamiNeural",
                    "ko": "ko-KR-SunHiNeural"
                }
            },
            "speech_rate": 1.0,
            "pitch": 0,
            "volume": 90
        },
        "timing": {
            "max_speed_ratio": 1.15,
            "min_speed_ratio": 0.95,
            "silence_padding": 0.1,
            "sync_tolerance": 0.15,
            "max_speed_variation": 0.1
        },
        "output": {
            "audio_format": "mp3",
            "sample_rate": 48000,
            "channels": 1,
            "bit_depth": 16
        },
        "logging": {
            "level": "INFO",
            "log_file": "logs/dubbing.log",
            "max_log_size": "10MB",
            "backup_count": 5
        },
        "supported_languages": [
            {"code": "en", "name": "English", "voice": "en-US-AndrewMultilingualNeural"},
            {"code": "es", "name": "Spanish", "voice": "es-MX-JorgeNeural"},
            {"code": "fr", "name": "French", "voice": "fr-FR-DeniseNeural"},
            {"code": "de", "name": "German", "voice": "de-DE-KatjaNeural"},
            {"code": "ja", "name": "Japanese", "voice": "ja-JP-NanamiNeural"},
            {"code": "ko", "name": "Korean", "voice": "ko-KR-SunHiNeural"}
        ]
    }


def validate_config(config: dict) -> tuple[bool, str]:
    """
    验证配置
    
    Args:
        config: 配置字典
        
    Returns:
        (是否有效, 错误消息)
    """
    try:
        # 检查必需的API密钥
        if not config.get("api_keys", {}).get("openai_api_key"):
            return False, "OpenAI API密钥不能为空"
        
        if not config.get("api_keys", {}).get("azure_speech_key_1"):
            return False, "Azure Speech Services密钥不能为空"
        
        if not config.get("api_keys", {}).get("azure_speech_region"):
            return False, "Azure区域不能为空"
        
        return True, ""
        
    except Exception as e:
        return False, f"配置验证失败: {str(e)}"


def main():
    """主应用程序"""
    st.set_page_config(
        page_title="AI配音系统 - SRT版",
        page_icon="🎬",
        layout="wide"
    )
    
    st.title("🎬 AI配音系统 - SRT字幕配音版")
    st.markdown("将中文SRT字幕智能翻译并配音到多种语言")
    
    # 侧边栏配置
    with st.sidebar:
        st.header("⚙️ 配置")
        
        # 使用智能配置管理器自动加载config.yaml
        config = None
        config_manager = ConfigManager()
        
        # 尝试自动加载配置文件
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
                
                # 显示找到的配置文件路径
                st.info(f"📂 配置文件: `{config_info['path']}`")
                
                # 提供重新配置选项
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("🔄 重新加载"):
                        if config_manager.reload_config():
                            st.success("重新加载成功")
                            st.rerun()
                        else:
                            st.error("重新加载失败")
                
                with col2:
                    if st.button("⚙️ 手动配置"):
                        config = None
                        st.rerun()
                    
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
                if st.button("📝 创建默认配置文件"):
                    template = config_manager.get_config_template()
                    project_root = Path(__file__).parent.parent
                    config_path = project_root / "config.yaml"
                    
                    if config_manager.save_config(template, str(config_path)):
                        st.success(f"✅ 默认配置文件已创建: {config_path}")
                        st.info("请编辑配置文件并添加您的API密钥")
                        st.rerun()
                    else:
                        st.error("❌ 创建配置文件失败")
                
        except Exception as e:
            st.error(f"❌ 配置管理器初始化失败: {str(e)}")
            config = None
        
        # 如果没有自动加载成功，提供手动配置选项
        if config is None:
            st.info("💡 未找到 config.yaml 或加载失败，请手动配置")
            
            # 配置模式选择
            config_mode = st.radio(
                "选择配置方式",
                ["手动输入API密钥", "上传配置文件"],
                help="可以直接输入API密钥，或上传完整的配置文件"
            )
            
            if config_mode == "上传配置文件":
                # 配置文件上传
                config_file = st.file_uploader("选择配置文件", type=['yaml', 'yml'])
                
                if config_file:
                    # 保存上传的配置文件
                    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
                        f.write(config_file.getvalue().decode())
                        config_path = f.name
                    
                    try:
                        config_manager = ConfigManager()
                        config = config_manager.load_config(config_path)
                        if config:
                            st.success("配置文件加载成功")
                        else:
                            st.error("配置文件加载失败")
                            return
                    except Exception as e:
                        st.error(f"配置文件加载失败: {str(e)}")
                        return
                else:
                    st.info("请上传配置文件")
                    with st.expander("📄 查看配置文件示例"):
                        st.code("""
# API配置
api_keys:
  openai_api_key: "your-openai-api-key"
  azure_speech_key_1: "your-azure-speech-key"
  azure_speech_region: "your-region"

# 翻译配置
translation:
  model: "gpt-4o"
  temperature: 0.3

# TTS配置  
tts:
  azure:
    voices:
      en: "en-US-AndrewMultilingualNeural"
      es: "es-MX-JorgeNeural"
                        """, language="yaml")
                    return
            else:
                # 手动输入API密钥模式
                st.subheader("🔑 API密钥配置")
                
                # OpenAI配置
                openai_key = st.text_input(
                    "OpenAI API密钥",
                    type="password",
                    help="用于翻译功能，获取地址：https://platform.openai.com/api-keys"
                )
                
                # Azure Speech Services配置
                azure_key = st.text_input(
                    "Azure Speech Services密钥",
                    type="password",
                    help="用于语音合成功能，获取地址：https://portal.azure.com"
                )
                
                azure_region = st.selectbox(
                    "Azure区域",
                    ["eastus", "westus", "westus2", "eastus2", "centralus", "northcentralus", "southcentralus", "westcentralus"],
                    help="选择Azure Speech Services所在区域"
                )
                
                # 验证API密钥
                if openai_key and azure_key:
                    config = create_default_config(openai_key, azure_key, azure_region)
                    is_valid, error_msg = validate_config(config)
                    
                    if is_valid:
                        st.success("✅ 配置验证成功")
                    else:
                        st.error(f"❌ 配置验证失败: {error_msg}")
                        return
                else:
                    st.warning("请输入OpenAI API密钥和Azure Speech Services密钥")
                    st.markdown("**获取API密钥的方法：**")
                    st.markdown("1. **OpenAI API密钥**: 访问 [OpenAI Platform](https://platform.openai.com/api-keys)")
                    st.markdown("2. **Azure Speech Services密钥**: 访问 [Azure Portal](https://portal.azure.com)")
                    return
    
    # 检查是否已经在处理中
    if 'processing_stage' in st.session_state and st.session_state.processing_stage != 'initial':
        # 如果已经在处理中，显示处理界面
        if config:
            handle_processing_stages(config)
        return
    
    # 如果processing_stage是'initial'，也需要处理
    if st.session_state.get('processing_stage') == 'initial':
        if config:
            handle_processing_stages(config)
        return
    
    # 主界面 - 文件上传阶段
    st.header("📝 Step 1: 上传SRT字幕文件")
    
    # 文件上传
    uploaded_file = st.file_uploader(
        "选择SRT字幕文件",
        type=['srt'],
        help="请确保SRT文件包含准确的中文字幕和时间码"
    )
    
    if uploaded_file:
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
                st.metric("文件大小", f"{file_info['size_mb']:.2f} MB")
            with col2:
                st.metric("文件类型", "SRT字幕")
            with col3:
                st.metric("状态", "✅ 验证通过")
            
            # 预览字幕内容
            with st.expander("👀 预览字幕内容"):
                try:
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
            
            # 智能分段分析按钮
            st.markdown("---")
            st.header("🧠 Step 2: 智能分段分析")
            st.markdown("AI将分析您的字幕内容，优化分段逻辑以获得更好的翻译和配音效果")
            
            col1, col2, col3 = st.columns([2, 1, 2])
            with col2:
                if st.button("🚀 开始智能分段分析", type="primary", use_container_width=True, key="start_analysis"):
                    if config:
                        # 保存文件路径到session state
                        st.session_state.input_file_path = input_file_path
                        st.session_state.processing_stage = 'initial'
                        # 清理之前的分析结果
                        for key in ['original_segments', 'segmented_segments']:
                            if key in st.session_state:
                                del st.session_state[key]
                        st.rerun()
                    else:
                        st.error("请先完成API配置")
                        
            st.markdown("**💡 智能分段的优势:**")
            st.markdown("- 🔗 将相关的字幕片段合并为完整的语义单元")
            st.markdown("- 🎯 提高翻译准确性和上下文理解")
            st.markdown("- 🗣️ 优化配音的自然度和流畅性")
            st.markdown("- ⏱️ 改善时间同步的精确度")
            
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


def handle_processing_stages(config: dict):
    """处理各个处理阶段"""
    stage = st.session_state.get('processing_stage', 'initial')
    
    # 显示当前状态（调试信息）
    with st.expander("🔍 系统状态（调试信息）"):
        st.write(f"当前阶段: {stage}")
        st.write(f"文件路径: {st.session_state.get('input_file_path', '未设置')}")
        st.write(f"原始片段数: {len(st.session_state.get('original_segments', []))}")
        st.write(f"分段片段数: {len(st.session_state.get('segmented_segments', []))}")
        st.write(f"目标语言: {st.session_state.get('target_lang', '未设置')}")
    
    if stage == 'initial':
        # 执行智能分段分析
        input_file_path = st.session_state.get('input_file_path')
        if input_file_path:
            perform_segmentation_analysis(input_file_path, config)
        else:
            st.error("❌ 未找到文件路径，请重新上传文件")
            st.session_state.processing_stage = 'initial'
    
    elif stage == 'confirm_segmentation':
        # 显示分段确认界面
        segments = st.session_state.get('original_segments')
        segmented_segments = st.session_state.get('segmented_segments')
        if segments and segmented_segments:
            show_segmentation_confirmation(segments, segmented_segments, config)
        else:
            st.error("❌ 分段数据丢失，请重新分析")
            st.session_state.processing_stage = 'initial'
    
    elif stage == 'language_selection':
        # 显示语言选择和处理选项
        show_language_selection(config)
    
    elif stage == 'processing':
        # 执行翻译和配音处理
        confirmed_segments = st.session_state.get('confirmed_segments')
        target_lang = st.session_state.get('target_lang')
        if confirmed_segments and target_lang:
            process_confirmed_segments(confirmed_segments, target_lang, config)
        else:
            st.error("❌ 确认的分段数据或目标语言丢失")
            st.session_state.processing_stage = 'language_selection'
    
    elif stage == 'completed':
        # 显示完成结果
        show_completion_results_persistent()


def perform_segmentation_analysis(input_path: str, config: dict):
    """执行智能分段分析"""
    st.header("🧠 智能分段分析中...")
    
    # 检查是否已经处理过，避免重复处理
    if (st.session_state.get('original_segments') is not None and 
        st.session_state.get('segmented_segments') is not None):
        st.session_state.processing_stage = 'confirm_segmentation'
        st.rerun()
        return
    
    # 创建进度条
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    try:
        # 步骤1: 加载字幕
        status_text.text("🔄 正在加载SRT字幕...")
        progress_bar.progress(20)
        
        subtitle_processor = SubtitleProcessor(config)
        segments = subtitle_processor.load_subtitle(input_path)
        st.session_state.original_segments = segments
        
        progress_bar.progress(40)
        status_text.text(f"✅ 字幕加载完成，共 {len(segments)} 个片段")
        
        # 步骤2: 智能分段处理
        status_text.text("🧠 正在进行智能分段分析...")
        progress_bar.progress(60)
        
        segmenter = SubtitleSegmenter(config)
        segmented_segments = segmenter.segment_subtitles(segments)
        st.session_state.segmented_segments = segmented_segments
        
        progress_bar.progress(80)
        status_text.text(f"✅ 智能分段完成，优化后共 {len(segmented_segments)} 个段落")
        
        progress_bar.progress(100)
        status_text.text("📝 分析完成，请查看结果...")
        
        # 设置阶段为确认
        st.session_state.processing_stage = 'confirm_segmentation'
        
        # 立即刷新到下一个阶段
        st.rerun()
        
    except Exception as e:
        st.error(f"❌ 分段分析过程中发生错误: {str(e)}")
        st.exception(e)
        # 重置状态
        st.session_state.processing_stage = 'initial'
        # 清理错误状态
        for key in ['original_segments', 'segmented_segments']:
            if key in st.session_state:
                del st.session_state[key]
    finally:
        # 清理临时文件（延迟清理，确保不会影响其他处理）
        if os.path.exists(input_path):
            try:
                os.unlink(input_path)
            except:
                pass  # 忽略删除错误


def show_segmentation_confirmation(segments: list, segmented_segments: list, config: dict):
    """显示分段确认界面"""
    
    # 🎨 美化的标题和说明
    st.markdown("""
    ## 🧠 Step 2: 智能分段结果
    """)
    
    # 关键信息卡片
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric(
            label="📄 原始片段", 
            value=len(segments),
            help="从SRT文件中读取的原始字幕片段数量"
        )
    with col2:
        st.metric(
            label="🎯 智能分段", 
            value=len(segmented_segments),
            delta=f"{len(segmented_segments) - len(segments):+d}",
            help="AI重新组织后的逻辑段落数量"
        )
    with col3:
        avg_duration = sum(seg['duration'] for seg in segmented_segments) / len(segmented_segments)
        st.metric(
            label="⏱️ 平均时长", 
            value=f"{avg_duration:.1f}秒",
            help="每个分段的平均持续时间"
        )
    with col4:
        avg_quality = sum(seg.get('quality_score', 0.5) for seg in segmented_segments) / len(segmented_segments)
        st.metric(
            label="⭐ 质量评分", 
            value=f"{avg_quality:.2f}",
            help="AI分段的质量评估分数"
        )
    
    # 可折叠的详细对比
    with st.expander("🔍 查看详细对比", expanded=True):
        # 使用选项卡来分别显示原始和分段结果
        tab1, tab2 = st.tabs(["📝 原始片段", "🎯 智能分段"])
        
        with tab1:
            st.caption(f"显示前10个原始片段（共{len(segments)}个）")
            for i, seg in enumerate(segments[:10]):
                with st.container():
                    col1, col2 = st.columns([1, 4])
                    with col1:
                        st.markdown(f"**#{seg['id']}**")
                        st.markdown(f"`{seg['start']:.1f}s - {seg['end']:.1f}s`")
                    with col2:
                        st.markdown(f"💬 {seg['text']}")
                if i < 9:  # 不在最后一个添加分隔线
                    st.divider()
            
            if len(segments) > 10:
                st.info(f"📋 还有 {len(segments) - 10} 个片段未显示")
        
        with tab2:
            st.caption(f"显示前10个智能分段（共{len(segmented_segments)}个）")
            for i, seg in enumerate(segmented_segments[:10]):
                with st.container():
                    col1, col2, col3 = st.columns([1, 4, 1])
                    with col1:
                        st.markdown(f"**段落 {seg['id']}**")
                        st.markdown(f"`{seg['start']:.1f}s - {seg['end']:.1f}s`")
                        st.markdown(f"*({seg['duration']:.1f}秒)*")
                    with col2:
                        st.markdown(f"📖 {seg['text']}")
                    with col3:
                        original_count = seg.get('original_count', 1)
                        quality_score = seg.get('quality_score', 0.5)
                        st.markdown(f"🔄 合并了 **{original_count}** 个片段")
                        # 质量评分可视化
                        if quality_score >= 0.8:
                            st.success(f"⭐ {quality_score:.2f}")
                        elif quality_score >= 0.6:
                            st.info(f"⭐ {quality_score:.2f}")
                        else:
                            st.warning(f"⭐ {quality_score:.2f}")
                if i < 9:
                    st.divider()
            
            if len(segmented_segments) > 10:
                st.info(f"📋 还有 {len(segmented_segments) - 10} 个段落未显示")
    
    # 美化的确认按钮区域
    st.markdown("---")
    st.markdown("### ✅ 请选择处理方式")
    
    col1, col2, col3 = st.columns([1, 1, 1])
    
    with col1:
        st.markdown("#### 🚀 推荐方式")
        if st.button(
            "✨ 使用智能分段结果", 
            type="primary", 
            use_container_width=True,
            key="use_smart_segments",
            help="使用AI优化后的分段结果，获得更好的翻译和配音效果"
        ):
            st.session_state.confirmed_segments = segmented_segments
            st.session_state.processing_stage = 'language_selection'
            st.rerun()
    
    with col2:
        st.markdown("#### 📄 保守方式")
        if st.button(
            "📋 使用原始片段", 
            type="secondary", 
            use_container_width=True,
            key="use_original_segments",
            help="保持原始SRT文件的分段方式"
        ):
            st.session_state.confirmed_segments = segments
            st.session_state.processing_stage = 'language_selection'
            st.rerun()
    
    with col3:
        st.markdown("#### 🔄 重新开始")
        if st.button(
            "🔙 返回上传", 
            use_container_width=True,
            key="restart_upload",
            help="重新上传SRT文件"
        ):
            # 重置所有状态
            for key in ['processing_stage', 'original_segments', 'segmented_segments']:
                if key in st.session_state:
                    del st.session_state[key]
            st.rerun()
    
    # 添加一些使用建议
    st.markdown("---")
    with st.expander("💡 选择建议"):
        st.markdown("""
        **🚀 推荐使用智能分段**，因为：
        - ✅ **逻辑更完整**：将破碎的句子重新组织成完整的段落
        - ✅ **翻译质量更好**：AI可以更好地理解完整的语境
        - ✅ **配音效果更自然**：避免在句子中间停顿
        - ✅ **时间同步更精确**：更合理的时长分布
        
        **📄 原始片段适用于**：
        - 原始SRT文件已经有很好的分段结构
        - 需要保持与原始字幕完全一致的时间码
        """)


def show_language_selection(config: dict):
    """显示语言选择和处理选项"""
    st.header("🌐 Step 3: 选择目标语言和处理选项")
    
    # 语言选择
    st.subheader("🗣️ 目标语言")
    languages = {
        'en': '英语 (English)',
        'es': '西班牙语 (Español)',
        'fr': '法语 (Français)',
        'de': '德语 (Deutsch)',
        'ja': '日语 (日本語)',
        'ko': '韩语 (한국어)'
    }
    
    target_lang = st.selectbox(
        "选择目标配音语言",
        options=list(languages.keys()),
        format_func=lambda x: languages[x],
        help="选择您希望将字幕翻译并配音的目标语言"
    )
    
    # 处理选项
    st.subheader("🔧 配音选项")
    col1, col2 = st.columns(2)
    
    with col1:
        speech_rate = st.slider(
            "语速", 
            0.5, 2.0, 1.0, 0.1,
            help="调整配音语速，1.0为正常速度"
        )
        
        translation_temp = st.slider(
            "翻译创意度", 
            0.0, 1.0, 0.3, 0.1,
            help="较低值更保守准确，较高值更有创意灵活"
        )
    
    with col2:
        pitch = st.slider(
            "音调", 
            -50, 50, 0, 5,
            help="调整配音音调，0为默认音调"
        )
        
        # 显示选择的语音
        selected_voice = config.get('tts', {}).get('azure', {}).get('voices', {}).get(target_lang, 'N/A')
        st.info(f"🎤 将使用语音: {selected_voice}")
    
    # 开始配音处理按钮
    st.markdown("---")
    col1, col2, col3 = st.columns([2, 1, 2])
    with col2:
        if st.button("🎬 开始配音处理", type="primary", use_container_width=True, key="start_dubbing"):
            # 更新配置
            config['tts']['speech_rate'] = speech_rate
            config['tts']['pitch'] = pitch
            config['translation']['temperature'] = translation_temp
            
            # 保存配置到session state
            st.session_state.target_lang = target_lang
            st.session_state.config = config
            st.session_state.processing_stage = 'processing'
            st.rerun()
    
    # 返回按钮
    col1, col2, col3 = st.columns([2, 1, 2])
    with col2:
        if st.button("🔙 返回分段选择", use_container_width=True, key="back_to_segmentation"):
            st.session_state.processing_stage = 'confirm_segmentation'
            st.rerun()


def process_confirmed_segments(segments: list, target_lang: str, config: dict):
    """处理用户确认的分段"""
    
    # 创建美化的进度界面
    st.markdown("## 🎬 正在生成配音...")
    
    # 创建进度条容器
    progress_container = st.container()
    with progress_container:
        progress_bar = st.progress(0)
        status_text = st.empty()
        stage_info = st.empty()
    
    try:
        # 步骤2: 翻译
        with stage_info:
            st.info("🌐 步骤2: 智能翻译字幕...")
        status_text.text("正在连接翻译服务...")
        progress_bar.progress(10)
        
        translator = Translator(config)
        status_text.text("正在翻译智能分段（用于配音）...")
        translated_segments = translator.translate_segments(segments, target_lang)
        
        # 同时翻译原始片段（用于字幕文件）
        status_text.text("正在翻译原始片段（用于字幕文件）...")
        original_segments = st.session_state.get('original_segments', segments)
        translated_original_segments = translator.translate_segments(original_segments, target_lang)
        
        progress_bar.progress(50)
        with stage_info:
            st.success("✅ 翻译完成")
        
        # 步骤3: 循环逼近时间同步优化
        with stage_info:
            st.info("⏱️ 步骤3: 循环逼近时间同步优化...")
        status_text.text("正在初始化TTS服务...")
        progress_bar.progress(60)
        
        tts = AzureTTS(config)
        sync_manager = AdvancedSyncManager(config)
        
        status_text.text("正在进行时间同步优化...")
        optimized_segments = sync_manager.optimize_timing_with_iteration(
            translated_segments, target_lang, translator, tts
        )
        
        progress_bar.progress(85)
        with stage_info:
            st.success("✅ 时间同步优化完成")
        
        # 步骤4: 音频合并
        with stage_info:
            st.info("🎵 步骤4: 合并音频...")
        status_text.text("正在合并所有音频片段...")
        progress_bar.progress(90)
        
        final_audio = sync_manager.merge_audio_segments(optimized_segments)
        
        # 保存结果
        audio_output = f"dubbed_audio_{target_lang}.wav"
        subtitle_output = f"translated_subtitle_{target_lang}.srt"
        
        subtitle_processor = SubtitleProcessor(config)
        
        status_text.text("正在保存文件...")
        final_audio.export(audio_output, format="wav")
        # 保存字幕时使用原始片段的翻译
        subtitle_processor.save_subtitle(translated_original_segments, subtitle_output, 'srt')
        
        progress_bar.progress(100)
        with stage_info:
            st.success("🎉 配音生成完成！")
        status_text.text("所有处理已完成！")
        
        # 保存完成结果数据到session state
        with open(audio_output, 'rb') as f:
            audio_data = f.read()
        with open(subtitle_output, 'rb') as f:
            subtitle_data = f.read()
        
        # 计算统计信息
        total_duration = max(seg['end'] for seg in segments)
        excellent_count = sum(1 for seg in optimized_segments if seg.get('sync_quality') == 'excellent')
        
        st.session_state.completion_results = {
            'audio_data': audio_data,
            'subtitle_data': subtitle_data,
            'target_lang': target_lang,
            'optimized_segments': optimized_segments,
            'stats': {
                'total_segments': len(segments),
                'total_duration': total_duration,
                'excellent_sync': excellent_count
            }
        }
        
        # 设置完成状态
        st.session_state.processing_stage = 'completed'
        st.rerun()
        
    except Exception as e:
        st.error(f"❌ 处理过程中发生错误: {str(e)}")
        st.exception(e)


def show_completion_results_persistent():
    """显示持久化的完成结果"""
    # 检查是否有保存的结果
    if 'completion_results' not in st.session_state:
        st.error("❌ 未找到处理结果，请重新开始")
        if st.button("🔄 重新开始", key="restart_from_error"):
            reset_all_states()
            st.rerun()
        return
    
    results = st.session_state.completion_results
    
    # 🎉 成功消息
    st.balloons()
    st.markdown("## 🎉 配音生成成功！")
    
    # 下载区域 - 使用持久化数据
    st.markdown("### 📥 下载文件")
    col1, col2 = st.columns(2)
    
    with col1:
        st.download_button(
            label="🎵 下载配音音频",
            data=results['audio_data'],
            file_name=f"dubbed_audio_{results['target_lang']}.wav",
            mime="audio/wav",
            use_container_width=True,
            help="下载生成的配音音频文件"
        )
    
    with col2:
        st.download_button(
            label="📄 下载翻译字幕",
            data=results['subtitle_data'],
            file_name=f"translated_subtitle_{results['target_lang']}.srt",
            mime="text/plain",
            use_container_width=True,
            help="下载翻译后的字幕文件"
        )
    
    # 音频播放器
    st.markdown("### 🎵 在线试听")
    st.audio(results['audio_data'], format='audio/wav')
    
    # 统计信息
    st.markdown("### 📊 处理统计")
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("字幕片段", results['stats']['total_segments'])
    
    with col2:
        st.metric("总时长", f"{results['stats']['total_duration']:.1f}秒")
    
    with col3:
        st.metric("目标语言", results['target_lang'].upper())
    
    with col4:
        st.metric("优秀同步", f"{results['stats']['excellent_sync']}项")
    
    # 详细结果
    with st.expander("📋 翻译结果对比"):
        optimized_segments = results['optimized_segments']
        for i, seg in enumerate(optimized_segments[:10]):
            col1, col2 = st.columns(2)
            with col1:
                st.markdown(f"**片段 {i+1}** `{seg['start']:.1f}s - {seg['end']:.1f}s`")
                # 安全地获取原文文本
                original_text = (seg.get('original_text') or 
                               seg.get('text') or 
                               seg.get('translated_text', '未找到原文'))
                st.markdown(f"🇨🇳 **原文**: {original_text}")
            with col2:
                st.markdown(f"🌐 **译文**: {seg['translated_text']}")
            st.divider()
        
        if len(optimized_segments) > 10:
            st.info(f"📋 还有 {len(optimized_segments) - 10} 个片段")
    
    # 操作按钮
    st.markdown("---")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button("🔄 处理新文件", use_container_width=True, key="new_file"):
            reset_all_states()
            st.rerun()
    
    with col2:
        if st.button("🎯 重新选择语言", use_container_width=True, key="reselect_language"):
            st.session_state.processing_stage = 'language_selection'
            st.rerun()
    
    with col3:
        if st.button("📋 重新分段", use_container_width=True, key="re_segment"):
            st.session_state.processing_stage = 'confirm_segmentation'
            st.rerun()


def reset_all_states():
    """重置所有状态"""
    keys_to_reset = [
        'processing_stage', 'original_segments', 'segmented_segments', 
        'confirmed_segments', 'target_lang', 'config', 'input_file_path',
        'completion_results'
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