"""
SCScraper — StreamingCommunity scraper with robust session and stream extraction.

Features:
  - Automatic domain resolution from anchor page (multi-pattern)
  - Session TTL: auto-refresh after SESSION_TTL minutes
  - HTTP retry with exponential backoff (up to MAX_RETRIES attempts)
  - Inertia session refresh on 409 / 419 responses
  - Multi-pattern token/expires/playlist extraction for resilience
"""

import html as htmlmod
import json
import re
import time
import urllib.parse
from datetime import datetime, timedelta
from typing import Any, Optional

import httpx

from shared import config


class SCScraper:
    # ------------------------------------------------------------------
    # Class-level constants
    # ------------------------------------------------------------------

    # Patterns to find SC domain candidates in the anchor page HTML
    _DOMAIN_PATTERNS: list[str] = [
        r'https://streamingcommunity[a-zA-Z0-9.-]+\.[a-z]{2,}',
        r'href=["\']+(https://streamingcommunity[a-zA-Z0-9.-]+\.[a-z]{2,})["\']',
        r'action=["\']+(https://streamingcommunity[a-zA-Z0-9.-]+\.[a-z]{2,})["\']',
    ]

    # Ordered fallback patterns for Vixcloud embed token extraction
    _TOKEN_PATTERNS: list[str] = [
        r"'token'\s*:\s*'([^']+)'",
        r'"token"\s*:\s*"([^"]+)"',
        r'token:\s*["\']([^"\']+)["\']',
        r'data-token=["\']([^"\']+)["\']',
    ]

    _EXPIRES_PATTERNS: list[str] = [
        r"'expires'\s*:\s*'([^']+)'",
        r'"expires"\s*:\s*"([^"]+)"',
        r'expires:\s*["\']([^"\']+)["\']',
    ]

    _PLAYLIST_PATTERNS: list[str] = [
        r"url:\s*'(https://vixcloud\.co/playlist/\d+)'",
        r'url:\s*"(https://vixcloud\.co/playlist/\d+)"',
        r'"url"\s*:\s*"(https://vixcloud\.co/playlist/\d+)"',
    ]

    MAX_RETRIES: int = 3
    SESSION_TTL: timedelta = timedelta(minutes=25)

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def __init__(self) -> None:
        self.active_domain: str = "https://streamingcommunityz.us"
        self.client = httpx.Client(
            headers={
                "User-Agent": config.USER_AGENT,
                "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
            },
            follow_redirects=True,
            timeout=httpx.Timeout(connect=10.0, read=20.0, write=10.0, pool=5.0),
        )
        self.inertia_version: Optional[str] = None
        self.xsrf_token: Optional[str] = None
        self._last_init: Optional[datetime] = None
        self._session_valid: bool = False

    # ------------------------------------------------------------------
    # Internal: HTTP with retry
    # ------------------------------------------------------------------

    def _get(self, url: str, **kwargs: Any) -> httpx.Response:
        """GET with exponential-backoff retry on network/timeout errors."""
        last_exc: Optional[Exception] = None
        for attempt in range(self.MAX_RETRIES):
            try:
                return self.client.get(url, **kwargs)
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
                last_exc = exc
                if attempt < self.MAX_RETRIES - 1:
                    wait = 2 ** attempt  # 1 s, 2 s, 4 s
                    if config.DEBUG:
                        print(f"[retry] Attempt {attempt + 1} failed for {url!r}: {exc}. Waiting {wait}s…")
                    time.sleep(wait)
        raise last_exc  # type: ignore[misc]

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def _is_session_stale(self) -> bool:
        if not self._session_valid or self._last_init is None:
            return True
        return datetime.now() - self._last_init > self.SESSION_TTL

    def resolve_domain(self) -> str:
        """Discover the live StreamingCommunity domain from the anchor page."""
        try:
            resp = self._get(config.SC_ANCHOR_URL)
            html = resp.text
            candidates: set[str] = set()
            for pattern in self._DOMAIN_PATTERNS:
                for match in re.findall(pattern, html):
                    url = match.rstrip("/")
                    if "school" not in url:
                        candidates.add(url)

            for candidate in sorted(candidates):  # deterministic order
                try:
                    test = self.client.get(candidate, timeout=5.0)
                    if test.status_code in (200, 301, 302, 308):
                        self.active_domain = candidate
                        if config.DEBUG:
                            print(f"[domain] Resolved → {self.active_domain}")
                        return self.active_domain
                except Exception:
                    continue

            # If no candidate responded, use the first found as fallback
            if candidates:
                self.active_domain = next(iter(candidates))
                if config.DEBUG:
                    print(f"[domain] Fallback → {self.active_domain}")

        except Exception as exc:
            if config.DEBUG:
                print(f"[domain] Resolution error: {exc}. Keeping: {self.active_domain}")

        return self.active_domain

    def init_session(self) -> None:
        """Resolve domain and fetch XSRF token + Inertia version."""
        self.resolve_domain()

        try:
            resp = self._get(f"{self.active_domain}/")
            html = resp.text

            # --- XSRF token from cookies ---
            self.xsrf_token = None
            for cookie in self.client.cookies.jar:
                if cookie.name == "XSRF-TOKEN":
                    self.xsrf_token = urllib.parse.unquote(cookie.value)
                    break

            # --- Inertia version ---
            self.inertia_version = None

            # Primary: parse the data-page JSON attribute
            match = re.search(r'data-page="([^"]+)"', html)
            if match:
                try:
                    data_page = json.loads(htmlmod.unescape(match.group(1)))
                    self.inertia_version = data_page.get("version")
                except (json.JSONDecodeError, ValueError):
                    pass

            # Fallback: bare version hash in script
            if not self.inertia_version:
                v_match = re.search(r'"version"\s*:\s*"([a-f0-9]{32})"', html)
                if v_match:
                    self.inertia_version = v_match.group(1)

            self._session_valid = bool(self.xsrf_token and self.inertia_version)
            self._last_init = datetime.now()

            if config.DEBUG:
                print(
                    f"[session] XSRF: {'✓' if self.xsrf_token else '✗'}  "
                    f"Inertia: {self.inertia_version or '✗'}  "
                    f"Valid: {self._session_valid}"
                )

        except Exception as exc:
            self._session_valid = False
            if config.DEBUG:
                print(f"[session] Init error: {exc}")

    def _ensure_session(self) -> None:
        """Re-initialize session only if stale."""
        if self._is_session_stale():
            self.init_session()

    def check_global_quality(self) -> str:
        """
        Tests a known high-quality title (e.g. 'Fallout') to determine the maximum
        resolution currently granted by Vixcloud for this session.
        Returns '1080p', '720p', etc.
        """
        try:
            titles = self.search("Fallout")
            if not titles: return "Unknown"
            
            title_id = titles[0]['id']
            slug = titles[0]['slug']
            details = self.get_title_details(title_id, slug)
            
            ep_id = details.get("loadedSeason", {}).get("episodes", [{}])[0].get("id")
            if not ep_id:
                ep_id = details.get("title", {}).get("episodes", [{}])[0].get("id")
            if not ep_id: return "Unknown"
            
            iframe_url = f"{self.active_domain}/it/iframe/{title_id}?episode_id={ep_id}&next_episode=1"
            iframe_resp = self._get(iframe_url, headers={'Referer': f"{self.active_domain}/it/watch/{title_id}?e={ep_id}"})
            
            import re
            embed_match = re.search(r'src=[\"\']+(https://vixcloud\.co/embed/[^\"\']+)[\"\']', iframe_resp.text)
            if not embed_match: return "Unknown"
            
            embed_url = embed_match.group(1).replace('&amp;', '&')
            vix_resp = self._get(embed_url, headers={'Referer': f"{self.active_domain}/"})
            
            token_match = re.search(r'\'token\': \'([^\']+)\'', vix_resp.text)
            expires_match = re.search(r'\'expires\': \'([^\']+)\'', vix_resp.text)
            playlist_match = re.search(r'url:\s*\'(https://vixcloud\.co/playlist/\d+)\'', vix_resp.text)
            
            if not (token_match and expires_match and playlist_match): return "Unknown"
            
            master_url = f"{playlist_match.group(1)}?ub=1&token={token_match.group(1)}&expires={expires_match.group(1)}"
            resp = self._get(master_url, headers={'Referer': 'https://vixcloud.co/', 'User-Agent': self.client.headers.get("User-Agent")})
            
            max_h = 0
            for line in resp.text.splitlines():
                res = re.search(r'RESOLUTION=\d+x(\d+)', line)
                if res:
                    max_h = max(max_h, int(res.group(1)))
            return f"{max_h}p" if max_h else "Unknown"
        except Exception:
            return "Unknown"

    # ------------------------------------------------------------------
    # Internal: Inertia requests
    # ------------------------------------------------------------------

    def _inertia_headers(self, referer_path: str = "/it/") -> dict[str, str]:
        return {
            "X-Inertia": "true",
            "X-Inertia-Version": self.inertia_version or "",
            "X-XSRF-TOKEN": self.xsrf_token or "",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "text/html, application/xhtml+xml",
            "Referer": f"{self.active_domain}{referer_path}",
        }

    def _inertia_get(self, url: str, referer_path: str = "/it/") -> Optional[dict[str, Any]]:
        """
        Perform a GET with Inertia headers.
        Automatically re-initializes the session on 409 / 419 and retries once.
        """
        self._ensure_session()
        try:
            resp = self._get(url, headers=self._inertia_headers(referer_path))

            if resp.status_code in (409, 419):
                if config.DEBUG:
                    print(f"[inertia] {resp.status_code} conflict — refreshing session and retrying…")
                self.init_session()
                resp = self._get(url, headers=self._inertia_headers(referer_path))

            if resp.status_code == 200:
                return resp.json().get("props", {})

            if config.DEBUG:
                print(f"[inertia] Unexpected status {resp.status_code} for {url}")

        except Exception as exc:
            if config.DEBUG:
                print(f"[inertia] GET {url!r} failed: {exc}")

        return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def search(self, query: str) -> list[dict[str, Any]]:
        """Search for titles. Returns a list of title dicts."""
        q = urllib.parse.quote(query)
        url = f"{self.active_domain}/it/search?q={q}"
        result = self._inertia_get(url)
        if result is None:
            return []
        return result.get("titles", [])

    def get_title_details(self, title_id: int, slug: str) -> dict[str, Any]:
        """Return the props dict for a title page (seasons, episodes, etc.)."""
        url = f"{self.active_domain}/it/titles/{title_id}-{slug}"
        return self._inertia_get(url) or {}

    def get_season_details(self, title_id: int, slug: str, season_num: int) -> dict[str, Any]:
        """Return the props dict for a specific season (episode list)."""
        url = f"{self.active_domain}/it/titles/{title_id}-{slug}/season-{season_num}"
        referer = f"/it/titles/{title_id}-{slug}"
        return self._inertia_get(url, referer_path=referer) or {}

    def get_stream_url(self, title_id: int, episode_id: int) -> Optional[str]:
        """
        Full pipeline to extract the master HLS M3U8 URL from Vixcloud.

        Pipeline:
          1. GET /it/iframe/{title_id}?episode_id={episode_id}
             → find Vixcloud embed URL in response HTML
          2. GET {embed_url}
             → extract token, expires, playlist URL from page JS
          3. Build and return master M3U8 URL
        """
        try:
            # ── Step 1: iframe page → embed URL ─────────────────────────
            iframe_url = (
                f"{self.active_domain}/it/iframe/{title_id}"
                f"?episode_id={episode_id}&next_episode=1"
            )
            watch_referer = f"{self.active_domain}/it/watch/{title_id}?e={episode_id}"

            iframe_resp = self._get(
                iframe_url,
                headers={"Referer": watch_referer, "Accept": "text/html"},
            )

            embed_match = re.search(
                r'src=["\']+(https://vixcloud\.co/embed/[^"\']+)["\']',
                iframe_resp.text,
            )
            if not embed_match:
                if config.DEBUG:
                    print(f"[stream] Embed URL not found (title={title_id}, ep={episode_id})")
                return None

            embed_url = htmlmod.unescape(embed_match.group(1))

            # ── Step 2: embed page → token / expires / playlist ──────────
            vix_resp = self._get(
                embed_url,
                headers={
                    "Referer": f"{self.active_domain}/",
                    "Accept": "text/html",
                },
            )
            vix_text = vix_resp.text

            def _first_match(patterns: list[str], text: str) -> Optional[str]:
                for pat in patterns:
                    m = re.search(pat, text)
                    if m:
                        return m.group(1)
                return None

            token = _first_match(self._TOKEN_PATTERNS, vix_text)
            expires = _first_match(self._EXPIRES_PATTERNS, vix_text)
            playlist_url = _first_match(self._PLAYLIST_PATTERNS, vix_text)

            if not (token and expires and playlist_url):
                if config.DEBUG:
                    print(
                        f"[stream] Missing fields — "
                        f"token:{bool(token)} expires:{bool(expires)} playlist:{bool(playlist_url)}"
                    )
                return None

            # ── Step 3: assemble M3U8 URL ────────────────────────────────
            master_m3u8 = (
                f"{playlist_url}?ub=1&token={token}&expires={expires}"
            )

            if config.DEBUG:
                print(f"[stream] OK → {master_m3u8[:80]}…")

            return master_m3u8

        except Exception as exc:
            if config.DEBUG:
                print(f"[stream] Extraction error: {exc}")
            return None

    def close(self) -> None:
        """Release the underlying HTTP client."""
        try:
            self.client.close()
        except Exception:
            pass
