FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/code/.hf_cache

LABEL org.opencontainers.image.title="sentinel-memory API"
LABEL org.opencontainers.image.description="RAG + semantic-transactional join service on Postgres + pgvector"
LABEL org.opencontainers.image.source="https://github.com/CristianCaro-portfolio/sentinel-memory"

WORKDIR /code

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download the embedding model into the image so the container
# starts fast and needs no network access at runtime.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"

COPY ./app ./app
COPY ./scripts ./scripts
COPY ./workers ./workers
COPY ./web ./web

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
