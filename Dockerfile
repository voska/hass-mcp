# MCP server Dockerfile for Claude Desktop integration
FROM ghcr.io/astral-sh/uv:0.6.6-python3.13-bookworm

# Create non-root user for security
RUN groupadd -r mcp && useradd -r -g mcp mcp

# Set working directory
WORKDIR /app

# Copy only necessary files (see .dockerignore for exclusions)
COPY pyproject.toml README.md LICENSE ./
COPY app/ ./app/

# Set environment for MCP communication
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Install package with UV (regular install, not editable)
RUN uv pip install --system .

# Change ownership and switch to non-root user
RUN chown -R mcp:mcp /app
USER mcp

# Run the MCP server with stdio communication using the module directly
ENTRYPOINT ["python", "-m", "app"]