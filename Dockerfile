FROM python:3.11-slim-bookworm

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV OPENEDU_MCP_HOST=0.0.0.0
ENV OPENEDU_MCP_PORT=8000
ENV OPENEDU_MCP_CACHE_PATH=/data/cache.db

EXPOSE 8000

CMD ["python", "src/http_entrypoint.py"]