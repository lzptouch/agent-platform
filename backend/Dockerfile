FROM python:3.12-slim

WORKDIR /app

# Chromium 系统依赖（小红书 MCP Server）+ 编译依赖（chromadb C 扩展）
RUN apt-get update && apt-get install -y \
    wget gnupg ca-certificates cmake g++ \
    fonts-liberation libasound2 libatk-bridge2.0-0 libatk1.0-0 libatspi2.0-0 \
    libcups2 libdbus-1-3 libdrm2 libgbm1 libgtk-3-0 libnspr4 libnss3 \
    libwayland-client0 libxcomposite1 libxdamage1 libxfixes3 libxkbcommon0 \
    libxrandr2 xdg-utils \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Python 依赖（Embedding 走 API，无 torch，镜像轻量）
COPY pyproject.toml ./
RUN pip install --no-cache-dir \
    "fastapi>=0.115" "uvicorn[standard]>=0.30" python-multipart \
    "pydantic>=2.7,<2.12" "pydantic-settings>=2.3,<2.11" pyyaml python-dotenv \
    "anthropic>=0.52.0" "openai>=1.58" \
    "mcp[cli]>=1.6.0,<2.0.0" "fastmcp==2.5.2" "httpx>=0.28.0" "requests>=2.32" \
    "playwright>=1.40.0" pypdf pdfplumber pandas matplotlib \
    "pymilvus>=2.5,<2.6" "milvus-lite>=2.5,<2.6" \
    "chromadb>=0.5" "langchain-core>=0.3" "langchain-openai>=0.2" \
    "langchain-chroma>=0.1.2" "langchain-text-splitters>=0.3" \
    "pymupdf>=1.24" "pymupdf4llm>=0.0.17" beautifulsoup4 lxml "setuptools<81" \
    && playwright install chromium

COPY app/ ./app/
COPY skills/ ./skills/
COPY scripts/ ./scripts/
COPY conftest.py ./

RUN mkdir -p data/outputs data/uploads data/browser_data data/pdf data/logs

# 数据卷：Cookie / PDF / Milvus 向量库 / 产出文件运行时挂载，不打包进镜像
VOLUME ["/app/data"]

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
