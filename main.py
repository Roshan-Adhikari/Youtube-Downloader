import os
import asyncio
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
import yt_dlp
import imageio_ffmpeg

FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()

app = FastAPI(title="YouTube Multi-Downloader API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class FetchRequest(BaseModel):
    url: str

class DownloadRequest(BaseModel):
    url: str
    format: str # e.g., "mp4", "mp3"
    resolution: str = None # e.g., "1080p", "720p". If format is mp3, resolution is ignored.

DOWNLOADS_DIR = "downloads"
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

@app.post("/fetch")
def fetch_info(req: FetchRequest):
    ydl_opts = {
        'skip_download': True,
        'quiet': True,
        'no_warnings': True,
        'ffmpeg_location': FFMPEG_PATH,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(req.url, download=False)
            
            # Extract basic info
            title = info.get('title', 'Unknown Title')
            thumbnail = info.get('thumbnail', '')
            duration = info.get('duration', 0)
            channel = info.get('uploader', 'Unknown Channel')
            
            # Extract resolutions
            formats = info.get('formats', [])
            resolutions = set()
            for f in formats:
                if f.get('vcodec') != 'none' and f.get('height'):
                    resolutions.add(f"{f.get('height')}p")
            
            sorted_resolutions = sorted(list(resolutions), key=lambda x: int(x.replace('p', '')))
            
            return {
                "title": title,
                "thumbnail": thumbnail,
                "duration": duration,
                "channel": channel,
                "resolutions": sorted_resolutions,
                "formats": ["MP4", "MP3"]
            }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

def cleanup_file(filepath: str):
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
    except Exception:
        pass

@app.post("/download")
async def download_video(req: DownloadRequest, background_tasks: BackgroundTasks):
    is_audio = req.format.lower() == "mp3"
    
    ydl_opts = {
        'outtmpl': f'{DOWNLOADS_DIR}/%(title)s.%(ext)s',
        'quiet': True,
        'no_warnings': True,
        'ffmpeg_location': FFMPEG_PATH,
    }
    
    if is_audio:
        ydl_opts['format'] = 'bestaudio/best'
        ydl_opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }]
    else:
        # User requested video
        if req.resolution:
            height = req.resolution.replace('p', '')
            ydl_opts['format'] = f'bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/best[height<={height}][ext=mp4]/best'
        else:
            ydl_opts['format'] = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
            
        ydl_opts['merge_output_format'] = 'mp4'

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(req.url, download=True)
            filename = ydl.prepare_filename(info)
            if is_audio:
                filename = os.path.splitext(filename)[0] + '.mp3'
            
            background_tasks.add_task(cleanup_file, filename)
            
            return FileResponse(
                path=filename, 
                filename=os.path.basename(filename),
                media_type='application/octet-stream'
            )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
