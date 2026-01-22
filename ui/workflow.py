"""
AI配音系统工作流管理器
统一管理UI流程，协调各个阶段的视图组件
"""

import streamlit as st
from typing import List, Dict, Any, Optional, Callable
from pathlib import Path
import sys
from loguru import logger

# 添加项目根目录到Python路径
sys.path.append(str(Path(__file__).parent.parent))

from models.segment_dto import SegmentDTO
from models.project_dto import ProjectDTO
from ui.components.segmentation_view import SegmentationView
from ui.components.language_selection_view import LanguageSelectionView
from ui.components.audio_confirmation_view import AudioConfirmationView
from ui.components.completion_view import CompletionView
from utils.project_integration import get_project_integration


def _get_current_user_id() -> str:
    """获取当前用户 ID（从 session_state）"""
    auth_username = st.session_state.get('auth_username')
    if auth_username:
        return auth_username
    return 'default_user'


class WorkflowManager:
    """工作流管理器 - 统一协调所有UI阶段"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._init_components()
    
    @property
    def project_integration(self):
        """动态获取当前用户的工程集成实例"""
        user_id = _get_current_user_id()
        return get_project_integration(user_id=user_id)
    
    def _init_components(self):
        """初始化所有UI组件"""
        self.segmentation_view = SegmentationView()
        self.language_selection_view = LanguageSelectionView()
        self.audio_confirmation_view = AudioConfirmationView()
        self.completion_view = CompletionView()
    
    def render_stage(self, stage: str, session_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        根据当前阶段渲染对应的视图
        
        Args:
            stage: 当前处理阶段
            session_data: 会话数据
            
        Returns:
            更新后的会话数据
        """
        logger.debug(f"🎬 WorkflowManager.render_stage 被调用，阶段: {stage}")
        
        # 阶段到渲染函数的映射（精简后的核心阶段）
        stage_renderers = {
            'segmentation': self._render_segmentation_analysis,
            'confirm_segmentation': self._render_segmentation_confirmation,
            'language_selection': self._render_language_selection,
            'translating': self._render_translation_progress,
            'user_confirmation': self._render_audio_confirmation,
            'completion': self._render_completion
        }
        
        renderer = stage_renderers.get(stage)
        if not renderer:
            logger.error(f"❌ 未找到阶段 {stage} 对应的渲染器")
            st.error(f"❌ 未知的处理阶段: {stage}")
            return session_data
        
        logger.debug(f"🎯 找到渲染器: {renderer.__name__}")
        
        try:
            result = renderer(session_data)
            new_stage = result.get('processing_stage', 'unknown')
            logger.debug(f"✅ 渲染器执行完成，返回状态: {new_stage}")
            logger.debug(f"📋 返回数据概览: segments={len(result.get('segments', []))}, segmented_segments={len(result.get('segmented_segments', []))}")
            
            # 自动保存工程进度
            # 对于 confirm_segmentation 和 user_confirmation 阶段，只在状态转换时才保存，避免频繁写入 Firebase
            # 用户在这些界面的每个操作都不需要立即保存，只有关键操作（确认片段、完成等）时才保存
            skip_auto_save_stages = ['confirm_segmentation', 'user_confirmation']
            skip_auto_save = stage in skip_auto_save_stages and new_stage == stage
            
            if not skip_auto_save:
                self._auto_save_project_progress(result)
            else:
                logger.debug(f"跳过自动保存: {stage} 阶段未发生状态转换")
            
            return result
        except Exception as e:
            logger.error(f"❌ 渲染阶段 {stage} 时发生错误: {e}", exc_info=True)
            st.error(f"❌ 渲染阶段 {stage} 时发生错误: {str(e)}")
            return session_data
    
    def _restore_audio_from_storage(self, segments: List[SegmentDTO], project: ProjectDTO) -> int:
        """
        检查片段是否有云端音频可用（不实际下载，使用懒加载策略）
        
        改进策略：
        - 不一次性下载所有音频（避免卡顿）
        - 只标记哪些片段有云端音频可用
        - 实际播放时使用 URL 流式播放
        - 只有在用户需要修改/确认时才按需下载单个片段
        
        Args:
            segments: 需要检查的片段列表
            project: 项目对象（包含 audio_storage_paths）
            
        Returns:
            有云端音频可用的片段数量
        """
        available_count = 0
        
        if not project or not hasattr(project, 'audio_storage_paths'):
            return 0
        
        audio_paths = project.audio_storage_paths
        if not audio_paths:
            logger.debug("项目没有保存的音频路径")
            return 0
        
        logger.debug(f"_restore_audio_from_storage: audio_paths keys = {list(audio_paths.keys())}")
        
        # 只检查并记录有多少片段有云端音频，不实际下载
        for seg in segments:
            if seg.audio_data is not None:
                # 已有内存中的音频数据
                available_count += 1
                continue
            
            # 检查是否有云端路径
            storage_path = audio_paths.get(seg.id) or audio_paths.get(f"{seg.id}_preview")
            if storage_path:
                # 标记该片段有云端音频可用（通过 audio_path 字段）
                seg.audio_path = storage_path
                available_count += 1
                logger.debug(f"片段 {seg.id} 设置 audio_path = {storage_path}")
        
        if available_count > 0:
            logger.debug(f"检测到 {available_count} 个片段有云端音频可用（使用 URL 流式播放）")
        
        return available_count
    
    def _download_single_segment_audio(self, segment: SegmentDTO, project: ProjectDTO) -> bool:
        """
        按需下载单个片段的音频数据（用于需要修改的场景）
        
        Args:
            segment: 需要下载音频的片段
            project: 项目对象
            
        Returns:
            是否下载成功
        """
        if segment.audio_data is not None:
            return True  # 已有音频数据
        
        if not project or not hasattr(project, 'audio_storage_paths'):
            return False
        
        audio_paths = project.audio_storage_paths
        storage_path = audio_paths.get(segment.id) or audio_paths.get(f"{segment.id}_preview")
        
        if not storage_path:
            return False
        
        try:
            from utils.firebase_storage import get_storage_manager
            from pydub import AudioSegment
            from io import BytesIO
            
            storage = get_storage_manager()
            if not storage or not storage.is_connected:
                logger.debug(f"Firebase Storage 未连接，无法下载片段 {segment.id}")
                return False
            
            # 🔥 兼容性处理：检查路径格式并转换
            actual_path = storage_path
            if '/audio/segments/' in storage_path:
                import re
                match = re.match(r'(.*/audio)/segments/([^/]+)/(preview|confirmed)\.mp3', storage_path)
                if match:
                    base_path = match.group(1)
                    segment_id = match.group(2)
                    stage = match.group(3)
                    new_path = f"{base_path}/{stage}/{segment_id}.mp3"
                    # 检查新路径是否存在
                    if storage.check_file_exists(new_path):
                        actual_path = new_path
                        logger.debug(f"路径兼容转换: {storage_path} -> {new_path}")
            
            # 下载音频数据
            audio_bytes = storage.download_audio(actual_path)
            if audio_bytes:
                audio_buffer = BytesIO(audio_bytes)
                if storage_path.endswith('.mp3'):
                    audio_segment = AudioSegment.from_mp3(audio_buffer)
                else:
                    audio_segment = AudioSegment.from_wav(audio_buffer)
                
                segment.set_audio_data(audio_segment)
                logger.info(f"按需下载片段 {segment.id} 音频成功")
                return True
            
            return False
            
        except Exception as e:
            logger.warning(f"按需下载片段 {segment.id} 音频失败: {e}")
            return False
    
    def _generate_audio_for_segments(self, segments: List[SegmentDTO], target_language: str) -> List[SegmentDTO]:
        """为翻译段生成音频并进行智能迭代优化（并发版本，使用公共迭代优化器）"""
        try:
            from tts import create_tts_engine
            from translation.text_optimizer import TextOptimizer
            from utils.audio_iteration_optimizer import AudioIterationOptimizer
            from concurrent.futures import ThreadPoolExecutor, as_completed
            import threading
            
            # 获取用户选择的TTS服务
            selected_tts_service = st.session_state.get('selected_tts_service', 'minimax')
            selected_voice_id = st.session_state.get('selected_voice_id')
            config = st.session_state.get('config', self.config)
            
            # 检查TTS实例是否需要重新创建（服务类型变更）
            tts_engine = st.session_state.get('tts_instance')
            current_service = st.session_state.get('current_tts_service')
            
            if not tts_engine or current_service != selected_tts_service:
                logger.info(f"创建TTS引擎: {selected_tts_service}")
                tts_engine = create_tts_engine(config, selected_tts_service)
                st.session_state['tts_instance'] = tts_engine
                st.session_state['current_tts_service'] = selected_tts_service
            
            # 如果用户选择了特定音色，设置它
            if selected_voice_id:
                tts_engine.set_voice(selected_voice_id)
                logger.info(f"{selected_tts_service}设置音色: {selected_voice_id}")
            
            # 获取音色名称
            if selected_tts_service == 'elevenlabs' and selected_voice_id:
                voice_name = selected_voice_id
            else:
                voice_name = tts_engine.voice_map.get(target_language) if hasattr(tts_engine, 'voice_map') else None
                if isinstance(voice_name, dict):
                    voice_name = list(voice_name.keys())[0] if voice_name else None
            
            if not voice_name:
                logger.warning(f"未配置语言 {target_language} 的音色，回退到简单生成模式")
                return self._generate_audio_simple(segments, target_language, tts_engine)
            
            # 创建文本优化器
            text_optimizer = TextOptimizer(config)
            
            # 检查TTS是否支持语速调整（ElevenLabs不支持）
            supports_speech_rate = selected_tts_service != 'elevenlabs'
            
            # 并发配置
            max_workers = min(5, len(segments))  # 最多5个并发worker
            
            logger.info(f"开始并发生成 {len(segments)} 个片段的音频 (workers={max_workers}, 语速调整: {'支持' if supports_speech_rate else '不支持'})")
            
            # 进度显示
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            # 线程安全的进度计数器
            completed_count = [0]  # 使用列表以便在闭包中修改
            progress_lock = threading.Lock()
            
            def process_segment(seg_idx: int, seg: SegmentDTO) -> tuple:
                """处理单个片段的迭代优化（线程安全）"""
                # 每个线程创建自己的迭代优化器实例
                thread_optimizer = AudioIterationOptimizer(
                    tts_engine=tts_engine,
                    text_optimizer=text_optimizer,
                    supports_speech_rate=supports_speech_rate
                )
                
                if not seg.final_text:
                    logger.warning(f"片段 {seg.id} 没有文本，跳过")
                    return seg_idx, None
                
                # 获取片段的当前参数
                current_text = seg.final_text
                original_text = seg.original_text or seg.translated_text or current_text
                target_duration = seg.target_duration
                initial_rate = seg.speech_rate or 1.0 if supports_speech_rate else 1.0
                
                # 如果目标时长太短，跳过迭代优化
                if target_duration < 0.5:
                    logger.warning(f"片段 {seg.id} 目标时长 {target_duration:.2f}s 太短，跳过迭代优化")
                    try:
                        audio_data = tts_engine._generate_single_audio(current_text, voice_name, initial_rate, target_duration)
                        return seg_idx, {
                            'success': True,
                            'audio_data': audio_data,
                            'text': current_text,
                            'speech_rate': initial_rate,
                            'error_ms': 0,
                            'error_percentage': 0,
                            'quality': 'good',
                            'is_valid': True
                        }
                    except Exception as e:
                        logger.error(f"片段 {seg.id} 音频生成失败: {e}")
                        return seg_idx, {'success': False, 'quality': 'error'}
                
                # 使用迭代优化器进行优化
                result = thread_optimizer.optimize_segment(
                    text=current_text,
                    original_text=original_text,
                    voice_name=voice_name,
                    target_duration=target_duration,
                    target_language=target_language,
                    initial_speech_rate=initial_rate,
                    source_language='zh'
                )
                
                return seg_idx, result
            
            # 使用线程池并发处理
            results_map = {}
            
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                # 提交所有任务
                future_to_idx = {
                    executor.submit(process_segment, idx, seg): idx 
                    for idx, seg in enumerate(segments)
                }
                
                # 收集结果
                for future in as_completed(future_to_idx):
                    idx = future_to_idx[future]
                    try:
                        seg_idx, result = future.result()
                        results_map[seg_idx] = result
                        
                        # 更新进度（线程安全）
                        with progress_lock:
                            completed_count[0] += 1
                            progress = completed_count[0] / len(segments)
                            progress_bar.progress(progress)
                            status_text.text(f"🔄 并发优化中: {completed_count[0]}/{len(segments)}")
                            
                    except Exception as e:
                        logger.error(f"处理片段 {idx} 时发生异常: {e}")
                        results_map[idx] = {'success': False, 'quality': 'error'}
            
            # 应用结果到segments
            for idx, seg in enumerate(segments):
                result = results_map.get(idx)
                if not result:
                    continue
                
                if result.get('success') and result.get('best_result'):
                    best = result['best_result']
                    seg.set_audio_data(best.audio_data)
                    seg.speech_rate = best.speech_rate
                    seg.update_final_text(best.text)
                    seg.timing_error_ms = abs(best.error_ms)
                    
                    # 设置质量评级
                    if best.is_valid:
                        seg.quality = 'excellent'
                    elif best.error_percentage <= 10:
                        seg.quality = 'good'
                    elif best.error_percentage <= 20:
                        seg.quality = 'fair'
                    else:
                        seg.quality = 'poor'
                    
                    logger.info(f"片段 {seg.id} 优化完成: 质量={seg.quality}, 误差={best.error_ms:.0f}ms")
                    
                elif result.get('success') and result.get('audio_data'):
                    # 短片段的简单处理结果
                    seg.set_audio_data(result['audio_data'])
                    seg.speech_rate = result.get('speech_rate', 1.0)
                    seg.quality = result.get('quality', 'good')
                else:
                    logger.warning(f"片段 {seg.id} 没有生成有效的音频")
                    seg.quality = 'error'
            
            progress_bar.progress(1.0)
            status_text.text(f"✅ 并发优化完成！共处理 {len(segments)} 个片段")
            
            # 统计优化结果
            quality_stats = {'excellent': 0, 'good': 0, 'fair': 0, 'poor': 0, 'error': 0}
            for seg in segments:
                quality = getattr(seg, 'quality', 'unknown')
                if quality in quality_stats:
                    quality_stats[quality] += 1
            
            logger.info(f"✅ 并发迭代优化完成: {quality_stats}")
            
            # 🔥 Stage 1: 上传预览音频到 Firebase Storage
            self._upload_preview_audios(segments)
            
            # 清理进度显示
            progress_bar.empty()
            status_text.empty()
            
            return segments
            
        except Exception as e:
            logger.error(f"❌ 并发迭代优化失败: {e}")
            st.error(f"❌ 并发迭代优化失败: {str(e)}")
            return segments
    
    def _upload_preview_audios(self, segments: List[SegmentDTO]):
        """
        Stage 1: 异步上传预览音频到 Firebase Storage
        
        在用户点击"开始配音处理"后，迭代优化生成的音频作为预览版本异步上传
        不阻塞主线程，提升用户体验
        
        Args:
            segments: 包含音频数据的片段列表
        """
        try:
            # 获取当前项目信息
            current_project = st.session_state.get('current_project')
            if not current_project:
                logger.debug("无项目信息，跳过预览音频上传")
                return
            
            # 检查是否使用 Firebase 存储后端
            if getattr(current_project, 'storage_backend', 'local') != 'firebase':
                logger.debug("非 Firebase 存储后端，跳过预览音频上传")
                return
            
            user_id = getattr(current_project, 'owner_id', '')
            project_id = getattr(current_project, 'id', '')
            
            if not user_id or not project_id:
                logger.warning("缺少用户 ID 或项目 ID，跳过预览音频上传")
                return
            
            from utils.firebase_storage import get_storage_manager
            from utils.async_upload_manager import get_upload_manager
            
            storage = get_storage_manager()
            if not storage.is_connected:
                logger.warning("Firebase Storage 未连接，跳过预览音频上传")
                return
            
            total_with_audio = sum(1 for seg in segments if seg.audio_data is not None)
            
            if total_with_audio == 0:
                logger.debug("没有需要上传的音频")
                return
            
            logger.info(f"开始异步上传 Stage 1 预览音频: {total_with_audio} 个片段")
            
            # 使用异步上传管理器
            upload_manager = get_upload_manager()
            
            # 定义上传完成回调，更新项目的音频存储路径
            def on_upload_complete(task_id: str, result_path: str, error: str):
                if error:
                    logger.warning(f"预览音频上传失败 [{task_id}]: {error}")
                    return
                
                if result_path:
                    # 从 task_id 中无法直接获取 segment_id，回调中只记录日志
                    logger.debug(f"预览音频上传完成 [{task_id}]: {result_path}")
            
            # 批量提交异步上传任务
            for seg in segments:
                if seg.audio_data is None:
                    continue
                
                upload_manager.submit_preview_upload(
                    user_id=user_id,
                    project_id=project_id,
                    segment_id=seg.id,
                    audio_data=seg.audio_data,
                    callback=on_upload_complete
                )
                
                # 预先设置预览路径占位（异步上传完成后会更新）
                # 路径格式: users/{user_id}/projects/{project_id}/audio/preview/{segment_id}.mp3
                preview_key = f"{seg.id}_preview"
                expected_path = f"users/{user_id}/projects/{project_id}/audio/preview/{seg.id}.mp3"
                current_project.update_audio_storage_path(preview_key, expected_path)
            
            logger.info(f"已提交 {total_with_audio} 个预览音频到异步上传队列")
            
            # 保存 TTS 配置
            selected_tts_service = st.session_state.get('selected_tts_service', 'minimax')
            selected_voice_id = st.session_state.get('selected_voice_id', '')
            current_project.set_tts_config(selected_tts_service, selected_voice_id)
            
            # 🔥 重要：立即保存项目以持久化 audio_storage_paths
            try:
                self.project_integration.save_project_state(current_project, st.session_state)
                logger.info(f"已保存项目音频路径映射: {len(current_project.audio_storage_paths)} 条")
            except Exception as save_err:
                logger.warning(f"保存音频路径映射时出错: {save_err}")
            
        except Exception as e:
            logger.error(f"提交预览音频上传任务失败: {e}")
    
    def _generate_audio_simple(self, segments: List[SegmentDTO], target_language: str, tts_engine) -> List[SegmentDTO]:
        """简单音频生成（无迭代优化，作为回退方案）"""
        logger.info(f"使用简单模式生成 {len(segments)} 个音频片段")
        
        # 准备TTS需要的数据格式
        segments_for_tts = []
        valid_segments = []
        
        for seg in segments:
            if seg.final_text:
                tts_segment = {
                    'id': seg.id,
                    'start': seg.start,
                    'end': seg.end,
                    'original_text': seg.original_text,
                    'translated_text': seg.final_text,
                    'duration': seg.target_duration
                }
                segments_for_tts.append(tts_segment)
                valid_segments.append(seg)
        
        if not segments_for_tts:
            logger.warning("没有有效的文本片段需要生成音频")
            return segments
        
        with st.spinner(f"正在生成 {len(segments_for_tts)} 个音频片段..."):
            audio_segments = tts_engine.generate_audio_segments(segments_for_tts, target_language)
        
        audio_map = {seg['id']: seg for seg in audio_segments}
        
        for seg in valid_segments:
            if seg.id in audio_map:
                audio_seg = audio_map[seg.id]
                if audio_seg.get('audio_data'):
                    seg.set_audio_data(audio_seg['audio_data'])
                    if seg.target_duration > 0:
                        error_ms = abs(seg.actual_duration - seg.target_duration) * 1000
                        seg.timing_error_ms = error_ms
                        error_percent = error_ms / (seg.target_duration * 1000) * 100
                        if error_percent <= 5:
                            seg.quality = 'excellent'
                        elif error_percent <= 15:
                            seg.quality = 'good'
                        elif error_percent <= 30:
                            seg.quality = 'fair'
                        else:
                            seg.quality = 'poor'
                    else:
                        seg.quality = 'good'
                else:
                    seg.quality = 'error'
        
        logger.info(f"✅ 简单模式生成 {len(segments)} 个片段音频完成")
        return segments
    
    
    def _render_segmentation_analysis(self, session_data: Dict[str, Any]) -> Dict[str, Any]:
        """渲染分段分析界面"""
        logger.debug("🧠 进入分段分析渲染方法")
        
        input_file_path = session_data.get('input_file_path')
        logger.debug(f"📁 输入文件路径: {input_file_path}")
        
        if not input_file_path:
            logger.error("❌ 未找到文件路径")
            
            # 检查是否是从工程加载的情况，如果是，说明用户应该直接跳到后续阶段
            current_project = session_data.get('current_project')
            if current_project and isinstance(current_project, ProjectDTO):
                logger.info("当前是工程模式，检查是否已有分段数据")
                if current_project.segmented_segments:
                    logger.info("工程已有分段数据，跳转到分段确认阶段")
                    session_data['processing_stage'] = 'confirm_segmentation'
                    return session_data
                elif current_project.confirmed_segments:
                    logger.info("工程已有确认分段数据，跳转到语言选择阶段")
                    session_data['processing_stage'] = 'language_selection'
                    return session_data
                elif current_project.translated_segments:
                    logger.info("工程已有翻译数据，跳转到音频确认阶段")
                    session_data['processing_stage'] = 'user_confirmation'
                    return session_data
                else:
                    st.error("❌ 工程没有可用的处理数据，请重新上传文件")
                    session_data['processing_stage'] = 'project_home'
                    return session_data
            else:
                st.error("❌ 未找到文件路径，请重新上传文件")
                session_data['processing_stage'] = 'project_home'
                return session_data
        
        # 检查是否已经处理过
        has_segments = 'segments' in session_data and session_data['segments']
        has_segmented = 'segmented_segments' in session_data and session_data['segmented_segments']
        logger.debug(f"🔍 检查已处理状态: segments={has_segments}, segmented_segments={has_segmented}")
        
        if (has_segments and has_segmented):
            logger.debug("✅ 数据已处理过，跳转到确认阶段")
            session_data['processing_stage'] = 'confirm_segmentation'
            return session_data  # 不需要rerun，让自然流程继续
        
        # 执行分段分析
        logger.info("🚀 开始执行分段分析")
        st.header("🧠 规则分段处理中...")
        progress_container = st.container()
        
        with progress_container:
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            def progress_callback(current: int, total: int, message: str):
                progress_bar.progress(current / 100)
                status_text.text(f"分段处理: {message}")
                logger.debug(f"📊 分段进度: {current}% - {message}")
            
            try:
                # 加载和分段处理
                logger.debug("📚 导入分段处理模块")
                from audio_processor.subtitle_processor import SubtitleProcessor
                from audio_processor.subtitle_segmenter import SubtitleSegmenter
                
                logger.debug("🔧 初始化字幕处理器")
                subtitle_processor = SubtitleProcessor(self.config)
                segments = subtitle_processor.load_subtitle(input_file_path)
                logger.info(f"📄 加载字幕成功，共 {len(segments)} 个片段")
                
                logger.debug("🔧 初始化分段器")
                segmenter = SubtitleSegmenter(self.config, progress_callback=progress_callback)
                segmented_segments = segmenter.segment_subtitles(segments)
                logger.info(f"✂️ 分段完成，共 {len(segmented_segments)} 个分段")
                
                # 转换为SegmentDTO格式
                logger.debug("�� 转换为SegmentDTO格式")
                try:
                    session_data['segments'] = [
                        SegmentDTO.from_legacy_segment(seg) for seg in segments
                    ]
                    logger.info(f"✅ 原始片段转换完成: {len(session_data['segments'])} 个")
                    
                    session_data['segmented_segments'] = [
                        SegmentDTO.from_legacy_segment(seg) for seg in segmented_segments
                    ]
                    logger.info(f"✅ 分段片段转换完成: {len(session_data['segmented_segments'])} 个")
                except Exception as dto_error:
                    logger.error(f"❌ SegmentDTO转换失败: {dto_error}", exc_info=True)
                    raise
                
                progress_bar.progress(100)
                status_text.text("📝 分析完成，请查看结果...")
                
                logger.debug("✅ 分段分析完成，设置下一阶段")
                session_data['processing_stage'] = 'confirm_segmentation'
                logger.debug("🔄 状态已设置为: confirm_segmentation")
                logger.debug(f"🔍 准备返回的数据: segments={len(session_data.get('segments', []))}, segmented_segments={len(session_data.get('segmented_segments', []))}")
                
                # 清理进度显示
                progress_bar.empty()
                status_text.empty()
                st.success("✅ 分段分析完成！正在跳转到确认页面...")
                
                # 重要：返回数据而不是立即rerun，让数据先被保存
                return session_data
                
            except Exception as e:
                logger.error(f"❌ 分段分析失败: {e}")
                st.error(f"❌ 分段分析失败: {str(e)}")
                session_data['processing_stage'] = 'initial'
        
        return session_data
    
    def _render_segmentation_confirmation(self, session_data: Dict[str, Any]) -> Dict[str, Any]:
        """渲染分段确认界面"""
        logger.debug("✅ 进入分段确认渲染方法")
        
        segments = session_data.get('segments', [])
        segmented_segments = session_data.get('segmented_segments', [])
        
        logger.debug(f"📊 分段确认数据: segments={len(segments)}, segmented_segments={len(segmented_segments)}")
        
        if not segments or not segmented_segments:
            logger.error("❌ 分段数据丢失")
            
            # 检查是否有当前工程，尝试从工程恢复数据
            current_project = session_data.get('current_project')
            if current_project and isinstance(current_project, ProjectDTO):
                logger.info("尝试从当前工程恢复分段数据")
                
                # 改进的恢复逻辑：优先恢复已确认的分段，然后是分段结果，最后是原始片段
                recovered = False
                
                # 1. 尝试从确认分段恢复（优先级最高）
                if current_project.confirmed_segments:
                    session_data['segmented_segments'] = [
                        SegmentDTO.from_legacy_segment(seg) for seg in current_project.confirmed_segments
                    ]
                    logger.info(f"✅ 从确认分段恢复segmented_segments: {len(session_data['segmented_segments'])} 个")
                    recovered = True
                
                # 2. 如果没有确认分段，从分段结果恢复
                elif current_project.segmented_segments:
                    session_data['segmented_segments'] = [
                        SegmentDTO.from_legacy_segment(seg) for seg in current_project.segmented_segments
                    ]
                    logger.info(f"✅ 从分段结果恢复segmented_segments: {len(session_data['segmented_segments'])} 个")
                    recovered = True
                
                # 3. 恢复原始片段
                if current_project.segments:
                    session_data['segments'] = [
                        SegmentDTO.from_legacy_segment(seg) for seg in current_project.segments
                    ]
                    logger.info(f"✅ 从工程恢复segments: {len(session_data['segments'])} 个")
                    recovered = True
                
                if recovered:
                    # 数据恢复成功，更新本地变量继续处理
                    segments = session_data.get('segments', [])
                    segmented_segments = session_data.get('segmented_segments', [])
                    logger.info(f"✅ 分段数据恢复完成: segments={len(segments)}, segmented_segments={len(segmented_segments)}")
                else:
                    st.error("❌ 分段数据丢失且工程中也没有备份数据，需要重新处理")
                    logger.warning("工程中没有任何分段数据，跳转回工程主页")
                    session_data['processing_stage'] = 'project_home'
                    return session_data
            else:
                st.error("❌ 分段数据丢失且无当前工程，请重新分析")
                logger.warning("无法恢复分段数据：没有当前工程或工程数据不完整")
                session_data['processing_stage'] = 'project_home'
                return session_data
        
        # 使用分段确认组件
        result = self.segmentation_view.render_confirmation(
            segments, segmented_segments, self.config
        )
        
        if result['action'] == 'confirm':
            # 转换确认的分段为SegmentDTO并添加ID
            confirmed_segments = []
            for i, seg in enumerate(result['confirmed_segments']):
                if isinstance(seg, SegmentDTO):
                    seg.id = f"seg_{i+1}"
                    confirmed_segments.append(seg)
                else:
                    dto = SegmentDTO.from_legacy_segment(seg)
                    dto.id = f"seg_{i+1}"
                    confirmed_segments.append(dto)
            
            session_data['confirmed_segments'] = confirmed_segments
            
            
            # 清理分段视图的session_state，因为已经确认完成
            segmentation_keys = ['segmentation_edited_segments', 'segmentation_current_page', 'segmentation_original_segments']
            for key in segmentation_keys:
                if key in st.session_state:
                    del st.session_state[key]
            
            # 进入下一阶段
            session_data['processing_stage'] = 'language_selection'
            
        elif result['action'] == 'restart':
            # 重置状态 - 但保持合理的处理阶段
            keys_to_reset = ['segments', 'segmented_segments', 'input_file_path']
            for key in keys_to_reset:
                session_data.pop(key, None)
            
            # 设置为工程管理主页，而不是删除processing_stage
            session_data['processing_stage'] = 'project_home'
            
            # 清理分段视图的session_state
            segmentation_keys = ['segmentation_edited_segments', 'segmentation_current_page', 'segmentation_original_segments']
            for key in segmentation_keys:
                if key in st.session_state:
                    del st.session_state[key]
        
        return session_data
    
    def _render_language_selection(self, session_data: Dict[str, Any]) -> Dict[str, Any]:
        """渲染语言选择界面"""
        logger.debug("🌍 进入语言选择渲染方法")
        
        result = self.language_selection_view.render(self.config)
        
        if result['action'] == 'start_dubbing':
            # 更新配置和目标语言
            logger.info(f"🎯 开始配音流程，目标语言: {result['target_lang']}")
            session_data['target_lang'] = result['target_lang']
            session_data['config'] = result['updated_config']
            session_data['processing_stage'] = 'translating'
            logger.debug(f"🔄 状态已设置为: {session_data['processing_stage']}")
            # 返回数据而不是立即rerun，让数据先被保存
            return session_data
            
        elif result['action'] == 'back_to_segmentation':
            logger.debug("🔙 用户选择返回分段确认")
            session_data['processing_stage'] = 'confirm_segmentation'
            logger.debug(f"🔄 状态已设置为: {session_data['processing_stage']}")
            # 返回数据而不是立即rerun，让数据先被保存
            return session_data
        
        return session_data
    
    def _render_translation_progress(self, session_data: Dict[str, Any]) -> Dict[str, Any]:
        """渲染翻译进度界面"""
        logger.debug("🔄 进入翻译进度渲染方法")
        
        confirmed_segments = session_data.get('confirmed_segments', [])
        target_language = session_data.get('target_lang')
        
        if not confirmed_segments or not target_language:
            st.error("❌ 缺少必要的数据进行翻译")
            session_data['processing_stage'] = 'language_selection'
            return session_data
        
        # 导入翻译工厂
        from translation.translation_factory import TranslationFactory
        
        # 创建进度显示
        progress_container = st.container()
        with progress_container:
            st.subheader("🌍 正在翻译字幕...")
            
            # 显示翻译服务信息
            translation_config = self.config.get('translation', {})
            if 'service' in translation_config:
                service_name = translation_config.get('service', 'google').upper()
                st.info(f"📡 使用 {service_name} 翻译服务进行上下文感知翻译")
            else:
                st.info("📡 使用传统GPT翻译服务")
            
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            def progress_callback(current, total, message):
                progress = int((current / total) * 100) if total > 0 else 0
                progress_bar.progress(progress)
                status_text.text(f"{message} ({current}/{total})")
            
            try:
                # 使用翻译工厂创建翻译器
                translator = TranslationFactory.create_translator(self.config, progress_callback)
                
                # 显示翻译器统计信息
                if hasattr(translator, 'get_translation_stats'):
                    st.info("📊 使用新一代上下文感知翻译引擎")
                else:
                    st.info("📊 使用传统GPT翻译引擎")
                
                # 转换为适合翻译的格式
                segments_for_translation = []
                for seg in confirmed_segments:
                    if isinstance(seg, SegmentDTO):
                        # 对于新的上下文翻译器，使用简化的字典格式
                        if hasattr(translator, 'translate_segments_with_context'):
                            segment_dict = {
                                'id': seg.id,
                                'start': seg.start,
                                'end': seg.end,
                                'text': seg.original_text,
                                'duration': seg.target_duration
                            }
                        else:
                            # 传统翻译器使用完整格式
                            segment_dict = seg.to_legacy_dict()
                    else:
                        segment_dict = seg
                    segments_for_translation.append(segment_dict)
                
                # 根据翻译器类型选择翻译方法
                if hasattr(translator, 'translate_segments_with_context'):
                    # 新的上下文感知翻译器
                    translated_segments = getattr(translator, 'translate_segments_with_context')(
                        segments_for_translation, target_language
                    )
                elif hasattr(translator, 'translate_segments_with_cache'):
                    # 传统翻译器
                    translated_segments = getattr(translator, 'translate_segments_with_cache')(
                        segments_for_translation, target_language, progress_callback
                    )
                else:
                    # 最基本的翻译方法
                    texts = [seg.get('text', '') for seg in segments_for_translation]
                    translated_texts = getattr(translator, 'translate_segments')(texts, target_language, progress_callback)
                    translated_segments = []
                    for i, seg in enumerate(segments_for_translation):
                        new_seg = seg.copy()
                        new_seg['translated_text'] = translated_texts[i] if i < len(translated_texts) else seg.get('text', '')
                        translated_segments.append(new_seg)
                
                # 转换回SegmentDTO格式
                translated_dto_segments = []
                for seg in translated_segments:
                    if isinstance(seg, dict):
                        dto = SegmentDTO.from_legacy_segment(seg)
                        # 确保翻译文本被正确设置
                        if 'translated_text' in seg:
                            dto.translated_text = seg['translated_text']
                            dto.final_text = seg['translated_text']  # 直接设置为最终文本，不需要优化
                    else:
                        dto = seg
                    translated_dto_segments.append(dto)
                
                # 保存翻译器实例用于统计
                session_data['translator_instance'] = translator
                session_data['translated_segments'] = translated_dto_segments
                
                # 🔥 关键修复：设置工程的翻译服务信息
                current_project = session_data.get('current_project')
                if current_project and isinstance(current_project, ProjectDTO):
                    # 获取实际使用的翻译服务名称
                    actual_translation_service = translation_config.get('service', 'google')
                    current_project.set_translation_config(
                        target_lang=target_language,
                        service=actual_translation_service
                    )
                    logger.info(f"工程翻译服务已设置为: {actual_translation_service}")
                
                progress_bar.progress(100)
                status_text.text("✅ 翻译完成！")
                
                # 直接进入音频确认，跳过优化迭代
                session_data['processing_stage'] = 'user_confirmation'
                
                # 清理进度显示
                progress_bar.empty()
                status_text.empty()
                st.success("✅ 翻译完成！正在跳转到音频确认页面...")
                
                return session_data
                
            except Exception as e:
                logger.error(f"❌ 翻译失败: {e}")
                st.error(f"❌ 翻译失败: {str(e)}")
                session_data['processing_stage'] = 'language_selection'
        
        return session_data
    

    
    def _render_optimization_progress_deprecated(self, session_data: Dict[str, Any]) -> Dict[str, Any]:
        """渲染优化进度界面"""
        with st.spinner("⏱️ 正在进行时间同步优化..."):
            try:
                validated_segments = session_data.get('validated_segments', [])
                target_lang = session_data.get('target_lang', 'en')
                user_choices = session_data.get('user_adjustment_choices', {})
                
                if not validated_segments:
                    st.error("❌ 翻译数据丢失")
                    session_data['processing_stage'] = 'language_selection'
                    return session_data
                
                from timing.sync_manager import PreciseSyncManager
                from translation.translator import Translator
                from tts import create_tts_engine
                
                sync_manager = PreciseSyncManager(self.config, progress_callback=None)
                
                # 优先使用已有的translator实例以保持统计连续性
                translator = session_data.get('translator_instance')
                if not translator:
                    translator = Translator(self.config)
                    session_data['translator_instance'] = translator
                
                tts = create_tts_engine(self.config)
                # 保存tts实例以便后续统计
                session_data['tts_instance'] = tts
                
                # 转换为legacy格式进行处理
                legacy_segments = [seg.to_legacy_dict() for seg in validated_segments]
                
                # 并发执行优化流程（三个步骤批量处理）
                st.info("🚀 开始并发优化处理...")
                
                # 显示进度条
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                def progress_callback(current: int, total: int, message: str):
                    progress = min(current / total, 1.0)
                    progress_bar.progress(progress)
                    status_text.text(f"优化进度: {message} ({current}/{total})")
                
                # 使用带进度回调的sync_manager
                sync_manager_with_progress = PreciseSyncManager(self.config, progress_callback=progress_callback)
                
                # 并发执行优化流程
                analyzed_segments = sync_manager_with_progress.concurrent_full_optimization(
                    legacy_segments, translator, tts, target_lang
                )
                
                progress_bar.progress(1.0)
                status_text.text("✅ 优化处理完成！")
                
                # 转换回SegmentDTO格式，确保音频数据正确传递
                optimized_dtos = []
                confirmation_dtos = []
                
                for seg in analyzed_segments:
                    # 优化后的数据
                    dto = SegmentDTO.from_legacy_segment(seg)
                    optimized_dtos.append(dto)
                    
                    # 确认数据（使用相同的音频数据，不重复生成）
                    confirmation_dto = SegmentDTO.from_legacy_segment(seg)
                    
                    # 确保音频数据正确设置
                    if seg.get('audio_data'):
                        confirmation_dto.set_audio_data(seg['audio_data'])
                        logger.debug(f"片段 {seg.get('id', 'unknown')} 音频数据设置完成")
                    elif seg.get('audio_file'):
                        # 如果有音频文件路径，尝试加载
                        try:
                            from pydub import AudioSegment
                            audio = AudioSegment.from_file(seg['audio_file'])
                            confirmation_dto.set_audio_data(audio)
                            logger.debug(f"片段 {seg.get('id', 'unknown')} 从文件加载音频数据")
                        except Exception as e:
                            logger.warning(f"无法从文件加载音频数据: {e}")
                    else:
                        logger.warning(f"片段 {seg.get('id', 'unknown')} 没有音频数据")
                    
                    # 重要：确保final_text显示的是实际用于生成音频的文本
                    # 优先使用optimized_text（多轮迭代优化后的结果）
                    if seg.get('optimized_text'):
                        confirmation_dto.final_text = seg['optimized_text']
                        logger.debug(f"片段 {seg.get('id', 'unknown')} 使用优化文本作为最终文本")
                    elif seg.get('translated_text'):
                        confirmation_dto.final_text = seg['translated_text']
                        logger.debug(f"片段 {seg.get('id', 'unknown')} 使用翻译文本作为最终文本")
                    else:
                        confirmation_dto.final_text = seg.get('original_text', '')
                        logger.warning(f"片段 {seg.get('id', 'unknown')} 使用原始文本作为最终文本")
                    
                    # 设置确认相关的字段
                    confirmation_dto.confirmed = False
                    confirmation_dto.user_modified = False
                    confirmation_dto.timing_error_ms = seg.get('timing_error_ms', 0)
                    confirmation_dto.quality = seg.get('quality', 'unknown')
                    confirmation_dto.timing_analysis = seg.get('timing_analysis', {})
                    confirmation_dto.adjustment_suggestions = seg.get('adjustment_suggestions', [])
                    confirmation_dto.needs_user_confirmation = seg.get('needs_user_confirmation', False)
                    
                    confirmation_dtos.append(confirmation_dto)
                
                session_data['optimized_segments'] = optimized_dtos
                session_data['confirmation_segments'] = confirmation_dtos
                
                # 生成最终字幕数据
                session_data['translated_original_segments'] = self._redistribute_translations(
                    optimized_dtos, session_data.get('segments', [])
                )
                
                # 记录音频数据统计
                audio_count = sum(1 for dto in confirmation_dtos if dto.audio_data is not None)
                logger.info(f"✅ 优化完成，共 {len(confirmation_dtos)} 个片段，其中 {audio_count} 个有音频数据")
                
                session_data['processing_stage'] = 'user_confirmation'
                logger.info(f"✅ 优化完成，状态设置为: {session_data['processing_stage']}")
                # 返回数据而不是立即rerun，让数据先被保存
                return session_data
                
            except Exception as e:
                st.error(f"❌ 优化过程中发生错误: {str(e)}")
                logger.error(f"优化失败: {e}")
                session_data['processing_stage'] = 'language_selection'
        
        return session_data
    
    def _render_audio_confirmation(self, session_data: Dict[str, Any]) -> Dict[str, Any]:
        """渲染音频确认界面"""
        # 支持新的翻译流程（直接来自翻译）和旧的优化流程
        translated_segments = session_data.get('translated_segments', [])
        optimized_segments = session_data.get('optimized_segments', [])
        confirmation_segments = session_data.get('confirmation_segments', [])
        translated_original_segments = session_data.get('translated_original_segments', [])
        target_lang = session_data.get('target_lang', 'en')
        
        # 🔥 检查云端音频可用性（懒加载策略，不实际下载）
        current_project = session_data.get('current_project')
        has_cloud_audio = False
        if current_project and hasattr(current_project, 'audio_storage_paths') and current_project.audio_storage_paths:
            # 检查 translated_segments 的云端音频
            if translated_segments and not any(seg.audio_data for seg in translated_segments):
                available_count = self._restore_audio_from_storage(translated_segments, current_project)
                if available_count > 0:
                    has_cloud_audio = True
            
            # 检查 confirmation_segments 的云端音频
            if confirmation_segments and not any(seg.audio_data for seg in confirmation_segments):
                available_count = self._restore_audio_from_storage(confirmation_segments, current_project)
                if available_count > 0:
                    has_cloud_audio = True
        
        # 如果有翻译数据但没有优化数据，直接使用翻译数据
        if translated_segments and not optimized_segments:
            logger.debug("使用直接翻译数据进行音频确认")
            
            # 🔥 改进：只有在没有云端音频且没有内存音频时才生成新音频
            has_memory_audio = any(seg.audio_data for seg in translated_segments)
            has_audio_path = any(seg.audio_path for seg in translated_segments)
            
            if not has_memory_audio and not has_audio_path and not has_cloud_audio:
                logger.info("开始为翻译段生成音频...")
                translated_segments = self._generate_audio_for_segments(translated_segments, target_lang)
                # 确保TTS实例在session_data中也保存
                if 'tts_instance' in st.session_state:
                    session_data['tts_instance'] = st.session_state['tts_instance']
            elif has_cloud_audio or has_audio_path:
                logger.debug("检测到云端音频可用，跳过重新生成")
            
            # 记录音频数据状态
            audio_count = sum(1 for seg in translated_segments if seg.audio_data is not None)
            path_count = sum(1 for seg in translated_segments if seg.audio_path)
            logger.debug(f"翻译段音频状态：共{len(translated_segments)}个段，{audio_count}个有内存音频，{path_count}个有云端路径")
            
            # 使用翻译段作为确认段（深度复制以确保数据完整性）
            optimized_segments = translated_segments
            confirmation_segments = []
            for seg in translated_segments:
                # 创建新的SegmentDTO实例确保数据完整性
                new_seg = SegmentDTO.from_legacy_segment(seg.to_legacy_dict())
                # 重要：确保音频数据和路径正确复制
                if seg.audio_data is not None:
                    new_seg.set_audio_data(seg.audio_data)
                    logger.debug(f"片段 {seg.id} 音频数据已复制到确认段")
                elif seg.audio_path:
                    new_seg.audio_path = seg.audio_path
                    logger.debug(f"片段 {seg.id} 云端音频路径已复制到确认段")
                else:
                    logger.warning(f"片段 {seg.id} 缺少音频数据和云端路径")
                confirmation_segments.append(new_seg)
            
            # 生成原始片段的翻译版本
            translated_original_segments = self._redistribute_translations(
                translated_segments, session_data.get('segments', [])
            )
            
            # 更新session_data
            session_data['optimized_segments'] = optimized_segments
            session_data['confirmation_segments'] = confirmation_segments
            session_data['translated_original_segments'] = translated_original_segments
        
        # 尝试从翻译数据重建缺少的派生数据（这是正常流程，不需要警告用户）
        if translated_segments:
            rebuilt_items = []
            
            if not optimized_segments:
                optimized_segments = translated_segments
                session_data['optimized_segments'] = optimized_segments
                rebuilt_items.append("优化片段")
            
            if not confirmation_segments:
                confirmation_segments = []
                for seg in translated_segments:
                    new_seg = SegmentDTO.from_legacy_segment(seg.to_legacy_dict())
                    if seg.audio_data is not None:
                        new_seg.set_audio_data(seg.audio_data)
                    elif seg.audio_path:
                        new_seg.audio_path = seg.audio_path
                    confirmation_segments.append(new_seg)
                session_data['confirmation_segments'] = confirmation_segments
                rebuilt_items.append("确认片段")
            
            if not translated_original_segments:
                translated_original_segments = self._redistribute_translations(
                    translated_segments, session_data.get('segments', [])
                )
                session_data['translated_original_segments'] = translated_original_segments
                rebuilt_items.append("翻译原始片段")
            
            if rebuilt_items:
                logger.info(f"从翻译数据重建派生数据: {', '.join(rebuilt_items)}")
        
        # 验证必要数据（仅在重建后仍然缺少关键数据时才提示）
        missing_critical_data = []
        if not optimized_segments:
            missing_critical_data.append("优化片段")
        if not confirmation_segments:
            missing_critical_data.append("确认片段")
        
        if missing_critical_data:
            # 真正缺少关键数据才需要回退
            logger.error(f"音频确认阶段缺少关键数据: {', '.join(missing_critical_data)}")
            st.error("❌ 关键翻译数据丢失，需要重新处理")
            session_data['processing_stage'] = 'language_selection'
            return session_data
        
        # 验证音频数据完整性（同时检查内存音频和云端路径）
        def has_audio_available(seg):
            """检查片段是否有可用音频（内存或云端）"""
            return seg.audio_data is not None or (seg.audio_path and len(seg.audio_path) > 0)
        
        audio_missing_count = sum(1 for seg in confirmation_segments if not has_audio_available(seg))
        audio_memory_count = sum(1 for seg in confirmation_segments if seg.audio_data is not None)
        audio_cloud_count = sum(1 for seg in confirmation_segments if seg.audio_path and seg.audio_data is None)
        
        if audio_missing_count > 0:
            logger.warning(f"警告：{audio_missing_count}/{len(confirmation_segments)} 个确认片段完全缺少音频")
            st.warning(f"⚠️ 发现 {audio_missing_count} 个片段缺少音频数据，系统将在确认时自动生成")
        
        # 使用音频确认组件
        result = self.audio_confirmation_view.render(
            optimized_segments, confirmation_segments, 
            translated_original_segments, target_lang, self.config
        )
        
        # 确保用户修改后的confirmation_segments被保存到session_data中
        session_data['confirmation_segments'] = confirmation_segments
        
        if result['action'] == 'generate_final':
            # 添加调试日志，检查确认后的segments数据
            confirmed_segments = result['confirmed_segments']
            logger.info(f"准备生成最终音频，确认片段数量: {len(confirmed_segments)}")
            
            # 详细记录每个片段的状态
            for i, seg in enumerate(confirmed_segments):
                logger.debug(f"确认片段 {i+1}/{len(confirmed_segments)}: "
                           f"id={seg.id}, confirmed={seg.confirmed}, "
                           f"user_modified={seg.user_modified}, "
                           f"final_text='{seg.final_text[:50]}...', "
                           f"quality={seg.quality}, "
                           f"timing_error_ms={seg.timing_error_ms}, "
                           f"has_audio={seg.audio_data is not None}")
            
            # 生成最终音频
            self._generate_final_audio(confirmed_segments, session_data)
            session_data['processing_stage'] = 'completion'
            logger.info(f"✅ 最终音频生成完成")
            # 返回数据而不是立即rerun，让数据先被保存
            return session_data
            
        elif result['action'] == 'back_to_language':
            session_data['processing_stage'] = 'language_selection'
            logger.debug(f"🔙 返回语言选择")
            # 返回数据而不是立即rerun，让数据先被保存
            return session_data
        
        return session_data
    
    def _render_completion(self, session_data: Dict[str, Any]) -> Dict[str, Any]:
        """渲染完成界面"""
        completion_data = session_data.get('completion_results')
        
        if not completion_data:
            st.error("❌ 未找到处理结果，请重新开始")
            if st.button("🔄 重新开始", key="restart_from_error"):
                self._reset_all_states(session_data)
                logger.info("🔄 用户从错误页面选择重新开始")
                # 返回数据而不是立即rerun，让数据先被保存
                return session_data
            return session_data
        
        # 使用完成界面组件
        result = self.completion_view.render(completion_data)
        
        if result['action'] == 'restart':
            self._reset_all_states(session_data)
            logger.info("🔄 用户选择重新开始")
            # 返回数据而不是立即rerun，让数据先被保存
            return session_data
        elif result['action'] == 'back_to_audio_confirmation':
            # 返回音频确认页面
            session_data['processing_stage'] = 'user_confirmation'
            logger.info("🔙 用户选择返回音频确认页面")
            # 返回数据而不是立即rerun，让数据先被保存
            return session_data
        
        return session_data
    
    
    def _redistribute_translations(self, translated_segments: List[SegmentDTO], 
        original_segments: List[SegmentDTO]) -> List[SegmentDTO]:
        """将翻译重新分配到原始时间分割上"""
        # 简化的重分配逻辑，避免依赖不存在的模块
        redistributed = []
        for i, original_seg in enumerate(original_segments):
            if i < len(translated_segments):
                # 创建新的SegmentDTO实例并复制翻译文本
                new_seg = SegmentDTO.from_legacy_segment(original_seg.to_legacy_dict())
                if hasattr(translated_segments[i], 'translated_text'):
                    new_seg.translated_text = translated_segments[i].translated_text  
                redistributed.append(new_seg)
            else:
                redistributed.append(original_seg)
        
        return redistributed
    
    def _generate_final_audio(self, confirmed_segments: List[SegmentDTO], 
                             session_data: Dict[str, Any]):
        """生成最终音频"""
        try:
            from timing.audio_synthesizer import AudioSynthesizer
            from tts import create_tts_engine
            
            audio_synthesizer = AudioSynthesizer(self.config)
            
            # 获取用户选择的TTS服务
            selected_tts_service = st.session_state.get('selected_tts_service', 'minimax')
            selected_voice_id = st.session_state.get('selected_voice_id')
            
            # 优先使用已保存的tts实例以保持统计连续性
            tts = session_data.get('tts_instance') or st.session_state.get('tts_instance')
            current_service = st.session_state.get('current_tts_service')
            
            # 检查是否需要重新创建TTS引擎（服务类型变更）
            if not tts or current_service != selected_tts_service:
                logger.info(f"创建TTS引擎用于最终音频: {selected_tts_service}")
                tts = create_tts_engine(self.config, selected_tts_service)
                session_data['tts_instance'] = tts
                st.session_state['tts_instance'] = tts
                st.session_state['current_tts_service'] = selected_tts_service
            
            # 如果是ElevenLabs且用户选择了特定音色，设置它
            if selected_tts_service == 'elevenlabs' and selected_voice_id:
                tts.set_voice(selected_voice_id)
            
            target_lang = session_data.get('target_lang', 'en')
            current_project = session_data.get('current_project')
            
            # 🔥 重要：在合并前下载缺失的云端音频
            # 检查已确认但只有云端路径没有内存数据的片段
            segments_need_download = [
                seg for seg in confirmed_segments 
                if seg.confirmed and seg.audio_data is None and seg.audio_path
            ]
            
            if segments_need_download and current_project:
                logger.info(f"发现 {len(segments_need_download)} 个已确认片段需要从云端下载音频")
                download_progress = st.progress(0, text="正在下载云端音频...")
                
                for i, seg in enumerate(segments_need_download):
                    download_progress.progress(
                        (i + 1) / len(segments_need_download),
                        text=f"正在下载音频 {i + 1}/{len(segments_need_download)}..."
                    )
                    success = self._download_single_segment_audio(seg, current_project)
                    if not success:
                        logger.warning(f"片段 {seg.id} 音频下载失败")
                
                download_progress.empty()
                logger.info("云端音频下载完成")
            
            # 验证确认片段的音频数据
            audio_available_count = sum(1 for seg in confirmed_segments if seg.audio_data is not None)
            confirmed_count = sum(1 for seg in confirmed_segments if seg.confirmed)
            logger.info(f"最终音频生成验证：{len(confirmed_segments)}个片段，{confirmed_count}个已确认，{audio_available_count}个有音频数据")
            
            if audio_available_count == 0:
                logger.error("❌ 所有确认片段都没有音频数据！")
                st.error("❌ 无法生成最终音频：所有片段都缺少音频数据，请确保至少有一个片段有音频")
                return
            elif audio_available_count < confirmed_count:
                missing_count = confirmed_count - audio_available_count
                logger.warning(f"⚠️ {missing_count}个已确认片段缺少音频数据")
                st.warning(f"⚠️ {missing_count}个已确认片段缺少音频数据，这些片段将在最终音频中显示为静音")
            
            # 转换为legacy格式
            legacy_segments = [seg.to_legacy_dict() for seg in confirmed_segments]
            
            # 合并音频
            final_audio = audio_synthesizer.merge_confirmed_audio_segments(legacy_segments)
            
            # 获取工程名用于输出文件命名
            project_name = getattr(current_project, 'name', None) if current_project else None
            
            # 如果没有工程名，使用默认名称
            if not project_name:
                project_name = f"dubbed_audio_{target_lang}"
            
            # 清理文件名中的非法字符
            safe_project_name = "".join(c if c.isalnum() or c in ('-', '_', ' ', '.') else '_' for c in project_name)
            
            # 保存文件 - 使用工程名作为文件名（音频使用 MP3 格式节省空间）
            audio_output = f"{safe_project_name}_{target_lang}.mp3"
            
            # Windows系统优化的音频导出
            import platform
            from pathlib import Path
            from utils.windows_audio_utils import get_windows_audio_utils, is_windows
            
            if is_windows():
                # 使用Windows音频工具进行安全导出
                windows_utils = get_windows_audio_utils()
                output_path = Path(audio_output)
                
                if windows_utils.safe_export_audio(final_audio, output_path):
                    logger.info(f"Windows系统音频导出完成: {audio_output}")
                else:
                    raise Exception(f"Windows音频导出失败: {audio_output}")
            else:
                # 非Windows系统使用原有逻辑，导出为 MP3 格式
                final_audio.export(audio_output, format="mp3", bitrate="128k")
                logger.info(f"音频导出完成: {audio_output}")
                
                # 验证输出文件
                output_path = Path(audio_output)
                if not output_path.exists() or output_path.stat().st_size == 0:
                    raise Exception(f"最终音频文件创建失败或为空: {audio_output}")
            
            # 保存结果到session
            with open(audio_output, 'rb') as f:
                audio_data = f.read()
            
            # 🔥 上传到 Firebase Storage（如果启用）
            storage_upload_results = self._upload_to_firebase_storage(
                current_project, confirmed_segments, audio_data,
                audio_output, selected_tts_service, selected_voice_id
            )
            
            # 计算统计信息
            optimized_segments = session_data.get('optimized_segments', [])
            
            # 汇总所有API使用统计
            tts_cost_summary = tts.get_cost_summary()
            
            # 获取翻译API的token统计
            translator = session_data.get('translator_instance')
            if not translator:
                # 如果没有保存的实例，创建一个新实例来获取统计（虽然可能不完整）
                from translation.translator import Translator
                translator = Translator(self.config)
            
            translation_stats = translator.get_token_stats()
            
            # 合并统计信息
            combined_api_usage = {
                'tts_api': tts_cost_summary,
                'translation_api': translation_stats,
                'total_api_calls': tts_cost_summary.get('api_calls', 0) + translation_stats.get('total_requests', 0),
                'session_duration_seconds': max(
                    tts_cost_summary.get('session_duration_seconds', 0),
                    translation_stats.get('session_duration_minutes', 0) * 60
                )
            }
            
            session_data['completion_results'] = {
                'audio_data': audio_data,
                'target_lang': target_lang,
                'project_name': safe_project_name,  # 工程名用于下载文件命名
                'optimized_segments': [seg.to_legacy_dict() for seg in confirmed_segments],  # 使用用户确认后的segments
                'cost_summary': tts_cost_summary,  # 保持向后兼容
                'api_usage_summary': combined_api_usage,  # 新的综合统计
                'stats': {
                    'total_segments': len(confirmed_segments),
                    'total_duration': max(seg.end for seg in confirmed_segments) if confirmed_segments else 0,
                    'excellent_sync': sum(1 for seg in confirmed_segments if seg.quality == 'excellent')
                }
            }
            
        except Exception as e:
            st.error(f"❌ 生成最终音频时发生错误: {str(e)}")
            logger.error(f"生成最终音频失败: {e}")
    
    def _upload_to_firebase_storage(
        self, 
        project: Optional['ProjectDTO'], 
        confirmed_segments: List[SegmentDTO],
        audio_data: bytes,
        audio_filename: str,
        tts_service: str,
        tts_voice_id: str
    ) -> Dict[str, Any]:
        """
        异步上传最终合成音频到 Firebase Storage（可选，优先级低）
        
        注意：片段音频已在 Stage 1/Stage 2 阶段上传，这里只上传最终合成的音频
        不阻塞主线程，提升用户体验
        
        Args:
            project: 当前项目
            confirmed_segments: 确认的片段列表
            audio_data: 最终合成音频数据
            audio_filename: 音频文件名
            tts_service: 使用的 TTS 服务
            tts_voice_id: 使用的音色 ID
            
        Returns:
            上传结果字典
        """
        results = {
            'uploaded': False,
            'final_audio_path': None,
            'error': None
        }
        
        if not project:
            logger.debug("无项目信息，跳过 Firebase Storage 上传")
            return results
        
        # 检查是否使用 Firebase 存储后端
        if project.storage_backend != "firebase":
            logger.debug(f"项目使用 {project.storage_backend} 存储后端，跳过 Firebase Storage 上传")
            return results
        
        try:
            from utils.firebase_storage import get_storage_manager
            from utils.async_upload_manager import get_upload_manager
            
            storage = get_storage_manager()
            if not storage.is_connected:
                logger.warning("Firebase Storage 未连接，跳过上传")
                return results
            
            user_id = project.owner_id
            project_id = project.id
            
            if not user_id or not project_id:
                logger.warning("缺少用户 ID 或项目 ID，跳过 Firebase Storage 上传")
                return results
            
            logger.info(f"开始异步上传最终合成文件到 Firebase Storage: 用户={user_id}, 项目={project_id}")
            
            # 使用异步上传管理器
            upload_manager = get_upload_manager()
            
            # 1. 异步上传最终音频文件
            expected_audio_path = f"users/{user_id}/projects/{project_id}/output/{audio_filename}"
            
            def on_audio_complete(task_id: str, result_path: str, error: str):
                if error:
                    logger.warning(f"最终音频上传失败: {error}")
                else:
                    logger.info(f"最终音频上传成功: {result_path}")
            
            upload_manager.submit_final_audio_upload(
                user_id=user_id,
                project_id=project_id,
                filename=audio_filename,
                audio_data=audio_data,
                callback=on_audio_complete
            )
            
            # 预先设置路径
            project.set_final_output_paths(audio_path=expected_audio_path)
            results['final_audio_path'] = expected_audio_path
            
            # 注意：片段音频已在 Stage 1 (预览) 和 Stage 2 (确认) 阶段上传
            # 这里不再重复上传片段音频
            
            # 2. 保存 TTS 配置到项目
            if tts_service:
                project.set_tts_config(tts_service, tts_voice_id or "")
                logger.info(f"TTS 配置已保存: {tts_service}, voice={tts_voice_id}")
            
            # 3. 记录用户活动日志
            self._log_user_activity(
                user_id, project_id, 
                'completion',
                f"项目完成: {len(confirmed_segments)} 个片段, TTS={tts_service}"
            )
            
            results['uploaded'] = True
            logger.info("最终合成文件已提交到异步上传队列")
            
        except Exception as e:
            results['error'] = str(e)
            logger.error(f"提交最终文件上传任务失败: {e}")
        
        return results
    
    def _log_user_activity(self, user_id: str, project_id: str, action: str, details: str = ""):
        """
        记录用户活动日志到 Firebase
        
        Args:
            user_id: 用户 ID
            project_id: 项目 ID
            action: 操作类型
            details: 详细信息
        """
        try:
            from utils.firebase_activity_logger import get_activity_logger
            
            activity_logger = get_activity_logger()
            activity_logger.log_activity(
                user_id=user_id,
                activity_type=action,
                project_id=project_id,
                details={'message': details} if details else None
            )
            
        except Exception as e:
            logger.warning(f"记录用户活动日志失败: {e}")
    
    def _reset_all_states(self, session_data: Dict[str, Any]):
        """重置所有状态（修复版本 - 不破坏已完成的工程）"""
        # 清理临时文件
        input_file_path = session_data.get('input_file_path')
        if input_file_path and Path(input_file_path).exists():
            try:
                Path(input_file_path).unlink()
                logger.info(f"清理了临时文件: {input_file_path}")
            except Exception as e:
                logger.warning(f"清理临时文件失败: {e}")
        
        # 获取当前工程信息（重要：在清理前保存）
        current_project = session_data.get('current_project')
        
        # 重置会话数据，但保护工程状态
        keys_to_reset = [
            'segments', 'segmented_segments', 
            'confirmed_segments', 'target_lang', 'config', 'input_file_path',
            'completion_results', 'optimized_segments', 'confirmation_segments',
            'translated_original_segments', 'translated_segments', 'validated_segments',
            'current_confirmation_index', 'confirmation_page', 'user_adjustment_choices'
        ]
        
        for key in keys_to_reset:
            session_data.pop(key, None)
        
        # 重要：完全清除工程关联，避免状态损坏
        if current_project:
            logger.info(f"清除工程关联: {getattr(current_project, 'name', '未知')}")
            # 不保存current_project的任何变化，避免污染工程数据
            session_data.pop('current_project', None)
        
        # 重置到工程管理首页（不关联任何具体工程）
        # 注意：不要保存这个状态到工程中！
        session_data['processing_stage'] = 'project_home'
        
        logger.info("用户选择重新开始 - 已重置会话状态，返回工程管理页面")
    
    def _auto_save_project_progress(self, session_data: Dict[str, Any]):
        """自动保存工程进度"""
        try:
            current_project = session_data.get('current_project')
            if current_project and isinstance(current_project, ProjectDTO):
                # 保存工程状态
                success = self.project_integration.save_project_state(current_project, session_data)
                if success:
                    logger.debug(f"工程进度自动保存成功: {current_project.name}")
                else:
                    logger.warning(f"工程进度自动保存失败: {current_project.name}")
        except Exception as e:
            logger.warning(f"自动保存工程进度失败: {e}") 