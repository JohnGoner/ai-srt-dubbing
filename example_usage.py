#!/usr/bin/env python3
"""
中文SRT翻译程序使用示例
展示各种翻译模式和配置选项
"""

import os
import sys
from pathlib import Path

def run_translation_examples():
    """运行各种翻译示例"""
    
    # 示例SRT文件路径
    input_file = "内稳态-中文字幕.srt"
    
    if not os.path.exists(input_file):
        print(f"错误：找不到输入文件 {input_file}")
        print("请确保当前目录下有中文SRT文件")
        return
    
    print("=== 中文SRT翻译程序使用示例 ===\n")
    
    # 示例1：标准模式（包含所有审核功能）
    print("1. 标准模式 - 完整翻译和审核")
    print("命令: python srt_translator.py 内稳态-中文字幕.srt -o standard_mode.srt")
    print("功能: 批次翻译 + 边界审核 + 全文优化 + 连贯性检查")
    print()
    
    # 示例2：快速模式（关闭所有审核）
    print("2. 快速模式 - 仅翻译，不审核")
    print("命令: python srt_translator.py 内稳态-中文字幕.srt -o quick_mode.srt --quick-mode")
    print("功能: 仅并发翻译，跳过所有审核步骤")
    print("适用: 快速预览、时间紧迫的情况")
    print()
    
    # 示例3：自定义并发数
    print("3. 高并发模式")
    print("命令: python srt_translator.py 内稳态-中文字幕.srt -o high_concurrent.srt --concurrent-batches 10")
    print("功能: 增加并发批次数，提高翻译速度")
    print("注意: 需要考虑API限制")
    print()
    
    # 示例4：部分审核模式
    print("4. 部分审核模式")
    print("命令: python srt_translator.py 内稳态-中文字幕.srt -o partial_review.srt --no-final-review")
    print("功能: 保留批次间审核，关闭全文审核")
    print("适用: 平衡质量和速度")
    print()
    
    # 示例5：翻译成其他语言
    print("5. 多语言翻译")
    print("命令: python srt_translator.py 内稳态-中文字幕.srt -o spanish.srt -l es")
    print("命令: python srt_translator.py 内稳态-中文字幕.srt -o french.srt -l fr")
    print("功能: 翻译成西班牙语、法语等")
    print()
    
    # 配置文件示例
    print("6. 配置文件要求")
    print("确保 config.yaml 文件包含:")
    print("""
api_keys:
  kimi_api_key: "你的Kimi API密钥"  # 推荐
  openai_api_key: "你的OpenAI API密钥"  # 备用

translation:
  use_kimi: true  # 使用Kimi API
  model: "kimi-k2-0711-preview"
  max_concurrent_batches: 5
  enable_batch_review: true
  enable_final_review: true
""")
    print()
    
    # 性能建议
    print("7. 性能优化建议")
    print("- 使用Kimi API比OpenAI更快更便宜")
    print("- 大文件建议使用标准模式确保质量")
    print("- 小文件可以使用快速模式节省时间")
    print("- 根据API限制调整并发数")
    print("- 网络不稳定时降低并发数")
    print()
    
    # 质量检查建议
    print("8. 翻译质量保证")
    print("程序包含以下质量检查机制:")
    print("✓ 重复内容检测和移除")
    print("✓ 时间码一致性验证")
    print("✓ 术语翻译统一性检查")
    print("✓ 批次间连贯性审核")
    print("✓ 全文流畅性优化")
    print("✓ 缺失段落自动补全")
    print()

def show_translation_workflow():
    """展示翻译工作流程"""
    print("=== 翻译工作流程 ===\n")
    
    steps = [
        "1. 文件验证 - 检查输入SRT文件格式和完整性",
        "2. 智能分段 - 将长字幕分成适当大小的批次",
        "3. 并发翻译 - 使用线程池同时翻译多个批次",
        "4. 边界审核 - 检查批次间连接处的连贯性（可选）",
        "5. 去重处理 - 移除重复翻译内容",
        "6. 时间码修复 - 确保时间码与原文完全一致",
        "7. 术语统一 - 统一专业术语的翻译",
        "8. 连贯性优化 - 全文流畅性检查和改进（可选）",
        "9. 质量检查 - 最终的完整性验证",
        "10. 文件输出 - 生成标准SRT格式文件"
    ]
    
    for step in steps:
        print(step)
    
    print()
    print("每个步骤都有错误处理和降级方案，确保程序稳定运行")

def main():
    """主函数"""
    run_translation_examples()
    print("\n" + "="*50 + "\n")
    show_translation_workflow()
    
    print("\n开始翻译请运行:")
    print("python srt_translator.py your_chinese_file.srt")

if __name__ == "__main__":
    main() 