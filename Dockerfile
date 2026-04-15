FROM python:3.11-slim

WORKDIR /app

# 시스템 의존성 (pymupdf, watchdog 등)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 의존성만 먼저 복사 (캐시 활용)
COPY pyproject.toml /app/
RUN pip install --no-cache-dir -e /app[*] || true

# 전체 코드
COPY . /app/
RUN pip install --no-cache-dir -e /app

# 데이터 디렉토리 (볼륨)
RUN mkdir -p /root/.raphael
VOLUME ["/root/.raphael"]

EXPOSE 7860 7861

ENV RAPHAEL_PROJECT_ROOT=/app
ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["raphael"]
CMD ["web"]
