import os
from pathlib import Path
from typing import List, Tuple, Optional
import numpy as np
from pydub import AudioSegment
from pydub.utils import make_chunks
from django.conf import settings

from src.utils import setup_logger, create_timestamp
from .models import YouTubeVideo, AudioSegment as AudioSegmentModel

logger = setup_logger(__name__)


class AudioProcessor:
    """Handles audio processing tasks like splitting and format conversion."""
    
    def __init__(self, cache_dir: Optional[Path] = None):
        self.cache_dir = cache_dir or settings.CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.segment_length = settings.AUDIO_SEGMENT_LENGTH * 1000  # Convert to milliseconds
        self.overlap = settings.AUDIO_OVERLAP * 1000  # Convert to milliseconds
        
    def load_audio(self, file_path: Path) -> Optional[AudioSegment]:
        """Load audio file into AudioSegment."""
        try:
            if not file_path.exists():
                logger.error(f"Audio file not found: {file_path}")
                return None
                
            audio = AudioSegment.from_file(str(file_path))
            logger.info(f"Loaded audio: {file_path.name} (duration: {len(audio)/1000:.1f}s)")
            return audio
            
        except Exception as e:
            logger.error(f"Error loading audio file: {e}")
            return None
    
    def split_audio(self, audio: AudioSegment, video: YouTubeVideo) -> List[AudioSegmentModel]:
        """Split audio into overlapping segments."""
        segments = []
        
        try:
            duration_ms = len(audio)
            duration_s = duration_ms / 1000
            
            # Calculate segment positions with overlap
            positions = []
            pos = 0
            
            while pos < duration_ms:
                end_pos = min(pos + self.segment_length, duration_ms)
                positions.append((pos, end_pos))
                
                # Move forward by (segment_length - overlap)
                pos += self.segment_length - self.overlap
                
                # If the remaining audio is too short, extend the last segment
                if pos < duration_ms and (duration_ms - pos) < self.segment_length / 2:
                    positions[-1] = (positions[-1][0], duration_ms)
                    break
            
            logger.info(f"Splitting audio into {len(positions)} segments")
            
            # Create segments
            for i, (start_ms, end_ms) in enumerate(positions):
                segment_audio = audio[start_ms:end_ms]
                
                # Save segment to file
                segment_filename = f"{video.video_id}_segment_{i:03d}_{start_ms}_{end_ms}.mp3"
                segment_path = self.cache_dir / segment_filename
                
                segment_audio.export(str(segment_path), format="mp3", bitrate="192k")
                
                # Create database entry
                segment = AudioSegmentModel.objects.create(
                    video=video,
                    file_path=str(segment_path),
                    start_time=start_ms / 1000,
                    end_time=end_ms / 1000,
                    duration=(end_ms - start_ms) / 1000
                )
                
                segments.append(segment)
                
            logger.info(f"Created {len(segments)} audio segments")
            return segments
            
        except Exception as e:
            logger.error(f"Error splitting audio: {e}")
            return []
    
    def process_video(self, video: YouTubeVideo) -> List[AudioSegmentModel]:
        """Process a video's audio file into segments."""
        if not video.audio_file_path:
            logger.error(f"No audio file for video: {video.title}")
            return []
            
        audio = self.load_audio(Path(video.audio_file_path))
        if not audio:
            return []
            
        # Check if segments already exist
        existing_segments = AudioSegmentModel.objects.filter(video=video).count()
        if existing_segments > 0:
            logger.info(f"Segments already exist for video: {video.title}")
            return list(AudioSegmentModel.objects.filter(video=video))
            
        return self.split_audio(audio, video)
    
    def normalize_audio(self, audio: AudioSegment, target_dBFS: float = -20.0) -> AudioSegment:
        """Normalize audio volume to target dBFS."""
        change_in_dBFS = target_dBFS - audio.dBFS
        return audio.apply_gain(change_in_dBFS)
    
    def convert_to_format(self, file_path: Path, output_format: str = "mp3") -> Optional[Path]:
        """Convert audio file to specified format."""
        try:
            audio = self.load_audio(file_path)
            if not audio:
                return None
                
            output_path = file_path.with_suffix(f'.{output_format}')
            audio.export(str(output_path), format=output_format)
            
            logger.info(f"Converted {file_path.name} to {output_format}")
            return output_path
            
        except Exception as e:
            logger.error(f"Error converting audio format: {e}")
            return None
    
    def extract_audio_features(self, audio_path: Path) -> Optional[dict]:
        """Extract audio features for analysis (requires librosa)."""
        try:
            import librosa
            
            # Load audio
            y, sr = librosa.load(str(audio_path), sr=None)
            
            # Extract features
            features = {
                'duration': librosa.get_duration(y=y, sr=sr),
                'tempo': float(librosa.beat.tempo(y=y, sr=sr)[0]),
                'spectral_centroid': float(np.mean(librosa.feature.spectral_centroid(y=y, sr=sr))),
                'zero_crossing_rate': float(np.mean(librosa.feature.zero_crossing_rate(y))),
                'mfcc': librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13).mean(axis=1).tolist(),
            }
            
            return features
            
        except Exception as e:
            logger.error(f"Error extracting audio features: {e}")
            return None
    
    def cleanup_segments(self, video: YouTubeVideo):
        """Remove segment files for a video."""
        segments = AudioSegmentModel.objects.filter(video=video)
        
        for segment in segments:
            if segment.file_path and Path(segment.file_path).exists():
                try:
                    Path(segment.file_path).unlink()
                    logger.info(f"Deleted segment file: {segment.file_path}")
                except Exception as e:
                    logger.error(f"Error deleting segment file: {e}")
                    
        segments.delete()
        logger.info(f"Cleaned up segments for video: {video.title}")
    
    def merge_segments(self, segments: List[AudioSegmentModel], output_path: Path) -> Optional[Path]:
        """Merge audio segments back into a single file."""
        try:
            if not segments:
                logger.error("No segments to merge")
                return None
                
            # Sort segments by start time
            segments = sorted(segments, key=lambda s: s.start_time)
            
            # Load and concatenate
            combined = AudioSegment.empty()
            
            for segment in segments:
                if not Path(segment.file_path).exists():
                    logger.warning(f"Segment file not found: {segment.file_path}")
                    continue
                    
                audio = AudioSegment.from_file(segment.file_path)
                combined += audio
                
            # Export merged audio
            combined.export(str(output_path), format="mp3", bitrate="192k")
            logger.info(f"Merged {len(segments)} segments into {output_path.name}")
            
            return output_path
            
        except Exception as e:
            logger.error(f"Error merging segments: {e}")
            return None