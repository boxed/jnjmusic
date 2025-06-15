import base64
import hashlib
import hmac
import json
import time
from typing import Dict, List, Optional, Tuple
import requests
from pathlib import Path

from .config import config
from .utils import setup_logger

logger = setup_logger(__name__)


class MusicRecognizer:
    """Base class for music recognition services."""
    
    def identify(self, audio_path: Path) -> Optional[Dict]:
        """Identify a song from an audio file."""
        raise NotImplementedError


class ACRCloudRecognizer(MusicRecognizer):
    """ACRCloud music recognition implementation."""
    
    def __init__(self):
        self.access_key = config.ACRCLOUD_ACCESS_KEY
        self.access_secret = config.ACRCLOUD_ACCESS_SECRET
        self.host = config.ACRCLOUD_HOST
        
        if not all([self.access_key, self.access_secret, self.host]):
            raise ValueError("ACRCloud credentials not configured. Please set environment variables.")
    
    def _build_signature(self, string_to_sign: str) -> str:
        """Generate signature for ACRCloud API."""
        return base64.b64encode(
            hmac.new(
                self.access_secret.encode('utf-8'),
                string_to_sign.encode('utf-8'),
                hashlib.sha1
            ).digest()
        ).decode('utf-8')
    
    def identify(self, audio_path: Path) -> Optional[Dict]:
        """Identify a song using ACRCloud API."""
        try:
            with open(audio_path, 'rb') as f:
                audio_data = f.read()
            
            timestamp = str(int(time.time()))
            string_to_sign = f"POST\n/v1/identify\n{self.access_key}\n{timestamp}"
            signature = self._build_signature(string_to_sign)
            
            files = {'sample': audio_data}
            data = {
                'access_key': self.access_key,
                'timestamp': timestamp,
                'signature': signature,
                'data_type': 'audio',
                'sample_bytes': len(audio_data)
            }
            
            url = f"https://{self.host}/v1/identify"
            response = requests.post(url, files=files, data=data, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                if result.get('status', {}).get('code') == 0:
                    return self._parse_result(result)
                else:
                    logger.warning(f"ACRCloud returned status code: {result.get('status', {}).get('code')}")
            else:
                logger.error(f"ACRCloud API error: {response.status_code}")
            
        except Exception as e:
            logger.error(f"Error identifying audio: {e}")
        
        return None
    
    def _parse_result(self, result: Dict) -> Dict:
        """Parse ACRCloud result into standardized format."""
        metadata = result.get('metadata', {})
        if not metadata:
            return None
        
        music_list = metadata.get('music', [])
        if not music_list:
            return None
        
        # Get the first (best) match
        music = music_list[0]
        
        return {
            'title': music.get('title', 'Unknown'),
            'artists': [artist.get('name', '') for artist in music.get('artists', [])],
            'album': music.get('album', {}).get('name', ''),
            'duration_ms': music.get('duration_ms', 0),
            'score': music.get('score', 0),
            'spotify_id': self._extract_spotify_id(music),
            'external_ids': music.get('external_ids', {}),
            'genres': music.get('genres', []),
            'release_date': music.get('release_date', ''),
            'raw_result': result
        }
    
    def _extract_spotify_id(self, music: Dict) -> Optional[str]:
        """Extract Spotify track ID from external metadata."""
        external_metadata = music.get('external_metadata', {})
        spotify_data = external_metadata.get('spotify', {})
        track_data = spotify_data.get('track', {})
        return track_data.get('id')


class ShazamKitRecognizer(MusicRecognizer):
    """Alternative implementation using ShazamKit (requires additional setup)."""
    
    def identify(self, audio_path: Path) -> Optional[Dict]:
        # Placeholder for ShazamKit implementation
        logger.warning("ShazamKit recognizer not implemented yet")
        return None


def get_recognizer(service: str = "acrcloud") -> MusicRecognizer:
    """Factory function to get appropriate music recognizer."""
    recognizers = {
        "acrcloud": ACRCloudRecognizer,
        "shazamkit": ShazamKitRecognizer,
    }
    
    recognizer_class = recognizers.get(service.lower())
    if not recognizer_class:
        raise ValueError(f"Unknown recognizer service: {service}")
    
    return recognizer_class()