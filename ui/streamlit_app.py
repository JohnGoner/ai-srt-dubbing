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
from audio_processor.simple_segmenter import SimpleSegmenter
from translation.translator import Translator
from tts.azure_tts import AzureTTS
from timing.sync_manager import AdvancedSyncManager
from utils.config_manager import ConfigManager
from utils.file_utils import get_file_info, validate_srt_file


def redistribute_translations_to_original_streamlit(translated_segments, original_segments):
    """
    将智能分段的翻译内容重新分配到原始时间分割上（Streamlit版本）
    确保音频和字幕使用相同的翻译内容，保持完全一致性
    
    Args:
        translated_segments: 翻译后的智能分段
        original_segments: 原始片段列表
        
    Returns:
        重新分配后的原始片段列表
    """
    try:
        redistributed_segments = []
        
        for orig_seg in original_segments:
            # 找到覆盖当前原始片段的智能分段
            covering_segment = None
            for trans_seg in translated_segments:
                if (trans_seg['start'] <= orig_seg['start'] and 
                    trans_seg['end'] >= orig_seg['end']):
                    covering_segment = trans_seg
                    break
            
            if covering_segment:
                # 计算原始片段在智能分段中的相对位置
                smart_duration = covering_segment['end'] - covering_segment['start']
                orig_start_offset = (orig_seg['start'] - covering_segment['start']) / smart_duration
                orig_end_offset = (orig_seg['end'] - covering_segment['start']) / smart_duration
                
                # 根据相对位置分割翻译文本
                translated_text = covering_segment['translated_text']
                
                # 简单的按比例分割
                if orig_start_offset <= 0.1:  # 智能分段的开头部分
                    if orig_end_offset >= 0.9:  # 覆盖整个智能分段
                        segment_text = translated_text
                    else:  # 只是开头部分
                        words = translated_text.split()
                        split_point = max(1, int(len(words) * orig_end_offset))
                        segment_text = ' '.join(words[:split_point])
                else:
                    # 中间或结尾部分
                    words = translated_text.split()
                    start_point = max(0, int(len(words) * orig_start_offset))
                    end_point = min(len(words), int(len(words) * orig_end_offset))
                    segment_text = ' '.join(words[start_point:end_point])
                
                # 如果分割结果为空，使用完整翻译
                if not segment_text.strip():
                    segment_text = translated_text
                
                redistributed_seg = orig_seg.copy()
                redistributed_seg['translated_text'] = segment_text
                redistributed_seg['original_text'] = orig_seg['text']
                redistributed_seg['source_smart_segment_id'] = covering_segment['id']
                redistributed_segments.append(redistributed_seg)
                
            else:
                # 如果没有找到覆盖的智能分段，保持原文
                redistributed_seg = orig_seg.copy()
                redistributed_seg['translated_text'] = orig_seg['text']
                redistributed_seg['original_text'] = orig_seg['text']
                redistributed_segments.append(redistributed_seg)
        
        return redistributed_segments
        
    except Exception as e:
        # 如果重新分配失败，返回原始片段
        return original_segments


