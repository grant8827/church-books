FROM python:3.11-slim

WORKDIR /app

# Install essential system dependencies
RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    g++ \
    make \
    pkg-config \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    DEBUG=False \
    ALLOWED_HOSTS=localhost,127.0.0.1,0.0.0.0,*.up.railway.app,churchbooksmanagement.com,www.churchbooksmanagement.com \
    CSRF_TRUSTED_ORIGINS=https://*.up.railway.app,https://churchbooksmanagement.com,https://www.churchbooksmanagement.com,http://localhost:8080,https://localhost:8080

# Upgrade pip and install Python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip setuptools wheel

# Install core dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . .

# Make sure required directories exist
RUN mkdir -p /app/staticfiles /app/media/church_logos

# Collect static files - set environment to force SQLite usage during build
ENV DJANGO_COLLECTSTATIC_BUILD=1
RUN python manage.py collectstatic --noinput

# Make startup script executable
RUN chmod +x /app/start_server.sh

# Create a simple health check script for container startup
RUN echo '#!/bin/bash\ncurl -f http://localhost:$PORT/startup/ || exit 1' > /app/health_check.sh && \
    chmod +x /app/health_check.sh

# Add health check to the container itself
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD /app/health_check.sh

# Expose the port
EXPOSE $PORT

# Start the application
CMD ["/app/start_server.sh"]
