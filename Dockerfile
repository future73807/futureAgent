FROM python:3.13-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .

# 安装 Python 依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目代码
COPY . .

# 管理端可编辑的 Skill 与 RBAC 策略使用独立运行目录。Docker 首次挂载
# 空命名卷时会复制这些默认文件；后续重建镜像则继续使用卷内配置。
RUN mkdir -p /app/runtime/config/skills /app/runtime/config/auth \
    && cp -a /app/skills/. /app/runtime/config/skills/ \
    && cp /app/auth/rbac_policy.csv /app/runtime/config/auth/rbac_policy.csv

# 暴露端口
EXPOSE 8000

# 启动命令
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
