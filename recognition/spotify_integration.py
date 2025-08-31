import spotipy
from spotipy.oauth2 import SpotifyClientCredentials, SpotifyOAuth
from django.conf import settings
from typing import List, Dict, Optional
import time
import os

from src.utils import setup_logger
from .models import RecognitionResult, SpotifyPlaylist

logger = setup_logger(__name__)


class SpotifyIntegration:
    """Handles Spotify API integration for playlist creation and metadata enrichment."""
    
    def __init__(self, use_user_auth=False):
        self.client_id = os.getenv('SPOTIFY_CLIENT_ID', settings.SPOTIFY_CLIENT_ID)
        self.client_secret = os.getenv('SPOTIFY_CLIENT_SECRET', settings.SPOTIFY_CLIENT_SECRET)
        self.use_user_auth = use_user_auth
        
        if not all([self.client_id, self.client_secret]):
            raise ValueError("Spotify credentials not configured. Please set environment variables.")
        
        self._sp = None
    
    @property
    def sp(self):
        """Lazy load Spotify client."""
        if not self._sp:
            if self.use_user_auth:
                # User authentication for playlist management
                redirect_uri = os.getenv('SPOTIFY_REDIRECT_URI', 'http://localhost:8889/callback')
                scope = 'playlist-modify-public playlist-modify-private playlist-read-private user-library-read'
                
                auth_manager = SpotifyOAuth(
                    client_id=self.client_id,
                    client_secret=self.client_secret,
                    redirect_uri=redirect_uri,
                    scope=scope,
                    open_browser=True,
                    cache_path='.spotify_cache'
                )
            else:
                # Client credentials for read-only operations
                auth_manager = SpotifyClientCredentials(
                    client_id=self.client_id,
                    client_secret=self.client_secret
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
            import traceback
            logger.error(f"Error searching track '{title}': {e}")
            logger.error("Full stack trace:")
            traceback.print_exc()
            return None
    
    def enrich_recognition_result(self, result: RecognitionResult) -> bool:
        """Enrich a recognition result with Spotify metadata."""
        try:
            # Skip if already has Spotify ID
            if result.song.spotify_id:
                return True
            
            # Get artist names
            artists = [artist.name for artist in result.song.artist_set.all()]
            
            # Search for track
            track = self.search_track(result.song.title, artists)
            
            if track:
                # Update song with Spotify data
                result.song.spotify_id = track['id']
                
                # Add additional metadata
                if 'album' in track and track['album']:
                    result.song.album = track['album']['name']
                    if 'release_date' in track['album']:
                        result.song.release_date = track['album']['release_date']
                
                # Extract ISRC if available
                if 'external_ids' in track and 'isrc' in track['external_ids']:
                    result.song.isrc = track['external_ids']['isrc']
                
                result.song.save()
                logger.info(f"Enriched '{result.song.title}' with Spotify ID: {track['id']}")
                return True
            
            return False
            
        except Exception as e:
            import traceback
            logger.error(f"Error enriching result: {e}")
            logger.error("Full stack trace:")
            traceback.print_exc()
            return False
    
    def create_playlist(self, name: str, description: str = "", public: bool = True) -> Optional[str]:
        """Create a new Spotify playlist.
        
        Requires user authentication (use_user_auth=True in constructor).
        """
        if not self.use_user_auth:
            logger.warning("Playlist creation requires user authentication. " 
                          "Initialize SpotifyIntegration with use_user_auth=True.")
            return None
        
        try:
            user = self.sp.current_user()
            playlist = self.sp.user_playlist_create(
                user=user['id'],
                name=name,
                public=public,
                description=description
            )
            logger.info(f"Created playlist '{name}' with ID: {playlist['id']}")
            return playlist['id']
        except Exception as e:
            logger.error(f"Error creating playlist: {e}")
            return None
    
    def add_tracks_to_playlist(self, playlist_id: str, track_ids: List[str]) -> bool:
        """Add tracks to a playlist.
        
        Requires user authentication (use_user_auth=True in constructor).
        """
        if not self.use_user_auth:
            logger.warning("Adding tracks to playlist requires user authentication. "
                          "Initialize SpotifyIntegration with use_user_auth=True.")
            return False
        
        try:
            # Convert track IDs to URIs
            track_uris = [f'spotify:track:{tid}' for tid in track_ids]
            
            # Spotify API limits to 100 tracks per request
            for i in range(0, len(track_uris), 100):
                batch = track_uris[i:i+100]
                if i == 0:
                    # First batch replaces existing tracks
                    self.sp.playlist_replace_items(playlist_id, batch)
                else:
                    # Subsequent batches append
                    self.sp.playlist_add_items(playlist_id, batch)
            
            logger.info(f"Added {len(track_ids)} tracks to playlist {playlist_id}")
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
            import traceback
            logger.error(f"Error creating playlist from results: {e}")
            logger.error("Full stack trace:")
            traceback.print_exc()
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
            import traceback
            logger.error(f"Error getting track metadata: {e}")
            logger.error("Full stack trace:")
            traceback.print_exc()
            return None
