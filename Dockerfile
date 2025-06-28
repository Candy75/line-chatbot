# 1. 選一個含 Debian slim 的官方 Python 映像
FROM python:3.12-slim

# 2. 安裝編譯 aiohttp 等套件可能需要的系統函式庫
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      build-essential \
      python3-dev \
      libssl-dev \
      libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# 3. 建立工作目錄，先複製 requirements 只安裝依賴
WORKDIR /app
COPY requirements.txt .

# 4. 升級 pip、setuptools、wheel，並安裝所有 Python 套件
RUN pip install --upgrade pip setuptools wheel \
 && pip install -r requirements.txt

# 5. 複製剩餘程式碼
COPY . .

# 6. 暴露埠號（LINE webhook + FastAPI 預設 uvicorn 在 8000）
EXPOSE 8000

# 7. 啟動指令：uvicorn 啟動 main.py 裡的 FastAPI app
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]