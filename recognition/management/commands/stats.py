from django.core.management.base import BaseCommand
from django.db.models import Count, Q, Avg, F
from rich.console import Console
from rich.table import Table
from recognition.models import YouTubeVideo, RecognitionResult, AudioSegment, Song


class Command(BaseCommand):
    help = 'Display statistics about videos and recognized songs in the database'

    def handle(self, *args, **options):
        console = Console()
        
        # Get statistics
        total_videos = YouTubeVideo.objects.count()
        
        # Get unique songs (distinct Song objects)
        unique_songs = Song.objects.count()
        
        # Total songs detected (all recognition results)
        total_songs_detected = RecognitionResult.objects.count()
        
        # Videos without detected songs
        videos_with_songs = RecognitionResult.objects.values('video').distinct().count()
        videos_without_songs = total_videos - videos_with_songs
        
        # Songs with and without Spotify IDs
        songs_with_spotify_id = Song.objects.exclude(spotify_id='').exclude(spotify_id__isnull=True).count()
        songs_without_spotify_id = unique_songs - songs_with_spotify_id
        
        # Create a nice table for display
        table = Table(title="Music Recognition Database Statistics", show_header=True, header_style="bold magenta")
        table.add_column("Metric", style="cyan", no_wrap=True)
        table.add_column("Count", style="green", justify="right")
        
        table.add_row("Total Videos", str(total_videos))
        table.add_row("Unique Songs Detected", str(unique_songs))
        table.add_row("Total Songs Detected", str(total_songs_detected))
        table.add_row("Videos Without Detected Songs", str(videos_without_songs))
        table.add_row("Songs With Spotify ID", str(songs_with_spotify_id))
        table.add_row("Songs Without Spotify ID", str(songs_without_spotify_id))
        
        console.print(table)
        
        # Additional statistics
        if total_videos > 0:
            percentage_with_songs = (videos_with_songs / total_videos) * 100
            percentage_without_songs = (videos_without_songs / total_videos) * 100
            
            console.print("\n[bold]Additional Insights:[/bold]")
            console.print(f"• {percentage_with_songs:.1f}% of videos have detected songs")
            console.print(f"• {percentage_without_songs:.1f}% of videos have no detected songs")
            
            if total_songs_detected > 0 and videos_with_songs > 0:
                avg_songs_per_video = total_songs_detected / videos_with_songs
                console.print(f"• Average songs per video (with songs): {avg_songs_per_video:.1f}")
            
            if unique_songs > 0:
                spotify_coverage = (songs_with_spotify_id / unique_songs) * 100
                console.print(f"• Spotify ID coverage: {spotify_coverage:.1f}% of detected songs")
        
        # Segment efficiency statistics
        total_segments = AudioSegment.objects.count()
        processed_segments = AudioSegment.objects.filter(processed=True).count()
        
        if total_segments > 0:
            console.print("\n[bold]Segment Processing Efficiency:[/bold]")
            console.print(f"• Total segments created: {total_segments}")
            console.print(f"• Segments processed: {processed_segments}")
            console.print(f"• Processing efficiency: {(processed_segments/total_segments*100):.1f}%")
            
            # Calculate average segments per video
            videos_with_segments = AudioSegment.objects.values('video').distinct().count()
            if videos_with_segments > 0:
                avg_segments_per_video = total_segments / videos_with_segments
                console.print(f"• Average segments per video: {avg_segments_per_video:.1f}")
                
                # Calculate segment efficiency for videos with recognized songs
                videos_with_recognition = RecognitionResult.objects.values('video').distinct()
                segments_for_recognized = AudioSegment.objects.filter(
                    video__in=videos_with_recognition,
                    processed=True
                ).values('video').annotate(count=Count('id')).aggregate(avg=Avg('count'))
                
                if segments_for_recognized['avg']:
                    console.print(f"• Average segments processed to find songs: {segments_for_recognized['avg']:.1f}")