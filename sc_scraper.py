import httpx
import re
import json
import urllib.parse
import config

class SCScraper:
    def __init__(self):
        self.active_domain = None
        self.client = httpx.Client(
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept-Language": "it-IT,it;q=0.9,en;q=0.8"
            },
            follow_redirects=True,
            timeout=15.0
        )
        self.inertia_version = None
        self.xsrf_token = None

    def resolve_domain(self):
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
                except:
                    continue
            
            if not self.active_domain and urls:
                self.active_domain = urls[0]
            
            # If all fails, fallback
            if not self.active_domain:
                self.active_domain = "https://streamingcommunityz.us"
            
            return self.active_domain
        except Exception as e:
            if config.DEBUG: print(f"Domain resolve error: {e}")
            self.active_domain = "https://streamingcommunityz.us"
            return self.active_domain

    def init_session(self):
        """Initialize session, get XSRF and Inertia version."""
        if not self.active_domain:
            self.resolve_domain()
            
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
            import html as htmlmod
            data_page_str = htmlmod.unescape(match.group(1))
            try:
                data_page = json.loads(data_page_str)
                self.inertia_version = data_page.get('version')
            except:
                pass
                
        if not self.inertia_version:
            v_match = re.search(r'"version":"([a-f0-9]{32})"', html)
            if v_match:
                self.inertia_version = v_match.group(1)

    def _get_inertia_headers(self, referer_path="/it/"):
        return {
            "X-Inertia": "true",
            "X-Inertia-Version": self.inertia_version or "",
            "X-XSRF-TOKEN": self.xsrf_token or "",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "text/html, application/xhtml+xml",
            "Referer": f"{self.active_domain}{referer_path}"
        }

    def search(self, query: str):
        if not self.inertia_version:
            self.init_session()
            
        q = urllib.parse.quote(query)
        url = f"{self.active_domain}/it/search?q={q}"
        resp = self.client.get(url, headers=self._get_inertia_headers())
        
        if resp.status_code == 200:
            try:
                data = resp.json()
                return data.get('props', {}).get('titles', [])
            except:
                pass
        return []

    def get_title_details(self, title_id: int, slug: str):
        url = f"{self.active_domain}/it/titles/{title_id}-{slug}"
        resp = self.client.get(url, headers=self._get_inertia_headers())
        if resp.status_code == 200:
            try:
                return resp.json().get('props', {})
            except:
                pass
        return {}

    def get_season_details(self, title_id: int, slug: str, season_num: int):
        url = f"{self.active_domain}/it/titles/{title_id}-{slug}/season-{season_num}"
        resp = self.client.get(url, headers=self._get_inertia_headers(f"/it/titles/{title_id}-{slug}"))
        if resp.status_code == 200:
            try:
                return resp.json().get('props', {})
            except:
                pass
        return {}

    def get_stream_url(self, title_id: int, episode_id: int):
        """
        Execute the 6-step pipeline to extract the 1080p M3U8 stream URL.
        """
        # Step 4: Iframe extraction
        iframe_url = f"{self.active_domain}/it/iframe/{title_id}?episode_id={episode_id}&next_episode=1"
        referer = f"{self.active_domain}/it/watch/{title_id}?e={episode_id}"
        
        iframe_resp = self.client.get(iframe_url, headers={"Referer": referer, "Accept": "text/html"})
        
        embed_raw = re.search(r'src=["\'](https://vixcloud\.co/embed/[^"\']+)["\']', iframe_resp.text)
        if embed_raw:
            import html as htmlmod
            embed_url = htmlmod.unescape(embed_raw.group(1).replace('&amp;', '&'))
        else:
            return None

        # Step 5: Load Vixcloud Embed
        vix_resp = self.client.get(embed_url, headers={"Referer": f"{self.active_domain}/", "Accept": "text/html"})
        
        token = re.search(r"'token'\s*:\s*'([^']+)'", vix_resp.text)
        expires = re.search(r"'expires'\s*:\s*'([^']+)'", vix_resp.text)
        pl_url = re.search(r"url:\s*'(https://vixcloud\.co/playlist/\d+)'", vix_resp.text)
        
        if not (token and expires and pl_url):
            return None
            
        master_m3u8 = f"{pl_url.group(1)}?ub=1&token={token.group(1)}&expires={expires.group(1)}&h=1"
        
        # We must return the master playlist, not the specific 1080p sub-playlist.
        # The master playlist contains the references to audio and subtitle tracks.
        # IINA and ffmpeg will automatically select the highest quality video (1080p).
        
        # Step 6: Fetch master playlist to extract all subtitle URLs
        m3u8_resp = self.client.get(master_m3u8, headers={"Referer": embed_url.split('?')[0], "Origin": "https://vixcloud.co"})
        
        subs = []
        if m3u8_resp.status_code == 200:
            sub_matches = re.finditer(r'TYPE=SUBTITLES.+?NAME="([^"]+)".+?URI="([^"]+)"', m3u8_resp.text)
            for match in sub_matches:
                name = match.group(1)
                sub_playlist_url = match.group(2)
                sub_resp = self.client.get(sub_playlist_url, headers={"Referer": embed_url.split('?')[0], "Origin": "https://vixcloud.co"})
                if sub_resp.status_code == 200:
                    vtt_match = re.search(r'(https?://[^\s]+\.vtt[^\s]*)', sub_resp.text)
                    if vtt_match:
                        subs.append({"name": name, "url": vtt_match.group(1)})
                
        return master_m3u8, subs
