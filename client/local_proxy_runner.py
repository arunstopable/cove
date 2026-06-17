"""Local proxy runner for Mac client."""

import sys
import contextlib
import subprocess
import time
from typing import Generator

from client import ui

local_proxy_running = False


@contextlib.contextmanager
def local_proxy() -> Generator[str, None, None]:
    """Launch a temporary uvicorn proxy on localhost and yield its base URL."""
    global local_proxy_running

    ui.show_info("Starting temporary local proxy for Mac streaming...")
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "proxy.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8001",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    local_proxy_running = True
    try:
        # Give it a second to boot
        time.sleep(1)
        yield "http://127.0.0.1:8001"
    finally:
        ui.show_info("Shutting down temporary local proxy...")
        proc.terminate()
        proc.wait(timeout=3)
        local_proxy_running = False
