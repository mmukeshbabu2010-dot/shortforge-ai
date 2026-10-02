FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY app/requirements.txt ./requirements.txt
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

COPY app ./app
COPY web ./web

RUN mkdir -p /app/data/uploads /app/data/outputs /app/data/previews

EXPOSE 10000

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port \${PORT:-10000}"]
