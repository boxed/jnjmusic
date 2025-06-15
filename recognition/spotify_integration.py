import spotipy
from spotipy.oauth2 import SpotifyOAuth
from django.conf import settings
from typing import List, Dict, Optional
import time

from src.utils import setup_logger
from .models import RecognitionResult, SpotifyPlaylist

logger = setup_logger(__name__)


class SpotifyIntegration:
    """Handles Spotify API integration for playlist creation and metadata enrichment."""
    
    def __init__(self):
        self.client_id = settings.SPOTIFY_CLIENT_ID
        self.client_secret = settings.SPOTIFY_CLIENT_SECRET
        self.redirect_uri = settings.SPOTIFY_REDIRECT_URI
        
        if not all([self.client_id, self.client_secret]):
            raise ValueError("Spotify credentials not configured. Please set environment variables.")
        
        self.scope = "playlist-modify-public playlist-modify-private user-library-read"
        self._sp = None
    
    @property
    def sp(self):
        """Lazy load Spotify client."""
        if not self._sp:
            auth_manager = SpotifyOAuth(
                client_id=self.client_id,
                client_secret=self.client_secret,
                redirect_uri=self.redirect_uri,
                scope=self.scope,
                cache_path=settings.DATA_DIR / '.spotify_cache'
            )
            self._sp = spotipy.Spotify(auth_manager=auth_manager)
        return self._sp
    
    def search_track(self, title: str, artists: List[str]) -> Optional[Dict]:
        """Search for a track on Spotify."""
        try:
            # Build search query
            artist_str = ' '.join(artists[:2])  # Use first 2 artists
            query = f"track:{title} artist:{artist_str}"
            
            results = self.sp.search(q=query, type='track', limit=10)
            
            if not results['tracks']['items']:
                # Try with just title
                results = self.sp.search(q=f"track:{title}", type='track', limit=10)
            
            if results['tracks']['items']:
                # Find best match
                for track in results['tracks']['items']:
                    track_artists = [a['name'].lower() for a in track['artists']]
                    
                    # Check if any artist matches
                    for artist in artists:
                        if artist.lower() in track_artists:
                            return track
                
                # Return first result if no exact artist match
                return results['tracks']['items'][0]
            
            return None
            
        except Exception as e:
            logger.error(f"Error searching track '{title}': {e}")
            return None
    
    def enrich_recognition_result(self, result: RecognitionResult) -> bool:
        """Enrich a recognition result with Spotify metadata."""
        try:
            # Skip if already has Spotify ID
            if result.spotify_id:
                return True
            
            # Search for track
            track = self.search_track(result.title, result.artists)
            
            if track:
                # Update result with Spotify data
                result.spotify_id = track['id']
                
                # Add additional metadata
                if 'album' in track and track['album']:
                    result.album = track['album']['name']
                    if 'release_date' in track['album']:
                        result.release_date = track['album']['release_date']
                
                # Extract ISRC if available
                if 'external_ids' in track and 'isrc' in track['external_ids']:
                    result.isrc = track['external_ids']['isrc']
                
                result.save()
                logger.info(f"Enriched '{result.title}' with Spotify ID: {track['id']}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error enriching result: {e}")
            return False
    
    def create_playlist(self, name: str, description: str = "", public: bool = True) -> Optional[str]:
        """Create a new Spotify playlist."""
        try:
            user = self.sp.current_user()
            playlist = self.sp.user_playlist_create(
                user['id'],
                name,
                public=public,
                description=description
            )
            
            logger.info(f"Created playlist: {name} (ID: {playlist['id']})")
            return playlist['id']
            
        except Exception as e:
            logger.error(f"Error creating playlist: {e}")
            return None
    
    def add_tracks_to_playlist(self, playlist_id: str, track_ids: List[str]) -> bool:
        """Add tracks to a playlist."""
        try:
            # Spotify API limits to 100 tracks per request
            for i in range(0, len(track_ids), 100):
                batch = track_ids[i:i+100]
                track_uris = [f"spotify:track:{tid}" for tid in batch]
                self.sp.playlist_add_items(playlist_id, track_uris)
                
                # Rate limiting
                if i + 100 < len(track_ids):
                    time.sleep(0.5)
            
            logger.info(f"Added {len(track_ids)} tracks to playlist")
            return True
            
        except Exception as e:
            logger.error(f"Error adding tracks to playlist: {e}")
            return False
    
    def create_playlist_from_results(
        self, 
        results: List[RecognitionResult], 
        playlist_name: str,
        description: str = "",
        video=None
    ) -> Optional[SpotifyPlaylist]:
        """Create a Spotify playlist from recognition results."""
        try:
            # Filter results with Spotify IDs
            results_with_spotify = [r for r in results if r.spotify_id]
            
            if not results_with_spotify:
                logger.warning("No results with Spotify IDs to create playlist")
                return None
            
            # Remove duplicates
            seen_ids = set()
            unique_results = []
            for result in results_with_spotify:
                if result.spotify_id not in seen_ids:
                    seen_ids.add(result.spotify_id)
                    unique_results.append(result)
            
            # Create playlist
            playlist_id = self.create_playlist(playlist_name, description)
            if not playlist_id:
                return None
            
            # Add tracks
            track_ids = [r.spotify_id for r in unique_results]
            success = self.add_tracks_to_playlist(playlist_id, track_ids)
            
            if success:
                # Get playlist URL
                playlist_data = self.sp.playlist(playlist_id)
                playlist_url = playlist_data['external_urls']['spotify']
                
                # Save to database
                playlist = SpotifyPlaylist.objects.create(
                    name=playlist_name,
                    spotify_id=playlist_id,
                    spotify_url=playlist_url,
                    description=description,
                    video=video,
                    tracks_added=len(track_ids)
                )
                
                logger.info(f"Created playlist with {len(track_ids)} tracks: {playlist_url}")
                return playlist
            
            return None
            
        except Exception as e:
            logger.error(f"Error creating playlist from results: {e}")
            return None
    
    def get_track_metadata(self, track_id: str) -> Optional[Dict]:
        """Get detailed metadata for a track."""
        try:
            track = self.sp.track(track_id)
            
            # Get audio features
            features = self.sp.audio_features([track_id])[0]
            
            return {
                'track': track,
                'features': features,
                'popularity': track.get('popularity', 0),
                'preview_url': track.get('preview_url'),
                'duration_ms': track.get('duration_ms', 0),
            }
            
        except Exception as e:
            logger.error(f"Error getting track metadata: {e}")
            return None
    
    def authenticate_url(self) -> str:
        """Get the URL for Spotify authentication."""
        auth_manager = SpotifyOAuth(
            client_id=self.client_id,
            client_secret=self.client_secret,
            redirect_uri=self.redirect_uri,
            scope=self.scope,
            cache_path=settings.DATA_DIR / '.spotify_cache'
        )
        return auth_manager.get_authorize_url()
    
    def handle_callback(self, code: str) -> bool:
        """Handle the OAuth callback."""
        try:
            auth_manager = SpotifyOAuth(
                client_id=self.client_id,
                client_secret=self.client_secret,
                redirect_uri=self.redirect_uri,
                scope=self.scope,
                cache_path=settings.DATA_DIR / '.spotify_cache'
            )
            
            token_info = auth_manager.get_access_token(code)
            if token_info:
                logger.info("Successfully authenticated with Spotify")
                return True
                
            return False
            
        except Exception as e:
            logger.error(f"Error handling Spotify callback: {e}")
            return False