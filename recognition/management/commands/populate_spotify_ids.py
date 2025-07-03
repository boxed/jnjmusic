from django.core.management.base import BaseCommand
from django.db.models import Q
from recognition.models import Song, Artist
from recognition.spotify_integration import SpotifyIntegration
from src.utils import setup_logger
import time

logger = setup_logger(__name__)


class Command(BaseCommand):
    help = 'Populate Spotify IDs for songs and artists, fetching metadata from Spotify API'

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
        parser.add_argument(
            '--artists-only',
            action='store_true',
            help='Only process artists without Spotify IDs (skip songs)'
        )

    def handle(self, *args, **options):
        batch_size = options['batch_size']
        delay = options['delay']
        force = options['force']
        limit = options['limit']
        artists_only = options['artists_only']
        
        # Initialize Spotify integration
        try:
            spotify = SpotifyIntegration()
        except ValueError as e:
            self.stdout.write(self.style.ERROR(f"Failed to initialize Spotify: {e}"))
            return
        
        # Process artists only if requested
        if artists_only:
            self.process_artists_only(spotify, options)
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
                        
                        # Process artists from the track
                        if 'artists' in track:
                            for spotify_artist in track['artists']:
                                artist_name = spotify_artist['name']
                                artist_id = spotify_artist['id']
                                
                                # Try to find existing artist by name (case-insensitive)
                                artist = Artist.objects.filter(name__iexact=artist_name).first()
                                
                                if not artist:
                                    # Create new artist
                                    artist = Artist.objects.create(name=artist_name)
                                    logger.info(f"Created new artist: {artist_name}")
                                
                                # Update artist with Spotify data if not already populated
                                if not artist.spotify_id or force:
                                    artist.spotify_id = artist_id
                                    
                                    # Get full artist details from Spotify
                                    try:
                                        artist_details = spotify.sp.artist(artist_id)
                                        
                                        # Update artist metadata
                                        if 'genres' in artist_details:
                                            artist.genres = artist_details['genres']
                                        
                                        if 'popularity' in artist_details:
                                            artist.popularity = artist_details['popularity']
                                        
                                        if 'external_urls' in artist_details:
                                            artist.external_urls = artist_details['external_urls']
                                        
                                        artist.save()
                                        logger.info(f"Updated artist '{artist_name}' with Spotify data")
                                        
                                    except Exception as e:
                                        logger.error(f"Error fetching artist details for {artist_name}: {e}")
                                
                                # Link artist to song if not already linked
                                if artist not in song.artist_set.all():
                                    song.artist_set.add(artist)
                                    logger.info(f"Linked artist '{artist_name}' to song '{song.title}'")
                        
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
    
    def process_artists_only(self, spotify, options):
        """Process artists without Spotify IDs."""
        delay = options['delay']
        force = options['force']
        limit = options['limit']
        
        # Get artists to process
        artists_query = Artist.objects.all()
        if not force:
            artists_query = artists_query.filter(Q(spotify_id='') | Q(spotify_id__isnull=True))
        
        if limit:
            artists_query = artists_query[:limit]
        
        total_artists = artists_query.count()
        
        if total_artists == 0:
            self.stdout.write(self.style.SUCCESS("No artists need Spotify IDs"))
            return
        
        self.stdout.write(f"Found {total_artists} artists to process")
        
        success_count = 0
        failed_count = 0
        
        for i, artist in enumerate(artists_query, 1):
            self.stdout.write(f"\rProcessing artist {i}/{total_artists}: {artist.name[:50]}...", ending='')
            
            try:
                # Search for artist on Spotify
                results = spotify.sp.search(q=f"artist:{artist.name}", type='artist', limit=5)
                
                if results['artists']['items']:
                    # Find best match (exact name match preferred)
                    best_match = None
                    for spotify_artist in results['artists']['items']:
                        if spotify_artist['name'].lower() == artist.name.lower():
                            best_match = spotify_artist
                            break
                    
                    # If no exact match, use first result
                    if not best_match:
                        best_match = results['artists']['items'][0]
                    
                    # Update artist with Spotify data
                    artist.spotify_id = best_match['id']
                    
                    if 'genres' in best_match:
                        artist.genres = best_match['genres']
                    
                    if 'popularity' in best_match:
                        artist.popularity = best_match['popularity']
                    
                    if 'external_urls' in best_match:
                        artist.external_urls = best_match['external_urls']
                    
                    artist.save()
                    success_count += 1
                    logger.info(f"Updated artist '{artist.name}' with Spotify ID: {best_match['id']}")
                else:
                    failed_count += 1
                    logger.warning(f"No Spotify match found for artist '{artist.name}'")
                
                # Rate limiting
                time.sleep(delay)
                
            except Exception as e:
                failed_count += 1
                logger.error(f"Error processing artist '{artist.name}': {e}")
        
        # Summary
        self.stdout.write(
            self.style.SUCCESS(
                f"\nCompleted: {success_count} artists updated, {failed_count} failed"
            )
        )
        
        if failed_count > 0:
            remaining = Artist.objects.filter(Q(spotify_id='') | Q(spotify_id__isnull=True)).count()
            self.stdout.write(f"Artists still missing Spotify IDs: {remaining}")