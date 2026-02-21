# AI SRT Dubbing 生产 Dockerfile
# Python 3.9 + FFmpeg + Streamlit

FROM python:3.9-slim

# 安装 FFmpeg 和系统依赖
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先复制依赖文件，利用 Docker 缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 创建日志目录
RUN mkdir -p logs

EXPOSE 8501

# Streamlit 配置: 禁用浏览器自动打开, 允许外部访问
CMD ["streamlit", "run", "ui/streamlit_app_refactored.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false"]
