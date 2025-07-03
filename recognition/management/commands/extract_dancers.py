import re
from django.core.management.base import BaseCommand
from django.db import transaction
from recognition.models import YouTubeVideo, Dancer


class Command(BaseCommand):
    help = 'Extract dancer names from YouTube video titles'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be done without making changes'
        )

    def extract_dancers_from_title(self, title):
        """Extract two dancer names from a video title."""
        # First, explicitly check if title contains "Jack & Jill" or "J&J"
        if re.search(r'\bJack\s*&\s*Jill\b|\bJ&J\b', title, re.I):
            # Remove these terms from consideration
            title_cleaned = re.sub(r'\bJack\s*&\s*Jill\b|\bJ&J\b', '', title, flags=re.I)
        else:
            title_cleaned = title
            
        # Try to find names after common separators
        # Look for patterns like "| Name & Name" or "- Name & Name"
        separator_patterns = [
            r'(?:\||-)(?:[^|]*\|)*\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s*(?:&|and)\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)',
            r'(?:^|[|])([^|]+)\|\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s*(?:&|and)\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s*$',
        ]
        
        # Check the end of title first (most common location for dancer names)
        end_match = re.search(r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s*(?:&|and)\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)(?:\s*[-–]|\s*$)', title_cleaned)
        if end_match:
            # Found names at the end
            name1 = end_match.group(1).strip()
            name2 = end_match.group(2).strip()
            
            # Basic validation
            non_names = {'West', 'Coast', 'Swing', 'Dance', 'Open', 'Classic', 'Asia'}
            if (name1 not in non_names and name2 not in non_names and
                len(name1) > 2 and len(name2) > 2 and 
                name1 != "Jack" and name2 != "Jill"):
                return [name1, name2]
        
        # Try patterns after song titles in quotes
        quote_pattern = r'"[^"]+"\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s*(?:&|and)\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)'
        quote_match = re.search(quote_pattern, title)
        if quote_match:
            name1 = quote_match.group(1).strip()
            name2 = quote_match.group(2).strip()
            if len(name1) > 2 and len(name2) > 2:
                return [name1, name2]
        
        # Look for full names pattern anywhere in the title
        full_name_pattern = r'([A-Z][a-z]+\s+[A-Z][a-z]+)\s*(?:&|and)\s*([A-Z][a-z]+\s+[A-Z][a-z]+)'
        full_match = re.search(full_name_pattern, title_cleaned)
        if full_match:
            name1 = full_match.group(1).strip()
            name2 = full_match.group(2).strip()
            # Exclude common false positives
            exclude_phrases = ['West Coast', 'Costa Rica', 'Los Angeles', 'New York', 'San Francisco']
            if not any(phrase in name1 or phrase in name2 for phrase in exclude_phrases):
                return [name1, name2]
        
        return []

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        
        videos = YouTubeVideo.objects.all()
        self.stdout.write(f"Processing {videos.count()} videos...")
        
        dancers_created = 0
        videos_updated = 0
        
        with transaction.atomic():
            for video in videos:
                dancer_names = self.extract_dancers_from_title(video.title)
                
                if len(dancer_names) == 2:
                    if dry_run:
                        self.stdout.write(f"Would extract from '{video.title}': {dancer_names[0]} & {dancer_names[1]}")
                    else:
                        dancers = []
                        for name in dancer_names:
                            dancer, created = Dancer.objects.get_or_create(
                                name=name
                            )
                            if created:
                                dancers_created += 1
                                self.stdout.write(self.style.SUCCESS(f"Created dancer: {name}"))
                            dancers.append(dancer)
                        
                        video.dancers.set(dancers)
                        videos_updated += 1
                        self.stdout.write(f"Updated video '{video.title}' with dancers: {', '.join(dancer_names)}")
        
        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run completed. No changes were made."))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"Completed! Created {dancers_created} dancers and updated {videos_updated} videos."
            ))