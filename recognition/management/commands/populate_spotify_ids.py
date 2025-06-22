from django.core.management.base import BaseCommand
from django.db.models import Q
from recognition.models import Song
from recognition.spotify_integration import SpotifyIntegration
from src.utils import setup_logger
import time

logger = setup_logger(__name__)


class Command(BaseCommand):
    help = 'Populate Spotify IDs for songs that are missing them'

    def add_arguments(self, parser):
        parser.add_argument(
            '--batch-size',
            type=int,
            default=50,
            help='Number of songs to process in each batch'
        )
        parser.add_argument(
            '--delay',
            type=float,
            default=0.1,
            help='Delay between API calls in seconds'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force update even if song already has Spotify ID'
        )
        parser.add_argument(
            '--limit',
            type=int,
            help='Limit the number of songs to process'
        )

    def handle(self, *args, **options):
        batch_size = options['batch_size']
        delay = options['delay']
        force = options['force']
        limit = options['limit']
        
        # Initialize Spotify integration
        try:
            spotify = SpotifyIntegration()
        except ValueError as e:
            self.stdout.write(self.style.ERROR(f"Failed to initialize Spotify: {e}"))
            return
        
        # Get songs to process
        songs_query = Song.objects.all()
        if not force:
            songs_query = songs_query.filter(Q(spotify_id='') | Q(spotify_id__isnull=True))
        
        if limit:
            songs_query = songs_query[:limit]
        
        total_songs = songs_query.count()
        
        if total_songs == 0:
            self.stdout.write(self.style.SUCCESS("No songs need Spotify IDs"))
            return
        
        self.stdout.write(f"Found {total_songs} songs to process")
        
        success_count = 0
        failed_count = 0
        
        # Process songs in batches
        processed = 0
        for i in range(0, total_songs, batch_size):
            batch = songs_query[i:i+batch_size]
            
            for song in batch:
                processed += 1
                self.stdout.write(f"\rProcessing song {processed}/{total_songs}: {song.title[:50]}...", ending='')
                
                try:
                    # Get artist names
                    artists = [artist.name for artist in song.artist_set.all()]
                    
                    if not artists:
                        logger.warning(f"Song '{song.title}' has no artists, skipping")
                        failed_count += 1
                        continue
                    
                    # Search for track on Spotify
                    track = spotify.search_track(song.title, artists)
                    
                    if track:
                        # Update song with Spotify data
                        song.spotify_id = track['id']
                        
                        # Update additional metadata
                        if 'album' in track and track['album']:
                            song.album = track['album']['name']
                            if 'release_date' in track['album']:
                                song.release_date = track['album']['release_date']
                        
                        # Extract ISRC if available
                        if 'external_ids' in track and 'isrc' in track['external_ids']:
                            song.isrc = track['external_ids']['isrc']
                        
                        # Update duration
                        if 'duration_ms' in track:
                            song.duration_ms = track['duration_ms']
                        
                        song.save()
                        
                        success_count += 1
                        logger.info(f"Updated '{song.title}' with Spotify ID: {track['id']}")
                    else:
                        failed_count += 1
                        logger.warning(f"No Spotify match found for '{song.title}' by {', '.join(artists)}")
                    
                    # Rate limiting
                    time.sleep(delay)
                    
                except Exception as e:
                    failed_count += 1
                    logger.error(f"Error processing song '{song.title}': {e}")
        
        # Summary
        self.stdout.write(
            self.style.SUCCESS(
                f"\nCompleted: {success_count} songs updated, {failed_count} failed"
            )
        )
        
        if failed_count > 0:
            remaining = Song.objects.filter(Q(spotify_id='') | Q(spotify_id__isnull=True)).count()
            self.stdout.write(f"Songs still missing Spotify IDs: {remaining}")