#!/bin/bash
set -e

# Function to wait for database to be ready using Django management command
wait_for_db() {
    echo "Waiting for database to be ready..."
    python manage.py wait_for_db --timeout=60 || {
        echo "Database connection failed, but attempting to continue..."
        return 1
    }
    return 0
}

echo "=== Railway Django Startup ==="
echo "DATABASE_URL exists: $([ -n "$DATABASE_URL" ] && echo "Yes" || echo "No")"
echo "RAILWAY_ENVIRONMENT: ${RAILWAY_ENVIRONMENT}"

# Set default PORT if not provided
if [ -z "$PORT" ]; then
    export PORT=8080
fi
echo "PORT: $PORT"

# Wait for database to be ready before migrations
if ! wait_for_db; then
    echo "Database connection failed, but continuing with startup..."
fi

echo "Running database migrations..."
python manage.py migrate --noinput || {
    echo "Migration failed, but continuing..."
}

echo "Collecting static files..."
python manage.py collectstatic --noinput --clear || {
    echo "Static file collection failed, but continuing..."
}

echo "Ensuring superuser exists..."
python manage.py ensure_superuser || {
    echo "Superuser creation failed, but continuing..."
}

echo "=== Starting Gunicorn Server ==="
echo "Server will be available at http://0.0.0.0:$PORT"
echo "Health check endpoint: /healthz"

# Start Gunicorn with better configuration for Railway
exec gunicorn church_finance_project.wsgi:application \
    --bind 0.0.0.0:$PORT \
    --workers 2 \
    --worker-class sync \
    --worker-connections 1000 \
    --max-requests 1000 \
    --max-requests-jitter 100 \
    --timeout 30 \
    --keep-alive 2 \
    --log-level info \
    --access-logfile - \
    --error-logfile -