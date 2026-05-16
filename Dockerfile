# Stage 1: build wheel (needs .git for hatch-vcs version derivation)
FROM ghcr.io/astral-sh/uv:0.6.6-python3.13-bookworm AS builder

WORKDIR /build
COPY . .
RUN uv build --wheel

# Stage 2: runtime
FROM ghcr.io/astral-sh/uv:0.6.6-python3.13-bookworm

WORKDIR /app

COPY --from=builder /build/dist/*.whl /tmp/
RUN uv pip install --system /tmp/*.whl && rm /tmp/*.whl

ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "-m", "app"]
