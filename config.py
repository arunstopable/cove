import os
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")
USER_ID = os.environ.get("USER_ID", "d0e7bdf2-a61b-4849-9d9b-3628d00fe321")

TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "")
TMDB_BASE_URL = "https://api.themoviedb.org/3"

SC_ANCHOR_URL = "https://www.streaming-community.co/"

# For testing / local config
DEBUG = os.environ.get("COVE_DEBUG", "0") == "1"
