FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    libpq-dev \
    pkg-config \
    gcc \
    g++ \
    make \
    libxml2-dev \
    libxslt1-dev \
    zlib1g-dev \
    libjpeg-dev \
    libpng-dev \
    libfreetype6-dev \
    liblcms2-dev \
    libwebp-dev \
    libharfbuzz-dev \
    libfribidi-dev \
    libxcb1-dev \
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

# Install dependencies in stages to identify issues
RUN pip install --no-cache-dir Django==4.2.24 asgiref==3.8.1 sqlparse==0.5.1
RUN pip install --no-cache-dir psycopg2-binary==2.9.9 dj-database-url==2.1.0
RUN pip install --no-cache-dir gunicorn==21.2.0 whitenoise==6.6.0
RUN pip install --no-cache-dir python-dotenv==1.0.1 cryptography==41.0.8
RUN pip install --no-cache-dir requests==2.31.0 urllib3==2.0.7
RUN pip install --no-cache-dir paypalrestsdk==1.13.3
RUN pip install --no-cache-dir beautifulsoup4==4.12.3 lxml==5.2.2
RUN pip install --no-cache-dir pillow==10.4.0 reportlab==4.2.2
RUN pip install --no-cache-dir xhtml2pdf==0.2.16

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
