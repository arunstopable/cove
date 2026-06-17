import os

SUPABASE_URL = "https://nicfrsbfyltzjszptfzq.supabase.co"
SUPABASE_ANON_KEY = "sb_publishable_WLWJFE5huK1Kx53rkDphiQ_8j3O5lWd"
USER_ID = "d0e7bdf2-a61b-4849-9d9b-3628d00fe321"

TMDB_API_KEY = "997ad1ef3d401c5939f327938e355482"
TMDB_BASE_URL = "https://api.themoviedb.org/3"

SC_ANCHOR_URL = "https://www.streaming-community.co/"

# For testing / local config
DEBUG = os.environ.get("COVE_DEBUG", "0") == "1"
