FROM python:3.10-slim

RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    build-essential \
    curl \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --default-timeout=1000 --no-cache-dir -r requirements.txt


RUN python3 -c "from ultralytics import YOLO; YOLO('yolov8n.pt')"

COPY app/       ./app/
COPY pipeline/  ./pipeline/
COPY tests/     ./tests/
COPY data/      ./data/

RUN chmod +x ./pipeline/run.sh

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
