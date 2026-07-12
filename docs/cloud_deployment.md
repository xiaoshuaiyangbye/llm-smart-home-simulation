# Cloud Deployment Guide

This project can run locally with the existing PowerShell scripts and can also be deployed on a cloud server with Docker Compose.

## Directory Layout

```text
backend/Dockerfile          Backend API image
frontend/Dockerfile         Frontend build and Nginx image
deploy/docker-compose.yml   Cloud deployment composition
deploy/nginx/default.conf   Static frontend and API reverse proxy
deploy/backend.env.example  Backend runtime environment template
deploy/.env.example         Compose-level environment template
```

## First Deployment

Install Docker and Docker Compose on the server, then copy the example environment files:

```bash
cp deploy/backend.env.example deploy/backend.env
cp deploy/.env.example deploy/.env
```

Edit `deploy/backend.env` before enabling real LLM calls. Keep API keys only in this file on the server.

If Docker Hub image pulls fail with `failed to fetch oauth token` or a timeout,
edit `deploy/.env` and set a Docker Hub mirror prefix:

```env
DOCKER_HUB_PREFIX=m.daocloud.io/docker.io/library/
```

This rewrites the base images used by the Dockerfiles, for example
`python:3.11-slim` becomes `m.daocloud.io/docker.io/library/python:3.11-slim`.

Start the application:

```bash
cd deploy
docker compose up -d --build
```

Open:

```text
http://your-server-ip/
```

The frontend container serves the React build and proxies `/api/*` plus `/health` to the backend container. Only port `80` needs to be exposed by default.

## Updating

After pulling new code:

```bash
cd deploy
docker compose up -d --build
```

Generated logs and reports are mounted to:

```text
data/logs/
data/results/
```

## Production Notes

- Keep `LLM_MODE=mock` until the cloud LLM endpoint and key are configured.
- Put HTTPS, domain binding, and certificate renewal in front of this Compose stack when publishing publicly.
- If frontend and backend are served from the same domain through the included Nginx config, leave `VITE_API_BASE_URL` empty.
- If the browser calls a separate backend domain, set `VITE_API_BASE_URL` and `BACKEND_CORS_ORIGINS` explicitly.
