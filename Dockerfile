FROM ghcr.io/astral-sh/uv:0.8.15 AS uv

FROM python:3.12-slim AS builder

COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/

COPY pyproject.toml ./
RUN uv sync --no-dev --no-install-project

FROM python:3.12-slim AS runtime

RUN groupadd --system app && useradd --system --gid app --home-dir /app app
WORKDIR /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY --from=builder /app/.venv /app/.venv
COPY --chown=app:app . .

USER app

CMD ["python", "-m", "worker.main", "start"]
