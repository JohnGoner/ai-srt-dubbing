# 更新日志

## [1.1.0] - 2024-12-19

### 🎉 主要功能
- **智能翻译优化**: 支持Kimi K2和OpenAI双API，实现多版本翻译策略
- **精确语速控制**: 基于循环逼近算法的Azure TTS语速优化
- **统一数据结构**: 引入SegmentDTO标准化所有处理阶段的数据
- **模块化架构**: 重构为translation、audio_processor、timing、tts、ui、utils六大模块

### 🔧 核心改进
- **翻译引擎**: 
  - 支持Kimi K2-0711-preview模型
  - 多版本翻译策略（minimal/compact/standard/detailed）
  - 智能长度控制和字符数精确匹配
  - 高性能并发翻译（支持50并发，200 RPM）

- **TTS优化**:
  - Azure TTS双密钥故障切换
  - 动态校准因子提升估算精度
  - 循环逼近算法实现精确语速控制
  - 48kHz高保真音频输出

- **UI重构**:
  - Streamlit组件化架构
  - 工作流管理器统一协调
  - 实时音频预览和确认
  - 智能质量评估和建议

### 📊 数据结构
- **SegmentDTO**: 统一字幕片段数据结构
  - 支持多阶段文本（original/translated/optimized/final）
  - 时间同步分析和质量评估
  - 音频数据和元数据管理

### ⚡ 性能优化
- 并发翻译提升处理速度
- 智能缓存减少重复计算
- Token使用统计和成本控制
- 错误恢复和降级机制

### 🛠️ 技术栈
- Python 3.8+
- Streamlit UI框架
- Azure Speech Services
- Kimi/OpenAI API
- Pydub音频处理

### 📝 配置管理
- YAML配置文件统一管理
- 支持多语言语音映射
- 可调节的并发和频率限制
- 详细的日志记录

---

## [1.0.0] - 初始版本
- 基础SRT字幕翻译功能
- 简单TTS语音合成
- 基础Web界面 