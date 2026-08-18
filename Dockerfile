FROM python:3.12-slim

# Deps
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
ENV PATH="/app/.venv/bin:$PATH"

# Scripts
COPY scripts/migrate-paths /usr/local/bin/migrate-paths
RUN chmod +x /usr/local/bin/migrate-paths

# App
COPY app/ ./app/
RUN mkdir -p /app/data
EXPOSE 7734
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:7734/api/health')" || exit 1

# Run
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7734"]

