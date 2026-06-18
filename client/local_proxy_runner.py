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
        import urllib.request
        import urllib.error
        
        # Wait up to 30 seconds for the proxy to initialize (Cloudflare bypass can be slow)
        start_time = time.time()
        ready = False
        while time.time() - start_time < 30:
            try:
                resp = urllib.request.urlopen("http://127.0.0.1:8001/health", timeout=1)
                if resp.getcode() == 200:
                    ready = True
                    break
            except Exception:
                time.sleep(1)
                
        if not ready:
            ui.show_error("Failed to start local proxy (timeout waiting for readiness).")
            # We don't yield so the player won't open.
        else:
            yield "http://127.0.0.1:8001"
    finally:
        ui.show_info("Shutting down temporary local proxy...")
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        local_proxy_running = False
