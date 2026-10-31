FROM python:3.10-slim

WORKDIR /app

# 不要なキャッシュを残さない
ENV PYTHONUNBUFFERED=1

# 音声処理に必要なシステムライブラリ（libsndfile）をインストール
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# RenderのWebサーバー用ポート
EXPOSE 8080

CMD ["python", "main.py"]
