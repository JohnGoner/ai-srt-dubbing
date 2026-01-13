# AI配音系统 - 新手安装指南 🎯

基于Kimi/GPT和MiniMax TTS的智能SRT字幕翻译与语音合成系统，实现高精度时间同步的多语言配音。

## 📋 系统要求

- **操作系统**: Windows 10+, macOS 10.14+, 或 Linux
- **Python版本**: 3.8 或更高版本
- **内存**: 至少 4GB RAM
- **硬盘空间**: 至少 2GB 可用空间

## 🚀 完整安装步骤

### 步骤 1: 安装 Miniconda

#### Windows 用户:
1. 访问 [Miniconda官网](https://docs.conda.io/en/latest/miniconda.html)
2. 下载 Windows 版本的 Miniconda 安装程序
3. 运行安装程序，按默认设置安装
4. 安装完成后，打开 "Anaconda Prompt (miniconda3)"

#### macOS 用户:
```bash
# 方法1: 使用Homebrew安装（推荐）
brew install miniconda

# 方法2: 手动下载安装
# 访问官网下载 .pkg 文件并双击安装
```

#### Linux 用户:
```bash
# 下载安装脚本
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh

# 运行安装脚本
bash Miniconda3-latest-Linux-x86_64.sh

# 重启终端或运行
source ~/.bashrc
```

### 步骤 2: 创建专用Python环境

打开终端（Windows用户使用Anaconda Prompt），执行以下命令：

```bash
# 创建名为 ai-dubbing 的Python 3.9环境
conda create -n ai-dubbing python=3.9 -y

# 激活环境
conda activate ai-dubbing
```

### 步骤 3: 下载项目代码

```bash
# 方法1: 使用Git克隆（推荐）
git clone https://github.com/your-repo/ai-srt-dubbing.git
cd ai-srt-dubbing

# 方法2: 如果没有Git，直接下载ZIP文件
# 从GitHub下载ZIP文件并解压到本地文件夹
```

### 步骤 4: 安装 FFmpeg（必需）

`pydub` 库需要 FFmpeg 来处理音频文件。请根据你的操作系统安装：

#### Windows 用户:
```bash
# 方法1: 使用 Chocolatey（如果已安装）
choco install ffmpeg

# 方法2: 使用 Scoop（如果已安装）
scoop install ffmpeg

# 方法3: 手动安装
# 1. 访问 https://ffmpeg.org/download.html
# 2. 下载 Windows 版本
# 3. 解压并添加到系统 PATH 环境变量
```

#### macOS 用户:
```bash
# 使用 Homebrew 安装（推荐）
brew install ffmpeg

# 如果没有 Homebrew，先安装 Homebrew:
# /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

#### Linux 用户:
```bash
# Ubuntu/Debian
sudo apt update && sudo apt install -y ffmpeg

# CentOS/RHEL
sudo yum install -y ffmpeg

# Fedora
sudo dnf install -y ffmpeg
```

**验证安装**:
```bash
# 检查 ffmpeg 是否安装成功
ffmpeg -version
```

### 步骤 5: 安装项目依赖

确保你在项目根目录下，然后运行：

```bash
# 确认当前环境
conda info --envs

# 安装所有依赖包（这可能需要几分钟）
pip install -r requirements.txt
```

### 步骤 6: 配置API密钥

1. **复制配置文件**:
```bash
# 在项目根目录下，复制配置模板
cp config.yaml.template config.yaml
```

2. **获取API密钥**:
   - **Kimi API**: 访问 [Moonshot AI](https://platform.moonshot.cn/) 注册获取
   - **MiniMax TTS**: 访问 [MiniMax](https://www.minimaxi.com/) 创建TTS服务并获取API密钥

3. **编辑配置文件**:
```bash
# 使用文本编辑器打开config.yaml
# Windows: notepad config.yaml
# macOS: open -e config.yaml  
# Linux: nano config.yaml
```

在 `config.yaml` 文件中填入你的API密钥：
```yaml
api_keys:
  kimi_api_key: "sk-your-kimi-api-key-here"
  minimax_api_key: "your-minimax-api-key-here"
  minimax_group_id: "your-group-id-here"
```

### 步骤 7: 启动应用

```bash
# 确保在ai-dubbing环境中
conda activate ai-dubbing

# 启动Streamlit应用
streamlit run ui/streamlit_app_refactored.py
```

如果一切正常，你将看到类似输出：
```
You can now view your Streamlit app in your browser.

Local URL: http://localhost:8501
Network URL: http://192.168.1.100:8501
```

### 步骤 8: 打开浏览器使用

1. 打开浏览器
2. 访问 `http://localhost:8501`
3. 开始使用AI配音系统！

## 🎯 快速使用指南

### 第一次使用:
1. **上传SRT文件**: 点击"选择文件"上传你的字幕文件
2. **选择目标语言**: 从下拉菜单选择要翻译的目标语言
3. **开始处理**: 点击"开始翻译和配音"
4. **等待完成**: 系统会自动完成翻译、语音合成和时间同步
5. **下载结果**: 完成后下载生成的音频文件

### 支持的文件格式:
- **输入**: `.srt` 字幕文件
- **输出**: `.wav` 音频文件

## 🔧 常见问题解决

### 问题1: 环境激活失败
```bash
# 如果conda activate不工作，尝试:
source activate ai-dubbing

# 或者重新初始化conda:
conda init
# 然后重启终端
```

### 问题2: 依赖安装失败
```bash
# 更新pip到最新版本
pip install --upgrade pip

# 如果某个包安装失败，尝试单独安装
pip install package-name --no-cache-dir
```

### 问题3: FFmpeg 未找到警告
```bash
# macOS 用户：使用 Homebrew 安装
brew install ffmpeg

# 验证安装
ffmpeg -version

# 如果仍然出现警告，检查 PATH 环境变量
echo $PATH
```

### 问题4: Streamlit启动失败
```bash
# 检查端口是否被占用
netstat -an | grep 8501

# 使用不同端口启动
streamlit run ui/streamlit_app_refactored.py --server.port 8502
```

### 问题5: API密钥错误
- 确保API密钥格式正确
- 检查API密钥是否有足够的配额
- 确认MiniMax Group ID设置正确

## 📞 获取帮助

如果遇到问题：

1. **检查日志**: 查看 `logs/dubbing.log` 文件中的错误信息
2. **环境诊断**: 运行 `conda list` 检查安装的包版本
3. **重新安装**: 如果问题严重，可以删除环境重新创建：
   ```bash
   conda deactivate
   conda remove -n ai-dubbing --all
   # 然后从步骤2重新开始
   ```

## 🎉 恭喜！

如果你成功完成了所有步骤，现在你已经可以使用AI配音系统了！

享受高质量的AI配音体验吧！ 🎊

---

**版本**: 1.1.0  
**更新日期**: 2024-12-27  
**维护者**: AI配音系统团队