import yt_dlp
import whisper
import torch
import os
import sqlite3
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from googleapiclient.discovery import build
import re
import time
from tqdm import tqdm
from getVideoInfo import get_video_info
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound
import shutil
import os
from datetime import datetime

def load_config():
    """Load configuration from config.json"""
    try:
        with open('config.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        print("Error: config.json not found. Please create it using the template in config.example.json")
        exit(1)

def get_playlist_video_ids(playlist_url, max_retries=3):
    """Gets video IDs from a YouTube playlist using Selenium"""
    try:
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        
        driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=chrome_options
        )
        
        driver.get(playlist_url)
        time.sleep(3)
        
        last_height = driver.execute_script("return document.documentElement.scrollHeight")
        while True:
            driver.execute_script("window.scrollTo(0, document.documentElement.scrollHeight);")
            time.sleep(2)
            new_height = driver.execute_script("return document.documentElement.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height
        
        video_elements = driver.find_elements(By.CSS_SELECTOR, "a#video-title")
        video_ids = []
        
        for element in video_elements:
            href = element.get_attribute("href")
            if href:
                video_id = re.search(r"v=([^&]+)", href)
                if video_id:
                    video_ids.append(video_id.group(1))
        
        driver.quit()
        return video_ids
        
    except Exception as e:
        print(f"Error getting video IDs: {e}")
        if 'driver' in locals():
            driver.quit()
        return None

def create_whisper_database():
    """Create SQLite database for whisper transcripts"""
    conn = sqlite3.connect("whisper_transcripts.db")
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS whisper_transcripts (
            video_id TEXT PRIMARY KEY,
            title TEXT,
            transcript TEXT,
            processed_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    conn.commit()
    conn.close()

def store_whisper_transcript(video_id, title, transcript):
    """Store transcript in the whisper database"""
    conn = sqlite3.connect("whisper_transcripts.db")
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT OR REPLACE INTO whisper_transcripts (video_id, title, transcript)
        VALUES (?, ?, ?)
    """, (video_id, title, transcript))
    
    conn.commit()
    conn.close()

def get_processed_whisper_videos():
    """Get list of already processed video IDs"""
    conn = sqlite3.connect("whisper_transcripts.db")
    cursor = conn.cursor()
    
    cursor.execute("SELECT video_id FROM whisper_transcripts")
    processed = set(row[0] for row in cursor.fetchall())
    
    conn.close()
    return processed

def get_youtube_transcript(video_id):
    """Get transcript using YouTube API"""
    # Reference to dan.py get_transcript function
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        try:
            transcript = transcript_list.find_transcript(['en'])
        except:
            transcript = transcript_list.find_transcript(['en-US', 'es', 'fr', 'de'])
            transcript = transcript.translate('en')
        return " ".join([segment['text'] for segment in transcript.fetch()])
    except:
        return None


def get_whisper_transcript(video_id):
    """Try YouTube API first, fallback to Whisper if needed"""
    try:
        # First try YouTube's API (referencing dan.py get_transcript function)
        transcript = get_youtube_transcript(video_id)
        if transcript:
            return transcript, "youtube"
            
        # If no YouTube transcript, use Whisper
        print(f"No YouTube transcript found for {video_id}, using Whisper...")
        return download_and_transcribe(video_id), "whisper"
            
    except Exception as e:
        print(f"Error getting transcript for {video_id}: {e}")
        return None, None

def get_playlist_urls(channel_url, keywords):
    """Gets playlist URLs using YouTube Data API"""
    config = load_config()
    try:
        youtube = build('youtube', 'v3', developerKey=config['youtube_api_key'])
        
        # Get channel name from URL
        channel_handle = channel_url.split('@')[-1]
        
        channel_response = youtube.search().list(
            part='id',
            q=channel_handle,
            type='channel',
            maxResults=1
        ).execute()
        
        channel_id = channel_response['items'][0]['id']['channelId']
        print(f"Found channel ID: {channel_id}")
        
        playlists = []
        next_page_token = None
        
        while True:
            playlist_response = youtube.playlists().list(
                part='snippet',
                channelId=channel_id,
                maxResults=50,
                pageToken=next_page_token
            ).execute()
            
            for item in playlist_response['items']:
                title = item['snippet']['title'].lower()
                playlist_id = item['id']
                playlist_url = f"https://www.youtube.com/playlist?list={playlist_id}"
                
                if any(keyword.lower() in title for keyword in keywords):
                    playlists.append(playlist_url)
                    print(f"Found matching playlist: {title}")
            
            next_page_token = playlist_response.get('nextPageToken')
            if not next_page_token:
                break
        
        return playlists
    except Exception as e:
        print(f"Error getting playlist URLs: {e}")
        return None


def download_and_transcribe(video_id, model_name="base"):
    """Download and transcribe using Whisper when YouTube API fails"""
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    downloads_dir = "whisper_downloads"
    
    # Create downloads directory if it doesn't exist
    if not os.path.exists(downloads_dir):
        os.makedirs(downloads_dir)
        
    try:
        # Set download options with custom directory
        ydl_opts = {
            'format': 'bestaudio/best',
            'noplaylist': True,
            'outtmpl': os.path.join(downloads_dir, '%(id)s.%(ext)s'),
            
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(video_url, download=False)
                if info.get('is_live') or info.get('premiere_timestamp'):
                    print(f"Skipping premiering/live video: {video_id}")
                    return None
                info = ydl.extract_info(video_url, download=True)
                audio_file = ydl.prepare_filename(info)
            except Exception as e:
                if "Premieres" in str(e) or "Sign in to confirm your age" in str(e):
                    print(f"Skipping video {video_id}: {e}")
                    return None
                raise e

        if not shutil.which('ffmpeg'):
            print("Error: ffmpeg is not installed. Please install ffmpeg first.")
            return None

        model = whisper.load_model(model_name)
        result = model.transcribe(audio_file)
        transcript = result["text"]
        
        # Delete the audio file after successful transcription
        if os.path.exists(audio_file):
            os.remove(audio_file)
            
        return transcript

    except Exception as e:
        print(f"Whisper transcription failed for {video_id}: {e}")
        # Clean up file in case of error
        if 'audio_file' in locals() and os.path.exists(audio_file):
            os.remove(audio_file)
        return None
    
def process_whisper_videos(video_ids, model_name="base", max_workers=1):
    processed = get_processed_whisper_videos()
    remaining = [vid for vid in video_ids if vid not in processed]
    
    print(f"\nFound {len(processed)} already processed videos")
    print(f"Found {len(remaining)} videos remaining to process")
    
    batch_size = 10
    successful = {'youtube': 0, 'whisper': 0}
    failed = 0
    total_batches = len(remaining) // batch_size + (1 if len(remaining) % batch_size else 0)
    
    with tqdm(total=len(remaining), desc="Overall Progress", unit="video", position=0) as pbar:
        with tqdm(total=total_batches, desc="Batch Progress", unit="batch", position=1) as batch_pbar:
            for i in range(0, len(remaining), batch_size):
                batch = remaining[i:i + batch_size]
                
                for video_id in batch:
                    title, date = get_video_info(video_id)
                    if not title:
                        failed += 1
                        continue
                        
                    transcript, method = get_whisper_transcript(video_id)
                    if transcript and method:
                        store_whisper_transcript(video_id, title, transcript)
                        successful[method] += 1
                    else:
                        failed += 1
                    pbar.update(1)
                    time.sleep(2)
                
                batch_pbar.update(1)
                if i + batch_size < len(remaining):
                    time.sleep(30)
    
    print(f"\nProcessing complete:")
    print(f"YouTube API successful: {successful['youtube']}")
    print(f"Whisper successful: {successful['whisper']}")
    print(f"Failed: {failed}")

def create_whisper_database():
    """Create SQLite database for whisper transcripts"""
    conn = sqlite3.connect("whisper_transcripts.db")
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS whisper_transcripts (
            video_id TEXT PRIMARY KEY,
            title TEXT,
            transcript TEXT,
            processed_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    conn.commit()
    conn.close()

def store_whisper_transcript(video_id, title, transcript):
    """Store transcript in the whisper database"""
    conn = sqlite3.connect("whisper_transcripts.db")
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT OR REPLACE INTO whisper_transcripts (video_id, title, transcript)
        VALUES (?, ?, ?)
    """, (video_id, title, transcript))
    
    conn.commit()
    conn.close()

def process_whisper_videos(video_ids, model_name="base", max_workers=1):
    """Process videos with progress tracking"""
    processed = get_processed_whisper_videos()
    remaining = [vid for vid in video_ids if vid not in processed]
    
    print(f"\nFound {len(processed)} already processed videos")
    print(f"Found {len(remaining)} videos remaining to process")
    
    batch_size = 10
    successful = {'youtube': 0, 'whisper': 0}
    failed = 0
    total_batches = len(remaining) // batch_size + (1 if len(remaining) % batch_size else 0)
    
    with tqdm(total=len(remaining), desc="Overall Progress", unit="video", position=0) as pbar:
        with tqdm(total=total_batches, desc="Batch Progress", unit="batch", position=1) as batch_pbar:
            for i in range(0, len(remaining), batch_size):
                batch = remaining[i:i + batch_size]
                
                for video_id in batch:
                    title, date = get_video_info(video_id)
                    if not title:
                        failed += 1
                        continue
                        
                    transcript, method = get_whisper_transcript(video_id)
                    if transcript and method:
                        store_whisper_transcript(video_id, title, transcript)
                        successful[method] += 1
                    else:
                        failed += 1
                    pbar.update(1)
                    time.sleep(2)
                
                batch_pbar.update(1)
                if i + batch_size < len(remaining):
                    time.sleep(30)
    
    print(f"\nProcessing complete:")
    print(f"YouTube API successful: {successful['youtube']}")
    print(f"Whisper successful: {successful['whisper']}")
    print(f"Failed: {failed}")

def main():
    config = load_config()
    create_whisper_database()
    
    # Get configuration
    channel_url = config['channel_url']
    keywords = config['playlist_keywords']
    model_name = config.get('whisper_model', 'base')  # Options: tiny, base, small, medium, large
    
    try:
        print("Fetching playlist URLs...")
        playlist_urls = get_playlist_urls(channel_url, keywords)
        if not playlist_urls:
            print("Could not retrieve playlist URLs.")
            return

        # Rest of the main function remains the same
        all_video_ids = []
        for i, playlist_url in enumerate(playlist_urls, 1):
            print(f"\nProcessing playlist {i}/{len(playlist_urls)}: {playlist_url}")
            video_ids = get_playlist_video_ids(playlist_url)
            if video_ids:
                print(f"Found {len(video_ids)} videos in playlist")
                all_video_ids.extend(video_ids)
            else:
                print(f"No videos found in playlist: {playlist_url}")
            time.sleep(2)
        
        print(f"\nTotal videos found: {len(all_video_ids)}")
        process_whisper_videos(all_video_ids, model_name)
            
    except KeyboardInterrupt:
        print("\nScript interrupted by user. Exiting gracefully...")
    except Exception as e:
        print(f"\nUnexpected error in main: {e}")
    finally:
        print("\nScript completed.")

if __name__ == "__main__":
    main()