# syntax=docker/dockerfile:1
# One image for the app, eval, test and demo services. Gold and corpus specs are excluded by
# .dockerignore; the eval service mounts them read-only at run time.
FROM ghcr.io/astral-sh/uv:0.5.21 AS uv

FROM python:3.12-slim AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-install-project
COPY src ./src
COPY evals ./evals
RUN uv sync --locked

FROM python:3.12-slim
RUN useradd --create-home --uid 10001 bidwright
WORKDIR /app
COPY --from=build /app /app
COPY config ./config
COPY prompts ./prompts
COPY inputs ./inputs
COPY tests ./tests
ENV PATH="/app/.venv/bin:$PATH" BIDWRIGHT_HOME=/app LANGGRAPH_STRICT_MSGPACK=true
RUN mkdir -p /app/outputs /app/evals/results && chown -R bidwright:bidwright /app/outputs /app/evals/results
USER bidwright
ENTRYPOINT ["bidwright"]
CMD ["--help"]
