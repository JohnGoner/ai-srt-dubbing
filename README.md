# AI配音系统 v1.1.0

基于Kimi/GPT和Azure TTS的智能SRT字幕翻译与语音合成系统，实现高精度时间同步的多语言配音。

## 🏗️ 系统架构

### 核心模块
```
ai-srt-dubbing-master/
├── translation/          # 智能翻译引擎
├── audio_processor/      # 音频处理与分段
├── timing/              # 时间同步管理
├── tts/                 # 语音合成引擎
├── ui/                  # Streamlit界面
├── models/              # 数据模型
└── utils/               # 工具函数
```

### 数据流架构
```
SRT字幕 → 智能分段 → 并发翻译 → 文本优化 → TTS合成 → 时间同步 → 音频确认 → 最终输出
```

## 📊 核心数据结构

### SegmentDTO - 统一片段模型
```python
@dataclass
class SegmentDTO:
    # 基础信息
    id: str                    # 片段唯一标识
    start: float              # 开始时间（秒）
    end: float                # 结束时间（秒）
    
    # 多阶段文本处理
    original_text: str        # 原始字幕文本
    translated_text: str      # 第一轮翻译结果
    optimized_text: str       # 算法优化后文本
    final_text: str          # 最终TTS使用文本
    
    # 时间与音频
    target_duration: float    # 目标时长
    actual_duration: float    # 实际音频时长
    speech_rate: float        # 语速倍率
    
    # 质量评估
    quality: str             # 质量评级
    timing_error_ms: float   # 时长误差
    sync_ratio: float        # 同步比例
```

## 🚀 核心功能

### 1. 智能翻译引擎
- **双API支持**: Kimi K2-0711-preview + OpenAI GPT-4
- **多版本策略**: minimal/compact/standard/detailed
- **精确长度控制**: 字符数精确匹配目标时长
- **并发优化**: 支持50并发，200 RPM限制

```python
# 翻译配置示例
translation:
  model: "kimi-k2-0711-preview"
  use_kimi: true
  max_concurrent_batches: 5
  multi_version_prompts:
    minimal: {length_factor: 0.60}
    compact: {length_factor: 0.75}
    standard: {length_factor: 1.0}
    detailed: {length_factor: 1.30}
```

### 2. 精确TTS控制
- **Azure TTS双密钥**: 故障切换机制
- **循环逼近算法**: 精确语速控制
- **动态校准**: 实时优化估算精度
- **高保真输出**: 48kHz音频质量

```python
# TTS优化流程
1. 估算目标语速 → 2. 生成音频 → 3. 计算误差 → 4. 调整语速 → 5. 重新生成
```

### 3. 时间同步算法
- **智能分段**: 保持句子完整性
- **重叠处理**: 自然语音过渡
- **误差容忍**: 20%同步容忍度
- **迭代优化**: 最大5轮优化

### 4. 模块化UI架构
- **工作流管理**: WorkflowManager统一协调
- **组件化设计**: 各阶段独立组件
- **实时预览**: 音频确认界面
- **质量评估**: 智能建议系统

## ⚙️ 配置管理

### 核心配置项
```yaml
# API配置
api_keys:
  kimi_api_key: "sk-..."
  azure_speech_key_1: "..."
  azure_speech_key_2: "..."

# 翻译配置
translation:
  use_kimi: true
  max_concurrent_batches: 5
  max_tokens: 8000

# TTS配置
tts:
  speech_rate: 1.0
  voices:
    en: "en-US-AndrewMultilingualNeural"
    es: "es-MX-JorgeNeural"

# 时间同步
timing:
  sync_tolerance: 0.20
  max_iterations: 5
  max_speed_ratio: 1.15
```

## 🛠️ 技术栈

- **后端**: Python 3.8+
- **UI框架**: Streamlit
- **AI服务**: Kimi K2, OpenAI GPT-4
- **TTS服务**: Azure Speech Services
- **音频处理**: Pydub
- **并发控制**: ThreadPoolExecutor
- **配置管理**: PyYAML

## 📈 性能特性

### 并发处理
- 翻译并发: 50请求/分钟
- TTS并发: 8请求/分钟
- 缓存命中: 智能重复检测

### 精度控制
- 时长误差: <100ms
- 字符匹配: ±8字符容差
- 同步比例: 0.95-1.15范围

### 成本优化
- Token统计: 实时使用量监控
- 缓存机制: 避免重复翻译
- 降级策略: API故障自动切换

## 🚀 快速开始

### 环境要求
```bash
Python 3.8+
pip install -r requirements.txt
```

### 配置设置
1. 复制`config.yaml`并填入API密钥
2. 配置目标语言和语音参数
3. 调整并发和频率限制

### 启动应用
```bash
streamlit run ui/streamlit_app_refactored.py
```

## 📝 开发规范

### 代码风格
- 中文注释，英文函数名
- 类型提示: `from typing import`
- 模块化设计，单一职责
- 异常处理和降级方案

### API优化原则
- 优先考虑token效率
- 支持双API切换
- 并发控制和延迟管理
- 缓存和统计监控

## 📄 许可证

MIT License - 详见 [LICENSE](LICENSE) 文件

## 🤝 贡献指南

1. Fork项目
2. 创建功能分支
3. 提交更改
4. 发起Pull Request

---

**版本**: 1.1.0  
**更新日期**: 2024-12-19  
**维护者**: AI配音系统团队 