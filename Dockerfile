# Two stages: build the frontend, then a slim Python image that serves API + UI.
FROM node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    BRANDGUARD_DATA_DIR=/app/data BRANDGUARD_WEB_DIST=/app/web/dist
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir -e ".[api,llm,icons,live,serper,whois]"
COPY data/ ./data/
COPY --from=web /web/dist ./web/dist
VOLUME ["/app/data"]
EXPOSE 8000
CMD ["python", "-m", "brandguard.api", "--host", "0.0.0.0", "--port", "8000"]
