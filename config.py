import os
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# StreamingCommunity
# ---------------------------------------------------------------------------
# Anchor page used to discover the active domain
SC_ANCHOR_URL: str = os.environ.get("SC_ANCHOR_URL", "https://www.streaming-community.co/")

# ---------------------------------------------------------------------------
# Proxy server (used when generating .strm file URLs)
# ---------------------------------------------------------------------------
PROXY_SERVER_IP: str = os.environ.get("PROXY_SERVER_IP", "192.168.1.120")
PROXY_SERVER_PORT: int = int(os.environ.get("PROXY_SERVER_PORT", "8000"))

# ---------------------------------------------------------------------------
# NFS / Jellyfin library paths
# ---------------------------------------------------------------------------
NFS_SHOWS_PATH: str = os.environ.get("NFS_SHOWS_PATH", "/Volumes/Logan/shows")
NFS_MOVIES_PATH: str = os.environ.get("NFS_MOVIES_PATH", "/Volumes/Logan/movies")

# ---------------------------------------------------------------------------
# Local player (macOS app name or CLI binary)
# Supported values: IINA, VLC, mpv
# ---------------------------------------------------------------------------
PLAYER_APP: str = os.environ.get("PLAYER_APP", "IINA")

# ---------------------------------------------------------------------------
# Debug logging
# ---------------------------------------------------------------------------
DEBUG: bool = os.environ.get("COVE_DEBUG", "0") == "1"
