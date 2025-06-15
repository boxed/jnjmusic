from django.contrib import admin
from .models import YouTubeVideo, RecognitionResult, SpotifyPlaylist, RecognitionSession, AudioSegment


@admin.register(YouTubeVideo)
class YouTubeVideoAdmin(admin.ModelAdmin):
    list_display = ['video_id', 'title', 'channel', 'duration', 'downloaded_at', 'processed']
    list_filter = ['processed', 'downloaded_at']
    search_fields = ['title', 'channel', 'video_id', 'url']
    readonly_fields = ['audio_file_hash', 'downloaded_at']
    ordering = ['-downloaded_at']


@admin.register(RecognitionResult)
class RecognitionResultAdmin(admin.ModelAdmin):
    list_display = ['title', 'artists_display', 'album', 'video', 'timestamp_start', 'confidence_score', 'spotify_id']
    list_filter = ['service', 'recognized_at', 'confidence_score']
    search_fields = ['title', 'artists', 'album', 'spotify_id', 'isrc']
    readonly_fields = ['recognized_at', 'raw_result']
    raw_id_fields = ['video']
    ordering = ['-recognized_at']
    
    def artists_display(self, obj):
        return obj.artists_display
    artists_display.short_description = 'Artists'


@admin.register(SpotifyPlaylist)
class SpotifyPlaylistAdmin(admin.ModelAdmin):
    list_display = ['name', 'spotify_id', 'tracks_added', 'created_at', 'video']
    list_filter = ['created_at']
    search_fields = ['name', 'spotify_id', 'description']
    readonly_fields = ['created_at', 'updated_at', 'spotify_url']
    raw_id_fields = ['video']
    ordering = ['-created_at']


@admin.register(RecognitionSession)
class RecognitionSessionAdmin(admin.ModelAdmin):
    list_display = ['name', 'started_at', 'status', 'videos_processed', 'songs_recognized', 'service']
    list_filter = ['status', 'service', 'started_at']
    search_fields = ['name']
    readonly_fields = ['started_at']
    ordering = ['-started_at']


@admin.register(AudioSegment)
class AudioSegmentAdmin(admin.ModelAdmin):
    list_display = ['video', 'start_time', 'end_time', 'duration', 'processed', 'created_at']
    list_filter = ['processed', 'created_at']
    raw_id_fields = ['video']
    ordering = ['video', 'start_time']
