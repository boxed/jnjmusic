from django.core.management.base import BaseCommand
from django.db.models import Count
from rich.console import Console
from rich.table import Table

from recognition.models import RecognitionSession, RecognitionResult

console = Console()


class Command(BaseCommand):
    help = 'Manage recognition sessions'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--list',
            action='store_true',
            help='List all sessions'
        )
        
        parser.add_argument(
            '--show',
            type=int,
            metavar='SESSION_ID',
            help='Show details of a specific session'
        )
        
        parser.add_argument(
            '--export',
            type=int,
            metavar='SESSION_ID',
            help='Export results from a session'
        )
        
        parser.add_argument(
            '--format',
            type=str,
            choices=['csv', 'json'],
            default='csv',
            help='Export format (default: csv)'
        )
        
        parser.add_argument(
            '--delete',
            type=int,
            metavar='SESSION_ID',
            help='Delete a session and its results'
        )
    
    def handle(self, *args, **options):
        if options['list']:
            self.list_sessions()
        elif options['show']:
            self.show_session(options['show'])
        elif options['export']:
            self.export_session(options['export'], options['format'])
        elif options['delete']:
            self.delete_session(options['delete'])
        else:
            self.list_sessions()
    
    def list_sessions(self):
        """List all recognition sessions."""
        sessions = RecognitionSession.objects.annotate(
            result_count=Count('recognitionresult')
        ).order_by('-started_at')
        
        if not sessions:
            console.print("[yellow]No sessions found[/yellow]")
            return
        
        table = Table(title="Recognition Sessions")
        table.add_column("ID", style="cyan")
        table.add_column("Name", style="green")
        table.add_column("Started", style="blue")
        table.add_column("Status", style="magenta")
        table.add_column("Videos", style="yellow")
        table.add_column("Songs", style="white")
        table.add_column("Service", style="cyan")
        
        for session in sessions:
            status_color = {
                'pending': 'yellow',
                'processing': 'blue',
                'completed': 'green',
                'failed': 'red'
            }.get(session.status, 'white')
            
            table.add_row(
                str(session.id),
                session.name or "-",
                session.started_at.strftime("%Y-%m-%d %H:%M"),
                f"[{status_color}]{session.status}[/{status_color}]",
                str(session.videos_processed),
                str(session.songs_recognized),
                session.service
            )
        
        console.print(table)
    
    def show_session(self, session_id):
        """Show details of a specific session."""
        try:
            session = RecognitionSession.objects.get(id=session_id)
        except RecognitionSession.DoesNotExist:
            console.print(f"[red]Session {session_id} not found[/red]")
            return
        
        # Session info
        console.print(f"\n[bold]Session #{session.id}[/bold]")
        console.print(f"Name: {session.name or 'Unnamed'}")
        console.print(f"Started: {session.started_at}")
        console.print(f"Status: {session.status}")
        console.print(f"Service: {session.service}")
        console.print(f"Videos processed: {session.videos_processed}")
        console.print(f"Songs recognized: {session.songs_recognized}")
        
        if session.error_message:
            console.print(f"[red]Error: {session.error_message}[/red]")
        
        # Get results for this session
        results = RecognitionResult.objects.filter(
            video__recognitionsession=session
        ).select_related('video').order_by('video', 'timestamp_start')
        
        if results:
            console.print(f"\n[bold]Recognition Results:[/bold]")
            
            current_video = None
            for result in results:
                if result.video != current_video:
                    current_video = result.video
                    console.print(f"\n[cyan]{current_video.title}[/cyan]")
                
                console.print(
                    f"  [{result.timestamp_start:.1f}s] "
                    f"[green]{result.title}[/green] by "
                    f"[blue]{result.artists_display}[/blue]"
                )
    
    def export_session(self, session_id, format):
        """Export results from a session."""
        try:
            session = RecognitionSession.objects.get(id=session_id)
        except RecognitionSession.DoesNotExist:
            console.print(f"[red]Session {session_id} not found[/red]")
            return
        
        results = RecognitionResult.objects.filter(
            video__recognitionsession=session
        ).select_related('video')
        
        if not results:
            console.print("[yellow]No results to export[/yellow]")
            return
        
        from pathlib import Path
        from django.conf import settings
        from recognition.export import export_results
        
        filename = f"session_{session_id}_results.{format}"
        filepath = Path(settings.DATA_DIR) / filename
        
        export_results(results, filepath, format)
        console.print(f"[green]Results exported to: {filepath}[/green]")
    
    def delete_session(self, session_id):
        """Delete a session and its results."""
        try:
            session = RecognitionSession.objects.get(id=session_id)
        except RecognitionSession.DoesNotExist:
            console.print(f"[red]Session {session_id} not found[/red]")
            return
        
        # Confirm deletion
        result_count = RecognitionResult.objects.filter(
            video__recognitionsession=session
        ).count()
        
        console.print(f"[yellow]This will delete session #{session_id} and {result_count} results.[/yellow]")
        confirm = console.input("Are you sure? (y/N): ")
        
        if confirm.lower() == 'y':
            session.delete()
            console.print(f"[green]Session {session_id} deleted[/green]")
        else:
            console.print("[yellow]Deletion cancelled[/yellow]")