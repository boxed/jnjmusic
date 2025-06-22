from django.core.management.base import BaseCommand
from django.db import transaction
from recognition.models import Song, Artist
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from django.conf import settings


class Command(BaseCommand):
    help = '''Fill in artist_set for songs based on their Spotify ID.
    
    This command:
    1. Finds all songs with a valid Spotify ID (22-character alphanumeric)
    2. Fetches track information from Spotify API
    3. Links existing Artists to Songs based on the artist's Spotify ID
    
    Unlike populate_artists, this only fills in the relationships and doesn't
    create new Artist records. Run 'populate_artists' first to create Artist records.
    
    Note: Requires SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET environment variables.
    '''

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Run the command without making any changes to the database',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Update artist_set even if it already has artists',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        force = options['force']
        
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN MODE - No changes will be made'))
        
        # Get Spotify client using client credentials (no user auth needed)
        try:
            if not settings.SPOTIFY_CLIENT_ID or settings.SPOTIFY_CLIENT_ID.startswith('your-'):
                self.stdout.write(self.style.ERROR('Spotify credentials not configured!'))
                self.stdout.write(self.style.ERROR('Please set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET'))
                return
            
            client_credentials_manager = SpotifyClientCredentials(
                client_id=settings.SPOTIFY_CLIENT_ID,
                client_secret=settings.SPOTIFY_CLIENT_SECRET
            )
            spotify = spotipy.Spotify(client_credentials_manager=client_credentials_manager)
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Failed to initialize Spotify client: {e}'))
            return
        
        # Get songs to process
        songs = Song.objects.filter(spotify_id__regex=r'^[a-zA-Z0-9]{22}$')
        if not force:
            songs = songs.filter(artist_set__isnull=True)
        
        total_songs = songs.count()
        self.stdout.write(f'Found {total_songs} songs to process')
        
        if total_songs == 0:
            self.stdout.write(self.style.SUCCESS('No songs need processing!'))
            return
        
        updated_count = 0
        failed_count = 0
        artist_links_created = 0
        
        for i, song in enumerate(songs):
            try:
                # Fetch track data from Spotify
                track = spotify.track(song.spotify_id)
                
                if not track or 'artists' not in track:
                    self.stdout.write(self.style.WARNING(f'No artist data for {song.title}'))
                    failed_count += 1
                    continue
                
                # Clear existing relationships if force is True
                if force and not dry_run:
                    song.artist_set.clear()
                
                # Find matching artists in our database
                artists_linked = 0
                for spotify_artist in track['artists']:
                    artist_spotify_id = spotify_artist['id']
                    
                    try:
                        artist = Artist.objects.get(spotify_id=artist_spotify_id)
                        
                        if not dry_run:
                            song.artist_set.add(artist)
                            artists_linked += 1
                            artist_links_created += 1
                        else:
                            self.stdout.write(f'  Would link: {song.title} -> {artist.name}')
                            artists_linked += 1
                            
                    except Artist.DoesNotExist:
                        self.stdout.write(
                            self.style.WARNING(
                                f'  Artist not found: {spotify_artist["name"]} '
                                f'(Spotify ID: {artist_spotify_id})'
                            )
                        )
                
                if artists_linked > 0:
                    updated_count += 1
                    if not dry_run:
                        self.stdout.write(
                            self.style.SUCCESS(
                                f'  Updated {song.title} with {artists_linked} artist(s)'
                            )
                        )
                
                # Progress indicator
                if (i + 1) % 10 == 0:
                    self.stdout.write(f'Progress: {i + 1}/{total_songs} songs...')
                    
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f'Failed to process {song.title}: {e}')
                )
                failed_count += 1
                continue
        
        # Summary
        self.stdout.write('\n' + '='*50)
        self.stdout.write(self.style.SUCCESS(f'Songs updated: {updated_count}'))
        self.stdout.write(self.style.SUCCESS(f'Artist links created: {artist_links_created}'))
        if failed_count > 0:
            self.stdout.write(self.style.WARNING(f'Songs failed: {failed_count}'))
        
        if dry_run:
            self.stdout.write(self.style.WARNING('\nDRY RUN - No changes were made'))
        else:
            self.stdout.write(self.style.SUCCESS('\nDone!'))