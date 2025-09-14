#!/bin/bash
set -e

echo "=== Environment Variables Debug ==="
echo "DATABASE_URL: ${DATABASE_URL}"
echo "RAILWAY_ENVIRONMENT: ${RAILWAY_ENVIRONMENT}"
echo "DB_NAME: ${DB_NAME}"
echo "DB_HOST: ${DB_HOST}"

# Set default PORT if not provided
if [ -z "$PORT" ]; then
    export PORT=8080
fi

echo "PORT: $PORT"
echo "==============================="

echo "Running database migrations..."
python manage.py migrate --noinput

echo "Starting server..."
exec gunicorn church_finance_project.wsgi:application --bind 0.0.0.0:$PORT --log-level info --timeout 300