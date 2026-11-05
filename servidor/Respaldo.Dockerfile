FROM postgres:17-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends \
    restic python3 python3-psycopg ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN mkdir -m 700 /trabajo
