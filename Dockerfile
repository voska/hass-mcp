# MCP server Dockerfile for Claude Desktop integration
FROM ghcr.io/astral-sh/uv:0.6.6-python3.13-bookworm

# Set working directory
WORKDIR /app

# Copy project files
COPY . .

# Set environment for MCP communication
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Install package with UV (using --system flag)
RUN uv pip install --system -e .

# Run the MCP server with stdio communication using the module directly
ENTRYPOINT ["python", "-m", "app"]