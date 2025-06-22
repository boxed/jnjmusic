"""Optimized audio processor with strategic segment sampling and binary search."""
import os
from pathlib import Path
from typing import List, Tuple, Optional, Dict
import numpy as np
from pydub import AudioSegment
from django.conf import settings

from src.utils import setup_logger
from .models import YouTubeVideo, AudioSegment as AudioSegmentModel
from .audio_processor import AudioProcessor

logger = setup_logger(__name__)


class OptimizedAudioProcessor(AudioProcessor):
    """Audio processor with optimized segment sampling strategy."""
    
    def create_segment_at_position(self, audio: AudioSegment, video: YouTubeVideo, 
                                   start_ms: int, segment_index: int) -> Optional[AudioSegmentModel]:
        """Create a single audio segment at a specific position."""
        try:
            duration_ms = len(audio)
            end_ms = min(start_ms + self.segment_length, duration_ms)
            
            # Extract segment audio
            segment_audio = audio[start_ms:end_ms]
            
            # Save segment to file
            segment_filename = f"{video.video_id}_segment_{segment_index:03d}_{start_ms}_{end_ms}.mp3"
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
            
            return segment
            
        except Exception as e:
            logger.error(f"Error creating segment at position {start_ms}: {e}")
            return None
    
    def get_strategic_positions(self, audio_duration_ms: int) -> List[Tuple[int, str]]:
        """Get strategic positions for initial sampling (1/3 and 2/3 into the audio)."""
        positions = []
        
        # Sample at 1/3 and 2/3 positions
        one_third = audio_duration_ms // 3
        two_thirds = (audio_duration_ms * 2) // 3
        
        # Adjust positions to ensure we have enough audio for a full segment
        max_start = audio_duration_ms - self.segment_length
        
        if one_third <= max_start:
            positions.append((one_third, "1/3"))
        else:
            positions.append((max_start // 2, "middle"))
            
        if two_thirds <= max_start:
            positions.append((two_thirds, "2/3"))
        else:
            positions.append((max_start, "end"))
            
        return positions
    
    def binary_search_for_song(self, audio: AudioSegment, video: YouTubeVideo, 
                               start_ms: int, end_ms: int, recognizer, 
                               found_songs: Dict[str, Tuple[int, int]],
                               segment_counter: int, depth: int = 0) -> Tuple[Optional[Dict], Optional[AudioSegmentModel], int]:
        """
        Binary search for a song in a given range.
        Returns (result, segment, updated_counter) if found, (None, None, updated_counter) otherwise.
        """
        # Base case: if range is too small for a segment or too deep
        if end_ms - start_ms < self.segment_length or depth > 10:
            if depth > 10:
                logger.warning(f"Binary search depth limit reached at depth {depth}")
            return None, None, segment_counter
        
        # Try the middle of the range
        mid_ms = (start_ms + end_ms) // 2
        
        # Ensure we don't go beyond the valid range
        segment_start = min(mid_ms, end_ms - self.segment_length)
        
        logger.info(f"Binary search (depth {depth}): checking segment at {segment_start/1000:.1f}s in range [{start_ms/1000:.1f}s, {end_ms/1000:.1f}s]")
        
        # Create and check segment
        segment = self.create_segment_at_position(audio, video, segment_start, segment_counter)
        segment_counter += 1
        
        if not segment:
            return None, None, segment_counter
        
        # Recognize the segment with timeout protection
        import signal
        from contextlib import contextmanager
        
        @contextmanager
        def timeout(seconds):
            def timeout_handler(signum, frame):
                raise TimeoutError(f"Recognition timed out after {seconds} seconds")
            
            # Set the signal handler and alarm
            old_handler = signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(seconds)
            try:
                yield
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old_handler)
        
        try:
            with timeout(20):  # 20 second timeout for recognition
                result = recognizer.identify(Path(segment.file_path))
        except TimeoutError as e:
            logger.error(f"Recognition timeout: {e}")
            result = None
        
        if result:
            # Check if this is a duplicate song (already found)
            song_key = f"{result['title']}_{result['artists']}"
            if song_key in found_songs:
                prev_start, prev_end = found_songs[song_key]
                # If this segment overlaps with a previously found instance, skip it
                if (segment_start < prev_end * 1000 and 
                    segment_start + self.segment_length > prev_start * 1000):
                    logger.info(f"Found duplicate song at {segment_start/1000:.1f}s, skipping")
                    segment.processed = True
                    segment.save()
                    return None, None, segment_counter
            
            return result, segment, segment_counter
        
        # Mark segment as processed
        segment.processed = True
        segment.save()
        
        # If no song found at middle, recursively search both halves
        # Search first half
        if mid_ms - start_ms >= self.segment_length:
            result, segment, segment_counter = self.binary_search_for_song(
                audio, video, start_ms, mid_ms, recognizer, found_songs, segment_counter, depth + 1
            )
            if result:
                return result, segment, segment_counter
        
        # Search second half
        if end_ms - (mid_ms + self.segment_length) >= self.segment_length:
            result, segment, segment_counter = self.binary_search_for_song(
                audio, video, mid_ms + self.segment_length, end_ms, recognizer, found_songs, segment_counter, depth + 1
            )
            if result:
                return result, segment, segment_counter
        
        return None, None, segment_counter
    
    def process_video_optimized(self, video: YouTubeVideo, recognizer, max_songs: int = 2) -> List[Dict]:
        """
        Process a video using optimized segment sampling strategy.
        Returns list of recognition results.
        """
        if not video.audio_file_path:
            logger.error(f"No audio file for video: {video.title}")
            return []
        
        audio = self.load_audio(Path(video.audio_file_path))
        if not audio:
            return []
        
        duration_ms = len(audio)
        logger.info(f"Processing video with optimized strategy: {video.title} (duration: {duration_ms/1000:.1f}s)")
        
        results = []
        found_songs = {}  # Track found songs to avoid duplicates
        segment_counter = 0
        
        # Step 1: Check strategic positions first (1/3 and 2/3)
        strategic_positions = self.get_strategic_positions(duration_ms)
        
        for position_ms, position_name in strategic_positions:
            if len(found_songs) >= max_songs:
                break
                
            logger.info(f"Checking strategic position: {position_name} ({position_ms/1000:.1f}s)")
            
            segment = self.create_segment_at_position(audio, video, position_ms, segment_counter)
            segment_counter += 1
            
            if segment:
                try:
                    import signal
                    from contextlib import contextmanager
                    
                    @contextmanager
                    def timeout(seconds):
                        def timeout_handler(signum, frame):
                            raise TimeoutError(f"Recognition timed out after {seconds} seconds")
                        
                        old_handler = signal.signal(signal.SIGALRM, timeout_handler)
                        signal.alarm(seconds)
                        try:
                            yield
                        finally:
                            signal.alarm(0)
                            signal.signal(signal.SIGALRM, old_handler)
                    
                    with timeout(20):
                        result = recognizer.identify(Path(segment.file_path))
                except TimeoutError as e:
                    logger.error(f"Recognition timeout at {position_name}: {e}")
                    result = None
                
                if result:
                    song_key = f"{result['title']}_{result['artists']}"
                    if song_key not in found_songs:
                        found_songs[song_key] = (segment.start_time, segment.end_time)
                        results.append({
                            'result': result,
                            'segment': segment,
                            'position': position_name
                        })
                        logger.info(f"Found song at {position_name}: {result['title']}")
                
                segment.processed = True
                segment.save()
        
        # Step 2: If we haven't found enough songs, use binary search on each half
        if len(found_songs) < max_songs:
            logger.info(f"Found {len(found_songs)} songs from strategic positions, performing binary search")
            
            # Determine the halfway point
            half_point = duration_ms // 2
            
            # Search first half
            if len(found_songs) < max_songs:
                logger.info("Binary searching first half of video")
                result, segment, segment_counter = self.binary_search_for_song(
                    audio, video, 0, half_point, recognizer, found_songs, segment_counter
                )
                
                if result and segment:
                    song_key = f"{result['title']}_{result['artists']}"
                    if song_key not in found_songs:
                        found_songs[song_key] = (segment.start_time, segment.end_time)
                        results.append({
                            'result': result,
                            'segment': segment,
                            'position': 'first_half'
                        })
                        logger.info(f"Found song in first half: {result['title']}")
                    segment.processed = True
                    segment.save()
            
            # Search second half
            if len(found_songs) < max_songs:
                logger.info("Binary searching second half of video")
                result, segment, segment_counter = self.binary_search_for_song(
                    audio, video, half_point, duration_ms, recognizer, found_songs, segment_counter
                )
                
                if result and segment:
                    song_key = f"{result['title']}_{result['artists']}"
                    if song_key not in found_songs:
                        found_songs[song_key] = (segment.start_time, segment.end_time)
                        results.append({
                            'result': result,
                            'segment': segment,
                            'position': 'second_half'
                        })
                        logger.info(f"Found song in second half: {result['title']}")
                    segment.processed = True
                    segment.save()
        
        logger.info(f"Optimized processing complete. Found {len(results)} songs using {segment_counter} segments")
        
        # If we still haven't found enough songs and the user wants more thorough search
        # we could fall back to sequential processing, but for now we'll stop here
        
        return results
    
    def cleanup_unprocessed_segments(self, video: YouTubeVideo):
        """Clean up any unprocessed segments for a video."""
        unprocessed = AudioSegmentModel.objects.filter(video=video, processed=False)
        
        for segment in unprocessed:
            if segment.file_path and Path(segment.file_path).exists():
                try:
                    Path(segment.file_path).unlink()
                except Exception as e:
                    logger.error(f"Error deleting segment file: {e}")
        
        unprocessed.delete()
        logger.info(f"Cleaned up {unprocessed.count()} unprocessed segments")