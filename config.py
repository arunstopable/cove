import os
from dotenv import load_dotenv

load_dotenv()

SC_ANCHOR_URL = "https://www.streaming-community.co/"

# For testing / local config
DEBUG = os.environ.get("COVE_DEBUG", "0") == "1"
