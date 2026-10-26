FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FASTEMBED_CACHE_PATH=/opt/models

RUN useradd --system --uid 10001 --create-home app \
    && mkdir -p /app/data /opt/models \
    && chown -R app /app /opt/models
WORKDIR /app

# libraries first: a change in our code does not redo this layer
COPY requirements-runtime.txt .
RUN pip install --no-cache-dir -r requirements-runtime.txt

USER app

# the embedding model is part of the image, so no start downloads it (keep the name in step with embedder.MODEL_NAME)
RUN python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='BAAI/bge-small-en-v1.5')"

COPY --chown=app *.py ./

EXPOSE 8000
# the chat service; the jobs run the same image with another command (python pipeline.py, policy_index.py, retention.py)
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
