FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for building python packages
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
# Install dependencies directly from pyproject.toml
RUN pip install --no-cache-dir .

COPY . .