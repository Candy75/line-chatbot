# 1. 選一個輕量的 Python 基底映像
FROM python:3.10-slim

WORKDIR /app

# 2. 安裝編譯 aiohttp 需要的系統套件
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      build-essential \
      libssl-dev \
      libffi-dev && \
    rm -rf /var/lib/apt/lists/*

# 3. 安裝 Python 套件
COPY requirements.txt .
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# 4. 複製你的程式碼
COPY . .

# 5. 啟動指令 (Railway 用 $PORT)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]