def create_default_config(openai_key: str = "", azure_key: str = "", azure_region: str = "eastus", kimi_key: str = "", use_kimi: bool = True) -> dict:
    """
    创建默认配置
    
    Args:
        openai_key: OpenAI API密钥
        azure_key: Azure Speech Services密钥
        azure_region: Azure区域
        kimi_key: Kimi API密钥
        use_kimi: 是否使用Kimi API
        
    Returns:
        配置字典
    """
    return {
        "api_keys": {
            "kimi_api_key": kimi_key,
            "kimi_base_url": "https://api.moonshot.cn/v1",
            "openai_api_key": openai_key,
            "azure_speech_key_1": azure_key,
            "azure_speech_region": azure_region,
            "azure_speech_endpoint": f"https://{azure_region}.api.cognitive.microsoft.com/"
        },
        "translation": {
            "model": "kimi-k2-0711-preview" if use_kimi else "gpt-4o",
            "max_tokens": 8000 if use_kimi else 4000,
            "temperature": 0.3,
            "use_kimi": use_kimi,
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
        # 检查翻译API密钥
        use_kimi = config.get("translation", {}).get("use_kimi", False)
        
        if use_kimi:
            if not config.get("api_keys", {}).get("kimi_api_key"):
                return False, "Kimi API密钥不能为空"
        else:
            if not config.get("api_keys", {}).get("openai_api_key"):
                return False, "OpenAI API密钥不能为空"
        
        # 检查Azure Speech Services配置
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
  # Kimi API配置（推荐）
  kimi_api_key: "your-kimi-api-key"
  kimi_base_url: "https://api.moonshot.cn/v1"
  
  # OpenAI API配置（备用）
  openai_api_key: "your-openai-api-key"
  
  # Azure Speech Services配置
  azure_speech_key_1: "your-azure-speech-key"
  azure_speech_region: "your-region"

# 翻译配置
translation:
  model: "kimi-k2-0711-preview"
  max_tokens: 8000
  temperature: 0.3
  use_kimi: true

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
                
                # API选择
                api_mode = st.radio(
                    "选择翻译API",
                    ["Kimi (推荐)", "OpenAI"],
                    help="Kimi提供更好的中文理解和更大的token限制，推荐使用"
                )
                
                use_kimi = api_mode == "Kimi (推荐)"
                
                # 翻译API配置
                if use_kimi:
                    translation_key = st.text_input(
                        "Kimi API密钥",
                        type="password",
                        help="用于翻译和智能分段功能，获取地址：https://platform.moonshot.cn/"
                    )
                else:
                    translation_key = st.text_input(
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
                if translation_key and azure_key:
                    if use_kimi:
                        config = create_default_config("", azure_key, azure_region, translation_key, True)
                    else:
                        config = create_default_config(translation_key, azure_key, azure_region, "", False)
                    
                    is_valid, error_msg = validate_config(config)
                    
                    if is_valid:
                        st.success("✅ 配置验证成功")
                        if use_kimi:
                            st.info("🎯 已启用Kimi API，将获得更好的中文理解和智能分段效果")
                    else:
                        st.error(f"❌ 配置验证失败: {error_msg}")
                        return
                else:
                    api_name = "Kimi" if use_kimi else "OpenAI"
                    st.warning(f"请输入{api_name} API密钥和Azure Speech Services密钥")
                    st.markdown("**获取API密钥的方法：**")
                    if use_kimi:
                        st.markdown("1. **Kimi API密钥**: 访问 [Kimi平台](https://platform.moonshot.cn/)")
                    else:
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
            api_name = "Kimi" if config and config.get("translation", {}).get("use_kimi", False) else "AI"
            st.markdown(f"{api_name}将分析您的整个字幕文档，理解上下文进行智能分段，获得更好的翻译和配音效果")
            
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
            st.markdown("- 🧠 理解整个文档的上下文，进行更智能的分段")
            st.markdown("- 🎯 提高翻译准确性和上下文理解")
            st.markdown("- 🗣️ 优化配音的自然度和流畅性")
            st.markdown("- ⏱️ 基于时间戳进行合理的时长分配")
            
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
    
    # 创建进度显示容器
    progress_container = st.container()
    with progress_container:
        progress_bar = st.progress(0)
        status_text = st.empty()
        detail_text = st.empty()
    
    # 分段进度回调函数
    def segmentation_progress_callback(current: int, total: int, message: str):
        """分段进度回调"""
        progress_bar.progress(current / 100)
        status_text.text(f"智能分段: {message}")
        detail_text.info(f"进度: {current}% - {message}")
    
    try:
        # 步骤1: 加载字幕
        status_text.text("🔄 正在加载SRT字幕...")
        detail_text.info("正在读取和解析SRT文件...")
        progress_bar.progress(10)
        
        subtitle_processor = SubtitleProcessor(config)
        segments = subtitle_processor.load_subtitle(input_path)
        st.session_state.original_segments = segments
        
        status_text.text(f"✅ 字幕加载完成，共 {len(segments)} 个片段")
        detail_text.success(f"成功加载{len(segments)}个原始片段")
        
        # 步骤2: 智能分段处理（使用进度回调）
        status_text.text("🧠 正在进行智能分段分析...")
        detail_text.info("Kimi正在分析整个字幕文档，理解上下文进行智能分段...")
        
        # 创建带进度回调的简化分段器
        segmenter = SimpleSegmenter(config, progress_callback=segmentation_progress_callback)
        segmented_segments = segmenter.segment_subtitles(segments)
        st.session_state.segmented_segments = segmented_segments
        
        # 最终状态
        progress_bar.progress(100)
        status_text.text("📝 分析完成，请查看结果...")
        detail_text.success(f"智能分段完成！优化后共 {len(segmented_segments)} 个语义段落")
        
        # 设置阶段为确认
        st.session_state.processing_stage = 'confirm_segmentation'
        
        # 立即刷新到下一个阶段
        st.rerun()
        
    except Exception as e:
        st.error(f"❌ 分段分析过程中发生错误: {str(e)}")
        detail_text.error(f"错误详情: {str(e)}")
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
    ## 🧠 Step 2: 智能分段结果对比与编辑
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
        current_segments = st.session_state.get('edited_segments', segmented_segments)
        st.metric(
            label="🎯 智能分段", 
            value=len(current_segments),
            delta=f"{len(current_segments) - len(segments):+d}",
            help="AI重新组织后的逻辑段落数量"
        )
    with col3:
        avg_duration = sum(seg['duration'] for seg in current_segments) / len(current_segments)
        st.metric(
            label="⏱️ 平均时长", 
            value=f"{avg_duration:.1f}秒",
            help="每个分段的平均持续时间"
        )
    with col4:
        avg_quality = sum(seg.get('quality_score', 0.5) for seg in current_segments) / len(current_segments)
        st.metric(
            label="⭐ 质量评分", 
            value=f"{avg_quality:.2f}",
            help="AI分段的质量评估分数"
        )
    
    # 初始化编辑状态
    if 'edited_segments' not in st.session_state:
        st.session_state.edited_segments = segmented_segments.copy()
    
    # 初始化分页状态
    if 'current_page' not in st.session_state:
        st.session_state.current_page = 1
    
    # 分页设置
    segments_per_page = 10
    total_segments = len(st.session_state.edited_segments)
    total_pages = (total_segments + segments_per_page - 1) // segments_per_page
    
    # 编辑模式切换和分页控制
    col1, col2, col3 = st.columns([1, 2, 1])
    with col1:
        edit_mode = st.toggle("✏️ 编辑模式", value=False, help="开启编辑模式以修改智能分段结果")
    with col2:
        if edit_mode:
            st.info("💡 编辑模式已开启：您可以合并、拆分、修改智能分段结果")
        else:
            st.info("🔍 查看模式：左右对应关系显示每个智能分段的组成来源")
    with col3:
        st.markdown(f"**总共 {total_segments} 个段落，{total_pages} 页**")
    
    # 分页控制
    st.markdown("---")
    page_col1, page_col2, page_col3, page_col4, page_col5, page_col6 = st.columns([1, 1, 1.5, 1, 1, 1])
    
    with page_col1:
        if st.button("⬅️ 上一页", disabled=st.session_state.current_page <= 1):
            st.session_state.current_page -= 1
            st.rerun()
    
    with page_col2:
        if st.button("➡️ 下一页", disabled=st.session_state.current_page >= total_pages):
            st.session_state.current_page += 1
            st.rerun()
    
    with page_col3:
        st.markdown(f"**第 {st.session_state.current_page} 页 / 共 {total_pages} 页**")
        # 页面快速跳转
        jump_page = st.number_input("跳转到第", min_value=1, max_value=total_pages, value=st.session_state.current_page, key="jump_page")
        if st.button("🔄 跳转"):
            st.session_state.current_page = jump_page
            st.rerun()
    
    with page_col4:
        if st.button("🏠 首页"):
            st.session_state.current_page = 1
            st.rerun()
    
    with page_col5:
        if st.button("🔚 末页"):
            st.session_state.current_page = total_pages
            st.rerun()
    
    with page_col6:
        # 每页显示数量调整
        if st.button("⚙️ 设置"):
            with st.popover("分页设置"):
                new_per_page = st.slider("每页显示数量", 5, 20, segments_per_page)
                if st.button("应用设置"):
                    # 重新计算页码
                    current_start = (st.session_state.current_page - 1) * segments_per_page
                    new_page = (current_start // new_per_page) + 1
                    st.session_state.current_page = new_page
                    st.rerun()
    
    # 主要对比界面：并排显示原始和智能分段
    st.markdown("### 📊 分段对比")
    
    # 计算当前页显示的段落
    current_segments = st.session_state.edited_segments
    start_idx = (st.session_state.current_page - 1) * segments_per_page
    end_idx = min(start_idx + segments_per_page, len(current_segments))
    page_segments = current_segments[start_idx:end_idx]
    
    # 创建并排的对比界面
    left_col, right_col = st.columns([1, 1])
    
    with left_col:
        st.markdown("#### 📝 原始片段")
        original_container = st.container()
        with original_container:
            # 为当前页的每个智能分段，显示其对应的原始片段
            for seg_idx, seg in enumerate(page_segments):
                actual_idx = start_idx + seg_idx
                original_indices = seg.get('original_indices', [])
                
                if original_indices:
                    # 显示对应的原始片段
                    st.markdown(f"**🔗 对应智能分段 {seg['id']}：**")
                    for orig_idx in original_indices:
                        if 1 <= orig_idx <= len(segments):
                            orig_seg = segments[orig_idx - 1]
                            with st.container():
                                # 用颜色区分不同的智能分段
                                color_idx = actual_idx % 6
                                colors = ["🔴", "🟡", "🟢", "🔵", "🟣", "🟠"]
                                color = colors[color_idx]
                                
                                st.markdown(f"{color} **#{orig_seg['id']}** `{orig_seg['start']:.1f}s - {orig_seg['end']:.1f}s`")
                                st.markdown(f"💬 {orig_seg['text']}")
                    st.divider()
                else:
                    # 如果没有原始片段信息，显示提示
                    st.markdown(f"**🔗 对应智能分段 {seg['id']}：**")
                    st.info("⚠️ 未找到原始片段映射信息")
                    st.divider()
    
    with right_col:
        st.markdown("#### 🎯 智能分段结果")
        edited_container = st.container()
        with edited_container:
            # 显示智能分段结果（支持编辑）
            for seg_idx, seg in enumerate(page_segments):
                actual_idx = start_idx + seg_idx
                
                with st.container():
                    # 用颜色标识对应关系
                    color_idx = actual_idx % 6
                    colors = ["🔴", "🟡", "🟢", "🔵", "🟣", "🟠"]
                    color = colors[color_idx]
                    
                    seg_col1, seg_col2 = st.columns([4, 1])
                    
                    with seg_col1:
                        original_indices = seg.get('original_indices', [])
                        indices_str = ", ".join(f"#{idx}" for idx in original_indices) if original_indices else "无映射"
                        
                        st.markdown(f"{color} **段落 {seg['id']}** `{seg['start']:.1f}s - {seg['end']:.1f}s` *({seg['duration']:.1f}秒)*")
                        st.markdown(f"📋 **来源**: {indices_str}")
                        
                        if edit_mode:
                            # 编辑模式：允许修改文本和拆分
                            text_key = f"edit_text_{actual_idx}_{seg['id']}"
                            
                            edited_text = st.text_area(
                                f"编辑段落 {seg['id']}",
                                value=seg['text'],
                                height=80,
                                key=text_key,
                                label_visibility="collapsed",
                                help="💡 在需要拆分的位置按回车，然后点击'应用拆分'按钮"
                            )
                            
                            # 检查是否有换行符（表示用户想要拆分）
                            if '\n' in edited_text:
                                st.info("🔍 检测到换行符，可以在此位置拆分段落")
                                if st.button("✂️ 应用拆分", key=f"apply_split_{actual_idx}_{seg['id']}", help="在换行符位置拆分段落"):
                                    _split_segment_at_newline(actual_idx, edited_text)
                                    st.rerun()
                            else:
                                # 检查文本是否被修改
                                if edited_text != seg['text']:
                                    st.session_state.edited_segments[actual_idx]['text'] = edited_text
                        else:
                            # 非编辑模式：只显示文本
                            st.markdown(f"📖 {seg['text']}")
                    
                    with seg_col2:
                        original_count = seg.get('original_count', 1)
                        quality_score = seg.get('quality_score', 0.5)
                        st.markdown(f"🔄 合并了 **{original_count}** 个")
                        
                        # 质量评分可视化
                        if quality_score >= 0.8:
                            st.success(f"⭐ {quality_score:.2f}")
                        elif quality_score >= 0.6:
                            st.info(f"⭐ {quality_score:.2f}")
                        else:
                            st.warning(f"⭐ {quality_score:.2f}")
                        
                        # 编辑操作按钮
                        if edit_mode:
                            if actual_idx > 0 and st.button(f"⬆️ 合并", key=f"merge_up_{actual_idx}_{seg['id']}", help="与上一个段落合并"):
                                _merge_segments(actual_idx-1, actual_idx)
                                st.rerun()
                            
                            if st.button(f"🗑️ 删除", key=f"delete_{actual_idx}_{seg['id']}", help="删除此段落"):
                                _delete_segment(actual_idx)
                                st.rerun()
                    
                    if seg_idx < len(page_segments) - 1:
                        st.divider()
    
    # 编辑工具栏
    if edit_mode:
        st.markdown("---")
        st.markdown("### 🛠️ 编辑工具")
        
        tool_col1, tool_col2, tool_col3, tool_col4 = st.columns(4)
        
        with tool_col1:
            if st.button("🔄 重置到原始", help="重置为AI智能分段的原始结果"):
                st.session_state.edited_segments = segmented_segments.copy()
                st.session_state.current_page = 1
                st.success("✅ 已重置为原始智能分段结果")
                st.rerun()
        
        with tool_col2:
            if st.button("💾 保存编辑", help="保存当前编辑结果"):
                st.success("✅ 编辑已保存")
        
        with tool_col3:
            if st.button("🔍 质量检查", help="检查编辑后的分段质量"):
                _check_segment_quality()
        
        with tool_col4:
            if st.button("📊 统计信息", help="显示编辑后的统计信息"):
                _show_edit_statistics()
    
    # 确认按钮区域
    st.markdown("---")
    st.markdown("### ✅ 确认分段结果")
    
    col1, col2, col3 = st.columns([1, 1, 1])
    
    with col1:
        st.markdown("#### 🚀 推荐方式")
        if st.button(
            "✨ 使用当前分段结果", 
            type="primary", 
            use_container_width=True,
            key="use_current_segments",
            help="使用当前显示的分段结果（包含您的编辑）"
        ):
            st.session_state.confirmed_segments = st.session_state.edited_segments
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
            for key in ['processing_stage', 'original_segments', 'segmented_segments', 'edited_segments', 'display_count']:
                if key in st.session_state:
                    del st.session_state[key]
            st.rerun()
    
    # 添加一些使用建议
    st.markdown("---")
    with st.expander("💡 操作指南"):
        st.markdown("""
        **🚀 推荐使用智能分段**，因为：
        - ✅ **逻辑更完整**：将破碎的句子重新组织成完整的段落
        - ✅ **翻译质量更好**：AI可以更好地理解完整的语境
        - ✅ **配音效果更自然**：避免在句子中间停顿
        - ✅ **时间同步更精确**：更合理的时长分布
        
        **📊 界面说明**：
        - 🎨 **颜色标识**：相同颜色的emoji表示左右对应关系
        - 📋 **来源显示**：每个智能分段显示来源的原始片段编号
        - 📄 **分页浏览**：使用分页控件浏览所有段落
        - 🔄 **快速跳转**：输入页码直接跳转到指定页面
        
        **✏️ 编辑功能**：
        - 📝 **修改文本**：直接编辑段落内容
        - ✂️ **智能拆分**：在需要拆分的位置按回车换行，然后点击"应用拆分"
        - ⬆️ **合并段落**：将相邻段落合并为一个
        - 🗑️ **删除段落**：删除不需要的段落
        - 🔄 **重置**：恢复到AI智能分段的原始结果
        
        **🔧 拆分技巧**：
        - 在文本框中需要拆分的位置按回车键
        - 可以一次性拆分为多个段落（多个换行）
        - 系统会智能分配时间给每个拆分后的段落
        """)
    
    # 快速预览
    with st.expander("🔍 快速预览 - 对应关系总览"):
        st.markdown("**智能分段与原始片段的对应关系：**")
        preview_data = []
        
        for i, seg in enumerate(st.session_state.edited_segments):
            original_indices = seg.get('original_indices', [])
            color_idx = i % 6
            colors = ["🔴", "🟡", "🟢", "🔵", "🟣", "🟠"]
            color = colors[color_idx]
            
            preview_data.append({
                "颜色": color,
                "智能分段": f"段落 {seg['id']}",
                "时长": f"{seg['duration']:.1f}秒",
                "原始片段": ", ".join(f"#{idx}" for idx in original_indices) if original_indices else "无映射",
                "文本预览": seg['text'][:50] + "..." if len(seg['text']) > 50 else seg['text']
            })
        
        if preview_data:
            st.dataframe(preview_data, use_container_width=True)


def _generate_unique_id(existing_ids: set, base_id: str) -> str:
    """生成唯一的段落ID"""
    if base_id not in existing_ids:
        return base_id
    
    counter = 1
    while f"{base_id}_{counter}" in existing_ids:
        counter += 1
    
    return f"{base_id}_{counter}"


def _reorganize_segment_ids():
    """重新组织段落ID，确保连续性"""
    segments = st.session_state.edited_segments
    for i, seg in enumerate(segments):
        seg['id'] = f"seg_{i+1}"


def _update_segment_text(segment_index: int, new_text: str):
    """更新段落文本"""
    if segment_index < len(st.session_state.edited_segments):
        st.session_state.edited_segments[segment_index]['text'] = new_text


def _split_segment_at_newline(segment_index: int, text_with_newlines: str):
    """在换行符位置拆分段落"""
    segments = st.session_state.edited_segments
    if segment_index >= len(segments):
        return
    
    seg = segments[segment_index]
    lines = text_with_newlines.split('\n')
    
    # 如果只有一行或者有空行，不进行拆分
    non_empty_lines = [line.strip() for line in lines if line.strip()]
    if len(non_empty_lines) < 2:
        st.warning("⚠️ 需要至少两个非空段落才能拆分")
        return
    
    # 删除原始段落
    original_seg = segments.pop(segment_index)
    
    # 为每个非空行创建新段落
    total_chars = sum(len(line) for line in non_empty_lines)
    duration_per_char = original_seg['duration'] / total_chars if total_chars > 0 else original_seg['duration'] / len(non_empty_lines)
    
    current_time = original_seg['start']
    new_segments = []
    
    for i, line in enumerate(non_empty_lines):
        line_chars = len(line)
        line_duration = line_chars * duration_per_char
        
        # 确保最后一个段落的结束时间与原始段落一致
        if i == len(non_empty_lines) - 1:
            line_end_time = original_seg['end']
        else:
            line_end_time = current_time + line_duration
        
        new_seg = original_seg.copy()
        new_seg['text'] = line.strip()
        new_seg['start'] = current_time
        new_seg['end'] = line_end_time
        new_seg['duration'] = line_end_time - current_time
        new_seg['original_count'] = 1  # 重置合并计数
        
        # 保持原始片段索引（拆分后的每个段落都继承原始索引）
        if 'original_indices' in original_seg:
            new_seg['original_indices'] = original_seg['original_indices'].copy()
        
        new_segments.append(new_seg)
        current_time = line_end_time
    
    # 插入新段落
    for i, new_seg in enumerate(new_segments):
        segments.insert(segment_index + i, new_seg)
    
    # 重新组织ID
    _reorganize_segment_ids()
    
    # 清除相关的text_area状态，避免key冲突
    keys_to_remove = []
    for key in st.session_state.keys():
        if key.startswith(f"edit_text_{segment_index}_") or key.startswith("edit_text_"):
            keys_to_remove.append(key)
    
    for key in keys_to_remove:
        del st.session_state[key]
    
    # 检查当前页是否还有效（拆分后段落增加，通常不需要调整页码）
    segments_per_page = 10
    total_segments = len(segments)
    total_pages = (total_segments + segments_per_page - 1) // segments_per_page
    
    if st.session_state.current_page > total_pages:
        st.session_state.current_page = max(1, total_pages)
    
    st.success(f"✅ 段落已拆分为 {len(new_segments)} 个部分")


def _split_segment(segment_index: int):
    """拆分指定的段落（智能拆分）"""
    segments = st.session_state.edited_segments
    if segment_index >= len(segments):
        return
    
    seg = segments[segment_index]
    text = seg['text']
    
    # 如果文本太短，不拆分
    if len(text) < 10:
        st.warning("段落文本太短，无法拆分")
        return
    
    mid_point = len(text) // 2
    
    # 找到合适的分割点（优先选择标点符号）
    for i in range(mid_point, len(text)):
        if text[i] in '。！？；，':
            mid_point = i + 1
            break
    
    # 如果没找到标点符号，在空格处分割
    if mid_point == len(text) // 2:
        for i in range(mid_point, len(text)):
            if text[i] == ' ':
                mid_point = i + 1
                break
    
    # 创建两个新段落
    duration = seg['duration']
    text_ratio = mid_point / len(text)
    mid_time = seg['start'] + duration * text_ratio
    
    seg1 = seg.copy()
    seg1['text'] = text[:mid_point].strip()
    seg1['end'] = mid_time
    seg1['duration'] = mid_time - seg1['start']
    
    seg2 = seg.copy()
    seg2['text'] = text[mid_point:].strip()
    seg2['start'] = mid_time
    seg2['duration'] = seg2['end'] - mid_time
    
    # 更新段落列表
    segments[segment_index] = seg1
    segments.insert(segment_index + 1, seg2)
    
    # 重新组织ID
    _reorganize_segment_ids()
    
    st.success(f"✅ 段落已拆分为两个部分")


def _merge_segments(index1: int, index2: int):
    """合并两个相邻段落"""
    segments = st.session_state.edited_segments
    if index1 >= len(segments) or index2 >= len(segments):
        return
    
    seg1 = segments[index1]
    seg2 = segments[index2]
    
    # 创建合并后的段落
    merged_seg = seg1.copy()
    merged_seg['text'] = f"{seg1['text']} {seg2['text']}"
    merged_seg['end'] = seg2['end']
    merged_seg['duration'] = seg2['end'] - seg1['start']
    merged_seg['original_count'] = seg1.get('original_count', 1) + seg2.get('original_count', 1)
    
    # 合并原始片段索引
    orig_indices1 = seg1.get('original_indices', [])
    orig_indices2 = seg2.get('original_indices', [])
    merged_seg['original_indices'] = orig_indices1 + orig_indices2
    
    # 更新段落列表
    segments[index1] = merged_seg
    segments.pop(index2)
    
    # 重新组织ID
    _reorganize_segment_ids()
    
    # 检查当前页是否还有效
    segments_per_page = 10
    total_segments = len(segments)
    total_pages = (total_segments + segments_per_page - 1) // segments_per_page
    
    if st.session_state.current_page > total_pages:
        st.session_state.current_page = max(1, total_pages)
    
    st.success(f"✅ 段落已合并")


def _delete_segment(segment_index: int):
    """删除指定段落"""
    segments = st.session_state.edited_segments
    if segment_index >= len(segments):
        return
    
    # 至少保留一个段落
    if len(segments) <= 1:
        st.warning("⚠️ 不能删除最后一个段落")
        return
    
    deleted_seg = segments.pop(segment_index)
    
    # 重新组织ID
    _reorganize_segment_ids()
    
    # 检查当前页是否还有效
    segments_per_page = 10
    total_segments = len(segments)
    total_pages = (total_segments + segments_per_page - 1) // segments_per_page
    
    if st.session_state.current_page > total_pages:
        st.session_state.current_page = max(1, total_pages)
    
    st.success(f"✅ 段落已删除: {deleted_seg['text'][:30]}...")


def _check_segment_quality():
    """检查分段质量"""
    segments = st.session_state.edited_segments
    issues = []
    
    for i, seg in enumerate(segments):
        # 检查文本长度
        if len(seg['text']) < 10:
            issues.append(f"段落 {seg['id']}: 文本过短")
        elif len(seg['text']) > 200:
            issues.append(f"段落 {seg['id']}: 文本过长")
        
        # 检查时长
        if seg['duration'] < 2:
            issues.append(f"段落 {seg['id']}: 时长过短")
        elif seg['duration'] > 15:
            issues.append(f"段落 {seg['id']}: 时长过长")
    
    if issues:
        st.warning(f"发现 {len(issues)} 个质量问题：")
        for issue in issues:
            st.write(f"⚠️ {issue}")
    else:
        st.success("✅ 分段质量检查通过")


def _show_edit_statistics():
    """显示编辑统计信息"""
    segments = st.session_state.edited_segments
    
    total_duration = sum(seg['duration'] for seg in segments)
    total_chars = sum(len(seg['text']) for seg in segments)
    avg_duration = total_duration / len(segments)
    avg_chars = total_chars / len(segments)
    
    st.info(f"""
    📊 编辑统计：
    - 总段落数：{len(segments)}
    - 总时长：{total_duration:.1f}秒
    - 总字符数：{total_chars}
    - 平均时长：{avg_duration:.1f}秒
    - 平均字符数：{avg_chars:.0f}
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
    
    # 创建进度显示容器
    progress_container = st.container()
    with progress_container:
        # 总体进度
        overall_progress = st.progress(0)
        overall_status = st.empty()
        
        # 当前阶段进度
        stage_progress = st.progress(0)
        stage_status = st.empty()
        stage_detail = st.empty()
    
    # 翻译进度回调
    def translation_progress_callback(current: int, total: int, message: str):
        """翻译进度回调"""
        stage_progress.progress(current / 100)
        stage_status.text(f"翻译进度: {message}")
        stage_detail.info(f"翻译: {current}% - {message}")
    
    # TTS同步进度回调
    def sync_progress_callback(current: int, total: int, message: str):
        """TTS同步进度回调"""
        stage_progress.progress(current / 100)
        stage_status.text(f"时间同步: {message}")
        stage_detail.info(f"同步优化: {current}% - {message}")
    
    try:
        # 步骤1: 翻译
        overall_status.text("🌐 步骤1: 智能翻译字幕...")
        stage_status.text("正在初始化翻译服务...")
        stage_detail.info("连接OpenAI翻译服务...")
        overall_progress.progress(10)
        
        # 创建带进度回调的翻译器
        translator = Translator(config, progress_callback=translation_progress_callback)
        translated_segments = translator.translate_segments(segments, target_lang)
        
        # 将智能分段的翻译内容重新分配到原始时间分割
        stage_status.text("正在重新分配翻译内容...")
        stage_detail.info("确保音频和字幕使用相同的翻译内容...")
        original_segments = st.session_state.get('original_segments', segments)
        translated_original_segments = redistribute_translations_to_original_streamlit(translated_segments, original_segments)
        
        overall_progress.progress(50)
        overall_status.text("✅ 翻译完成")
        stage_detail.success("翻译阶段完成！")
        
        # 步骤2: 循环逼近时间同步优化
        overall_status.text("⏱️ 步骤2: 循环逼近时间同步优化...")
        stage_status.text("正在初始化TTS和同步服务...")
        stage_detail.info("连接Azure TTS服务...")
        
        tts = AzureTTS(config)
        # 创建带进度回调的同步管理器
        sync_manager = AdvancedSyncManager(config, progress_callback=sync_progress_callback)
        
        optimized_segments = sync_manager.optimize_timing_with_iteration(
            translated_segments, target_lang, translator, tts
        )
        
        overall_progress.progress(85)
        overall_status.text("✅ 时间同步优化完成")
        stage_detail.success("时间同步优化完成！")
        
        # 步骤3: 音频合并
        overall_status.text("🎵 步骤3: 合并音频...")
        stage_status.text("正在合并所有音频片段...")
        stage_detail.info("生成最终的配音文件...")
        stage_progress.progress(0)
        
        final_audio = sync_manager.merge_audio_segments(optimized_segments)
        
        # 保存结果
        audio_output = f"dubbed_audio_{target_lang}.wav"
        subtitle_output = f"translated_subtitle_{target_lang}.srt"
        
        subtitle_processor = SubtitleProcessor(config)
        
        stage_status.text("正在保存文件...")
        stage_detail.info("保存配音音频和翻译字幕...")
        stage_progress.progress(50)
        
        final_audio.export(audio_output, format="wav")
        # 保存字幕时使用原始片段的翻译
        subtitle_processor.save_subtitle(translated_original_segments, subtitle_output, 'srt')
        
        # 最终完成
        overall_progress.progress(100)
        overall_status.text("🎉 配音生成完成！")
        stage_progress.progress(100)
        stage_status.text("所有处理已完成！")
        stage_detail.success("配音文件生成成功！")
        
        # 保存完成结果数据到session state
        with open(audio_output, 'rb') as f:
            audio_data = f.read()
        with open(subtitle_output, 'rb') as f:
            subtitle_data = f.read()
        
        # 计算统计信息
        total_duration = max(seg['end'] for seg in segments)
        excellent_count = sum(1 for seg in optimized_segments if seg.get('sync_quality') == 'excellent')
        
        # 获取成本摘要
        cost_summary = tts.get_cost_summary()
        
        st.session_state.completion_results = {
            'audio_data': audio_data,
            'subtitle_data': subtitle_data,
            'target_lang': target_lang,
            'optimized_segments': optimized_segments,
            'cost_summary': cost_summary,  # 添加成本摘要
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
        stage_detail.error(f"错误详情: {str(e)}")
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
    
    # 增强的统计信息和质量分析
    st.markdown("### 📊 时长匹配度与质量分析")
    
    # 获取优化后的片段数据
    optimized_segments = results['optimized_segments']
    
    # 计算详细的质量指标
    quality_metrics = calculate_quality_metrics(optimized_segments)
    
    # 显示核心指标
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("字幕片段", quality_metrics['total_segments'])
    
    with col2:
        st.metric("总时长", f"{quality_metrics['total_duration']:.1f}秒")
    
    with col3:
        st.metric(
            "时长匹配度", 
            f"{quality_metrics['timing_accuracy']:.1f}%",
            help="平均时长匹配精度"
        )
    
    with col4:
        st.metric(
            "优秀同步率", 
            f"{quality_metrics['excellent_rate']:.1f}%",
            help="优秀质量片段占比"
        )
    
    # 详细的质量分析图表
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("#### 🎯 同步质量分布")
        quality_dist = quality_metrics['quality_distribution']
        quality_labels = ['优秀', '良好', '一般', '较差', '短文本', '长文本', '兜底']
        quality_colors = ['#00C851', '#39C0ED', '#ffbb33', '#ff4444', '#ff8800', '#aa66cc', '#999999']
        
        # 创建质量分布图
        quality_data = []
        for i, (key, count) in enumerate(quality_dist.items()):
            if count > 0:
                quality_data.append({
                    'quality': quality_labels[i],
                    'count': count,
                    'percentage': count / quality_metrics['total_segments'] * 100
                })
        
        if quality_data:
            st.bar_chart(
                data={item['quality']: item['count'] for item in quality_data},
                height=300
            )
    
    with col2:
        st.markdown("#### ⚡ 语速调整分布")
        speed_dist = quality_metrics['speed_distribution']
        speed_labels = ['0.95-1.00', '1.00-1.05', '1.05-1.10', '1.10-1.15']
        
        speed_data = {label: count for label, count in speed_dist.items() if count > 0}
        if speed_data:
            st.bar_chart(data=speed_data, height=300)
    
    # 💰 成本报告
    with st.expander("💰 Azure TTS 成本报告", expanded=False):
        cost_summary = results.get('cost_summary', {})
        
        if cost_summary:
            st.markdown("#### 💰 API调用成本分析")
            
            # 核心成本指标
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.metric(
                    "API调用次数",
                    f"{cost_summary.get('api_calls', 0)}",
                    help="总共调用Azure TTS API的次数"
                )
                st.metric(
                    "总字符数",
                    f"{cost_summary.get('total_characters', 0):,}",
                    help="发送到Azure TTS的总字符数"
                )
            
            with col2:
                st.metric(
                    "估计成本",
                    f"${cost_summary.get('estimated_cost_usd', 0):.4f}",
                    help="基于字符数估算的成本（USD）"
                )
                st.metric(
                    "处理时长",
                    f"{cost_summary.get('session_duration_seconds', 0):.1f}s",
                    help="从开始到结束的总处理时间"
                )
            
            with col3:
                st.metric(
                    "调用频率",
                    f"{cost_summary.get('avg_calls_per_minute', 0):.1f}/min",
                    help="平均每分钟API调用次数"
                )
                st.metric(
                    "平均字符/调用",
                    f"{cost_summary.get('avg_characters_per_call', 0):.1f}",
                    help="平均每次API调用的字符数"
                )
            
            # 成本优化建议
            if cost_summary.get('api_calls', 0) > 50:
                st.info("💡 **成本优化建议**：启用成本优化模式可减少60-80%的API调用次数")
                st.markdown("""
                **优化方法：**
                - 在配置中启用 `enable_cost_optimization: true`
                - 使用 `use_estimation_first: true` 优先使用估算方法
                - 调整 `max_api_calls_per_segment` 限制每个片段的最大调用次数
                """)
            
            # 成本对比
            if cost_summary.get('api_calls', 0) > 0:
                optimized_calls = max(len(results['optimized_segments']), 1)  # 优化模式下的预估调用次数
                current_calls = cost_summary.get('api_calls', 0)
                potential_savings = max(0, (current_calls - optimized_calls) / current_calls * 100)
                
                if potential_savings > 0:
                    st.success(f"🎯 **启用成本优化模式预计可节省 {potential_savings:.1f}% 的API调用**")
        else:
            st.info("成本信息不可用")
    
    # 详细的同步质量报告
    with st.expander("📋 详细同步质量报告", expanded=True):
        st.markdown("#### 🎯 时长匹配度详情")
        
        # 时长匹配度概览
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric(
                "平均时长误差",
                f"{quality_metrics['avg_timing_error']:.1f}%",
                help="所有片段的平均时长偏差"
            )
        
        with col2:
            st.metric(
                "最大时长误差",
                f"{quality_metrics['max_timing_error']:.1f}%",
                help="单个片段的最大时长偏差"
            )
        
        with col3:
            st.metric(
                "平均语速",
                f"{quality_metrics['avg_speed']:.2f}x",
                help="所有片段的平均语速倍率"
            )
        
        # 问题片段统计
        if quality_metrics['problematic_segments']:
            st.markdown("#### ⚠️ 需要关注的片段")
            problem_segments = quality_metrics['problematic_segments']
            
            # 显示问题片段表格
            problem_data = []
            for seg in problem_segments:
                problem_data.append({
                    "片段ID": seg['id'],
                    "时间码": f"{seg['start']:.1f}s-{seg['end']:.1f}s",
                    "时长比例": f"{seg['sync_ratio']:.2f}",
                    "语速": f"{seg['final_speed']:.2f}x",
                    "质量": seg['sync_quality'],
                    "问题": seg['issue_type']
                })
            
            if problem_data:
                st.dataframe(
                    problem_data,
                    use_container_width=True,
                    height=300
                )
        
        # 优秀片段示例
        excellent_segments = [seg for seg in optimized_segments if seg.get('sync_quality') == 'excellent']
        if excellent_segments:
            st.markdown("#### ✅ 优秀同步片段示例")
            st.info(f"共有 {len(excellent_segments)} 个片段达到优秀同步质量（时长误差 < 5%）")
            
            # 显示前3个优秀片段
            for i, seg in enumerate(excellent_segments[:3]):
                if i < 3:
                    sync_ratio = seg.get('sync_ratio', 1.0)
                    error_pct = abs(sync_ratio - 1.0) * 100
                    st.success(
                        f"片段 {seg['id']} ({seg['start']:.1f}s-{seg['end']:.1f}s): "
                        f"时长比例 {sync_ratio:.3f} (误差 {error_pct:.1f}%), "
                        f"语速 {seg.get('final_speed', 1.0):.2f}x"
                    )
    
    # 详细的片段级质量分析
    with st.expander("🔍 片段级质量分析"):
        st.markdown("#### 📊 所有片段的时长匹配度详情")
        
        # 创建片段分析数据
        segment_data = []
        for seg in optimized_segments:
            sync_ratio = seg.get('sync_ratio', 1.0)
            timing_error = abs(sync_ratio - 1.0) * 100
            
            # 确定质量等级的显示颜色
            quality = seg.get('sync_quality', 'unknown')
            if quality == 'excellent':
                quality_color = '🟢'
            elif quality == 'good':
                quality_color = '🟡'
            elif quality == 'fair':
                quality_color = '🟠'
            else:
                quality_color = '🔴'
            
            segment_data.append({
                "片段": seg['id'],
                "时间码": f"{seg['start']:.1f}s-{seg['end']:.1f}s",
                "目标时长": f"{seg['duration']:.2f}s",
                "实际时长": f"{seg.get('actual_duration', 0):.2f}s",
                "时长比例": f"{sync_ratio:.3f}",
                "时长误差": f"{timing_error:.1f}%",
                "语速": f"{seg.get('final_speed', 1.0):.2f}x",
                "质量": f"{quality_color} {quality}",
                "迭代次数": seg.get('iterations', 0)
            })
        
        # 显示数据表格
        st.dataframe(
            segment_data,
            use_container_width=True,
            height=400
        )
    
    # 详细结果对比
    with st.expander("📋 翻译结果对比"):
        st.markdown("#### 🔄 原文与翻译对比")
        for i, seg in enumerate(optimized_segments[:10]):
            col1, col2 = st.columns(2)
            with col1:
                st.markdown(f"**片段 {i+1}** `{seg['start']:.1f}s - {seg['end']:.1f}s`")
                # 安全地获取原文文本
                original_text = (seg.get('original_text') or 
                               seg.get('text') or 
                               "原文未找到")
                st.text_area(
                    label="原文",
                    value=original_text,
                    height=80,
                    disabled=True,
                    key=f"original_{i}"
                )
            
            with col2:
                st.markdown(f"**翻译** `质量: {seg.get('sync_quality', 'unknown')}`")
                translated_text = (seg.get('optimized_text') or 
                                 seg.get('translated_text') or 
                                 "翻译未找到")
                st.text_area(
                    label="翻译",
                    value=translated_text,
                    height=80,
                    disabled=True,
                    key=f"translated_{i}"
                )
    
    # 操作按钮
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("🔄 重新开始", key="restart_completed", use_container_width=True):
            reset_all_states()
            st.rerun()
    
    with col2:
        if st.button("📊 生成详细报告", key="generate_report", use_container_width=True):
            # 生成并显示详细报告
            generate_detailed_report(optimized_segments)

def calculate_quality_metrics(segments):
    """计算质量指标"""
    if not segments:
        return {}
    
    total_segments = len(segments)
    quality_counts = {'excellent': 0, 'good': 0, 'fair': 0, 'poor': 0, 'short_text': 0, 'long_text': 0, 'fallback': 0}
    speeds = []
    timing_errors = []
    problematic_segments = []
    total_duration = 0
    
    for seg in segments:
        # 质量统计
        quality = seg.get('sync_quality', 'unknown')
        if quality in quality_counts:
            quality_counts[quality] += 1
        
        # 时长和语速统计
        sync_ratio = seg.get('sync_ratio', 1.0)
        speed = seg.get('final_speed', 1.0)
        duration = seg.get('duration', 0)
        
        speeds.append(speed)
        timing_error = abs(sync_ratio - 1.0) * 100
        timing_errors.append(timing_error)
        total_duration += duration
        
        # 识别问题片段
        issue_type = None
        if seg.get('was_truncated', False):
            issue_type = "音频被截断"
        elif sync_ratio < 0.8:
            issue_type = "时长过短"
        elif sync_ratio > 1.2:
            issue_type = "时长过长"
        elif timing_error > 20:
            issue_type = "时长误差过大"
        
        if issue_type:
            problematic_segments.append({
                'id': seg['id'],
                'start': seg['start'],
                'end': seg['end'],
                'sync_ratio': sync_ratio,
                'final_speed': speed,
                'sync_quality': quality,
                'issue_type': issue_type
            })
    
    # 计算综合指标
    avg_timing_error = sum(timing_errors) / len(timing_errors) if timing_errors else 0
    max_timing_error = max(timing_errors) if timing_errors else 0
    avg_speed = sum(speeds) / len(speeds) if speeds else 1.0
    timing_accuracy = max(0, 100 - avg_timing_error)
    excellent_rate = quality_counts['excellent'] / total_segments * 100
    
    # 语速分布
    speed_distribution = {
        '0.95-1.00': sum(1 for s in speeds if 0.95 <= s < 1.00),
        '1.00-1.05': sum(1 for s in speeds if 1.00 <= s < 1.05),
        '1.05-1.10': sum(1 for s in speeds if 1.05 <= s < 1.10),
        '1.10-1.15': sum(1 for s in speeds if 1.10 <= s <= 1.15)
    }
    
    return {
        'total_segments': total_segments,
        'total_duration': total_duration,
        'quality_distribution': quality_counts,
        'speed_distribution': speed_distribution,
        'avg_timing_error': avg_timing_error,
        'max_timing_error': max_timing_error,
        'avg_speed': avg_speed,
        'timing_accuracy': timing_accuracy,
        'excellent_rate': excellent_rate,
        'problematic_segments': problematic_segments
    }

def generate_detailed_report(segments):
    """生成详细报告"""
    st.markdown("### 📊 详细质量报告")
    
    # 创建同步管理器实例以生成报告
    sync_manager = AdvancedSyncManager({})
    
    # 生成优化报告
    optimization_report = sync_manager.create_optimization_report(segments)
    
    # 显示报告
    st.code(optimization_report, language="text")
    
    # 提供下载选项
    st.download_button(
        label="📥 下载详细报告",
        data=optimization_report,
        file_name="timing_optimization_report.txt",
        mime="text/plain",
        use_container_width=True
    )


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