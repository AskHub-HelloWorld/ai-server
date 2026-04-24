FROM python:3.12-alpine

WORKDIR /app

COPY index.html styles.css server.py proxy_rag_smoke.py github_rag_smoke.py ./
COPY js/ ./js/

ENV PORT=8080
ENV STATIC_ROOT=/app
ENV AI_SERVER_BASE_URL=http://host.docker.internal:8000

EXPOSE 8080

CMD ["python", "server.py"]
