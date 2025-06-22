from django.core.management.base import BaseCommand, CommandError
from django.core.management import call_command
from django.conf import settings
from django.utils import timezone
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.progress import Progress
import time

from recognition.youtube_search import YouTubeSearcher
from recognition.youtube_downloader import YouTubeDownloader
from recognition.models import YouTubeVideo, RecognitionSession
from src.utils import setup_logger

console = Console()
logger = setup_logger(__name__)


class Command(BaseCommand):
    help = 'Automatically discover and process J&J WCS videos'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--days-back',
            type=int,
            default=30,
            help='Number of days back to search for videos'
        )
        
        parser.add_argument(
            '--years',
            type=int,
            default=5,
            help='Number of years back to search for videos (default: 5)'
        )
        
        parser.add_argument(
            '--max-videos',
            type=int,
            default=50,
            help='Maximum number of videos to process'
        )
        
        parser.add_argument(
            '--service',
            type=str,
            default='shazamkit',
            choices=['acrcloud', 'shazamkit'],
            help='Recognition service to use'
        )
        
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be processed without actually doing it'
        )
        
        parser.add_argument(
            '--channels',
            action='store_true',
            help='Also search popular WCS channels'
        )
        
        parser.add_argument(
            '--continuous',
            action='store_true',
            help='Run continuously, checking for new videos periodically'
        )
        
        parser.add_argument(
            '--interval',
            type=int,
            default=3600,
            help='Interval between checks in seconds (for continuous mode)'
        )
    
    def handle(self, *args, **options):
        console.print("[bold blue]J&J WCS Auto Discovery System[/bold blue]")
        console.print(f"Searching for videos from the last {options['days_back']} days and {options['years']} years\n")
        
        if options['continuous']:
            self.run_continuous(options)
        else:
            self.run_once(options)
    
    def run_once(self, options):
        """Run the discovery and processing once."""
        try:
            # Discover videos
            discovered_urls = self.discover_videos(options)
            
            if not discovered_urls:
                console.print("[bold yellow]No NEW videos found to process[/bold yellow]")
                console.print("[dim]All recent videos have already been discovered[/dim]")
                return
                
            if options['dry_run']:
                console.print(f"[cyan]Would process {len(discovered_urls)} videos:[/cyan]")
                for url in discovered_urls[:10]:
                    console.print(f"  • {url}")
                if len(discovered_urls) > 10:
                    console.print(f"  ... and {len(discovered_urls) - 10} more")
                return
            
            # Process videos
            self.process_videos(discovered_urls, options)
            
        except Exception as e:
            import traceback
            logger.error(f"Error in auto discovery: {e}")
            logger.error("Full stack trace:")
            traceback.print_exc()
            raise CommandError(f"Auto discovery failed: {e}")
    
    def run_continuous(self, options):
        """Run continuously, checking for new videos periodically."""
        console.print(f"[green]Running in continuous mode, checking every {options['interval']} seconds[/green]\n")
        
        while True:
            try:
                console.print(f"\n[bold]Check started at {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}[/bold]")
                self.run_once(options)
                
                console.print(f"\n[dim]Sleeping for {options['interval']} seconds...[/dim]")
                time.sleep(options['interval'])
                
            except KeyboardInterrupt:
                console.print("\n[red]Stopped by user[/red]")
                break
            except Exception as e:
                import traceback
                logger.error(f"Error in continuous mode: {e}")
                logger.error("Full stack trace:")
                traceback.print_exc()
                console.print(f"[red]Error: {e}[/red]")
                console.print(f"[dim]Retrying in {options['interval']} seconds...[/dim]")
                time.sleep(options['interval'])
    
    def discover_videos(self, options) -> list:
        """Discover new videos to process."""
        searcher = YouTubeSearcher()
        discovered_urls = []
        
        console.print("[cyan]Searching for new J&J WCS videos...[/cyan]")
        
        # Search with queries
        urls = searcher.discover_new_videos(days_back=options['days_back'], year_range=options['years'])
        query_new_count = len(urls)
        discovered_urls.extend(urls)
        console.print(f"[green]Found {query_new_count} NEW videos from search queries[/green]")
        
        # Search channels if requested
        channel_new_count = 0
        if options['channels']:
            console.print("\n[cyan]Searching popular WCS channels...[/cyan]")
            channels = searcher.get_popular_wcs_channels()
            
            for channel in channels:
                try:
                    channel_urls = searcher.search_by_channel(channel, max_results=20)
                    if channel_urls:
                        channel_new_count += len(channel_urls)
                        console.print(f"  • {channel.split('/')[-1]}: {len(channel_urls)} NEW videos")
                    discovered_urls.extend(channel_urls)
                except Exception as e:
                    import traceback
                    logger.warning(f"Error searching channel {channel}: {e}")
                    logger.warning("Full stack trace:")
                    traceback.print_exc()
            
            if channel_new_count > 0:
                console.print(f"[green]Found {channel_new_count} NEW videos from channels[/green]")
        
        # Remove duplicates
        original_count = len(discovered_urls)
        discovered_urls = list(set(discovered_urls))
        duplicate_count = original_count - len(discovered_urls)
        
        if duplicate_count > 0:
            console.print(f"[yellow]Removed {duplicate_count} duplicate URLs[/yellow]")
        
        # Limit to max videos
        if len(discovered_urls) > options['max_videos']:
            console.print(f"[yellow]Limiting to {options['max_videos']} videos (from {len(discovered_urls)} found)[/yellow]")
            discovered_urls = discovered_urls[:options['max_videos']]
        
        console.print(f"\n[bold green]Total: {len(discovered_urls)} NEW videos to process[/bold green]")
        return discovered_urls
    
    def process_videos(self, urls: list, options):
        """Download and process videos for music recognition."""
        # Create session
        session_name = f"Auto Discovery {timezone.now().strftime('%Y-%m-%d %H:%M')}"
        session = RecognitionSession.objects.create(
            name=session_name,
            service=options['service'],
            segment_length=30,
            overlap=5
        )
        
        console.print(f"\n[bold]Processing {len(urls)} videos[/bold]")
        
        try:
            # Download videos
            downloader = YouTubeDownloader()
            videos = downloader.download_batch(urls, session)
            
            if not videos:
                console.print("[yellow]No videos were successfully downloaded[/yellow]")
                session.status = 'failed'
                session.error_message = "No videos downloaded"
                session.save()
                return
            
            console.print(f"[green]Downloaded {len(videos)} videos[/green]")
            
            # Process with recognize_music command
            video_urls = [video.url for video in videos]
            
            console.print("\n[cyan]Starting music recognition...[/cyan]")
            call_command(
                'recognize_music',
                *video_urls,
                service=options['service'],
                no_download=True,  # Videos already downloaded
                session_name=session_name
            )
            
            # Update session
            session.refresh_from_db()
            console.print(f"\n[bold green]✓ Processing complete![/bold green]")
            console.print(f"Videos processed: {session.videos_processed}")
            console.print(f"Songs recognized: {session.songs_recognized}")
            
            # Show summary table
            self.show_summary(videos)
            
        except Exception as e:
            import traceback
            session.status = 'failed'
            session.error_message = str(e)
            session.save()
            logger.error(f"Error processing videos: {e}")
            logger.error("Full stack trace:")
            traceback.print_exc()
            raise
    
    def show_summary(self, videos):
        """Show a summary of processed videos."""
        table = Table(title="Processed Videos Summary")
        table.add_column("Video", style="cyan", width=50)
        table.add_column("Duration", style="green")
        table.add_column("Songs Found", style="yellow")
        
        for video in videos[:10]:  # Show first 10
            recognition_count = video.recognition_results.count()
            duration_str = f"{video.duration // 60}:{video.duration % 60:02d}" if video.duration else "N/A"
            table.add_row(
                video.title[:47] + "..." if len(video.title) > 50 else video.title,
                duration_str,
                str(recognition_count)
            )
        
        if len(videos) > 10:
            table.add_row("...", "...", "...")
            
        console.print(table)