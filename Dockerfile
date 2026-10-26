FROM python:3.10-slim

WORKDIR /app

# 不要なキャッシュを残さない
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# RenderのWebサーバー用ポート
EXPOSE 8080

CMD ["python", "main.py"]
