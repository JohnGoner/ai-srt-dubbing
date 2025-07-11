#!/usr/bin/env python3
"""
AI配音系统主程序 - 第一期版本
支持SRT字幕文件翻译和TTS合成，采用循环逼近算法实现精确时间同步
"""

import argparse
import sys
from pathlib import Path
from loguru import logger

from audio_processor.subtitle_processor import SubtitleProcessor
from audio_processor.subtitle_segmenter import SubtitleSegmenter
from translation.translator import Translator
from tts.azure_tts import AzureTTS
from timing.sync_manager import AdvancedSyncManager
from utils.config_manager import ConfigManager
from utils.file_utils import create_output_dir, select_file_interactive, validate_srt_file, select_file_enhanced, save_recent_file


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='AI配音系统 - SRT字幕配音版（循环逼近优化）')
    parser.add_argument('--subtitle', '-s', help='SRT字幕文件路径（可选，如果不提供会启动文件选择器）')
    parser.add_argument('--target-lang', '-t', default='en', help='目标语言代码')
    parser.add_argument('--output', '-o', help='输出目录路径')
    parser.add_argument('--config', '-c', default='config.yaml', help='配置文件路径')
    parser.add_argument('--gui', action='store_true', help='启动图形界面')
    parser.add_argument('--debug', action='store_true', help='开启调试模式')

    
    args = parser.parse_args()
    
    # 加载配置
    try:
        config_manager = ConfigManager()
        config = config_manager.load_config(args.config)
        if config is None:
            logger.error(f"配置文件 {args.config} 不存在，请参考 config.example.yaml 创建")
            sys.exit(1)
    except Exception as e:
        logger.error(f"配置文件加载失败: {str(e)}")
        sys.exit(1)
    
    # 设置日志级别
    if args.debug:
        logger.remove()
        logger.add(sys.stderr, level="DEBUG")
    
    # 启动图形界面
    if args.gui:
        from ui.streamlit_app import run_streamlit_app
        run_streamlit_app(config)
        return
    
    # 获取SRT文件路径
    subtitle_path = args.subtitle
    
    # 如果没有提供SRT文件路径，启动文件选择器
    if not subtitle_path:
        # 优先尝试使用增强版文件选择器
        try:
            subtitle_path = select_file_enhanced()
        except Exception as e:
            logger.warning(f"增强文件选择器失败，使用基础版本: {str(e)}")
            print("📁 请选择SRT字幕文件...")
            subtitle_path = select_file_interactive(
                file_types=[("SRT字幕文件", "*.srt"), ("所有文件", "*.*")],
                title="选择SRT字幕文件"
            )
        
        if not subtitle_path:
            logger.info("用户取消了文件选择，程序退出")
            sys.exit(0)
    
    # 验证SRT文件
    if not validate_srt_file(subtitle_path):
        logger.error(f"SRT文件 {subtitle_path} 不存在或格式不正确")
        # 如果文件验证失败，提供重新选择的机会
        if not args.subtitle:  # 只有当文件是通过选择器选择的时候才提供重新选择
            print("文件验证失败，是否重新选择？(y/n)")
            if input().lower() == 'y':
                return main()
        sys.exit(1)
    
    # 创建输出目录
    output_path = args.output or f"output/{Path(subtitle_path).stem}_{args.target_lang}"
    create_output_dir(output_path)
    
    logger.info(f"开始处理SRT文件: {subtitle_path}")
    logger.info(f"目标语言: {args.target_lang}")
    logger.info(f"输出路径: {output_path}")
    logger.info("处理模式: 循环逼近模式")
    
    try:
        # 步骤1: 加载SRT字幕
        logger.info("步骤1: 加载SRT字幕文件...")
        subtitle_processor = SubtitleProcessor(config)
        segments = subtitle_processor.load_subtitle(subtitle_path)
        logger.info(f"加载完成，共 {len(segments)} 个字幕片段")
        
        # 步骤1.5: 智能分段处理
        logger.info("步骤1.5: 智能分段处理...")
        segmenter = SubtitleSegmenter(config)
        segmented_segments = segmenter.segment_subtitles(segments)
        logger.info(f"智能分段完成，处理后共 {len(segmented_segments)} 个段落")
        
        # 生成分段报告
        segmentation_report = segmenter.create_segmentation_report(segments, segmented_segments)
        logger.info("智能分段报告:\n" + segmentation_report)
        
        # 步骤2: 翻译文本
        logger.info("步骤2: 翻译字幕文本...")
        translator = Translator(config)
        
        # 同时翻译智能分段（用于TTS）和原始片段（用于字幕文件）
        logger.info("翻译智能分段（用于配音）...")
        translated_segments = translator.translate_segments(segmented_segments, args.target_lang)
        
        logger.info("翻译原始片段（用于字幕文件）...")
        translated_original_segments = translator.translate_segments(segments, args.target_lang)
        
        logger.info("翻译完成")
        
        # 初始化TTS和时间同步管理器
        tts = AzureTTS(config)
        sync_manager = AdvancedSyncManager(config)
        
        # 循环逼近模式：高精度时间同步
        logger.info("步骤3: 循环逼近时间同步优化...")
        optimized_segments = sync_manager.optimize_timing_with_iteration(
            translated_segments, args.target_lang, translator, tts
        )
        
        # 音频已在优化过程中生成，直接使用
        audio_segments = optimized_segments
        
        # 步骤5: 合成最终音频
        logger.info("步骤5: 合成最终配音...")
        final_audio = sync_manager.merge_audio_segments(audio_segments)
        
        # 保存结果
        audio_output = f"{output_path}/dubbed_audio.wav"
        subtitle_output = f"{output_path}/translated_subtitle.srt"
        
        # 保存音频
        final_audio.export(audio_output, format="wav")
        logger.success(f"配音音频保存完成: {audio_output}")
        
        # 保存翻译后的字幕（使用原始片段的翻译）
        subtitle_processor.save_subtitle(translated_original_segments, subtitle_output, 'srt')
        logger.success(f"翻译字幕保存完成: {subtitle_output}")
        
        # 生成详细报告
        generate_comprehensive_report(
            optimized_segments, args.target_lang, sync_manager, tts, 
            f"{output_path}/report.txt", segmentation_report
        )
        
        # 输出处理摘要
        print_processing_summary(optimized_segments, args.target_lang, len(segments), len(segmented_segments))
        
        # 保存到最近文件列表
        save_recent_file(subtitle_path)
        
        logger.success("🎉 配音处理完成！")
        
    except Exception as e:
        logger.error(f"处理过程中发生错误: {str(e)}")
        if args.debug:
            import traceback
            traceback.print_exc()
        sys.exit(1)





