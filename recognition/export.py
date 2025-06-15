import csv
import json
import pandas as pd
from pathlib import Path
from typing import List, Union
from django.db.models import QuerySet

from src.utils import setup_logger
from .models import RecognitionResult, YouTubeVideo

logger = setup_logger(__name__)


def export_results(
    results: Union[List[RecognitionResult], QuerySet], 
    output_path: Path, 
    format: str = 'csv'
) -> bool:
    """Export recognition results to CSV or JSON format."""
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        if format.lower() == 'csv':
            return export_to_csv(results, output_path)
        elif format.lower() == 'json':
            return export_to_json(results, output_path)
        else:
            logger.error(f"Unsupported export format: {format}")
            return False
            
    except Exception as e:
        logger.error(f"Error exporting results: {e}")
        return False


def export_to_csv(results: Union[List[RecognitionResult], QuerySet], output_path: Path) -> bool:
    """Export results to CSV file."""
    try:
        with open(output_path, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = [
                'video_title',
                'video_url',
                'timestamp_start',
                'timestamp_end',
                'title',
                'artists',
                'album',
                'confidence_score',
                'spotify_id',
                'isrc',
                'genres',
                'release_date',
                'recognized_at'
            ]
            
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            
            for result in results:
                writer.writerow({
                    'video_title': result.video.title,
                    'video_url': result.video.url,
                    'timestamp_start': result.timestamp_start,
                    'timestamp_end': result.timestamp_end,
                    'title': result.title,
                    'artists': ', '.join(result.artists) if result.artists else '',
                    'album': result.album,
                    'confidence_score': result.confidence_score,
                    'spotify_id': result.spotify_id,
                    'isrc': result.isrc,
                    'genres': ', '.join(result.genres) if result.genres else '',
                    'release_date': result.release_date,
                    'recognized_at': result.recognized_at.isoformat()
                })
        
        logger.info(f"Exported {len(results)} results to CSV: {output_path}")
        return True
        
    except Exception as e:
        logger.error(f"Error exporting to CSV: {e}")
        return False


def export_to_json(results: Union[List[RecognitionResult], QuerySet], output_path: Path) -> bool:
    """Export results to JSON file."""
    try:
        data = []
        
        for result in results:
            data.append({
                'video': {
                    'id': result.video.video_id,
                    'title': result.video.title,
                    'url': result.video.url,
                    'channel': result.video.channel,
                    'duration': result.video.duration
                },
                'recognition': {
                    'timestamp_start': result.timestamp_start,
                    'timestamp_end': result.timestamp_end,
                    'title': result.title,
                    'artists': result.artists,
                    'album': result.album,
                    'duration_ms': result.duration_ms,
                    'confidence_score': result.confidence_score,
                    'spotify_id': result.spotify_id,
                    'isrc': result.isrc,
                    'external_ids': result.external_ids,
                    'genres': result.genres,
                    'release_date': result.release_date,
                    'service': result.service,
                    'recognized_at': result.recognized_at.isoformat()
                }
            })
        
        with open(output_path, 'w', encoding='utf-8') as jsonfile:
            json.dump(data, jsonfile, indent=2, ensure_ascii=False)
        
        logger.info(f"Exported {len(results)} results to JSON: {output_path}")
        return True
        
    except Exception as e:
        logger.error(f"Error exporting to JSON: {e}")
        return False


def export_to_dataframe(results: Union[List[RecognitionResult], QuerySet]) -> pd.DataFrame:
    """Convert results to pandas DataFrame for further analysis."""
    data = []
    
    for result in results:
        data.append({
            'video_id': result.video.video_id,
            'video_title': result.video.title,
            'video_url': result.video.url,
            'video_channel': result.video.channel,
            'video_duration': result.video.duration,
            'timestamp_start': result.timestamp_start,
            'timestamp_end': result.timestamp_end,
            'title': result.title,
            'artists': ', '.join(result.artists) if result.artists else '',
            'album': result.album,
            'duration_ms': result.duration_ms,
            'confidence_score': result.confidence_score,
            'spotify_id': result.spotify_id,
            'isrc': result.isrc,
            'genres': ', '.join(result.genres) if result.genres else '',
            'release_date': result.release_date,
            'service': result.service,
            'recognized_at': result.recognized_at
        })
    
    return pd.DataFrame(data)


def export_playlist_format(results: Union[List[RecognitionResult], QuerySet], output_path: Path) -> bool:
    """Export results in a format suitable for playlist creation."""
    try:
        # Group by unique tracks
        unique_tracks = {}
        
        for result in results:
            key = (result.title, tuple(result.artists))
            if key not in unique_tracks:
                unique_tracks[key] = {
                    'title': result.title,
                    'artists': result.artists,
                    'album': result.album,
                    'spotify_id': result.spotify_id,
                    'isrc': result.isrc,
                    'occurrences': [],
                    'total_confidence': 0,
                    'count': 0
                }
            
            unique_tracks[key]['occurrences'].append({
                'video': result.video.title,
                'timestamp': result.timestamp_start,
                'confidence': result.confidence_score
            })
            unique_tracks[key]['total_confidence'] += result.confidence_score
            unique_tracks[key]['count'] += 1
        
        # Calculate average confidence and sort
        playlist_data = []
        for track_data in unique_tracks.values():
            track_data['average_confidence'] = track_data['total_confidence'] / track_data['count']
            playlist_data.append(track_data)
        
        playlist_data.sort(key=lambda x: x['average_confidence'], reverse=True)
        
        # Save to file
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(playlist_data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Exported {len(playlist_data)} unique tracks to playlist format: {output_path}")
        return True
        
    except Exception as e:
        logger.error(f"Error exporting playlist format: {e}")
        return False


def generate_statistics(results: Union[List[RecognitionResult], QuerySet]) -> dict:
    """Generate statistics from recognition results."""
    if not results:
        return {}
    
    df = export_to_dataframe(results)
    
    stats = {
        'total_recognitions': len(results),
        'unique_songs': df['title'].nunique(),
        'unique_artists': len(set(artist for artists in df['artists'].str.split(', ') for artist in artists if artist)),
        'average_confidence': df['confidence_score'].mean(),
        'confidence_std': df['confidence_score'].std(),
        'videos_processed': df['video_id'].nunique(),
        
        'top_songs': df.groupby('title').size().nlargest(10).to_dict(),
        'top_artists': df['artists'].value_counts().head(10).to_dict(),
        
        'by_video': df.groupby('video_title').size().to_dict(),
        
        'spotify_coverage': (df['spotify_id'] != '').sum() / len(df) * 100 if len(df) > 0 else 0,
    }
    
    return stats


def export_statistics(results: Union[List[RecognitionResult], QuerySet], output_path: Path) -> bool:
    """Export recognition statistics to JSON file."""
    try:
        stats = generate_statistics(results)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(stats, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Exported statistics to: {output_path}")
        return True
        
    except Exception as e:
        logger.error(f"Error exporting statistics: {e}")
        return False