import httpx
import re
import json
import urllib.parse
import html as htmlmod
from typing import Any, Optional
import config

class SCScraper:
    def __init__(self) -> None:
        self.active_domain: str = "https://streamingcommunityz.us"
        self.client = httpx.Client(
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept-Language": "it-IT,it;q=0.9,en;q=0.8"
            },
            follow_redirects=True,
            timeout=15.0
        )
        self.inertia_version: Optional[str] = None
        self.xsrf_token: Optional[str] = None

    def resolve_domain(self) -> str:
        """Resolve the active StreamingCommunity domain."""
        try:
            resp = self.client.get(config.SC_ANCHOR_URL)
            html = resp.text
            # Look for the redirect link like "https://streamingcommunityz.us"
            urls = re.findall(r'https://streamingcommunity[a-zA-Z0-9-]+\.[a-z]{2,}', html)
            for url in set(urls):
                if 'school' in url:
                    continue # Skip the landing redirect if possible
                try:
                    test_resp = self.client.get(url, timeout=5)
                    if test_resp.status_code == 200:
                        self.active_domain = url
                        break
                except Exception:
                    continue
            
            if not self.active_domain and urls:
                self.active_domain = urls[0]
            
            return self.active_domain
        except Exception as e:
            if config.DEBUG: print(f"Domain resolve error: {e}")
            return self.active_domain

    def init_session(self) -> None:
        """Initialize session, get XSRF and Inertia version."""
        self.resolve_domain()
            
        try:
            resp = self.client.get(f"{self.active_domain}/")
            html = resp.text
            
            # Extract XSRF from cookies
            for cookie in self.client.cookies.jar:
                if cookie.name == 'XSRF-TOKEN':
                    self.xsrf_token = urllib.parse.unquote(cookie.value)
                    break
                
            # Extract Inertia Version
            match = re.search(r'data-page="([^"]+)"', html)
            if match:
                data_page_str = htmlmod.unescape(match.group(1))
                try:
                    data_page = json.loads(data_page_str)
                    self.inertia_version = data_page.get('version')
                except json.JSONDecodeError:
                    pass
                    
            if not self.inertia_version:
                v_match = re.search(r'"version":"([a-f0-9]{32})"', html)
                if v_match:
                    self.inertia_version = v_match.group(1)
        except Exception as e:
            if config.DEBUG: print(f"Session init error: {e}")

    def _get_inertia_headers(self, referer_path: str = "/it/") -> dict[str, str]:
        return {
            "X-Inertia": "true",
            "X-Inertia-Version": self.inertia_version or "",
            "X-XSRF-TOKEN": self.xsrf_token or "",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "text/html, application/xhtml+xml",
            "Referer": f"{self.active_domain}{referer_path}"
        }

    def search(self, query: str) -> list[dict[str, Any]]:
        if not self.inertia_version:
            self.init_session()
            
        q = urllib.parse.quote(query)
        url = f"{self.active_domain}/it/search?q={q}"
        try:
            resp = self.client.get(url, headers=self._get_inertia_headers())
            if resp.status_code == 200:
                data = resp.json()
                return data.get('props', {}).get('titles', [])
        except Exception as e:
            if config.DEBUG: print(f"Search error: {e}")
        return []

    def get_title_details(self, title_id: int, slug: str) -> dict[str, Any]:
        url = f"{self.active_domain}/it/titles/{title_id}-{slug}"
        try:
            resp = self.client.get(url, headers=self._get_inertia_headers())
            if resp.status_code == 200:
                return resp.json().get('props', {})
        except Exception as e:
            if config.DEBUG: print(f"Title details error: {e}")
        return {}

    def get_season_details(self, title_id: int, slug: str, season_num: int) -> dict[str, Any]:
        url = f"{self.active_domain}/it/titles/{title_id}-{slug}/season-{season_num}"
        try:
            resp = self.client.get(url, headers=self._get_inertia_headers(f"/it/titles/{title_id}-{slug}"))
            if resp.status_code == 200:
                return resp.json().get('props', {})
        except Exception as e:
            if config.DEBUG: print(f"Season details error: {e}")
        return {}

    def get_stream_url(self, title_id: int, episode_id: int) -> Optional[str]:
        """
        Execute the pipeline to extract the master M3U8 stream URL.
        """
        try:
            # Step 1: Iframe extraction
            iframe_url = f"{self.active_domain}/it/iframe/{title_id}?episode_id={episode_id}&next_episode=1"
            referer = f"{self.active_domain}/it/watch/{title_id}?e={episode_id}"
            
            iframe_resp = self.client.get(iframe_url, headers={"Referer": referer, "Accept": "text/html"})
            
            embed_raw = re.search(r'src=["\'](https://vixcloud\.co/embed/[^"\']+)["\']', iframe_resp.text)
            if embed_raw:
                embed_url = htmlmod.unescape(embed_raw.group(1).replace('&amp;', '&'))
            else:
                return None

            # Step 2: Load Vixcloud Embed
            vix_resp = self.client.get(embed_url, headers={"Referer": f"{self.active_domain}/", "Accept": "text/html"})
            
            token = re.search(r"'token'\s*:\s*'([^']+)'", vix_resp.text)
            expires = re.search(r"'expires'\s*:\s*'([^']+)'", vix_resp.text)
            pl_url = re.search(r"url:\s*'(https://vixcloud\.co/playlist/\d+)'", vix_resp.text)
            
            if not (token and expires and pl_url):
                return None
                
            master_m3u8 = f"{pl_url.group(1)}?ub=1&token={token.group(1)}&expires={expires.group(1)}&h=1"
            return master_m3u8
            
        except Exception as e:
            if config.DEBUG: print(f"Stream extraction error: {e}")
            return None
