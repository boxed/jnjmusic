import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

class Config:
    BASE_DIR = Path(__file__).parent.parent
    DATA_DIR = BASE_DIR / "data"
    DOWNLOADS_DIR = DATA_DIR / "downloads"
    CACHE_DIR = DATA_DIR / "cache"
    
    # ACRCloud settings
    ACRCLOUD_ACCESS_KEY = os.getenv("ACRCLOUD_ACCESS_KEY")
    ACRCLOUD_ACCESS_SECRET = os.getenv("ACRCLOUD_ACCESS_SECRET")
    ACRCLOUD_HOST = os.getenv("ACRCLOUD_HOST", "identify-us-west-2.acrcloud.com")
    
    # Spotify settings
    SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
    SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
    SPOTIFY_REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI", "http://localhost:8888/callback")
    
    # Database
    DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR}/jnj_music.db")
    
    # Application settings
    DEBUG = os.getenv("DEBUG", "false").lower() == "true"
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    
    # Audio processing settings
    AUDIO_SEGMENT_LENGTH = 30  # seconds
    AUDIO_OVERLAP = 5  # seconds
    AUDIO_FORMAT = "mp3"
    
    @classmethod
    def ensure_directories(cls):
        """Create necessary directories if they don't exist."""
        for dir_path in [cls.DATA_DIR, cls.DOWNLOADS_DIR, cls.CACHE_DIR]:
            dir_path.mkdir(parents=True, exist_ok=True)

config = Config()
config.ensure_directories()