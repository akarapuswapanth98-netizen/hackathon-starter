FROM mcr.microsoft.com/devcontainers/python:3.13

# Install Node.js 20 for frontend
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && apt-get update && apt-get install -y nodejs

# Install uv for faster pip (optional)
RUN pip install --no-cache-dir uv

WORKDIR /workspaces/hackathon-starter