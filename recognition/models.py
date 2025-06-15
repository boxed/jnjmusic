from django.db import models
from django.utils import timezone
import json


class YouTubeVideo(models.Model):
    """Represents a YouTube video that has been processed."""
    video_id = models.CharField(max_length=20, unique=True, db_index=True)
    url = models.URLField()
    title = models.CharField(max_length=500)
    channel = models.CharField(max_length=200, blank=True)
    duration = models.IntegerField(help_text="Duration in seconds", null=True)
    description = models.TextField(blank=True)
    downloaded_at = models.DateTimeField(default=timezone.now)
    audio_file_path = models.CharField(max_length=500, blank=True)
    audio_file_hash = models.CharField(max_length=64, blank=True, db_index=True)
    processed = models.BooleanField(default=False)
    error = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-downloaded_at']
        indexes = [
            models.Index(fields=['processed', 'downloaded_at']),
        ]
    
    def __str__(self):
        return f"{self.title} ({self.video_id})"


class RecognitionResult(models.Model):
    """Stores music recognition results."""
    video = models.ForeignKey(YouTubeVideo, on_delete=models.CASCADE, related_name='recognition_results')
    timestamp_start = models.FloatField(help_text="Start time in seconds")
    timestamp_end = models.FloatField(help_text="End time in seconds")
    
    # Song information
    title = models.CharField(max_length=500)
    artists = models.JSONField(default=list)  # List of artist names
    album = models.CharField(max_length=500, blank=True)
    duration_ms = models.IntegerField(null=True)
    confidence_score = models.FloatField(default=0.0)
    
    # External IDs
    spotify_id = models.CharField(max_length=50, blank=True, db_index=True)
    isrc = models.CharField(max_length=20, blank=True)
    external_ids = models.JSONField(default=dict)
    
    # Additional metadata
    genres = models.JSONField(default=list)
    release_date = models.CharField(max_length=20, blank=True)
    label = models.CharField(max_length=200, blank=True)
    
    # Recognition service info
    service = models.CharField(max_length=50, default='acrcloud')
    raw_result = models.JSONField(null=True, blank=True)
    
    recognized_at = models.DateTimeField(default=timezone.now)
    
    class Meta:
        ordering = ['video', 'timestamp_start']
        indexes = [
            models.Index(fields=['spotify_id']),
            models.Index(fields=['title', 'artists']),
        ]
        unique_together = [['video', 'timestamp_start', 'title']]
    
    def __str__(self):
        artists_str = ', '.join(self.artists) if self.artists else 'Unknown'
        return f"{self.title} by {artists_str} @ {self.timestamp_start}s"
    
    @property
    def artists_display(self):
        """Return artists as a formatted string."""
        return ', '.join(self.artists) if self.artists else 'Unknown'


class SpotifyPlaylist(models.Model):
    """Tracks created Spotify playlists."""
    name = models.CharField(max_length=200)
    spotify_id = models.CharField(max_length=50, unique=True)
    spotify_url = models.URLField()
    description = models.TextField(blank=True)
    
    video = models.ForeignKey(YouTubeVideo, on_delete=models.SET_NULL, null=True, blank=True, related_name='playlists')
    tracks_added = models.IntegerField(default=0)
    
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return self.name


class RecognitionSession(models.Model):
    """Groups recognition operations together."""
    name = models.CharField(max_length=200, blank=True)
    started_at = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    videos_processed = models.IntegerField(default=0)
    songs_recognized = models.IntegerField(default=0)
    
    # Session configuration
    segment_length = models.IntegerField(default=30)
    overlap = models.IntegerField(default=5)
    service = models.CharField(max_length=50, default='acrcloud')
    
    status = models.CharField(max_length=20, choices=[
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ], default='pending')
    
    error_message = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-started_at']
    
    def __str__(self):
        return self.name or f"Session {self.started_at.strftime('%Y-%m-%d %H:%M')}"


class AudioSegment(models.Model):
    """Represents an audio segment extracted from a video."""
    video = models.ForeignKey(YouTubeVideo, on_delete=models.CASCADE, related_name='audio_segments')
    file_path = models.CharField(max_length=500)
    start_time = models.FloatField()
    end_time = models.FloatField()
    duration = models.FloatField()
    processed = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)
    
    class Meta:
        ordering = ['video', 'start_time']
        unique_together = [['video', 'start_time', 'end_time']]
    
    def __str__(self):
        return f"{self.video.title} [{self.start_time:.1f}-{self.end_time:.1f}s]"
