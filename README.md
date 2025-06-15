# J&J Music Recognition System

A Django-based system for recognizing music from YouTube videos using ACRCloud.

## Features

- Download YouTube videos/playlists
- Extract and split audio into segments
- Recognize music using ACRCloud API
- Export results to CSV/JSON
- Create Spotify playlists from recognized songs
- Django admin interface for data management

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Copy `.env.example` to `.env` and fill in your API credentials:
```bash
cp .env.example .env
```

3. Run migrations:
```bash
python manage.py migrate
```

4. Create a superuser:
```bash
python manage.py createsuperuser
```

## Usage

### Recognize music from YouTube videos:
```bash
python manage.py recognize_music "https://youtube.com/watch?v=VIDEO_ID"
```

### Download videos without recognition:
```bash
python manage.py download_video "https://youtube.com/watch?v=VIDEO_ID"
```

### Manage recognition sessions:
```bash
python manage.py manage_sessions --list
python manage.py manage_sessions --show SESSION_ID
python manage.py manage_sessions --export SESSION_ID --format csv
```

### Django Admin

Access the admin interface at `http://localhost:8000/admin` to view and manage:
- YouTube videos
- Recognition results
- Spotify playlists
- Recognition sessions

## Command Options

### recognize_music
- `--service`: Recognition service (default: acrcloud)
- `--segment-length`: Audio segment length in seconds (default: 30)
- `--overlap`: Overlap between segments (default: 5)
- `--export`: Export format (csv/json)
- `--session-name`: Name for the recognition session

### download_video
- `--audio-only`: Download audio only (default)
- `--video`: Download full video
- `--list`: List downloaded videos
- `--cleanup DAYS`: Clean up downloads older than DAYS

## Development

Run the development server:
```bash
python manage.py runserver
```

## API Keys Required

- **ACRCloud**: Sign up at https://console.acrcloud.com/
- **Spotify** (optional): Create app at https://developer.spotify.com/dashboard/