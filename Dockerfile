# Stage 1: build the React frontend
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# Stage 2: Python API serving the built frontend
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8000
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY core/ core/
COPY api/ api/
COPY sample_data/ sample_data/
COPY --from=web /web/dist frontend/dist
EXPOSE 8000
# Render/Railway/Fly inject $PORT; Hugging Face Spaces expects 7860 (set PORT=7860 there).
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT}"]
