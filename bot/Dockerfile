FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Persistent volume will be mounted at /data
RUN mkdir -p /data
ENV DB_PATH=/data/bot.db

CMD ["python", "main.py"]
