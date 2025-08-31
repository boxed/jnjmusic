import re
from collections import defaultdict
from django.core.management.base import BaseCommand
from django.db.models import Q
from recognition.models import RecognitionResult, Song, YouTubeVideo
from src.utils import setup_logger
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import os
from django.conf import settings

logger = setup_logger(__name__)


class Command(BaseCommand):
    help = 'Sync all WCS J&J songs to a single Spotify playlist'

    def add_arguments(self, parser):
        parser.add_argument(
            '--years',
            nargs='+',
            type=int,
            help='Specific years to include (e.g., --years 2023 2024)'
        )
        parser.add_argument(
            '--playlist-name',
            type=str,
            default='WCS J&J Collection',
            help='Name for the playlist (default: "WCS J&J Collection")'
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

    def extract_year_from_title(self, title):
        """Extract year from video title using regex."""
        # Look for 4-digit years in the title
        year_matches = re.findall(r'\b(19\d{2}|20\d{2})\b', title)
        if year_matches:
            # Return the most recent year found
            return max(int(year) for year in year_matches)
        return None

    def get_songs_by_year(self, verbose=False):
        """Group songs by year based on video titles."""
        import re
        
        songs_by_year = defaultdict(set)
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
            
            # Extract year from video title
            year = self.extract_year_from_title(result.video.title)
            if not year:
                skipped_no_year.append({
                    'title': result.song.title,
                    'video': result.video.title
                })
                if verbose:
                    logger.info(f"Skipped (no year): '{result.song.title}' from video '{result.video.title}'")
                continue
            
            songs_by_year[year].add(spotify_id)

        # Log statistics
        if len(skipped_no_spotify) > 0 or len(skipped_invalid_spotify) > 0 or len(skipped_no_year) > 0:
            logger.info(f"Processed {total_results} recognition results:")
            logger.info(f"  - {len(skipped_no_spotify)} skipped (no Spotify ID)")
            logger.info(f"  - {len(skipped_invalid_spotify)} skipped (invalid Spotify ID)")
            logger.info(f"  - {len(skipped_no_year)} skipped (no year in title)")
            logger.info(f"  - {total_results - len(skipped_no_spotify) - len(skipped_invalid_spotify) - len(skipped_no_year)} included")

        return songs_by_year, {
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
        years_filter = options.get('years')
        playlist_name = options['playlist_name']
        dry_run = options['dry_run']
        force = options['force']
        public = options['public']
        verbose = options['verbose']

        # Get songs grouped by year
        self.stdout.write("Analyzing songs...")
        songs_by_year, stats = self.get_songs_by_year(verbose=verbose)

        if not songs_by_year:
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

        # Filter years if specified
        if years_filter:
            songs_by_year = {
                year: songs for year, songs in songs_by_year.items()
                if year in years_filter
            }

        # Sort years
        sorted_years = sorted(songs_by_year.keys())
        
        # Combine all songs into a single set (removes duplicates across years)
        all_track_ids = set()
        for year in sorted_years:
            all_track_ids.update(songs_by_year[year])
        
        # Convert to list for ordering
        all_track_ids = list(all_track_ids)

        # Display summary
        self.stdout.write(f"\nFound songs from {len(sorted_years)} years:")
        total_songs_with_dupes = sum(len(songs) for songs in songs_by_year.values())
        for year in sorted_years:
            self.stdout.write(f"  {year}: {len(songs_by_year[year])} songs")
        
        self.stdout.write(f"\nTotal unique songs (duplicates removed): {len(all_track_ids)}")
        if total_songs_with_dupes > len(all_track_ids):
            self.stdout.write(f"  ({total_songs_with_dupes - len(all_track_ids)} duplicates removed)")

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
            # Generate description with year range
            year_range = f"{min(sorted_years)}-{max(sorted_years)}" if len(sorted_years) > 1 else str(sorted_years[0])
            description = f"West Coast Swing Jack & Jill music collection ({year_range})"
            
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
