import re
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import yt_dlp
from django.utils import timezone
from django.conf import settings

from src.utils import setup_logger
from .models import YouTubeVideo

logger = setup_logger(__name__)


class YouTubeSearcher:
    """Search and discover YouTube videos for J&J WCS events."""

    def __init__(self):
        self.search_queries = [
            "J&J WCS finals",
            "J&J WCS prelims",
            "Jack and Jill WCS finals",
            "Jack and Jill West Coast Swing finals",
            "J&J West Coast Swing competition",
            "WCS Jack Jill finals",
            "West Coast Swing J&J competition",
        ]

        self.event_keywords = [
            "SwingDiego",
            "US Open Swing",
            "Phoenix 4th of July",
            "Seattle Easter Swing",
            "Boogie by the Bay",
            "MADjam",
            "Summer Hummer",
            "Swingin' New England",
            "Capital Swing",
            "SwingCouver",
            "Desert City Swing",
            "Monterey Swing Fest",
            "All Star Championships",
            "Classic Championships",
            "NASDE",
            "WSDC",
            "Championship",
            "Invitational",
            "Strictly Swing",
            "d-town swing",
            "the after party",
            "Atlanta Swing Classic",
            "wild wild westie",
            "freedom swing",
            "liberty swing",
            "Wild Wild Westie",
            "Americano Dance Camp",
            "SaunaSwing",
            "Big Apple Dance Festival",
            "MY Swing 2025",
            "Carolina Summer Swing",
            "Mediterranean Open WCS",
            "St. Petersburg WCS Nights",
            "Midwest Westie Fest 2025",
            "Toronto Open",
            "Rock the Barn",
            "Revitalise WCS",
            "Dance Mardi Gras",
            "Florida Dance Magic",
            "Odyssey West Coast Swing",
            "Sea Sun & Swing Camp",
            "Arizona Dance Classic",
            "New England Dance Festival",
            "Bristol Swing Fiesta",
            "Lisbon Westie Fest",
            "Warsaw Summer Nights Westival",
            "Swing Fling",
            "German Open West Coast Swing",
            "Swingtacular: The Galactic Open",
            "Lonestar Invitational",
            "SwingTime Denver",
            "Grand Party Sofia (GPS)",
            "UpTown Swing",
            "Chicagoland Country and Swing Dance Festival",
            "The Bend Connection",
            "Swing Dance Mania",
            "Shakedown Swing",
            "Rolling Swing",
            "Jax Westie Fest",
            "South Bay Dance Fling",
            "Trilogy Swing",
            "Korea Westival 2025",
            "Sea Dance Fest",
            "Bavarian Open West Coast Swing Championships",
            "Best of the Best WCS",
            "Retaliation Swing",
            "WCS Party",
            "Philly Swing Dance Classic",
            "Finnfest",
            "Austin Rocks",
            "Meet Me in St. Louis Swing Dance Championships",
            "Midland Swing Open",
            "Mooseland Swing 2025",
            "Norwegian Open WCS",
            "The Aloha Open",
            "Milan Modern Swing 2025",
            "Paradise dance festival",
            "Go West SwingFest",
            "The New Zealand West Coast Swing Open",
            "Montreal Westie Fest",
            "Swustlicious",
            "Augsburg Westie Station",
            "Swing City Chicago",
            "Halloween SwingThing",
            "Swingside Invitational",
            "SASS Spooky Albany Swing Spectacular",
            "WCS Festival",
            "Warsaw Halloween Swing",
            "Mountain Magic Dance Convention",
            "Scandinavian Open WCS",
            "SNOW",
            "Rocket City Swing",
            "Spooky Westie Weekend",
            "Simply Adelaide West Coast Swing",
            "Tampa Bay",
        ]

        self.year_range = 5  # Look for videos from last 5 years by default

    def _get_ydl_search_opts(self) -> dict:
        """Get yt-dlp options for searching."""
        return {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
            'force_generic_extractor': False,
            'ignoreerrors': True,
            'nocheckcertificate': True,
        }

    def search_videos(self, query: str, max_results: int = 50) -> List[Dict]:
        """Search YouTube for videos matching the query."""
        videos = []

        try:
            ydl_opts = self._get_ydl_search_opts()

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                search_query = f"ytsearch{max_results}:{query}"
                search_results = ydl.extract_info(search_query, download=False)

                if 'entries' in search_results:
                    for entry in search_results['entries']:
                        if entry and self._is_relevant_video(entry):
                            videos.append({
                                'video_id': entry.get('id'),
                                'url': f"https://www.youtube.com/watch?v={entry.get('id')}",
                                'title': entry.get('title'),
                                'channel': entry.get('uploader'),
                                'duration': entry.get('duration'),
                                'upload_date': entry.get('upload_date'),
                                'view_count': entry.get('view_count', 0),
                            })

            # Count new videos (not in database)
            new_videos_count = 0
            for video in videos:
                if not YouTubeVideo.objects.filter(video_id=video['video_id']).exists():
                    new_videos_count += 1

            logger.info(f"Found {len(videos)} relevant videos for query: {query} ({new_videos_count} new)")

        except Exception as e:
            import traceback
            logger.error(f"Error searching YouTube: {e}")
            logger.error("Full stack trace:")
            traceback.print_exc()

        return videos

    def _is_relevant_video(self, video_info: Dict) -> bool:
        """Check if a video is relevant for J&J WCS content."""
        title = video_info.get('title', '').lower()
        duration = video_info.get('duration', 0)

        # Check duration (typically J&J videos are 3-15 minutes)
        if duration < 180 or duration > 900:  # 3-15 minutes
            return False

        # Check for J&J or Jack & Jill mentions
        if not any(term in title for term in ['j&j', 'jack', 'jill', 'j & j']):
            return False

        # Check for WCS or West Coast Swing
        if not any(term in title for term in ['wcs', 'west coast swing', 'westcoast']):
            return False

        # Exclude tutorials, lessons, workshops
        exclude_terms = ['tutorial', 'lesson', 'workshop', 'how to', 'technique', 'basic', 'intermediate']
        if any(term in title for term in exclude_terms):
            return False

        return True

    def discover_new_videos(self, days_back: int = 30, year_range: Optional[int] = None) -> List[str]:
        """Discover new J&J WCS videos from the last N days and Y years."""
        all_videos = []
        discovered_urls = []

        # Use provided year_range or default
        years_to_search = year_range or self.year_range

        # Add time-based queries
        current_year = datetime.now().year
        time_queries = []

        # Search across multiple years
        for year_offset in range(years_to_search):
            search_year = current_year - year_offset

            for query in self.search_queries:
                # Search with specific year
                time_queries.append(f"{query} {search_year}")


            # Add event-specific searches for each year
            for event in self.event_keywords:
                time_queries.append(f"{event} J&J finals {search_year}")
                time_queries.append(f"{event} Jack Jill {search_year}")

        # Search for each query
        for query in time_queries:
            videos = self.search_videos(query, max_results=20)
            all_videos.extend(videos)

        # Remove duplicates and filter
        seen_ids = set()
        unique_videos = []

        for video in all_videos:
            video_id = video['video_id']
            if video_id not in seen_ids:
                seen_ids.add(video_id)

                # Check if already in database
                if not YouTubeVideo.objects.filter(video_id=video_id).exists():
                    # Check upload date if available
                    if video.get('upload_date'):
                        try:
                            upload_date = datetime.strptime(video['upload_date'], '%Y%m%d')
                            cutoff_date = datetime.now() - timedelta(days=days_back)

                            if upload_date >= cutoff_date:
                                unique_videos.append(video)
                                discovered_urls.append(video['url'])
                        except Exception as e:
                            import traceback
                            # If date parsing fails, include it anyway
                            logger.error(f"Error parsing date: {e}")
                            logger.error("Full stack trace:")
                            traceback.print_exc()
                            unique_videos.append(video)
                            discovered_urls.append(video['url'])
                    else:
                        unique_videos.append(video)
                        discovered_urls.append(video['url'])

        logger.info(f"Discovered {len(discovered_urls)} new videos to process")
        return discovered_urls

    def search_by_channel(self, channel_url: str, max_results: int = 50) -> List[str]:
        """Search for J&J videos from a specific channel."""
        videos = []
        urls = []

        try:
            ydl_opts = self._get_ydl_search_opts()

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                channel_info = ydl.extract_info(channel_url, download=False)

                if 'entries' in channel_info:
                    for entry in channel_info['entries'][:max_results]:
                        if entry and self._is_relevant_video(entry):
                            video_id = entry.get('id')
                            if not YouTubeVideo.objects.filter(video_id=video_id).exists():
                                urls.append(f"https://www.youtube.com/watch?v={video_id}")

        except Exception as e:
            import traceback
            logger.error(f"Error searching channel: {e}")
            logger.error("Full stack trace:")
            traceback.print_exc()

        return urls

    def get_popular_wcs_channels(self) -> List[str]:
        """Get list of popular WCS YouTube channels."""
        return [
            "https://www.youtube.com/c/WestCoastSwingDanceCouncil",
            "https://www.youtube.com/c/SwingDiego",
            "https://www.youtube.com/c/USOpenSwingDanceChampionships",
            "https://www.youtube.com/c/Boogiebythebay",
            "https://www.youtube.com/c/SeattleEasterSwing",
            "https://www.youtube.com/user/MADjamTV",
            "https://www.youtube.com/c/PhoenixFourthofJuly",
            "https://www.youtube.com/c/SummerHummer",
            "https://www.youtube.com/c/AllStarChampionships",
        ]