def generate_comprehensive_report(segments, target_language: str, sync_manager, tts, 
                                report_path: str, segmentation_report: str = None):
    """生成综合处理报告"""
    try:
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write("AI配音系统综合处理报告\n")
            f.write("=" * 40 + "\n\n")
            
            # 基本信息
            f.write(f"处理时间: {Path().absolute()}\n")
            f.write(f"处理模式: 循环逼近模式 + 智能分段\n")
            f.write(f"目标语言: {target_language}\n")
            f.write(f"总片段数: {len(segments)}\n")
            f.write(f"总时长: {max(seg['end'] for seg in segments):.2f}秒\n\n")
            
            # 智能分段报告
            if segmentation_report:
                f.write("智能分段处理报告:\n")
                f.write("-" * 30 + "\n")
                f.write(segmentation_report)
                f.write("\n\n")
            
            # 时间同步报告
            # 详细的循环逼近报告
            timing_report = sync_manager.create_optimization_report(segments)
            f.write("时间同步详细报告:\n")
            f.write(timing_report)
            f.write("\n")
            
            # TTS合成报告
            if hasattr(tts, 'create_synthesis_report'):
                synthesis_report = tts.create_synthesis_report(segments)
                f.write(synthesis_report)
                f.write("\n")
            
            # 质量分析
            excellent_count = sum(1 for seg in segments if seg.get('sync_quality') == 'excellent')
            good_count = sum(1 for seg in segments if seg.get('sync_quality') == 'good')
            fallback_count = sum(1 for seg in segments if seg.get('sync_quality') == 'fallback')
            
            f.write("质量分析摘要:\n")
            f.write(f"  - 优秀同步 (<5%误差): {excellent_count} 片段 ({excellent_count/len(segments)*100:.1f}%)\n")
            f.write(f"  - 良好同步 (<15%误差): {good_count} 片段 ({good_count/len(segments)*100:.1f}%)\n")
            f.write(f"  - 兜底处理: {fallback_count} 片段 ({fallback_count/len(segments)*100:.1f}%)\n\n")
            
            # 详细片段信息（前10个）
            f.write("详细片段信息 (前10个):\n")
            f.write("-" * 50 + "\n")
            for i, seg in enumerate(segments[:10]):
                f.write(f"\n片段 {seg['id']}:\n")
                f.write(f"  时间: {seg['start']:.2f}s - {seg['end']:.2f}s\n")
                # 安全地获取原文文本
                original_text = (seg.get('original_text') or 
                               seg.get('text') or 
                               seg.get('translated_text', '未找到原文'))
                f.write(f"  原文: {original_text}\n")
                f.write(f"  译文: {seg.get('translated_text', seg.get('optimized_text', ''))}\n")
                
                f.write(f"  语速: {seg.get('final_speed', 1.0):.3f}\n")
                f.write(f"  同步比例: {seg.get('sync_ratio', 1.0):.3f}\n")
                f.write(f"  迭代次数: {seg.get('iterations', 0)}\n")
                f.write(f"  质量等级: {seg.get('sync_quality', 'unknown')}\n")
            
            if len(segments) > 10:
                f.write(f"\n... 还有 {len(segments) - 10} 个片段\n")
        
        logger.info(f"综合处理报告已保存: {report_path}")
        
    except Exception as e:
        logger.error(f"生成综合报告失败: {str(e)}")


