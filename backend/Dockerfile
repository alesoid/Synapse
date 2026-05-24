FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_MODE=local-lite \
    LLM_BACKEND=mock \
    EMBEDDINGS_BACKEND=mock \
    STORAGE_BACKEND=mock

WORKDIR /app

COPY pyproject.toml ./
COPY backend ./backend
COPY docs/corpus ./docs/corpus
COPY frontend ./frontend
RUN pip install --no-cache-dir .

EXPOSE 8000

CMD ["uvicorn", "backend.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
