import re
from django.core.management.base import BaseCommand
from django.db import transaction
from recognition.models import Artist, Song
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import os


class Command(BaseCommand):
    help = 'Identify and fix invalid Spotify IDs in the database'

    def __init__(self):
        super().__init__()
        self.sp = None
        self.invalid_entries = {'artists': [], 'songs': []}
        self.fixed_entries = {'artists': [], 'songs': []}

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Run without making changes to the database',
        )

    def setup_spotify(self):
        """Initialize Spotify client."""
        client_id = os.environ.get('SPOTIFY_CLIENT_ID')
        client_secret = os.environ.get('SPOTIFY_CLIENT_SECRET')
        
        if not client_id or not client_secret:
            self.stdout.write(self.style.ERROR(
                'Please set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET environment variables'
            ))
            return False
        
        try:
            auth_manager = SpotifyClientCredentials(
                client_id=client_id,
                client_secret=client_secret
            )
            self.sp = spotipy.Spotify(auth_manager=auth_manager)
            return True
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Failed to initialize Spotify client: {e}'))
            return False

    def is_valid_spotify_id(self, spotify_id, id_type='track'):
        """
        Check if a Spotify ID is valid.
        Spotify IDs are 22 characters long and contain only alphanumeric characters.
        """
        if not spotify_id:
            return False
        
        # Basic format check
        if not re.match(r'^[a-zA-Z0-9]{22}$', spotify_id):
            return False
        
        # Try to fetch the item from Spotify to verify it exists
        if self.sp:
            try:
                if id_type == 'track':
                    self.sp.track(spotify_id)
                elif id_type == 'artist':
                    self.sp.artist(spotify_id)
                return True
            except:
                return False
        
        return True  # If no Spotify client, just check format

    def search_spotify(self, name, item_type='track', artist_name=None):
        """Search Spotify for the correct ID."""
        if not self.sp:
            return None
        
        try:
            if item_type == 'track' and artist_name:
                query = f'track:{name} artist:{artist_name}'
            else:
                query = name
            
            results = self.sp.search(q=query, type=item_type, limit=1)
            
            if item_type == 'track' and results['tracks']['items']:
                return results['tracks']['items'][0]['id']
            elif item_type == 'artist' and results['artists']['items']:
                return results['artists']['items'][0]['id']
            
            return None
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'Search failed for "{name}": {e}'))
            return None

    def identify_invalid_spotify_ids(self):
        """Identify all invalid Spotify IDs in the database."""
        self.stdout.write('Checking Artists...')
        
        # Check Artists
        artists_with_ids = Artist.objects.exclude(spotify_id='')
        for artist in artists_with_ids:
            if not self.is_valid_spotify_id(artist.spotify_id, 'artist'):
                self.invalid_entries['artists'].append({
                    'obj': artist,
                    'name': artist.name,
                    'invalid_id': artist.spotify_id
                })
                self.stdout.write(self.style.WARNING(
                    f'  Invalid Artist ID: {artist.name} - {artist.spotify_id}'
                ))
        
        self.stdout.write(f'Found {len(self.invalid_entries["artists"])} artists with invalid IDs\n')
        
        # Check Songs
        self.stdout.write('Checking Songs...')
        songs_with_ids = Song.objects.exclude(spotify_id='')
        for song in songs_with_ids:
            if not self.is_valid_spotify_id(song.spotify_id, 'track'):
                # Get first artist name for search
                artist_name = song.artist_set.first().name if song.artist_set.exists() else None
                self.invalid_entries['songs'].append({
                    'obj': song,
                    'title': song.title,
                    'artist': artist_name,
                    'invalid_id': song.spotify_id
                })
                self.stdout.write(self.style.WARNING(
                    f'  Invalid Song ID: {song.title} - {song.spotify_id}'
                ))
        
        self.stdout.write(f'Found {len(self.invalid_entries["songs"])} songs with invalid IDs\n')

    def fix_invalid_ids(self, dry_run=False):
        """Clear invalid IDs and search for correct ones."""
        if not self.sp:
            self.stdout.write(self.style.WARNING(
                'Spotify client not initialized. Will only clear invalid IDs without searching for new ones.'
            ))
        
        # Fix Artists
        self.stdout.write('\nFixing Artists...')
        for entry in self.invalid_entries['artists']:
            artist = entry['obj']
            old_id = artist.spotify_id
            
            # Search for correct ID
            new_id = self.search_spotify(artist.name, 'artist') if self.sp else None
            
            if new_id:
                self.stdout.write(self.style.SUCCESS(
                    f'  Found new ID for {artist.name}: {new_id}'
                ))
                if not dry_run:
                    artist.spotify_id = new_id
                    artist.save()
                self.fixed_entries['artists'].append({
                    'name': artist.name,
                    'old_id': old_id,
                    'new_id': new_id
                })
            else:
                self.stdout.write(self.style.WARNING(
                    f'  No match found for {artist.name}, clearing invalid ID'
                ))
                if not dry_run:
                    artist.spotify_id = ''
                    artist.save()
        
        # Fix Songs
        self.stdout.write('\nFixing Songs...')
        for entry in self.invalid_entries['songs']:
            song = entry['obj']
            old_id = song.spotify_id
            
            # Search for correct ID
            new_id = self.search_spotify(
                song.title, 
                'track', 
                artist_name=entry['artist']
            ) if self.sp else None
            
            if new_id:
                self.stdout.write(self.style.SUCCESS(
                    f'  Found new ID for {song.title}: {new_id}'
                ))
                if not dry_run:
                    song.spotify_id = new_id
                    song.save()
                self.fixed_entries['songs'].append({
                    'title': song.title,
                    'artist': entry['artist'],
                    'old_id': old_id,
                    'new_id': new_id
                })
            else:
                self.stdout.write(self.style.WARNING(
                    f'  No match found for {song.title}, clearing invalid ID'
                ))
                if not dry_run:
                    song.spotify_id = ''
                    song.save()

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN MODE - No changes will be made\n'))
        
        # Setup Spotify client
        self.setup_spotify()
        
        # Identify invalid IDs
        self.stdout.write(self.style.NOTICE('Identifying invalid Spotify IDs...\n'))
        self.identify_invalid_spotify_ids()
        
        # Fix invalid IDs
        if self.invalid_entries['artists'] or self.invalid_entries['songs']:
            self.stdout.write(self.style.NOTICE('\nAttempting to fix invalid IDs...'))
            with transaction.atomic():
                self.fix_invalid_ids(dry_run)
                
                if dry_run:
                    transaction.set_rollback(True)
        
        # Summary
        self.stdout.write(self.style.SUCCESS('\n' + '='*50))
        self.stdout.write(self.style.SUCCESS('SUMMARY'))
        self.stdout.write(self.style.SUCCESS('='*50))
        
        self.stdout.write(f'\nInvalid entries found:')
        self.stdout.write(f'  Artists: {len(self.invalid_entries["artists"])}')
        self.stdout.write(f'  Songs: {len(self.invalid_entries["songs"])}')
        
        self.stdout.write(f'\nFixed entries:')
        self.stdout.write(f'  Artists: {len(self.fixed_entries["artists"])}')
        self.stdout.write(f'  Songs: {len(self.fixed_entries["songs"])}')
        
        if dry_run:
            self.stdout.write(self.style.WARNING('\nDRY RUN COMPLETE - No changes were made'))
        else:
            self.stdout.write(self.style.SUCCESS('\nAll invalid Spotify IDs have been processed'))