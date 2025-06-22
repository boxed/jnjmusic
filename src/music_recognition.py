import asyncio
import json
import time
import base64
import hmac
import hashlib
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from shazamio import Shazam
import requests

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
            response = requests.post(url, files=files, data=data, timeout=10)
            
            if response.status_code == 200:
                result = response.json()
                if result.get('status', {}).get('code') == 0:
                    return self._parse_result(result)
                else:
                    logger.warning(f"ACRCloud returned status code: {result.get('status', {}).get('code')}")
            else:
                logger.error(f"ACRCloud API error: {response.status_code}")
            
        except Exception as e:
            import traceback
            logger.error(f"Error identifying audio: {e}")
            logger.error("Full stack trace:")
            traceback.print_exc()
        
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
    """Shazam music recognition implementation using shazamio."""
    
    def __init__(self):
        self.shazam = Shazam()
    
    def identify(self, audio_path: Path) -> Optional[Dict]:
        """Identify a song using Shazam API."""
        try:
            # Run async function in sync context with timeout
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(
                    asyncio.wait_for(self._identify_async(audio_path), timeout=15.0)
                )
            except asyncio.TimeoutError:
                logger.error(f"Shazam recognition timeout for {audio_path}")
                result = None
            finally:
                loop.close()
            return result
        except Exception as e:
            import traceback
            logger.error(f"Error identifying audio with Shazam: {e}")
            logger.error("Full stack trace:")
            traceback.print_exc()
            return None
    
    async def _identify_async(self, audio_path: Path) -> Optional[Dict]:
        """Async method to identify song."""
        try:
            # Recognize song
            out = await self.shazam.recognize(str(audio_path))
            
            logger.debug(f"Shazam response: {json.dumps(out, indent=2) if out else 'None'}")
            
            if not out:
                logger.warning("Empty Shazam response")
                return None
            
            # Check if there are matches
            if 'matches' in out and not out['matches']:
                logger.info("No matches found by Shazam for this audio segment")
                return None
            
            if 'track' not in out:
                logger.warning(f"No track found in Shazam response. Response keys: {list(out.keys())}")
                return None
            
            return self._parse_result(out)
        except Exception as e:
            import traceback
            logger.error(f"Shazam recognition error: {e}")
            logger.error("Full stack trace:")
            traceback.print_exc()
            return None
    
    def _parse_result(self, result: Dict) -> Dict:
        """Parse Shazam result into standardized format."""
        track = result.get('track', {})
        
        if not track:
            return None
        
        # Extract artists
        artists = []
        if 'subtitle' in track:
            artists = [track['subtitle']]
        
        # Extract Spotify ID if available
        spotify_id = None
        if 'hub' in track:
            for provider in track['hub'].get('providers', []):
                if provider.get('type') == 'SPOTIFY':
                    for action in provider.get('actions', []):
                        if 'uri' in action:
                            # Extract ID from spotify:track:ID format
                            spotify_id = action['uri'].split(':')[-1]
                            break
        
        # Extract genres
        genres = []
        if 'genres' in track:
            genres = list(track['genres'].values()) if isinstance(track['genres'], dict) else track['genres']
        
        # Extract album safely
        album = ''
        sections = track.get('sections', [])
        if sections and len(sections) > 0:
            metadata_list = sections[0].get('metadata', [])
            if metadata_list and len(metadata_list) > 0:
                album = metadata_list[0].get('text', '')
        
        return {
            'title': track.get('title', 'Unknown'),
            'artists': artists,
            'album': album,
            'duration_ms': 0,  # Shazam doesn't provide duration in the recognition response
            'score': 100 if track else 0,  # Shazam doesn't provide confidence scores
            'spotify_id': spotify_id,
            'external_ids': {},
            'genres': genres,
            'release_date': '',
            'raw_result': result
        }


def get_recognizer(service: str = "shazamkit") -> MusicRecognizer:
    """Factory function to get appropriate music recognizer."""
    recognizers = {
        "acrcloud": ACRCloudRecognizer,
        "shazamkit": ShazamKitRecognizer,
    }
    
    recognizer_class = recognizers.get(service.lower())
    if not recognizer_class:
        raise ValueError(f"Unknown recognizer service: {service}")
    
    return recognizer_class()