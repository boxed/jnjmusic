from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from django.utils import timezone
from django.db import models
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.progress import Progress

from src.music_recognition import get_recognizer
from recognition.models import YouTubeVideo, RecognitionResult, RecognitionSession, Song
from recognition.youtube_downloader import YouTubeDownloader
from recognition.audio_processor import AudioProcessor
from recognition.optimized_audio_processor import OptimizedAudioProcessor
from recognition.youtube_search import YouTubeSearcher

console = Console()


class Command(BaseCommand):
    help = 'Recognize music from YouTube videos. If no URLs provided, processes all unprocessed videos.'
    
    def add_arguments(self, parser):
        parser.add_argument(
            'urls',
            nargs='*',
            type=str,
            help='YouTube video URLs or playlist URLs. If omitted, processes all unprocessed videos.'
        )
        
        parser.add_argument(
            '--service',
            type=str,
            default='shazamkit',
            choices=['acrcloud', 'shazamkit'],
            help='Recognition service to use'
        )
        
        parser.add_argument(
            '--segment-length',
            type=int,
            default=30,
            help='Audio segment length in seconds'
        )
        
        parser.add_argument(
            '--overlap',
            type=int,
            default=5,
            help='Overlap between segments in seconds'
        )
        
        parser.add_argument(
            '--no-download',
            action='store_true',
            help='Skip downloading, use existing files'
        )
        
        
        parser.add_argument(
            '--export',
            type=str,
            choices=['csv', 'json'],
            help='Export results to file'
        )
        
        parser.add_argument(
            '--session-name',
            type=str,
            help='Name for this recognition session'
        )
        
        parser.add_argument(
            '--reprocess-empty',
            action='store_true',
            help='Reprocess videos that have been processed but have no recognized songs'
        )
        
        parser.add_argument(
            '--sequential',
            action='store_true',
            help='Use sequential segment processing instead of the default optimized strategy'
        )
    
    def handle(self, *args, **options):
        urls = options['urls']
        service = options['service']
        
        # If no URLs provided, get all unprocessed videos
        if not urls:
            if options.get('reprocess_empty'):
                # Get videos that have audio but no recognition results
                from django.db.models import Count
                videos_to_process = YouTubeVideo.objects.annotate(
                    recognition_count=Count('recognition_results')
                ).filter(
                    error='',
                    recognition_count=0
                ).exclude(
                    audio_file_path=''
                )
                if not videos_to_process.exists():
                    console.print("[yellow]No videos without recognized songs found in database[/yellow]")
                    return
                console.print(f"[bold blue]Found {videos_to_process.count()} videos without recognized songs to reprocess[/bold blue]")
            else:
                # Only get videos that haven't been processed yet
                videos_to_process = YouTubeVideo.objects.filter(
                    processed=False,
                    error=''
                ).exclude(
                    audio_file_path=''
                )
                if not videos_to_process.exists():
                    console.print("[yellow]No unprocessed videos found in database[/yellow]")
                    return
                console.print(f"[bold blue]Found {videos_to_process.count()} unprocessed videos[/bold blue]")
        
        # Create session
        session_name = options.get('session_name') or f"Recognition {timezone.now().strftime('%Y-%m-%d %H:%M')}"
        session = RecognitionSession.objects.create(
            name=session_name,
            service=service,
            segment_length=options['segment_length'],
            overlap=options['overlap']
        )
        
        try:
            # Initialize components
            downloader = YouTubeDownloader()
            processor = AudioProcessor() if options.get('sequential') else OptimizedAudioProcessor()
            recognizer = get_recognizer(service)
            searcher = YouTubeSearcher()
            
            # Override settings if provided
            if options['segment_length']:
                settings.AUDIO_SEGMENT_LENGTH = options['segment_length']
            if options['overlap']:
                settings.AUDIO_OVERLAP = options['overlap']
            
            # Download videos or use existing ones
            videos = []
            if urls:
                # Process specific URLs
                if not options['no_download']:
                    console.print("[bold blue]Downloading audio from YouTube...[/bold blue]")
                    videos = downloader.download_batch(urls, session)
                else:
                    # Get existing videos
                    for url in urls:
                        video = YouTubeVideo.objects.filter(url=url).first()
                        if video:
                            videos.append(video)
            else:
                # Process all unprocessed videos
                videos = list(videos_to_process)
            
            if not videos:
                raise CommandError("No videos to process")
            
            session.status = 'processing'
            session.save()
            
            # Process each video
            all_results = []
            
            with Progress() as progress:
                task = progress.add_task("[cyan]Processing videos...", total=len(videos))
                
                for video in videos:
                    console.print(f"\n[bold]Processing: {video.title}[/bold]")
                    
                    # Detect event and edition from video
                    edition = None
                    event_edition = searcher.detect_event_and_edition(
                        video.title, 
                        video.description if hasattr(video, 'description') else ""
                    )
                    if event_edition:
                        event, edition = event_edition
                        console.print(f"[green]Detected event: {event.name} - Edition: {edition}[/green]")
                    
                    if not options.get('sequential'):
                        # Use optimized processing (default)
                        console.print("[cyan]Using optimized segment sampling strategy[/cyan]")
                        
                        results = processor.process_video_optimized(video, recognizer, max_songs=2)
                        
                        for result_data in results:
                            result = result_data['result']
                            segment = result_data['segment']
                            
                            # First, create or get the Song
                            song, song_created = Song.objects.get_or_create(
                                title=result['title'],
                                spotify_id=result.get('spotify_id') or '',
                                defaults={
                                    'album': result.get('album') or '',
                                    'duration_ms': result.get('duration_ms', 0),
                                    'isrc': result.get('isrc') or '',
                                    'external_ids': result.get('external_ids', {}),
                                    'genres': result.get('genres', []),
                                    'release_date': result.get('release_date') or '',
                                    'label': result.get('label') or '',
                                }
                            )
                            
                            # Save recognition result
                            recognition, created = RecognitionResult.objects.get_or_create(
                                video=video,
                                song=song,
                                timestamp_start=segment.start_time,
                                defaults={
                                    'timestamp_end': segment.end_time,
                                    'confidence_score': result.get('score', 0),
                                    'service': service,
                                    'raw_result': result.get('raw_result'),
                                    'edition': edition
                                }
                            )
                            
                            all_results.append(recognition)
                            if created:
                                session.songs_recognized += 1
                                
                        # Clean up any unprocessed segments
                        processor.cleanup_unprocessed_segments(video)
                        
                    else:
                        # Use standard sequential processing
                        console.print("[yellow]Using sequential segment processing[/yellow]")
                        # Split audio into segments
                        segments = processor.process_video(video)
                        
                        if not segments:
                            console.print(f"[red]Failed to process audio for {video.title}[/red]")
                            continue
                        
                        # Recognize each segment
                        segment_task = progress.add_task(
                            f"[green]Recognizing {len(segments)} segments...", 
                            total=len(segments)
                        )
                        
                        songs_found_in_video = 0
                        
                        for segment in segments:
                            result = recognizer.identify(Path(segment.file_path))
                            
                            if result:
                                # First, create or get the Song
                                song, song_created = Song.objects.get_or_create(
                                    title=result['title'],
                                    spotify_id=result.get('spotify_id') or '',
                                    defaults={
                                        'album': result.get('album') or '',
                                        'duration_ms': result.get('duration_ms', 0),
                                        'isrc': result.get('isrc') or '',
                                        'external_ids': result.get('external_ids', {}),
                                        'genres': result.get('genres', []),
                                        'release_date': result.get('release_date') or '',
                                        'label': result.get('label') or '',
                                    }
                                )
                                
                                # Save recognition result
                                recognition, created = RecognitionResult.objects.get_or_create(
                                    video=video,
                                    song=song,
                                    timestamp_start=segment.start_time,
                                    defaults={
                                        'timestamp_end': segment.end_time,
                                        'confidence_score': result.get('score', 0),
                                        'service': service,
                                        'raw_result': result.get('raw_result'),
                                        'edition': edition
                                    }
                                )
                                
                                all_results.append(recognition)
                                if created:
                                    session.songs_recognized += 1
                                    songs_found_in_video += 1
                                
                                # Stop after finding 2 songs in this video
                                if songs_found_in_video >= 2:
                                    console.print(f"[yellow]Found 2 songs in video, skipping remaining segments[/yellow]")
                                    # Mark remaining segments as processed
                                    remaining_segments = segments[segments.index(segment)+1:]
                                    for remaining_segment in remaining_segments:
                                        remaining_segment.processed = True
                                        remaining_segment.save()
                                        progress.update(segment_task, advance=1)
                                    break
                                
                            segment.processed = True
                            segment.save()
                            
                            progress.update(segment_task, advance=1)
                    
                    video.processed = True
                    video.save()
                    
                    progress.update(task, advance=1)
            
            # Complete session
            session.status = 'completed'
            session.save()
            
            # Display results
            self.display_results(all_results)
            
            # Export if requested
            if options['export']:
                self.export_results(all_results, options['export'])
            
            console.print(f"\n[bold green]✓ Recognition complete![/bold green]")
            console.print(f"Videos processed: {len(videos)}")
            console.print(f"Songs recognized: {len(all_results)}")
            
        except Exception as e:
            import traceback
            session.status = 'failed'
            session.error_message = str(e)
            session.save()
            console.print("[red]Full stack trace:[/red]")
            traceback.print_exc()
            raise CommandError(f"Recognition failed: {e}")
    
    def display_results(self, results):
        """Display recognition results in a table."""
        if not results:
            console.print("[yellow]No songs recognized[/yellow]")
            return
        
        # If results is a list, we need to optimize the queries
        if isinstance(results, list) and results:
            # Prefetch related data to avoid N+1 queries
            from django.db.models import Prefetch
            result_ids = [r.id for r in results]
            results = RecognitionResult.objects.filter(id__in=result_ids).select_related('song').prefetch_related('song__artist_set')
        
        table = Table(title="Recognition Results")
        table.add_column("Time", style="cyan")
        table.add_column("Title", style="green")
        table.add_column("Artists", style="blue")
        table.add_column("Album", style="magenta")
        table.add_column("Confidence", style="yellow")
        
        for result in results:
            artists = ', '.join([artist.name for artist in result.song.artist_set.all()]) if result.song.artist_set.exists() else 'Unknown Artist'
            table.add_row(
                f"{result.timestamp_start:.1f}s",
                result.song.title,
                artists,
                result.song.album or "-",
                f"{result.confidence_score:.0f}%"
            )
        
        console.print(table)
    
    def export_results(self, results, format):
        """Export results to file."""
        from recognition.export import export_results
        
        filename = f"recognition_results_{RecognitionSession.objects.latest('started_at').id}.{format}"
        filepath = Path(settings.DATA_DIR) / filename
        
        export_results(results, filepath, format)
        console.print(f"\n[green]Results exported to: {filepath}[/green]")