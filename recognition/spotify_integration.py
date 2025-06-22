import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
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
        
        if not all([self.client_id, self.client_secret]):
            raise ValueError("Spotify credentials not configured. Please set environment variables.")
        
        self._sp = None
    
    @property
    def sp(self):
        """Lazy load Spotify client."""
        if not self._sp:
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
        
        Note: Playlist creation requires user authentication, which is not supported
        with Client Credentials flow. This method is preserved for future implementation
        with proper user OAuth flow.
        """
        logger.warning("Playlist creation requires user authentication. " 
                      "Please implement user OAuth flow for this functionality.")
        return None
    
    def add_tracks_to_playlist(self, playlist_id: str, track_ids: List[str]) -> bool:
        """Add tracks to a playlist.
        
        Note: Adding tracks to playlists requires user authentication, which is not supported
        with Client Credentials flow. This method is preserved for future implementation
        with proper user OAuth flow.
        """
        logger.warning("Adding tracks to playlist requires user authentication. "
                      "Please implement user OAuth flow for this functionality.")
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
    
