import json
import os
import httpx
from supabase import create_client, Client
import config

SESSION_FILE = os.path.join(os.path.dirname(__file__), "session.json")

# Initialize Supabase Client
supabase: Client = create_client(config.SUPABASE_URL, config.SUPABASE_ANON_KEY)

def load_session():
    if os.path.exists(SESSION_FILE):
        try:
            with open(SESSION_FILE, 'r') as f:
                session_data = json.load(f)
            supabase.auth.set_session(
                session_data.get('access_token'),
                session_data.get('refresh_token')
            )
            return True
        except:
            return False
    return False

def save_session(session):
    if session:
        with open(SESSION_FILE, 'w') as f:
            json.dump({
                'access_token': session.access_token,
                'refresh_token': session.refresh_token
            }, f)

def clear_session():
    if os.path.exists(SESSION_FILE):
        os.remove(SESSION_FILE)
    supabase.auth.sign_out()

def login(email, password):
    try:
        res = supabase.auth.sign_in_with_password({"email": email, "password": password})
        if res.session:
            save_session(res.session)
            return True, "Login successful"
        return False, "Login failed"
    except Exception as e:
        return False, str(e)

def is_logged_in():
    try:
        user = supabase.auth.get_user()
        return user is not None and user.user is not None
    except:
        return False

def get_watching_list():
    """
    Fetch the list of movies and tv shows currently being watched by the user.
    """
    try:
        user = supabase.auth.get_user()
        if not user or not user.user:
            return []
        uid = user.user.id
        response = supabase.table("user_media").select("*").eq("user_id", uid).eq("status", "watching").execute()
        return response.data
    except Exception as e:
        print(f"Error fetching from Supabase: {e}")
        return []

def get_watched_episodes(tmdb_show_id: int):
    """
    Fetch the watched episodes for a specific TV show.
    Returns a set of tuples: (season_number, episode_number)
    """
    try:
        user = supabase.auth.get_user()
        if not user or not user.user:
            return set()
        uid = user.user.id
        response = supabase.table("episode_progress").select("season_number, episode_number").eq("user_id", uid).eq("tmdb_show_id", tmdb_show_id).execute()
        watched_set = set()
        for item in response.data:
            watched_set.add((item['season_number'], item['episode_number']))
        return watched_set
    except Exception as e:
        print(f"Error fetching progress from Supabase: {e}")
        return set()

def fetch_tmdb_details(tmdb_id: int, media_type: str):
    """
    Fetch title and overview from TMDB API.
    """
    url = f"{config.TMDB_BASE_URL}/{media_type}/{tmdb_id}?api_key={config.TMDB_API_KEY}&language=en-US"
    try:
        with httpx.Client() as client:
            resp = client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                title = data.get('title') if media_type == 'movie' else data.get('name')
                return {
                    "title": title,
                    "overview": data.get("overview", ""),
                    "release_date": data.get("release_date") if media_type == "movie" else data.get("first_air_date")
                }
            return None
    except Exception as e:
        if config.DEBUG:
            print(f"TMDB Error: {e}")
        return None

def fetch_tmdb_search(query: str):
    """
    Search TMDB for movies and tv shows.
    """
    url = f"{config.TMDB_BASE_URL}/search/multi?api_key={config.TMDB_API_KEY}&query={query}&language=en-US&page=1"
    try:
        with httpx.Client() as client:
            resp = client.get(url)
            if resp.status_code == 200:
                results = resp.json().get('results', [])
                # filter only movies and tv shows
                return [r for r in results if r.get('media_type') in ['movie', 'tv']]
            return []
    except Exception as e:
        if config.DEBUG:
            print(f"TMDB Search Error: {e}")
        return []

# Attempt to load session at module import
load_session()
