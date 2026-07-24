#!/bin/bash
set -e

# Function to wait for database to be ready using Django management command
wait_for_db() {
    echo "Waiting for database to be ready..."
    "$PYTHON_BIN" manage.py wait_for_db --timeout=60 || {
        echo "Database connection failed, but attempting to continue..."
        return 1
    }
    return 0
}

echo "=== Railway Django Startup ==="
echo "DATABASE_URL exists: $([ -n "$DATABASE_URL" ] && echo "Yes" || echo "No")"
echo "RAILWAY_ENVIRONMENT: ${RAILWAY_ENVIRONMENT}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

# Set default PORT if not provided
if [ -z "$PORT" ]; then
    export PORT=8080
fi
echo "PORT: $PORT"

run_startup_tasks() {
    # Wait for database to be ready before migrations
    if ! wait_for_db; then
        echo "Database connection failed, but continuing with startup..."
    fi

    echo "Running database migrations..."
    "$PYTHON_BIN" manage.py migrate --noinput || {
        echo "Migration failed, but continuing..."
    }

    echo "Seeding subscription plans..."
    "$PYTHON_BIN" manage.py seed_plans || {
        echo "Plan seeding failed, but continuing..."
    }

    echo "Ensuring superuser exists..."
    "$PYTHON_BIN" manage.py ensure_superuser || {
        echo "Superuser creation failed, but continuing..."
    }
}

# Ensure the local media directory exists (used when USE_S3 is not set / Railway Volume)
mkdir -p "${MEDIA_ROOT:-media}/church_logos"

# Finish schema and account setup before accepting traffic. Running these jobs
# beside Gunicorn made fresh deployments compete with live requests for CPU and
# database connections.
run_startup_tasks

echo "=== Starting Gunicorn Server ==="
echo "Server will be available at http://0.0.0.0:$PORT"
echo "Health check endpoint: /healthz"

# Two workers with four threads each allow up to eight concurrent requests
# without the memory cost of eight separate Django/WeasyPrint processes.
WEB_CONCURRENCY="${WEB_CONCURRENCY:-2}"
GUNICORN_THREADS="${GUNICORN_THREADS:-4}"

exec "$PYTHON_BIN" -m gunicorn church_finance_project.wsgi:application \
    --bind 0.0.0.0:$PORT \
    --workers "$WEB_CONCURRENCY" \
    --worker-class gthread \
    --threads "$GUNICORN_THREADS" \
    --max-requests 1000 \
    --max-requests-jitter 100 \
    --timeout 45 \
    --graceful-timeout 30 \
    --keep-alive 5 \
    --worker-tmp-dir /dev/shm \
    --log-level info \
    --access-logfile - \
    --error-logfile -
