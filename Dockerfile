# Use Python 3.13 slim image
FROM python:3.13-slim

# Set working directory
WORKDIR /app

# Install uv for faster dependency management
RUN pip install --no-cache-dir uv

# Copy dependency files
COPY pyproject.toml uv.lock* ./

# Install Python dependencies using uv and clean cache in same layer
RUN uv pip install --system -r pyproject.toml && \
    rm -rf /root/.cache/uv /root/.cache/pip

# Install Playwright browsers for web scraping
RUN playwright install --with-deps chromium && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Copy application code
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY data/input/ ./data/input/
COPY .streamlit/ ./.streamlit/
COPY docs/USER_GUIDE.md ./docs/USER_GUIDE.md

# Create directories for databases and logs
RUN mkdir -p data/db logs temp

# Expose Streamlit port
EXPOSE 8080

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV STREAMLIT_SERVER_PORT=8080
ENV STREAMLIT_SERVER_ADDRESS=0.0.0.0
ENV PYTHONPATH=/app/src

# Health check (using Python instead of curl)
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/_stcore/health').read()" || exit 1

# Run Streamlit app
CMD ["streamlit", "run", "src/ui/main_app.py", \
    "--server.port=8080", \
    "--server.address=0.0.0.0", \
    "--server.headless=true", \
    "--server.enableCORS=false", \
    "--server.enableXsrfProtection=false", \
    "--server.enableWebsocketCompression=false"]
