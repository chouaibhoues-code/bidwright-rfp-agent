# syntax=docker/dockerfile:1
# One image for the app, eval, test and demo services. Gold and corpus specs are excluded by
# .dockerignore; the eval service mounts them read-only at run time.
FROM ghcr.io/astral-sh/uv:0.5.21@sha256:87d729f94c87d0aade077260d07d899848f027b7ef37e734dca711c7ceffd3cf AS uv

FROM python:3.12-slim@sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30 AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-install-project
COPY src ./src
COPY evals ./evals
RUN uv sync --locked

FROM python:3.12-slim@sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30
RUN useradd --create-home --uid 10001 bidwright
WORKDIR /app
COPY --from=build /app /app
COPY config ./config
COPY prompts ./prompts
COPY knowledge_base ./knowledge_base
COPY research_packs ./research_packs
COPY inputs ./inputs
COPY tests ./tests
# BIDWRIGHT_ENV names the environment a run records, so a run started here is resumed and
# purged here (ADR-031): a lock taken in a container is not seen on the host.
ENV PATH="/app/.venv/bin:$PATH" BIDWRIGHT_HOME=/app LANGGRAPH_STRICT_MSGPACK=true \
    BIDWRIGHT_ENV=container
RUN mkdir -p /app/outputs /app/evals/results && chown -R bidwright:bidwright /app/outputs /app/evals/results
USER bidwright
ENTRYPOINT ["bidwright"]
CMD ["--help"]
