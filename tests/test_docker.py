"""
Docker integration tests for hass-mcp.

Builds the Dockerfile, then drives the resulting image through both transports
end-to-end. Verifies the published image works the same way users will run it.

Skipped automatically if docker isn't on PATH (e.g., CI runners without docker
or local devs who don't have it installed).
"""

import asyncio
import os
import shutil
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

from tests.test_transports import EXPECTED_TOOLS


pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(shutil.which("docker") is None, reason="docker not installed"),
]


@pytest.fixture
def anyio_backend():
    return "asyncio"


# Override conftest's autouse httpx mock so the MCP HTTP client uses real httpx.
@pytest.fixture(autouse=True)
def mock_get_client():
    yield


PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def docker_image():
    """Build the Dockerfile once per test module; return the image tag."""
    tag = f"hass-mcp-test:{uuid.uuid4().hex[:8]}"
    result = subprocess.run(
        ["docker", "build", "-t", tag, "."],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.fail(f"docker build failed:\n{result.stdout}\n{result.stderr}")
    yield tag
    subprocess.run(["docker", "rmi", "-f", tag], capture_output=True)


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_http(url, timeout=20):
    """Poll until the HTTP server responds (not just TCP accepts). The HTTP
    handler may take longer to come up than the port — especially in Docker."""
    import urllib.request
    import urllib.error

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            # Any response from the MCP endpoint (even 4xx/405 for GET) means
            # the HTTP handler is live.
            urllib.request.urlopen(url, timeout=0.5)
            return True
        except urllib.error.HTTPError:
            return True
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(0.2)
    return False


async def test_docker_image_version_metadata(docker_image):
    """hatch-vcs produced a real version; the package installed cleanly."""
    result = subprocess.run(
        [
            "docker", "run", "--rm", "--entrypoint", "python", docker_image,
            "-c", "import importlib.metadata; print(importlib.metadata.version('hass-mcp'))",
        ],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
    version = result.stdout.strip()
    # Either a clean release tag (X.Y.Z) or a dev version (X.Y.Z.devN+...)
    assert version, "hass-mcp version is empty inside the image"
    assert "." in version


async def test_docker_image_excludes_git_directory(docker_image):
    """Multi-stage build keeps .git only in the builder; the runtime image is clean."""
    result = subprocess.run(
        ["docker", "run", "--rm", "--entrypoint", "/bin/sh", docker_image,
         "-c", "test ! -d /app/.git && echo OK"],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0 and result.stdout.strip() == "OK"


async def test_docker_stdio_transport(docker_image):
    """`docker run -i` with stdio is how Claude Desktop launches hass-mcp."""
    params = StdioServerParameters(
        command="docker",
        args=[
            "run", "-i", "--rm",
            "-e", "HA_URL=http://localhost:8123",
            "-e", "HA_TOKEN=docker-stdio-test",
            docker_image,
        ],
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            assert init.serverInfo.name == "Hass-MCP"
            tools = await session.list_tools()
            assert {t.name for t in tools.tools} == EXPECTED_TOOLS
            prompts = await session.list_prompts()
            assert len(prompts.prompts) == 7


async def test_docker_streamable_http_transport(docker_image):
    """`docker run --http` exposes streamable HTTP for standalone deployments."""
    port = _free_port()
    container = f"hass-mcp-http-{uuid.uuid4().hex[:8]}"
    proc = subprocess.Popen(
        [
            "docker", "run", "--rm", "--name", container,
            "-p", f"{port}:{port}",
            "-e", "HA_URL=http://localhost:8123",
            "-e", "HA_TOKEN=docker-http-test",
            docker_image,
            "--http", "--host", "0.0.0.0", "--port", str(port),
        ],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        assert _wait_for_http(f"http://127.0.0.1:{port}/mcp"), (
            "Docker HTTP server failed to come up. "
            f"docker logs: "
            f"{subprocess.run(['docker', 'logs', container], capture_output=True, text=True).stderr}"
        )

        async with streamable_http_client(f"http://127.0.0.1:{port}/mcp") as (
            read, write, _get_session_id,
        ):
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                assert init.serverInfo.name == "Hass-MCP"
                tools = await session.list_tools()
                assert {t.name for t in tools.tools} == EXPECTED_TOOLS

                result = await session.call_tool("get_version", {})
                assert not result.isError
    finally:
        subprocess.run(["docker", "stop", "--time", "2", container], capture_output=True)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
