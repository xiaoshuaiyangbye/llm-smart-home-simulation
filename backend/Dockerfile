ARG DOCKER_HUB_PREFIX=
FROM ${DOCKER_HUB_PREFIX}python:3.11-slim

ENV APP_ENV=production \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY backend /app/backend
COPY docs /app/docs
COPY data/tasks /app/data/tasks
COPY data/logs/.gitkeep /app/data/logs/.gitkeep
COPY data/results/.gitkeep /app/data/results/.gitkeep

WORKDIR /app/backend

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"]

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
