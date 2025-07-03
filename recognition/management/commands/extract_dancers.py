import re
from django.core.management.base import BaseCommand
from django.db import transaction
from recognition.models import YouTubeVideo, Dancer


class Command(BaseCommand):
    help = 'Extract dancer names from YouTube video titles'
    
    # Competition-related terms that should not be treated as dancer names
    competition_terms = {'Advanced', 'Allstar', 'Final', 'Finals', 'All-skate', 'Showcase', 
                       'Spotlight', 'Semifinals', 'Novice', 'Intermediate', 'Pro', 'Amateur',
                       'Division', 'Competition', 'Contest', 'Championship', 'Champions',
                       'Invitational', 'Prelims', 'Preliminaries', 'Round', 'Heat'}

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be done without making changes'
        )

    def extract_dancers_from_description(self, description):
        """Extract two dancer names from video description by checking each line."""
        if not description:
            return []
            
        # Remove "Jack & Jill" and "Jack and Jill" from description to avoid false matches
        # Also remove lines that are competition descriptions
        description_cleaned = re.sub(r'\bJack\s*(?:&|and)\s*Jill\b', '', description, flags=re.I)
        # Remove common competition lines entirely
        description_cleaned = re.sub(r'^.*(?:Staff|Novice|Advanced|Pro|Amateur|Masters?|All[- ]?Star|Open)\s+.*(?:Finals?|Competition|Contest).*$', '', description_cleaned, flags=re.I | re.M)
        
        # First try to find names connected with & or and on the same line
        lines = description_cleaned.split('\n')
        for line in lines:
            # Skip empty lines
            if not line.strip():
                continue
                
            # Look for patterns like "Name & Name" or "Name and Name" in each line
            patterns = [
                r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s*(?:&|and)\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)',
                r'([A-Z][a-z]+\s+[A-Z][a-z]+)\s*(?:&|and)\s*([A-Z][a-z]+\s+[A-Z][a-z]+)'
            ]
            
            for pattern in patterns:
                match = re.search(pattern, line)
                if match:
                    name1 = match.group(1).strip()
                    name2 = match.group(2).strip()
                    
                    # Basic validation - expanded list of non-names
                    non_names = {'West', 'Coast', 'Swing', 'Dance', 'Open', 'Classic', 'Asia', 'Jack', 'Jill',
                                'Ballroom', 'Facebook', 'Instagram', 'Youtube', 'Twitter', 'Social', 'Media',
                                'Country', 'Videos', 'World', 'Rock', 'Roll', 'Confederation', 'International',
                                'Hustle', 'Salsa', 'Competition', 'Championships', 'Korean', 'Asian', 'European',
                                'American', 'Latin', 'Lindy', 'Hop', 'Balboa', 'Blues', 'Tango', 'Foxtrot',
                                'Down', 'Out', 'Up', 'In', 'Staff', 'Finals', 'Final', 'Song', 'Music', 'Track'}
                    name1_words = set(name1.split())
                    name2_words = set(name2.split())
                    
                    if (name1 not in non_names and name2 not in non_names and
                        name1 not in self.competition_terms and name2 not in self.competition_terms and
                        not name1_words.issubset(self.competition_terms) and
                        not name2_words.issubset(self.competition_terms) and
                        not name1_words.issubset(non_names) and
                        not name2_words.issubset(non_names) and
                        len(name1) > 2 and len(name2) > 2):
                        return [name1, name2]
        
        # If no paired names found, look for individual names on separate lines
        # Pattern for full names (First Last) - more flexible with case
        name_pattern = r'^([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)+)\s*$'
        potential_names = []
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            match = re.match(name_pattern, line)
            if match:
                name = match.group(1)
                # Validate it's not a known non-name phrase
                non_name_phrases = {'West Coast', 'West Coast Swing', 'Costa Rica', 'Los Angeles', 'New York', 
                           'San Francisco', 'Atlanta Swing Classic', 'Asia WCS Open', 'Sea to Sky',
                           'Professional Jack', 'All Star Jack', 'Staff Jack', 'Improv dance',
                           'Seattle Swing', 'Swing Dance', 'Dance Club', 'Dance Competition'}
                non_names = {'West', 'Coast', 'Swing', 'Dance', 'Open', 'Classic', 'Asia', 'Jack', 'Jill',
                            'Ballroom', 'Facebook', 'Instagram', 'Youtube', 'Twitter', 'Social', 'Media',
                            'Country', 'Videos', 'World', 'Rock', 'Roll', 'Confederation', 'International',
                            'Hustle', 'Salsa', 'Competition', 'Championships', 'Korean', 'Asian', 'European',
                            'American', 'Latin', 'Lindy', 'Hop', 'Balboa', 'Blues', 'Tango', 'Foxtrot',
                            'Down', 'Out', 'Up', 'In', 'Staff', 'Finals', 'Final', 'Song', 'Music', 'Track'}
                name_words = set(name.split())
                
                # Additional validation - should have exactly 2 words for most names
                if (name not in non_name_phrases and 
                    not name_words.issubset(self.competition_terms) and
                    not name_words.issubset(non_names) and
                    len(name.split()) >= 2 and len(name.split()) <= 3 and  # 2-3 words
                    len(name) > 5 and len(name) < 30):  # Reasonable length
                    potential_names.append(name)
                    
                    # Return the first two valid names found
                    if len(potential_names) == 2:
                        return potential_names
        
        return []

    def extract_dancers_from_title(self, title):
        """Extract two dancer names from a video title."""
        # Remove all variations of "Jack & Jill", "Jack and Jill", and "J&J" from the title
        title_cleaned = re.sub(r'\bJack\s*(?:&|and)\s*Jill\b|\bJ&J\b', '', title, flags=re.I)
        
        # Also remove common competition phrases that might contain "Jack"
        title_cleaned = re.sub(r'\b(?:Advanced|Allstar|All Star|Novice|Intermediate|Pro|Amateur|Masters?|Open|Staff)\s+(?:Jack|West Coast Swing Jack)\b', '', title_cleaned, flags=re.I)
            
        # Remove competition terms from the title to avoid false matches
        for term in self.competition_terms:
            title_cleaned = re.sub(r'\b' + term + r'\b', '', title_cleaned, flags=re.I)
            
        # Try to find names after common separators
        # Look for patterns like "| Name & Name" or "- Name & Name"
        separator_patterns = [
            r'(?:\||-)(?:[^|]*\|)*\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s*(?:&|and)\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)',
            r'(?:^|[|])([^|]+)\|\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s*(?:&|and)\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s*$',
        ]
        
        # Check the end of title first (most common location for dancer names)
        # More restrictive pattern to avoid matching competition terms
        end_match = re.search(r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s*(?:&|and)\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)(?:\s*[-–]|\s*$)', title_cleaned)
        if end_match:
            # Found names at the end
            name1 = end_match.group(1).strip()
            name2 = end_match.group(2).strip()
            
            # Basic validation - expanded list of non-names
            non_names = {'West', 'Coast', 'Swing', 'Dance', 'Open', 'Classic', 'Asia', 'Jack', 'Jill',
                        'Ballroom', 'Facebook', 'Instagram', 'Youtube', 'Twitter', 'Social', 'Media',
                        'Country', 'Videos', 'World', 'Rock', 'Roll', 'Confederation', 'International',
                        'Hustle', 'Salsa', 'Competition', 'Championships', 'Korean', 'Asian', 'European',
                        'American', 'Latin', 'Lindy', 'Hop', 'Balboa', 'Blues', 'Tango', 'Foxtrot',
                        'Down', 'Out', 'Up', 'In', 'Staff', 'Finals', 'Final', 'Song', 'Music', 'Track'}
            
            # Check if either name is a competition term or contains only competition terms
            name1_words = set(name1.split())
            name2_words = set(name2.split())
            
            if (name1 not in non_names and name2 not in non_names and
                name1 not in self.competition_terms and name2 not in self.competition_terms and
                not name1_words.issubset(self.competition_terms) and
                not name2_words.issubset(self.competition_terms) and
                not name1_words.issubset(non_names) and
                not name2_words.issubset(non_names) and
                not name1.endswith('Jack') and not name2.startswith('Jill') and
                len(name1) > 2 and len(name2) > 2):
                return [name1, name2]
        
        # Try patterns after song titles in quotes
        quote_pattern = r'"[^"]+"\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s*(?:&|and)\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)'
        quote_match = re.search(quote_pattern, title)
        if quote_match:
            name1 = quote_match.group(1).strip()
            name2 = quote_match.group(2).strip()
            
            # Apply same validation
            name1_words = set(name1.split())
            name2_words = set(name2.split())
            
            if (name1 not in non_names and name2 not in non_names and
                name1 not in self.competition_terms and name2 not in self.competition_terms and
                not name1_words.issubset(self.competition_terms) and
                not name2_words.issubset(self.competition_terms) and
                len(name1) > 2 and len(name2) > 2):
                return [name1, name2]
        
        # Look for full names pattern anywhere in the title
        full_name_pattern = r'([A-Z][a-z]+\s+[A-Z][a-z]+)\s*(?:&|and)\s*([A-Z][a-z]+\s+[A-Z][a-z]+)'
        full_match = re.search(full_name_pattern, title_cleaned)
        if full_match:
            name1 = full_match.group(1).strip()
            name2 = full_match.group(2).strip()
            # Exclude common false positives
            exclude_phrases = ['West Coast', 'Costa Rica', 'Los Angeles', 'New York', 'San Francisco']
            
            # Apply same validation
            name1_words = set(name1.split())
            name2_words = set(name2.split())
            
            if (not any(phrase in name1 or phrase in name2 for phrase in exclude_phrases) and
                not name1_words.issubset(self.competition_terms) and
                not name2_words.issubset(self.competition_terms)):
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
                # First try to extract from description
                dancer_names = self.extract_dancers_from_description(video.description)
                source = 'description'
                
                # If not found in description, try the title
                if len(dancer_names) != 2:
                    dancer_names = self.extract_dancers_from_title(video.title)
                    source = 'title'
                
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
                        self.stdout.write(f"Updated video '{video.title}' with dancers from {source}: {', '.join(dancer_names)}")
        
        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run completed. No changes were made."))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"Completed! Created {dancers_created} dancers and updated {videos_updated} videos."
            ))