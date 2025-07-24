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
from ui.components.segmentation_view import SegmentationView
from ui.components.language_selection_view import LanguageSelectionView
# from ui.components.translation_validation_view import TranslationValidationView  # 已移除
from ui.components.audio_confirmation_view import AudioConfirmationView
from ui.components.completion_view import CompletionView
# from ui.components.cache_selection_view import CacheSelectionView  # 注释掉cache相关


class WorkflowManager:
    """工作流管理器 - 统一协调所有UI阶段"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._init_components()
    
    def _init_components(self):
        """初始化所有UI组件"""
        self.segmentation_view = SegmentationView()
        self.language_selection_view = LanguageSelectionView()
        # self.translation_validation_view = TranslationValidationView()  # 已移除
        self.audio_confirmation_view = AudioConfirmationView()
        self.completion_view = CompletionView()
        # self.cache_selection_view = CacheSelectionView()  # 注释掉cache相关
    
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
        
        # 阶段到渲染函数的映射
        stage_renderers = {
            # 'cache_selection': self._render_cache_selection,  # 注释掉cache相关
            # 'cache_restore': self._render_cache_restore,  # 注释掉cache相关
            'initial': self._render_segmentation_analysis,
            'segmentation': self._render_segmentation_analysis,  # 添加segmentation阶段
            'confirm_segmentation': self._render_segmentation_confirmation,
            'language_selection': self._render_language_selection,
            'translating': self._render_translation_progress,
            'optimizing': self._render_optimization_progress,
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
            logger.debug(f"✅ 渲染器执行完成，返回状态: {result.get('processing_stage', 'unknown')}")
            logger.debug(f"📋 返回数据概览: segments={len(result.get('segments', []))}, segmented_segments={len(result.get('segmented_segments', []))}")
            return result
        except Exception as e:
            logger.error(f"❌ 渲染阶段 {stage} 时发生错误: {e}", exc_info=True)
            st.error(f"❌ 渲染阶段 {stage} 时发生错误: {str(e)}")
            return session_data
    
    # def _render_cache_selection(self, session_data: Dict[str, Any]) -> Dict[str, Any]:
    #     """渲染缓存选择界面"""
    #     input_file_path = session_data.get('input_file_path')
    #     if not input_file_path:
    #         st.error("❌ 未找到文件路径")
    #         session_data['processing_stage'] = 'initial'
    #         return session_data
    #     
    #     # 使用缓存选择组件
    #     result = self.cache_selection_view.render(input_file_path)
    #     
    #     if result['action'] == 'new_processing':
    #         session_data['processing_stage'] = 'initial'
    #     elif result['action'] == 'back':
    #         session_data['processing_stage'] = 'initial'
    #         session_data.pop('input_file_path', None)
    #     elif result['action'] == 'use_cache':
    #         session_data['selected_cache'] = result['cache_data']
    #         session_data['processing_stage'] = 'cache_restore'
    #     
    #     return session_data
    
    # def _render_cache_restore(self, session_data: Dict[str, Any]) -> Dict[str, Any]:
    #     """渲染缓存恢复界面"""
    #     selected_cache = session_data.get('selected_cache', {})
    #     
    #     if not selected_cache:
    #         st.error("❌ 缓存数据丢失")
    #         session_data['processing_stage'] = 'initial'
    #         return session_data
    #     
    #     # 显示恢复进度
    #     st.header("🔄 正在恢复缓存数据...")
    #     progress_bar = st.progress(0)
    #     status_text = st.empty()
    #     
    #     try:
    #         # 恢复数据并转换为SegmentDTO格式
    #         restored_data = self._restore_cache_data(selected_cache, progress_bar, status_text)
    #         session_data.update(restored_data)
    #             
    #         # 决定下一个阶段
    #         next_stage = self._determine_next_stage_from_cache(restored_data)
    #         session_data['processing_stage'] = 'next_stage'
    #             
    #         # 清理临时状态
    #         session_data.pop('selected_cache', None)
    #             
    #         st.success("🎉 缓存数据恢复完成！")
    #         st.rerun()
    #             
    #     except Exception as e:
    #         st.error(f"❌ 缓存数据恢复失败: {str(e)}")
    #         logger.error(f"缓存数据恢复失败: {e}")
    #         session_data['processing_stage'] = 'initial'
    #     
    #     return session_data
    
    def _render_segmentation_analysis(self, session_data: Dict[str, Any]) -> Dict[str, Any]:
        """渲染分段分析界面"""
        logger.debug("🧠 进入分段分析渲染方法")
        
        input_file_path = session_data.get('input_file_path')
        logger.debug(f"📁 输入文件路径: {input_file_path}")
        
        if not input_file_path:
            logger.error("❌ 未找到文件路径")
            st.error("❌ 未找到文件路径")
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
            st.error("❌ 分段数据丢失，请重新分析")
            session_data['processing_stage'] = 'initial'
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
            
            # 保存分段缓存
            # self._save_segmentation_cache(session_data, confirmed_segments)  # 注释掉cache相关
            
            # 进入下一阶段
            session_data['processing_stage'] = 'language_selection'
            
        elif result['action'] == 'restart':
            # 重置状态
            keys_to_reset = ['processing_stage', 'segments', 'segmented_segments']
            for key in keys_to_reset:
                session_data.pop(key, None)
        
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
        with st.spinner("🌐 正在翻译文本..."):
            try:
                confirmed_segments = session_data.get('confirmed_segments', [])
                target_lang = session_data.get('target_lang')
                
                if not confirmed_segments:
                    st.error("❌ 未找到确认的分段数据")
                    session_data['processing_stage'] = 'language_selection'
                    return session_data
                
                from translation.translator import Translator
                translator = Translator(self.config)
                
                # 转换为legacy格式进行翻译
                legacy_segments = [seg.to_legacy_dict() for seg in confirmed_segments]
                # translated_segments = translator.translate_segments_with_cache(  # 注释掉cache相关
                #     legacy_segments, target_lang, progress_callback=None
                # )
                
                # 提取文本进行翻译
                texts_to_translate = [seg.get('confirmed_text', seg.get('text', '')) for seg in legacy_segments]
                translated_texts = translator.translate_segments(  # 使用无缓存版本
                    texts_to_translate, target_lang or 'en', progress_callback=None
                )
                
                # 将翻译结果合并回片段
                translated_segments = []
                for i, (legacy_seg, translated_text) in enumerate(zip(legacy_segments, translated_texts)):
                    translated_seg = legacy_seg.copy()
                    translated_seg['translated_text'] = translated_text
                    translated_segments.append(translated_seg)
                
                # 转换回SegmentDTO格式并更新原对象
                for i, translated_seg in enumerate(translated_segments):
                    confirmed_segments[i].translated_text = translated_seg.get('translated_text', '')
                    confirmed_segments[i].processing_metadata.update(
                        translated_seg.get('processing_metadata', {})
                    )
                
                session_data['validated_segments'] = confirmed_segments
                session_data['processing_stage'] = 'optimizing'
                logger.info(f"✅ 翻译完成，直接进入优化阶段: {session_data['processing_stage']}")
                # 返回数据而不是立即rerun，让数据先被保存
                return session_data
                
            except Exception as e:
                st.error(f"💢 翻译失败: {str(e)}")
                st.info("请检查API设置和网络连接，然后重试")
                session_data['processing_stage'] = 'language_selection'
        
        return session_data
    

    
    def _render_optimization_progress(self, session_data: Dict[str, Any]) -> Dict[str, Any]:
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
                from tts.azure_tts import AzureTTS
                
                sync_manager = PreciseSyncManager(self.config, progress_callback=None)
                translator = Translator(self.config)
                tts = AzureTTS(self.config)
                
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
        optimized_segments = session_data.get('optimized_segments', [])
        confirmation_segments = session_data.get('confirmation_segments', [])
        translated_original_segments = session_data.get('translated_original_segments', [])
        target_lang = session_data.get('target_lang', 'en')
        
        if not all([optimized_segments, confirmation_segments, translated_original_segments]):
            st.error("❌ 优化数据丢失，请重新处理")
            session_data['processing_stage'] = 'language_selection'
            return session_data
        
        # 使用音频确认组件
        result = self.audio_confirmation_view.render(
            optimized_segments, confirmation_segments, 
            translated_original_segments, target_lang, self.config
        )
        
        if result['action'] == 'generate_final':
            # 生成最终音频
            self._generate_final_audio(result['confirmed_segments'], session_data)
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
        
        return session_data
    
    # def _restore_cache_data(self, selected_cache: Dict[str, Any], 
    #                        progress_bar, status_text) -> Dict[str, Any]:
    #     """恢复缓存数据并转换为SegmentDTO格式"""
    #     restored_data = {}
    #     
    #     # 恢复分段数据
    #     if "segmentation" in selected_cache and selected_cache.get("segmentation"):
    #         progress_bar.progress(25)
    #         status_text.text("正在恢复分段数据...")
    #             
    #         segmentation_data = selected_cache["segmentation"]
    #             
    #         if "original_segments" in segmentation_data:
    #             restored_data['segments'] = [
    #                 SegmentDTO.from_legacy_segment(seg) 
    #                 for seg in segmentation_data["original_segments"]
    #             ]
    #             
    #         if "confirmed_segments" in segmentation_data:
    #             restored_data['confirmed_segments'] = [
    #                 SegmentDTO.from_legacy_segment(seg) 
    #                 for seg in segmentation_data["confirmed_segments"]
    #             ]
    #     
    #     # 恢复翻译数据
    #     if "translation" in selected_cache and selected_cache.get("translation"):
    #         progress_bar.progress(50)
    #         status_text.text("正在恢复翻译数据...")
    #             
    #         translation_data = selected_cache["translation"]
    #             
    #         if "translated_segments" in translation_data:
    #             restored_data['translated_segments'] = [
    #                 SegmentDTO.from_legacy_segment(seg)
    #                 for seg in translation_data["translated_segments"]
    #             ]
    #             
    #         if "validated_segments" in translation_data:
    #             restored_data['validated_segments'] = [
    #                 SegmentDTO.from_legacy_segment(seg)
    #                 for seg in translation_data["validated_segments"]
    #             ]
    #     
    #     # 恢复确认数据
    #     if "confirmation" in selected_cache and selected_cache.get("confirmation"):
    #         progress_bar.progress(75)
    #         status_text.text("正在恢复确认数据...")
    #             
    #         confirmation_data = selected_cache["confirmation"]
    #             
    #         if "optimized_segments" in confirmation_data:
    #             restored_data['optimized_segments'] = [
    #                 SegmentDTO.from_legacy_segment(seg)
    #                 for seg in confirmation_data["optimized_segments"]
    #             ]
    #             
    #         if "confirmation_segments" in confirmation_data:
    #             restored_data['confirmation_segments'] = [
    #                 SegmentDTO.from_legacy_segment(seg)
    #                 for seg in confirmation_data["confirmation_segments"]
    #             ]
    #             
    #         if "translated_original_segments" in confirmation_data:
    #             restored_data['translated_original_segments'] = [
    #                 SegmentDTO.from_legacy_segment(seg)
    #                 for seg in confirmation_data["translated_original_segments"]
    #             ]
    #     
    #     # 恢复目标语言
    #     if "target_lang" in selected_cache:
    #         restored_data['target_lang'] = selected_cache["target_lang"]
    #     
    #     progress_bar.progress(100)
    #     status_text.text("缓存数据恢复完成！")
    #     
    #     return restored_data
    
    # def _determine_next_stage_from_cache(self, restored_data: Dict[str, Any]) -> str:
    #     """根据恢复的数据确定下一个阶段"""
    #     if restored_data.get('optimized_segments'):
    #         return 'user_confirmation'
    #     elif restored_data.get('validated_segments'):
    #         return 'translation_validation'
    #     elif restored_data.get('translated_segments'):
    #         return 'translation_validation'
    #     elif restored_data.get('confirmed_segments'):
    #         return 'language_selection'
    #     else:
    #         return 'initial'
    
    # def _save_segmentation_cache(self, session_data: Dict[str, Any], 
    #                             confirmed_segments: List[SegmentDTO]):
    #     """保存分段缓存"""
    #     try:
    #         input_file_path = session_data.get('input_file_path')
    #         if input_file_path:
    #             from utils.cache_integration import get_cache_integration
    #             cache_integration = get_cache_integration()
    #             
    #             original_segments = session_data.get('segments', [])
    #             cache_integration.save_confirmed_segmentation_cache(
    #                 input_file_path, 
    #                 [seg.to_legacy_dict() for seg in confirmed_segments],
    #                 [seg.to_legacy_dict() for seg in original_segments]
    #             )
    #             st.success("💾 分段结果已缓存")
    #     except Exception as e:
    #         logger.warning(f"保存分段缓存失败: {e}")
    
    # def _save_translation_cache(self, session_data: Dict[str, Any], 
    #                            validated_segments: List[SegmentDTO], target_lang: str):
    #     """保存翻译缓存"""
    #     try:
    #         input_file_path = session_data.get('input_file_path')
    #         if input_file_path:
    #             from utils.cache_integration import get_cache_integration
    #             cache_integration = get_cache_integration()
    #             
    #             translation_data = {
    #                 "translated_segments": [seg.to_legacy_dict() for seg in validated_segments],
    #                 "validated_segments": [seg.to_legacy_dict() for seg in validated_segments],
    #                 "translated_original_segments": [seg.to_legacy_dict() for seg in validated_segments],
    #                 "translation_timestamp": __import__('time').time(),
    #                 "is_user_confirmed": True
    #             }
    #             
    #             cache_integration.save_translation_cache(input_file_path, target_lang, translation_data)
    #             st.success("💾 翻译结果已缓存")
    #     except Exception as e:
    #         logger.warning(f"保存翻译缓存失败: {e}")
    
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
            from tts.azure_tts import AzureTTS
            
            audio_synthesizer = AudioSynthesizer(self.config)
            tts = AzureTTS(self.config)
            target_lang = session_data.get('target_lang', 'en')
            
            # 转换为legacy格式
            legacy_segments = [seg.to_legacy_dict() for seg in confirmed_segments]
            
            # 合并音频
            final_audio = audio_synthesizer.merge_confirmed_audio_segments(legacy_segments)
            
            # 保存文件
            audio_output = f"dubbed_audio_{target_lang}.wav"
            subtitle_output = f"translated_subtitle_{target_lang}.srt"
            
            final_audio.export(audio_output, format="wav")
            
            # 保存字幕
            from audio_processor.subtitle_processor import SubtitleProcessor
            subtitle_processor = SubtitleProcessor(self.config)
            translated_original = session_data.get('translated_original_segments', [])
            subtitle_processor.save_subtitle(
                [seg.to_legacy_dict() for seg in translated_original], 
                subtitle_output, 'srt'
            )
            
            # 保存结果到session
            with open(audio_output, 'rb') as f:
                audio_data = f.read()
            with open(subtitle_output, 'rb') as f:
                subtitle_data = f.read()
            
            # 计算统计信息
            optimized_segments = session_data.get('optimized_segments', [])
            cost_summary = tts.get_cost_summary()
            
            session_data['completion_results'] = {
                'audio_data': audio_data,
                'subtitle_data': subtitle_data,
                'target_lang': target_lang,
                'optimized_segments': [seg.to_legacy_dict() for seg in optimized_segments],
                'cost_summary': cost_summary,
                'stats': {
                    'total_segments': len(translated_original),
                    'total_duration': max(seg.end for seg in translated_original) if translated_original else 0,
                    'excellent_sync': sum(1 for seg in optimized_segments if seg.quality == 'excellent')
                }
            }
            
        except Exception as e:
            st.error(f"❌ 生成最终音频时发生错误: {str(e)}")
            logger.error(f"生成最终音频失败: {e}")
    
    def _reset_all_states(self, session_data: Dict[str, Any]):
        """重置所有状态"""
        # 清理临时文件
        input_file_path = session_data.get('input_file_path')
        if input_file_path and Path(input_file_path).exists():
            try:
                Path(input_file_path).unlink()
                logger.info(f"清理了临时文件: {input_file_path}")
            except Exception as e:
                logger.warning(f"清理临时文件失败: {e}")
        
        # 重置所有状态
        keys_to_reset = [
            'processing_stage', 'segments', 'segmented_segments', 
            'confirmed_segments', 'target_lang', 'config', 'input_file_path',
            'completion_results', 'optimized_segments', 'confirmation_segments',
            'translated_original_segments', 'translated_segments', 'validated_segments',
            'current_confirmation_index', 'confirmation_page', 'user_adjustment_choices'
        ]
        
        for key in keys_to_reset:
            session_data.pop(key, None)
        
        # 重置为初始状态
        session_data['processing_stage'] = 'file_upload' 