# 選 3.11-slim（已有大部分 wheel），也可改成 3.12-slim
FROM python:3.11-slim

# 安裝 gcc、Python headers、SSL & FFI headers
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential \
      python3-dev \
      libssl-dev \
      libffi-dev \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先只複製 requirements 並安裝
COPY requirements.txt .
RUN pip install --upgrade pip setuptools wheel \
 && pip install -r requirements.txt

# 再複製所有程式碼
COPY . .

# 對外暴露 8000，啟動 uvicorn
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]