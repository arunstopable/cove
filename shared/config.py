import os
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# StreamingCommunity
# ---------------------------------------------------------------------------
# Anchor page used to discover the active domain
SC_ANCHOR_URL: str = os.environ.get("SC_ANCHOR_URL", "https://streamingcommunity.buzz/")

# ──────────────────────────────────────────────────────────────────────────────
# Global Constants
# ──────────────────────────────────────────────────────────────────────────────
USER_AGENT: str = os.environ.get(
    "USER_AGENT",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
)

# ---------------------------------------------------------------------------
# Proxy server (used when generating .strm file URLs)
# ---------------------------------------------------------------------------
PROXY_SERVER_IP: str = os.environ.get("PROXY_SERVER_IP", "192.168.1.120")
PROXY_SERVER_PORT: int = int(os.environ.get("PROXY_SERVER_PORT", "8000"))

# ---------------------------------------------------------------------------
# NFS / Jellyfin library paths
# ── Local / NFS paths (used by CLI on Mac) ────────────────────────────────────
NFS_SHOWS_PATH: str = os.environ.get("NFS_SHOWS_PATH", "/Volumes/Logan/shows")
NFS_MOVIES_PATH: str = os.environ.get("NFS_MOVIES_PATH", "/Volumes/Logan/movies")

# ── Server container paths (used by Proxy to save downloads) ──────────────────
SERVER_SHOWS_PATH: str = os.environ.get("SERVER_SHOWS_PATH", "/shows")
SERVER_MOVIES_PATH: str = os.environ.get("SERVER_MOVIES_PATH", "/movies")
SERVER_WIP_PATH: str = os.environ.get("SERVER_WIP_PATH", "/wip")

MAX_CONCURRENT_DOWNLOADS: int = int(os.environ.get("MAX_CONCURRENT_DOWNLOADS", "3"))

# ---------------------------------------------------------------------------
# Local player (macOS app name or CLI binary)
# Supported values: IINA, VLC, mpv
# ---------------------------------------------------------------------------
PLAYER_APP: str = os.environ.get("PLAYER_APP", "IINA")

# ---------------------------------------------------------------------------
# Debug logging
# ---------------------------------------------------------------------------
DEBUG: bool = os.environ.get("COVE_DEBUG", "0") == "1"
