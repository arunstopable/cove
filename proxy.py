import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from sc_scraper import SCScraper
from typing import Optional

app = FastAPI(title="Cove Proxy for Jellyfin")

# Initialize a global scraper instance
scraper = SCScraper()

@app.on_event("startup")
def startup_event():
    print("Initializing SCScraper session...")
    scraper.init_session()
    print(f"Active domain: {scraper.active_domain}")

@app.get("/play")
def play_stream(title_id: int, episode_id: int):
    """
    Given a title_id and episode_id, extracts a fresh m3u8 URL from StreamingCommunity
    and redirects the client to it.
    """
    try:
        m3u8_url, _ = scraper.get_stream_url(title_id, episode_id)
        if m3u8_url:
            return RedirectResponse(url=m3u8_url, status_code=302)
        else:
            # Maybe the inertia version changed, let's try to re-init
            print("Failed to get stream, re-initializing session and retrying...")
            scraper.init_session()
            m3u8_url, _ = scraper.get_stream_url(title_id, episode_id)
            if m3u8_url:
                return RedirectResponse(url=m3u8_url, status_code=302)
            else:
                raise HTTPException(status_code=404, detail="Stream not found or extraction failed")
    except Exception as e:
        print(f"Error extracting stream: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run("proxy:app", host="0.0.0.0", port=8000, reload=True)
