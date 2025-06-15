from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.progress import Progress

from src.music_recognition import get_recognizer
from recognition.models import YouTubeVideo, RecognitionResult, RecognitionSession
from recognition.youtube_downloader import YouTubeDownloader
from recognition.audio_processor import AudioProcessor

console = Console()


class Command(BaseCommand):
    help = 'Recognize music from YouTube videos'
    
    def add_arguments(self, parser):
        parser.add_argument(
            'urls',
            nargs='+',
            type=str,
            help='YouTube video URLs or playlist URLs'
        )
        
        parser.add_argument(
            '--service',
            type=str,
            default='acrcloud',
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
    
    def handle(self, *args, **options):
        urls = options['urls']
        service = options['service']
        
        # Create session
        session = RecognitionSession.objects.create(
            name=options.get('session_name', ''),
            service=service,
            segment_length=options['segment_length'],
            overlap=options['overlap']
        )
        
        try:
            # Initialize components
            downloader = YouTubeDownloader()
            processor = AudioProcessor()
            recognizer = get_recognizer(service)
            
            # Override settings if provided
            if options['segment_length']:
                settings.AUDIO_SEGMENT_LENGTH = options['segment_length']
            if options['overlap']:
                settings.AUDIO_OVERLAP = options['overlap']
            
            # Download videos
            videos = []
            if not options['no_download']:
                console.print("[bold blue]Downloading audio from YouTube...[/bold blue]")
                videos = downloader.download_batch(urls, session)
            else:
                # Get existing videos
                for url in urls:
                    video = YouTubeVideo.objects.filter(url=url).first()
                    if video:
                        videos.append(video)
            
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
                    
                    for segment in segments:
                        result = recognizer.identify(Path(segment.file_path))
                        
                        if result:
                            # Save recognition result
                            recognition = RecognitionResult.objects.create(
                                video=video,
                                timestamp_start=segment.start_time,
                                timestamp_end=segment.end_time,
                                title=result['title'],
                                artists=result['artists'],
                                album=result.get('album', ''),
                                duration_ms=result.get('duration_ms', 0),
                                confidence_score=result.get('score', 0),
                                spotify_id=result.get('spotify_id', ''),
                                external_ids=result.get('external_ids', {}),
                                genres=result.get('genres', []),
                                release_date=result.get('release_date', ''),
                                service=service,
                                raw_result=result.get('raw_result')
                            )
                            
                            all_results.append(recognition)
                            session.songs_recognized += 1
                            
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
            session.status = 'failed'
            session.error_message = str(e)
            session.save()
            raise CommandError(f"Recognition failed: {e}")
    
    def display_results(self, results):
        """Display recognition results in a table."""
        if not results:
            console.print("[yellow]No songs recognized[/yellow]")
            return
        
        table = Table(title="Recognition Results")
        table.add_column("Time", style="cyan")
        table.add_column("Title", style="green")
        table.add_column("Artists", style="blue")
        table.add_column("Album", style="magenta")
        table.add_column("Confidence", style="yellow")
        
        for result in results:
            table.add_row(
                f"{result.timestamp_start:.1f}s",
                result.title,
                result.artists_display,
                result.album or "-",
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