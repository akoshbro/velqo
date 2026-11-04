FROM python:3.12-slim
WORKDIR /srv
COPY backend/requirements.txt backend/requirements.txt
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-rus tesseract-ocr-eng && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend backend
COPY webapp webapp
ENV STATIC_DIR=/srv/webapp PYTHONUNBUFFERED=1
WORKDIR /srv/backend
CMD ["python", "-m", "app.main"]
