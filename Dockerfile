FROM python:3.11-slim

WORKDIR /app

# Install essential system dependencies
RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    g++ \
    make \
    pkg-config \
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

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . .

# Make sure the staticfiles directory exists
RUN mkdir -p /app/staticfiles

# Collect static files - set environment to force SQLite usage during build
ENV DJANGO_COLLECTSTATIC_BUILD=1
RUN python manage.py collectstatic --noinput

# Make startup script executable
RUN chmod +x /app/start_server.sh

# Start the application
CMD ["/app/start_server.sh"]