def print_processing_summary(segments, target_language: str, original_count: int = None, segmented_count: int = None):
    """打印处理摘要到控制台"""
    print("\n" + "="*50)
    print("           处理完成摘要")
    print("="*50)
    print(f"目标语言: {target_language.upper()}")
    print(f"总片段数: {len(segments)}")
    print(f"总时长: {max(seg['end'] for seg in segments):.1f}秒")
    print("处理模式: 循环逼近模式 + 智能分段")
    
    # 显示智能分段统计
    if original_count and segmented_count:
        print(f"\n智能分段统计:")
        print(f"  原始片段数: {original_count}")
        print(f"  分段后片段数: {segmented_count}")
        print(f"  压缩比例: {segmented_count/original_count:.2f}")
    
    # 显示循环逼近统计
    excellent_count = sum(1 for seg in segments if seg.get('sync_quality') == 'excellent')
    good_count = sum(1 for seg in segments if seg.get('sync_quality') == 'good')
    avg_speed = sum(seg.get('final_speed', 1.0) for seg in segments) / len(segments)
    avg_iterations = sum(seg.get('iterations', 0) for seg in segments) / len(segments)
    
    print(f"\n时间同步质量:")
    print(f"  优秀 (<5%误差): {excellent_count} 片段")
    print(f"  良好 (<15%误差): {good_count} 片段")
    print(f"  平均语速: {avg_speed:.3f}")
    print(f"  平均迭代: {avg_iterations:.1f} 次")
    
    print("\n输出文件:")
    print("  📁 dubbed_audio.wav - 配音音频")
    print("  📝 translated_subtitle.srt - 翻译字幕")
    print("  📊 report.txt - 详细报告")
    print("="*50)


if __name__ == "__main__":
    main() 