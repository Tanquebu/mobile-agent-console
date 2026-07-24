FROM python:3.14-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends tmux \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --create-home --shell /bin/bash mac
USER mac
WORKDIR /workspace
CMD ["sh", "-lc", "tmux -S /tmux/mobile-agent-console.sock new-session -d -s __runtime__ sleep infinity 2>/dev/null || true; exec sleep infinity"]
