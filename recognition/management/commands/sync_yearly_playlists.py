import os

import spotipy
from django.conf import settings
from django.core.management.base import BaseCommand
from spotipy.oauth2 import SpotifyOAuth

from recognition.models import RecognitionResult
from src.utils import setup_logger

logger = setup_logger(__name__)


class Command(BaseCommand):
    help = 'Sync all WCS J&J songs to a single Spotify playlist'

    def add_arguments(self, parser):
        parser.add_argument(
            '--playlist-name',
            type=str,
            default='WCS competition music',
            help='Name for the playlist (default: "WCS competition music")'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be done without making changes'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force recreation of playlist (replace existing)'
        )
        parser.add_argument(
            '--public',
            action='store_true',
            default=False,
            help='Make playlist public (default is private)'
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Show detailed information about skipped songs'
        )

    def get_songs_by_year(self, verbose=False):
        """Get all songs with valid Spotify IDs."""
        import re

        all_songs = set()
        skipped_no_spotify = []
        skipped_invalid_spotify = []
        skipped_no_year = []
        total_results = 0

        # Get all recognition results
        all_results = RecognitionResult.objects.select_related(
            'song', 'video'
        ).prefetch_related('song__artist_set')

        for result in all_results:
            total_results += 1

            # Skip songs without Spotify IDs
            if not result.song.spotify_id or result.song.spotify_id.strip() == '':
                artists = ', '.join([a.name for a in result.song.artist_set.all()]) or 'Unknown Artist'
                skipped_no_spotify.append({
                    'title': result.song.title,
                    'artists': artists,
                    'video': result.video.title
                })
                if verbose:
                    logger.info(f"Skipped (no Spotify ID): '{result.song.title}' by {artists}")
                continue

            # Validate Spotify ID format (should be 22 alphanumeric characters)
            spotify_id = result.song.spotify_id.strip()
            if not re.match(r'^[a-zA-Z0-9]{22}$', spotify_id):
                artists = ', '.join([a.name for a in result.song.artist_set.all()]) or 'Unknown Artist'
                skipped_invalid_spotify.append({
                    'title': result.song.title,
                    'artists': artists,
                    'spotify_id': spotify_id,
                    'video': result.video.title
                })
                if verbose:
                    logger.info(f"Skipped (invalid Spotify ID): '{result.song.title}' by {artists} - ID: {spotify_id}")
                continue

            all_songs.add(spotify_id)

        # Log statistics
        if len(skipped_no_spotify) > 0 or len(skipped_invalid_spotify) > 0 or len(skipped_no_year) > 0:
            logger.info(f"Processed {total_results} recognition results:")
            logger.info(f"  - {len(skipped_no_spotify)} skipped (no Spotify ID)")
            logger.info(f"  - {len(skipped_invalid_spotify)} skipped (invalid Spotify ID)")
            logger.info(f"  - {len(skipped_no_year)} skipped (no year in title)")
            logger.info(f"  - {total_results - len(skipped_no_spotify) - len(skipped_invalid_spotify) - len(skipped_no_year)} included")

        return list(all_songs), {
            'total': total_results,
            'skipped_no_spotify': skipped_no_spotify,
            'skipped_invalid_spotify': skipped_invalid_spotify,
            'skipped_no_year': skipped_no_year
        }

    def get_spotify_client(self):
        """Get Spotify client with user authentication."""
        # Check for user auth credentials - prioritize environment variables, fallback to settings
        client_id = settings.SPOTIFY_CLIENT_ID
        client_secret = settings.SPOTIFY_CLIENT_SECRET
        redirect_uri = os.getenv('SPOTIFY_REDIRECT_URI', 'http://localhost:8889/callback')

        if not all([client_id, client_secret]):
            raise ValueError("Spotify credentials not configured. Please set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET in settings or environment variables.")

        # Set up OAuth with required scopes for playlist management
        scope = 'playlist-modify-public playlist-modify-private playlist-read-private'

        auth_manager = SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            scope=scope,
            open_browser=True,
            cache_path='.spotify_cache'
        )

        return spotipy.Spotify(auth_manager=auth_manager)

    def get_or_create_playlist(self, sp, playlist_name, description, public=False):
        """Get existing playlist or create a new one."""
        # Get current user
        user = sp.current_user()
        user_id = user['id']

        # Check if playlist already exists
        playlists = sp.current_user_playlists(limit=50)
        existing_playlist = None

        while playlists:
            for playlist in playlists['items']:
                if playlist['name'] == playlist_name and playlist['owner']['id'] == user_id:
                    existing_playlist = playlist
                    break

            if existing_playlist:
                break

            if playlists['next']:
                playlists = sp.next(playlists)
            else:
                break

        if existing_playlist:
            return existing_playlist['id'], False
        else:
            # Create new playlist
            playlist = sp.user_playlist_create(
                user=user_id,
                name=playlist_name,
                public=public,
                description=description
            )
            return playlist['id'], True

    def sync_playlist(self, sp, playlist_id, track_ids, replace=True):
        """Sync tracks to a playlist."""
        if replace:
            # Clear existing tracks
            sp.playlist_replace_items(playlist_id, [])

        # Spotify API limits to 100 tracks per request
        for i in range(0, len(track_ids), 100):
            batch = track_ids[i:i+100]
            # Format track IDs as URIs
            track_uris = [f'spotify:track:{track_id}' for track_id in batch]

            if i == 0 and replace:
                # First batch replaces all
                sp.playlist_replace_items(playlist_id, track_uris)
            else:
                # Subsequent batches append
                sp.playlist_add_items(playlist_id, track_uris)

    def handle(self, *args, **options):
        playlist_name = options['playlist_name']
        dry_run = options['dry_run']
        force = options['force']
        public = options['public']
        verbose = options['verbose']

        # Get all songs
        self.stdout.write("Analyzing songs...")
        all_track_ids, stats = self.get_songs_by_year(verbose=verbose)

        if not all_track_ids:
            self.stdout.write(self.style.WARNING("No songs with valid Spotify IDs found"))
            if len(stats['skipped_no_spotify']) > 0:
                self.stdout.write(f"  {len(stats['skipped_no_spotify'])} songs skipped (no Spotify ID)")
            if len(stats['skipped_invalid_spotify']) > 0:
                self.stdout.write(f"  {len(stats['skipped_invalid_spotify'])} songs skipped (invalid Spotify ID)")
            if len(stats['skipped_no_year']) > 0:
                self.stdout.write(f"  {len(stats['skipped_no_year'])} songs skipped (no year in title)")
            return

        # Display filtering statistics
        if len(stats['skipped_no_spotify']) > 0 or len(stats['skipped_invalid_spotify']) > 0 or len(stats['skipped_no_year']) > 0:
            self.stdout.write(f"\nFiltering statistics:")
            self.stdout.write(f"  Total recognition results: {stats['total']}")
            if len(stats['skipped_no_spotify']) > 0:
                self.stdout.write(f"  Skipped (no Spotify ID): {len(stats['skipped_no_spotify'])}")
                if verbose and len(stats['skipped_no_spotify']) <= 10:
                    for song in stats['skipped_no_spotify'][:10]:
                        self.stdout.write(f"    - '{song['title']}' by {song['artists']}")
                    if len(stats['skipped_no_spotify']) > 10:
                        self.stdout.write(f"    ... and {len(stats['skipped_no_spotify']) - 10} more")
            if len(stats['skipped_invalid_spotify']) > 0:
                self.stdout.write(f"  Skipped (invalid Spotify ID): {len(stats['skipped_invalid_spotify'])}")
                if verbose and len(stats['skipped_invalid_spotify']) <= 10:
                    for song in stats['skipped_invalid_spotify'][:10]:
                        self.stdout.write(f"    - '{song['title']}' by {song['artists']} (ID: {song['spotify_id'][:30]}...)")
                    if len(stats['skipped_invalid_spotify']) > 10:
                        self.stdout.write(f"    ... and {len(stats['skipped_invalid_spotify']) - 10} more")
            if len(stats['skipped_no_year']) > 0:
                self.stdout.write(f"  Skipped (no year in title): {len(stats['skipped_no_year'])}")
                if verbose and len(stats['skipped_no_year']) <= 10:
                    for song in stats['skipped_no_year'][:10]:
                        self.stdout.write(f"    - '{song['title']}' from '{song['video']}'")
                    if len(stats['skipped_no_year']) > 10:
                        self.stdout.write(f"    ... and {len(stats['skipped_no_year']) - 10} more")
            self.stdout.write(f"  Included in playlist: {stats['total'] - len(stats['skipped_no_spotify']) - len(stats['skipped_invalid_spotify']) - len(stats['skipped_no_year'])}")

        # Display summary
        self.stdout.write(f"\nTotal unique songs: {len(all_track_ids)}")

        if dry_run:
            self.stdout.write(self.style.SUCCESS("\nDry run completed. No changes made."))
            return

        # Initialize Spotify client
        try:
            self.stdout.write("\nAuthenticating with Spotify...")
            sp = self.get_spotify_client()
            user = sp.current_user()
            self.stdout.write(f"Authenticated as: {user['display_name']} ({user['id']})")
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Failed to authenticate with Spotify: {e}"))
            self.stdout.write("\nMake sure you have set up the following environment variables:")
            self.stdout.write("  - SPOTIFY_CLIENT_ID")
            self.stdout.write("  - SPOTIFY_CLIENT_SECRET")
            self.stdout.write("  - SPOTIFY_REDIRECT_URI (optional, defaults to http://localhost:8889/callback)")
            return

        # Create or update the single playlist
        self.stdout.write(f"\nCreating/updating playlist: {playlist_name}")
        self.stdout.write(f"Total songs to add: {len(all_track_ids)}")

        try:
            # Generate description
            description = f"West Coast Swing competition music collection"

            # Get or create playlist
            playlist_id, created = self.get_or_create_playlist(
                sp,
                playlist_name,
                description,
                public=public
            )

            if created:
                self.stdout.write(f"Created new playlist: {playlist_name}")
            else:
                if force:
                    self.stdout.write(f"Updating existing playlist: {playlist_name}")
                else:
                    self.stdout.write(f"Found existing playlist: {playlist_name}")

            # Sync tracks
            self.sync_playlist(sp, playlist_id, all_track_ids, replace=True)

            # Get playlist URL
            playlist_data = sp.playlist(playlist_id, fields='external_urls')
            playlist_url = playlist_data['external_urls']['spotify']

            self.stdout.write(self.style.SUCCESS(f"\n✓ Successfully synced {len(all_track_ids)} songs to '{playlist_name}'"))
            self.stdout.write(f"Playlist URL: {playlist_url}")

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"\n✗ Failed to sync playlist: {e}"))
            logger.error(f"Error syncing playlist: {e}", exc_info=True)
