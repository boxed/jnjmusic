from django.core.management.base import BaseCommand
from django.db import transaction
from recognition.models import Song, Artist
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from django.conf import settings
import time


class Command(BaseCommand):
    help = '''Populate Artist table from Spotify API.
    
    This command:
    1. Searches for songs on Spotify to get correct track IDs (if needed)
    2. Fetches artist information from Spotify API 
    3. Creates/updates Artist records with Spotify metadata (genres, popularity, etc)
    4. Links Songs to their Artists via ManyToMany relationship
    
    Requires valid Spotify API credentials set as environment variables.
    '''

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Run the command without making any changes to the database',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN MODE - No changes will be made'))
        
        # Initialize Spotify client with client credentials (no user auth needed)
        if not settings.SPOTIFY_CLIENT_ID or settings.SPOTIFY_CLIENT_ID.startswith('your-'):
            self.stdout.write(self.style.ERROR('Spotify credentials not configured!'))
            self.stdout.write(self.style.ERROR('Please set the following environment variables:'))
            self.stdout.write(self.style.ERROR('  - SPOTIFY_CLIENT_ID'))
            self.stdout.write(self.style.ERROR('  - SPOTIFY_CLIENT_SECRET'))
            self.stdout.write(self.style.ERROR('\nYou can get these from https://developer.spotify.com/dashboard'))
            return
        
        try:
            client_credentials_manager = SpotifyClientCredentials(
                client_id=settings.SPOTIFY_CLIENT_ID,
                client_secret=settings.SPOTIFY_CLIENT_SECRET
            )
            spotify = spotipy.Spotify(client_credentials_manager=client_credentials_manager)
            # Test the connection
            spotify.search(q='test', type='track', limit=1)
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Failed to initialize Spotify: {e}'))
            self.stdout.write(self.style.ERROR('Please check your Spotify credentials.'))
            return
        
        # Get all songs to process
        songs = Song.objects.all()
        
        self.stdout.write(f'Processing {songs.count()} songs...')
        
        artist_data = {}  # spotify_id -> artist info
        songs_with_valid_spotify = []  # Track songs with valid Spotify IDs
        
        # First, search for actual Spotify track IDs and fetch artist data
        for i, song in enumerate(songs):
            try:
                # Check if spotify_id looks like a valid Spotify ID (22 chars alphanumeric)
                is_valid_spotify_id = (song.spotify_id and 
                                     len(song.spotify_id) == 22 and 
                                     song.spotify_id.replace('_', '').isalnum())
                
                track_data = None
                
                if is_valid_spotify_id:
                    # Try to use existing Spotify ID
                    try:
                        track_data = spotify.track(song.spotify_id)
                    except:
                        is_valid_spotify_id = False
                
                if not is_valid_spotify_id:
                    # Search for the track on Spotify
                    # Extract artists from title if stored as "Title Artist"
                    title_parts = song.spotify_id.split(' ') if song.spotify_id else []
                    search_artists = title_parts[1:] if len(title_parts) > 1 else []
                    
                    # Use song.artist_set if available
                    if not search_artists and song.artist_set.exists():
                        search_artists = [artist.name for artist in song.artist_set.all()]
                    
                    # Search on Spotify
                    if search_artists:
                        query = f"track:{song.title} artist:{' '.join(search_artists)}"
                    else:
                        query = f"track:{song.title}"
                    
                    results = spotify.search(q=query, type='track', limit=1)
                    
                    if results['tracks']['items']:
                        track_data = results['tracks']['items'][0]
                        # Update song with correct Spotify ID if not in dry run
                        if not dry_run:
                            song.spotify_id = track_data['id']
                            song.save()
                            self.stdout.write(f'  Updated {song.title} with Spotify ID: {track_data["id"]}')
                
                if track_data and 'artists' in track_data:
                    songs_with_valid_spotify.append(song)
                    
                    for artist in track_data['artists']:
                        artist_id = artist['id']
                        if artist_id not in artist_data:
                            # Fetch full artist data
                            artist_info = spotify.artist(artist_id)
                            artist_data[artist_id] = artist_info
                            self.stdout.write(f'  Fetched artist: {artist_info["name"]} (ID: {artist_id})')
                            
                            # Rate limiting
                            time.sleep(0.1)
                
                # Progress indicator
                if (i + 1) % 10 == 0:
                    self.stdout.write(f'  Processed {i + 1}/{songs.count()} songs...')
                    
            except Exception as e:
                self.stdout.write(self.style.WARNING(f'  Failed to process song {song.title}: {e}'))
                continue
        
        self.stdout.write(f'\nFound {len(artist_data)} unique artists from Spotify')
        
        if not dry_run:
            # Create/update Artist objects
            created_count = 0
            updated_count = 0
            
            with transaction.atomic():
                for spotify_id, artist_info in artist_data.items():
                    artist, created = Artist.objects.update_or_create(
                        spotify_id=spotify_id,
                        defaults={
                            'name': artist_info['name'],
                            'genres': artist_info.get('genres', []),
                            'popularity': artist_info.get('popularity'),
                            'external_urls': artist_info.get('external_urls', {})
                        }
                    )
                    
                    if created:
                        created_count += 1
                    else:
                        updated_count += 1
            
            self.stdout.write(self.style.SUCCESS(f'Created {created_count} new Artist objects'))
            self.stdout.write(self.style.SUCCESS(f'Updated {updated_count} existing Artist objects'))
            
            # Link songs to artists
            link_count = 0
            with transaction.atomic():
                for song in songs_with_valid_spotify:
                    try:
                        # Clear existing artist relationships to avoid duplicates
                        song.artist_set.clear()
                        
                        # Get track data to link artists
                        is_valid_id = len(song.spotify_id) == 22 if song.spotify_id else False
                        
                        if is_valid_id:
                            track_data = spotify.track(song.spotify_id)
                            
                            if track_data and 'artists' in track_data:
                                for artist in track_data['artists']:
                                    artist_obj = Artist.objects.get(spotify_id=artist['id'])
                                    song.artist_set.add(artist_obj)
                                    link_count += 1
                            
                            time.sleep(0.05)  # Rate limiting
                        
                    except Exception as e:
                        self.stdout.write(self.style.WARNING(f'  Failed to link artists for song {song.title}: {e}'))
                        continue
            
            self.stdout.write(
                self.style.SUCCESS(f'Created {link_count} song-artist relationships')
            )
        else:
            # Dry run - show what would be created/updated
            existing_artists = {}
            for artist in Artist.objects.filter(spotify_id__in=artist_data.keys()):
                existing_artists[artist.spotify_id] = artist
            
            new_artists = []
            update_artists = []
            
            for spotify_id, artist_info in artist_data.items():
                if spotify_id in existing_artists:
                    update_artists.append((existing_artists[spotify_id], artist_info))
                else:
                    new_artists.append(artist_info)
            
            self.stdout.write(f'\nWould create {len(new_artists)} new Artist objects:')
            for artist_info in new_artists[:10]:  # Show first 10
                self.stdout.write(f'  - {artist_info["name"]} (ID: {artist_info["id"]})')
            if len(new_artists) > 10:
                self.stdout.write(f'  ... and {len(new_artists) - 10} more')
            
            self.stdout.write(f'\nWould update {len(update_artists)} existing Artist objects:')
            for artist, artist_info in update_artists[:10]:  # Show first 10
                self.stdout.write(f'  - {artist.name} -> {artist_info["name"]} (ID: {artist_info["id"]})')
            if len(update_artists) > 10:
                self.stdout.write(f'  ... and {len(update_artists) - 10} more')
            
            # Count relationships that would be created
            self.stdout.write(f'\nWould create song-artist relationships for {len(songs_with_valid_spotify)} songs')
        
        self.stdout.write(self.style.SUCCESS('\nDone!'))