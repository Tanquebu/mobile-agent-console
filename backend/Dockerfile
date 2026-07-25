# Il client tmux deve combaciare con la versione del server tmux host in
# modalità host (ADR 005): trixie fornisce 3.5a, quindi si compila la
# versione pinnata dal sorgente. Aggiornare TMUX_VERSION insieme all'host.
FROM python:3.14-slim AS tmux-build
ARG TMUX_VERSION=3.6a
RUN apt-get update \
    && apt-get install -y --no-install-recommends bison ca-certificates curl gcc make libevent-dev libncurses-dev \
    && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL "https://github.com/tmux/tmux/releases/download/${TMUX_VERSION}/tmux-${TMUX_VERSION}.tar.gz" | tar -xz -C /tmp \
    && cd "/tmp/tmux-${TMUX_VERSION}" \
    && ./configure \
    && make \
    && make install

FROM python:3.14-slim AS base
RUN apt-get update \
    && apt-get install -y --no-install-recommends libevent-core-2.1-7t64 libncurses6 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=tmux-build /usr/local/bin/tmux /usr/local/bin/tmux
RUN tmux -V
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin mac
WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir .
COPY app ./app
COPY alembic.ini .
COPY migrations ./migrations
USER mac
CMD ["python", "-m", "app.start"]

FROM base AS test
USER root
RUN pip install --no-cache-dir ".[dev]"
COPY tests ./tests
USER mac
CMD ["sh", "-c", "pytest -q tests && ruff check --no-cache ."]
