import os
import re
from pathlib import Path
from typing import List, Optional, Tuple
import yt_dlp
from django.conf import settings
from django.utils import timezone
import hashlib

from src.utils import setup_logger
from .models import YouTubeVideo, RecognitionSession

logger = setup_logger(__name__)


class YouTubeDownloader:
    """Downloads audio from YouTube videos."""
    
    def __init__(self, download_dir: Optional[Path] = None):
        self.download_dir = download_dir or settings.DOWNLOAD_DIR
        self.download_dir.mkdir(parents=True, exist_ok=True)
        
    def _get_ydl_opts(self, output_template: str) -> dict:
        """Get yt-dlp options for audio-only download."""
        return {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'outtmpl': output_template,
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'nocheckcertificate': True,
            'ignoreerrors': False,
            'logtostderr': False,
            'no_color': True,
        }
    
    def _sanitize_filename(self, filename: str) -> str:
        """Sanitize filename for filesystem."""
        filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
        filename = filename.strip('. ')
        return filename[:200]  # Limit length
    
    def _calculate_file_hash(self, file_path: Path) -> str:
        """Calculate SHA256 hash of file."""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
    
    def download_audio(self, url: str) -> Optional[YouTubeVideo]:
        """Download audio from a YouTube video."""
        try:
            # Extract video info first
            with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
                info = ydl.extract_info(url, download=False)
                
            video_id = info['id']
            title = info.get('title', 'Unknown')
            channel = info.get('uploader', '')
            duration = info.get('duration', 0)
            description = info.get('description', '')
            
            # Check if already exists
            existing = YouTubeVideo.objects.filter(video_id=video_id).first()
            if existing:
                logger.info(f"Video already exists: {title}")
                return existing
            
            # Prepare filename
            safe_title = self._sanitize_filename(title)
            output_template = str(self.download_dir / f"{video_id}_{safe_title}.%(ext)s")
            
            # Download audio
            logger.info(f"Downloading audio: {title}")
            ydl_opts = self._get_ydl_opts(output_template)
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            
            # Find the downloaded file
            audio_file = self.download_dir / f"{video_id}_{safe_title}.mp3"
            if not audio_file.exists():
                raise FileNotFoundError(f"Downloaded file not found: {audio_file}")
            
            # Calculate file hash
            file_hash = self._calculate_file_hash(audio_file)
            
            # Create database entry
            video = YouTubeVideo.objects.create(
                video_id=video_id,
                url=url,
                title=title,
                channel=channel,
                duration=duration,
                description=description,
                audio_file_path=str(audio_file),
                audio_file_hash=file_hash,
                downloaded_at=timezone.now()
            )
            
            logger.info(f"Successfully downloaded audio: {title}")
            return video
            
        except Exception as e:
            import traceback
            logger.error(f"Error downloading audio from {url}: {e}")
            logger.error("Full stack trace:")
            traceback.print_exc()
            return None
    
    def download_playlist(self, playlist_url: str) -> List[YouTubeVideo]:
        """Download audio from all videos in a playlist."""
        videos = []
        
        try:
            # Extract playlist info
            with yt_dlp.YoutubeDL({'quiet': True, 'extract_flat': True}) as ydl:
                playlist_info = ydl.extract_info(playlist_url, download=False)
                
            if 'entries' not in playlist_info:
                logger.error("No videos found in playlist")
                return videos
                
            logger.info(f"Found {len(playlist_info['entries'])} videos in playlist")
            
            # Download each video
            for entry in playlist_info['entries']:
                if entry:
                    video_url = f"https://www.youtube.com/watch?v={entry['id']}"
                    video = self.download_audio(video_url)
                    if video:
                        videos.append(video)
                        
        except Exception as e:
            import traceback
            logger.error(f"Error downloading playlist: {e}")
            logger.error("Full stack trace:")
            traceback.print_exc()
            
        return videos
    
    def download_batch(self, urls: List[str], session: Optional[RecognitionSession] = None) -> List[YouTubeVideo]:
        """Download audio from multiple URLs."""
        videos = []
        
        for url in urls:
            if 'playlist' in url or 'list=' in url:
                playlist_videos = self.download_playlist(url)
                videos.extend(playlist_videos)
            else:
                video = self.download_audio(url)
                if video:
                    videos.append(video)
                    
        if session:
            session.videos_processed = len(videos)
            session.save()
            
        return videos
    
    def cleanup_old_files(self, days: int = 7):
        """Remove audio files older than specified days."""
        cutoff_date = timezone.now() - timezone.timedelta(days=days)
        old_videos = YouTubeVideo.objects.filter(downloaded_at__lt=cutoff_date)
        
        for video in old_videos:
            if video.audio_file_path and Path(video.audio_file_path).exists():
                try:
                    Path(video.audio_file_path).unlink()
                    logger.info(f"Deleted old audio file: {video.audio_file_path}")
                except Exception as e:
                    import traceback
                    logger.error(f"Error deleting file: {e}")
                    logger.error("Full stack trace:")
                    traceback.print_exc()
                    
        logger.info(f"Cleaned up {old_videos.count()} old audio files")