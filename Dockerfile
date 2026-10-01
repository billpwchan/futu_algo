# futu_algo in a container. OpenD runs elsewhere (host or another container); point
# futu.host at it. If OpenD is not on the same host, it requires an RSA key for trading.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install . && useradd --create-home --uid 1000 futu
USER futu
WORKDIR /work
EXPOSE 8765
# Mount a directory with config.yaml (+ .env) at /work. Set web.host: 0.0.0.0 and
# FUTU_ALGO_WEB_TOKEN when exposing the console outside the container.
ENTRYPOINT ["futu-algo"]
CMD ["web", "-c", "/work/config.yaml", "--engine"]
