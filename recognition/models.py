from django.db import models
from django.utils import timezone
import json


class Artist(models.Model):
    """Represents a music artist."""
    name = models.CharField(max_length=200, unique=True, db_index=True)
    spotify_id = models.CharField(max_length=50, blank=True, db_index=True)
    genres = models.JSONField(default=list)
    popularity = models.IntegerField(null=True, blank=True)
    external_urls = models.JSONField(default=dict)

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Dancer(models.Model):
    """Represents a dancer who appears in videos."""
    name = models.CharField(max_length=200, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['name']
    
    def __str__(self):
        return self.name


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
    dancers = models.ManyToManyField('Dancer', related_name='videos', blank=True)

    class Meta:
        ordering = ['-downloaded_at']
        indexes = [
            models.Index(fields=['processed', 'downloaded_at']),
        ]

    def __str__(self):
        return f"{self.title} ({self.video_id})"


class Song(models.Model):
    """Represents a unique song."""
    title = models.CharField(max_length=500)
    artist_set = models.ManyToManyField(Artist, related_name='songs', blank=True)
    album = models.CharField(max_length=500, blank=True)
    duration_ms = models.IntegerField(null=True)

    # External IDs
    spotify_id = models.CharField(max_length=50, blank=True, db_index=True)  # Removed unique=True due to data issues
    isrc = models.CharField(max_length=20, blank=True, db_index=True)
    external_ids = models.JSONField(default=dict)

    # Additional metadata
    genres = models.JSONField(default=list)
    release_date = models.CharField(max_length=20, blank=True)
    label = models.CharField(max_length=200, blank=True)

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title


class RecognitionResult(models.Model):
    """Stores music recognition results."""
    video = models.ForeignKey(YouTubeVideo, on_delete=models.CASCADE, related_name='recognition_results')
    song = models.ForeignKey(Song, on_delete=models.CASCADE, related_name='recognition_results')
    timestamp_start = models.FloatField(help_text="Start time in seconds")
    timestamp_end = models.FloatField(help_text="End time in seconds")

    # Recognition-specific data
    confidence_score = models.FloatField(default=0.0)

    # Recognition service info
    service = models.CharField(max_length=50, default='acrcloud')
    raw_result = models.JSONField(null=True, blank=True)

    recognized_at = models.DateTimeField(default=timezone.now)


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
