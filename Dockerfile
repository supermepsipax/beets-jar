FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1
RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends \
        ffmpeg              `# convert, replaygain, acousticbrainz` \
        libchromaprint-tools `# chroma` \
        imagemagick         `# fetchart, embedart` \
        mp3val              `# badfiles` \
        flac                `# badfiles` \
        libfftw3-dev        `# bpsync` \
        libopus-dev         `# opus codec support` \
    && rm -rf /var/lib/apt/lists/*

# Create app user with configurable UID/GID
ARG UID=1000
ARG GID=1000
RUN groupadd -g "${GID}" appuser \
    && useradd --create-home --no-log-init -u "${UID}" -g "${GID}" appuser

# Deps
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /bin/uv
WORKDIR /app
RUN chown appuser:appuser /app
COPY --chown=appuser:appuser pyproject.toml uv.lock ./

# Scripts (installed as root so they're on the system PATH)
COPY scripts/migrate-paths /usr/local/bin/migrate-paths
RUN chmod +x /usr/local/bin/migrate-paths
COPY --chown=appuser:appuser beetsplug/ ./beetsplug/

# Switch to app user — everything after this is owned by appuser
USER appuser
RUN uv sync --frozen --no-dev
ENV PATH="/app/.venv/bin:$PATH"

# App
COPY --chown=appuser:appuser app/ ./app/
RUN mkdir -p /app/data
EXPOSE 7734

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7734"]
