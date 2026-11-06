# syntax=docker/dockerfile:1
# One image for the app, eval, test and demo services. Gold and corpus specs are excluded by
# .dockerignore; the eval service mounts them read-only at run time.
FROM ghcr.io/astral-sh/uv:0.5.21@sha256:87d729f94c87d0aade077260d07d899848f027b7ef37e734dca711c7ceffd3cf AS uv

# Node for the pinned sequential-thinking server behind the gated reflect tool (Iteration 3,
# ADR-047): npm ci installs package-lock.json's exact versions at build time, never at run time.
FROM node:22-slim@sha256:5ec23b7c622b00547753bc6ffd78085dd868a68aeb41c8e0a1418f033e13d96d AS node
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts --omit=dev

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
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /app/node_modules ./node_modules
COPY package.json package-lock.json ./
COPY config ./config
COPY prompts ./prompts
COPY knowledge_base ./knowledge_base
COPY research_packs ./research_packs
COPY inputs ./inputs
COPY app ./app
# The committed sample run: what the UI shows first, and what its tests read (WP-3.6).
COPY samples ./samples
COPY tests ./tests
# BIDWRIGHT_ENV names the environment a run records, so a run started here is resumed and
# purged here (ADR-031): a lock taken in a container is not seen on the host.
ENV PATH="/app/.venv/bin:$PATH" BIDWRIGHT_HOME=/app LANGGRAPH_STRICT_MSGPACK=true \
    BIDWRIGHT_ENV=container
RUN mkdir -p /app/outputs /app/evals/results && chown -R bidwright:bidwright /app/outputs /app/evals/results
USER bidwright
ENTRYPOINT ["bidwright"]
CMD ["--help"]
