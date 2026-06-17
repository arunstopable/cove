import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response
import httpx
import urllib.parse

from sc_scraper import SCScraper

app = FastAPI(title="Cove Proxy for Jellyfin")

# Initialize a global scraper instance
scraper = SCScraper()

@app.on_event("startup")
def startup_event():
    print("Initializing SCScraper session...")
    scraper.init_session()
    print(f"Active domain: {scraper.active_domain}")

@app.get("/play")
def play_stream(request: Request, title_id: int, episode_id: int):
    """
    Fetches the master M3U8 URL and returns the modified M3U8 text.
    """
    try:
        m3u8_url, _ = scraper.get_stream_url(title_id, episode_id)
        if not m3u8_url:
            print("Failed to get stream, re-initializing session and retrying...")
            scraper.init_session()
            m3u8_url, _ = scraper.get_stream_url(title_id, episode_id)
            
        if not m3u8_url:
            raise HTTPException(status_code=404, detail="Stream not found or extraction failed")
            
        # Fetch the master M3U8
        with httpx.Client() as client:
            resp = client.get(m3u8_url, headers={"Referer": "https://vixcloud.co/"})
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail="Failed to fetch master M3U8 from upstream")
                
            m3u8_text = resp.text
            
            # Rewrite child M3U8 URLs
            lines = m3u8_text.splitlines()
            modified_lines = []
            for line in lines:
                if line.startswith("http"):
                    encoded_url = urllib.parse.quote(line)
                    modified_lines.append(f"/proxy_child?url={encoded_url}")
                else:
                    modified_lines.append(line)
                    
            return Response(content="\n".join(modified_lines), media_type="application/vnd.apple.mpegurl")

    except Exception as e:
        print(f"Error extracting stream: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/proxy_child")
def proxy_child(request: Request, url: str):
    """
    Proxies a child M3U8 file and modifies the enc.key URI if present.
    """
    try:
        with httpx.Client() as client:
            resp = client.get(url, headers={"Referer": "https://vixcloud.co/"})
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail="Failed to fetch child M3U8")
                
            m3u8_text = resp.text
            
            # Rewrite enc.key URI if it exists
            m3u8_text = m3u8_text.replace('URI="/storage/enc.key"', 'URI="https://vixcloud.co/storage/enc.key"')
            
            return Response(content=m3u8_text, media_type="application/vnd.apple.mpegurl")
    except Exception as e:
        print(f"Error proxying child m3u8: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run("proxy:app", host="0.0.0.0", port=8000, reload=True)
