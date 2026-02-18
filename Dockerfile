FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    # For image processing (optional PIL dependency)
    libjpeg-dev libpng-dev libwebp-dev \
    # For file operations and downloads
    curl wget \
    # Build tools for some Python packages
    gcc g++ \
    # Clean up
    && rm -rf /var/lib/apt/lists/*

# Install external binaries needed by tools
RUN curl -L https://github.com/sharkdp/fd/releases/download/v10.1.0/fd-v10.1.0-x86_64-unknown-linux-musl.tar.gz | tar -xz -C /usr/local/bin --strip-components=1 fd-v10.1.0-x86_64-unknown-linux-musl/fd && \
    wget https://github.com/BurntSushi/ripgrep/releases/download/14.1.0/ripgrep_14.1.0-1_amd64.deb && \
    dpkg -i ripgrep_14.1.0-1_amd64.deb && \
    rm ripgrep_14.1.0-1_amd64.deb

# Copy project files first (for better layer caching)
COPY pyproject.toml setup.py* ./
COPY src ./src

# Install Python dependencies using pip (since project uses setuptools)
RUN pip install --no-cache-dir -e .

# Install playwright for crawl4ai web scraping
RUN crawl4ai-setup

# Copy configuration files
COPY config ./config

# Expose port
EXPOSE 8000

# Run the application
CMD ["uvicorn", "src.modules.api.main:app", "--host", "0.0.0.0", "--port", "8000"]