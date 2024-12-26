# YouTube Channel Transcriber

A Python script that downloads and transcribes videos from YouTube channels using OpenAI's Whisper. The script first attempts to use YouTube's built-in transcription API, and falls back to Whisper if no transcript is available.

## Features

- Fetches all playlists from a YouTube channel matching specified keywords
- Downloads and processes videos in batches
- Uses YouTube's transcript API when available
- Falls back to OpenAI's Whisper for videos without transcripts
- Stores transcripts in SQLite database
- Shows progress with tqdm progress bars

## Prerequisites

- Python 3.7+
- ffmpeg (required for Whisper)
- Chrome/Chromium browser (for Selenium)
- YouTube Data API key

## Installation

1. Clone this repository
2. Install required packages:

```bash
pip install -r requirements.txt
```

3. Install ffmpeg (if not already installed):
   - Ubuntu: `sudo apt install ffmpeg`
   - macOS: `brew install ffmpeg`
   - Windows: Download from [ffmpeg website](https://ffmpeg.org/download.html)

4. Copy `config.example.json` to `config.json` and update with your settings:
   - Get a YouTube API key from [Google Cloud Console](https://console.cloud.google.com/)
   - Set your target channel URL
   - Define keywords to match playlists

## Usage

1. Configure your settings in `config.json`
2. Run the script:
