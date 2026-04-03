# Local Production Server Configuration

## Overview

This document describes the current local production server setup used for Docker-based deployment with a GitHub Actions self-hosted runner.

## Current Setup (Implemented)

- **Host OS**: Linux (in-prem server)
- **Container runtime**: Docker Engine + Docker Compose plugin (`docker compose` command)
- **GitHub runner**: self-hosted runner service on same server under the user gh-runner
- **Runner labels**: `self-hosted`, `linux`
- **Deploy trigger**: push to `main` (including PR merge into `main`) or manual `workflow_dispatch`
- **Compose file**: `docker-compose-deploy.yml`
- **App health endpoint**: `http://127.0.0.1:8080/_stcore/health`
- **Image strategy**: build image locally on the runner host (`stock-analysis-app:latest`), then deploy

## Docker Runtime Notes

- Deploy compose runs two services:
  - `stock-analysis` (UI/API, port `8080`)
  - `scheduler` (background jobs)
- Named volumes are used for persistence:
  - `stock-db` -> `/app/data/db`
  - `stock-logs` -> `/app/logs`
  - `stock-temp` -> `/app/temp`
- Data is preserved across normal deploys (`up -d --build --remove-orphans`).
- Data is removed only if volumes are explicitly deleted (for example, `docker compose down -v`).

## Runner Service Notes

- Runner should be installed as a system service and kept online.
- Runner user must have permission to run Docker commands.
- Keep runner version updated to support latest GitHub Actions runtimes (for example Node 24-based actions).

## Deployment Workflow Behavior (Current)

Current `.github/workflows/cd-main.yml` deploy flow:

1. Checkout repository on self-hosted runner.
2. Verify Docker/Compose availability.
3. Build local image: `docker build -t stock-analysis-app:latest .`.
4. Stop existing services gracefully: `docker compose -f docker-compose-deploy.yml stop -t 45`.
5. Start updated stack: `docker compose -f docker-compose-deploy.yml up -d --build --remove-orphans`.
6. Poll app health endpoint on `8080` until healthy or timeout.

## Required Runtime Configuration on Server

- Keep application env vars in server-local `.env` used by compose (including API keys).
- Keep file permissions restrictive (recommended `chmod 600` for `.env`).
- `APP_PASSWORD` is provided to deploy workflow via GitHub secret and consumed by compose environment.

## Inspecting the logs

Use two ways: container stdout logs and app log files.

1. Stream runtime logs immediately (best first check)

```bash
ssh mircea@haas
cd /path/to/your/repo
docker compose -f docker-compose-deploy.yml logs -f stock-analysis scheduler
```

Or by container name:

```bash
docker logs -f stock-analysis-app
docker logs -f stock-analysis-scheduler
```

2. Read the actual log files written by the app
The app writes files under /app/logs/app inside the container, and that path is persisted in a Docker volume.

```bash
ssh mircea@haas
docker exec -it stock-analysis-app sh -lc "ls -lah /app/logs/app; tail -n 200 /app/logs/app/app_$(date +%Y%m%d).log"
```

Scheduler logs often have prefixed files too:

```bash
docker exec -it stock-analysis-scheduler sh -lc "ls -lah /app/logs/app; tail -n 200 /app/logs/app/job_tracked_batch_$(date +%Y%m%d).log"
```

3. Access the volume directly on host (if needed)
Compose named volume may be prefixed, so discover it first:

```bash
docker volume ls | grep stock-logs
docker volume inspect <volume_name>
```

Then inspect the mountpoint path from inspect output:

```bash
sudo ls -lah <Mountpoint>/app
sudo tail -n 200 <Mountpoint>/app/app_YYYYMMDD.log
```


## Quick Verification Commands (Server)

- `docker --version`
- `docker compose version`
- `docker compose -f docker-compose-deploy.yml ps`
- `docker compose -f docker-compose-deploy.yml logs --tail 100`
- `curl -fsS http://127.0.0.1:8080/_stcore/health`
