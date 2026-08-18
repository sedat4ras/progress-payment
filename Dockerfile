FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PP_DATABASE_URL=sqlite:////data/progress_payment.db \
    PP_MATCHER_BACKEND=rules

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app app
COPY data data
COPY scripts scripts

RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 8000

# The image ships without a model on purpose: with PP_MATCHER_BACKEND=rules the
# whole pipeline runs on exact/alias/fuzzy matching alone. Point
# PP_OLLAMA_HOST at a host running Ollama to add the semantic layer.
#
# Nothing is fetched at runtime: the interface is server-rendered Jinja with one
# stylesheet and one script served from the image, so the container works with
# no network at all.
CMD ["sh", "-c", "python -m scripts.bootstrap && exec uvicorn app.web.main:app --host 0.0.0.0 --port 8000"]
