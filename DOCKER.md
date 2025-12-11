# Docker Deployment Guide

## Prerequisites

- Docker Engine 20.10+
- Docker Compose 2.0+
- At least 2GB RAM available
- API keys for: OpenAI, Google Custom Search, Finnhub, Financial Modeling Prep

## Quick Start

### 1. Configure Environment Variables

Copy the example environment file and fill in your API keys:

```bash
cp .env.example .env
```

Edit `.env` and add your API keys:
```env
OPENAI_API_KEY=sk-...
GOOGLE_API_KEY=AIza...
GOOGLE_CSE_ID=...
FINNHUB_API_KEY=...
FMP_API_KEY=...
```

### 2. Build and Run with Docker Compose

```bash
# Build and start the container
docker-compose up -d

# View logs
docker-compose logs -f

# Stop the container
docker-compose down
```

The application will be available at: http://localhost:8080

### 3. Build and Run with Docker Only

```bash
# Build the image
docker build -t stock-analysis-app .

# Run the container
docker run -d \
  --name stock-analysis \
  -p 8080:8080 \
  -v $(pwd)/data/db:/app/data/db \
  -v $(pwd)/logs:/app/logs \
  --env-file .env \
  stock-analysis-app

# View logs
docker logs -f stock-analysis

# Stop the container
docker stop stock-analysis
docker rm stock-analysis
```

Alternatively to bind mounts you can use docker named volumes. This is better for production, but less convinient for development and debugging:
```bash
# Create named volumes (optional - Docker will create them automatically if they don't exist)
docker volume create stock-db
docker volume create stock-logs
docker volume create stock-temp

# Run the container with named volumes
docker run -d \
  --name stock-analysis \
  -p 8080:8080 \
  -v stock-db:/app/data/db \
  -v stock-logs:/app/logs \
  -v stock-temp:/app/temp \
  --env-file .env \
  stock-analysis-app
```

### 4. Starting the container without the sources

The `docker-compose-deploy.yml` file is designed for deployment scenarios where you don't need the source code. It uses a pre-built Docker image instead of building from source.

#### Minimum Required Files

To start the container using `docker-compose-deploy.yml`, you only need:

1. **docker-compose-deploy.yml** - The deployment compose file
2. **.env** - Environment file with your API keys

The Docker image (`stock-analysis-app:latest`) must be available either:
- Built locally and tagged as `stock-analysis-app:latest`
- Pulled from a Docker registry where it's been published (e.g. mirceapaciu/stock-analysis-app:latest)

#### Starting the Deployment

```bash
# Start using the deploy compose file
docker-compose -f docker-compose-deploy.yml up -d

# View logs
docker-compose -f docker-compose-deploy.yml logs -f

# Stop the container
docker-compose -f docker-compose-deploy.yml down
```

## Volume Mounts

The container uses the following volumes for persistence:

- `./data/db` - SQLite and DuckDB databases
- `./logs` - Application logs
- `./temp` - Temporary workflow files

## Environment Variables

Required:
- `OPENAI_API_KEY` - OpenAI API key for LLM extraction
- `GOOGLE_API_KEY` - Google API key for Custom Search
- `GOOGLE_CSE_ID` - Google Custom Search Engine ID
- `FINNHUB_API_KEY` - Finnhub API key for market data
- `FMP_API_KEY` - Financial Modeling Prep API key

Optional:
- `OPENAI_MODEL` - OpenAI model to use (default: gpt-4o-mini)
- `MAX_PE_RATIO` - Maximum P/E ratio filter (default: 15.0)
- `MIN_MARKET_CAP` - Minimum market cap filter (default: 1000000000)
- `APP_PASSWORD` - Application password (default: "")

## Ports

- `8080` - Streamlit web interface

## Health Check

The container includes a health check endpoint:
```bash
curl http://localhost:8080/_stcore/health
```

## Troubleshooting

### Container fails to start

Check logs:
```bash
docker-compose logs
```

### Database errors

Ensure the `data/db` directory exists and has write permissions:
```bash
mkdir -p data/db
chmod 755 data/db
```

### API rate limits

The application may hit API rate limits on free tiers:
- Google Custom Search: 100 queries/day
- OpenAI: Monitor usage dashboard
- Finnhub: 60 calls/minute

### Playwright browser issues

If web scraping fails, rebuild with Playwright dependencies:
```bash
docker-compose build --no-cache
```

## Production Deployment

### Security Recommendations

1. **Use Docker Secrets** instead of environment variables:
```yaml
secrets:
  openai_key:
    file: ./secrets/openai_key.txt
services:
  stock-analysis:
    secrets:
      - openai_key
```

2. **Add reverse proxy** (nginx/Traefik) for HTTPS:
```yaml
services:
  nginx:
    image: nginx:alpine
    ports:
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
      - ./ssl:/etc/nginx/ssl
```

3. **Set resource limits**:
```yaml
services:
  stock-analysis:
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 4G
        reservations:
          cpus: '1'
          memory: 2G
```
