FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    default-libmysqlclient-dev \
    pkg-config \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    DEBUG=False \
    ALLOWED_HOSTS=localhost,127.0.0.1,0.0.0.0,*.up.railway.app,churchbooksmanagement.com,www.churchbooksmanagement.com \
    CSRF_TRUSTED_ORIGINS=https://*.up.railway.app,https://churchbooksmanagement.com,https://www.churchbooksmanagement.com,http://localhost:8080,https://localhost:8080

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . .

# Make sure the staticfiles directory exists
RUN mkdir -p /app/staticfiles

# Collect static files
RUN python manage.py collectstatic --noinput

# Create startup script
RUN echo '#!/bin/bash\nset -e\necho "Running database migrations..."\npython manage.py migrate --noinput\necho "Starting server..."\nexec gunicorn church_finance_project.wsgi:application --bind 0.0.0.0:$PORT --log-level debug --timeout 300' > /app/start.sh
RUN chmod +x /app/start.sh

# Start the application
CMD ["/app/start.sh"]
