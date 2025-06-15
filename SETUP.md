# J&J WCS Music Recognition System Setup

## Overview
This system automatically discovers Jack & Jill West Coast Swing competition videos on YouTube, downloads the audio, and identifies the music used.

## Quick Start

1. **Set up environment variables** in `.env` file:
```bash
ACRCLOUD_ACCESS_KEY=your_access_key
ACRCLOUD_ACCESS_SECRET=your_secret_key
ACRCLOUD_HOST=identify-us-west-2.acrcloud.com
SPOTIFY_CLIENT_ID=your_spotify_client_id
SPOTIFY_CLIENT_SECRET=your_spotify_client_secret
```

2. **Run migrations**:
```bash
python manage.py migrate
```

3. **Start automatic discovery** (one-time):
```bash
python manage.py auto_discover --days-back 30 --max-videos 10
```

4. **Run continuous discovery** (keeps checking for new videos):
```bash
python manage.py auto_discover --continuous --interval 3600
```

5. **Set up cron job** (optional, for scheduled runs):
```bash
python manage.py setup_cron --interval daily
```

## Commands

### Auto Discovery
```bash
# Basic discovery
python manage.py auto_discover

# Options:
--days-back 30        # Look for videos from last N days
--max-videos 50       # Max videos to process per run
--channels            # Also search popular WCS channels
--dry-run            # Preview what would be processed
--continuous         # Run continuously
--interval 3600      # Check interval in seconds (continuous mode)
```

### Manual Recognition
```bash
# Process specific videos
python manage.py recognize_music https://youtube.com/watch?v=VIDEO_ID

# Options:
--service acrcloud   # Recognition service (acrcloud or shazamkit)
--no-download        # Use existing audio files
```

### Cron Setup
```bash
# Set up automated runs
python manage.py setup_cron --interval daily    # or hourly, weekly
python manage.py setup_cron --remove           # Remove cron job
```

## Features

- **Automatic Discovery**: Searches YouTube for J&J WCS competition videos
- **Audio-Only Download**: Downloads only audio to save bandwidth and storage
- **Music Recognition**: Identifies songs using ACRCloud or ShazamKit
- **Continuous Mode**: Keeps checking for new videos
- **Smart Filtering**: Filters out tutorials, workshops, and non-competition content
- **Event-Aware**: Searches for major WCS events (SwingDiego, US Open, etc.)
- **Duplicate Prevention**: Tracks processed videos to avoid reprocessing

## Configuration

Edit `jnjmusic/settings.py` to customize:

- `AUTO_DISCOVERY_DAYS_BACK`: How far back to search (default: 30 days)
- `AUTO_DISCOVERY_MAX_VIDEOS`: Max videos per run (default: 50)
- `AUTO_DISCOVERY_SEARCH_CHANNELS`: Search WCS channels (default: True)
- `AUTO_DISCOVERY_INTERVAL`: Check interval in continuous mode (default: 3600s)

## Database

Access Django admin at http://localhost:8000/admin/ to view:
- Downloaded videos
- Recognition results
- Processing sessions
- Spotify playlists (if configured)