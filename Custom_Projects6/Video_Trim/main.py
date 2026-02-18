from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import subprocess
import requests
import os
import uuid
import shutil
import time
from apscheduler.schedulers.background import BackgroundScheduler

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

VIDEOS_DIR = "/app/videos"
os.makedirs(VIDEOS_DIR, exist_ok=True)

class TrimRequest(BaseModel):
    video_url: str
    start_time: float = 0
    end_time: float = 7
    fade_duration: float = 0.5

def cleanup_old_videos():
    """Delete videos older than 1 hour"""
    try:
        now = time.time()
        deleted = 0
        total = 0
        
        for filename in os.listdir(VIDEOS_DIR):
            filepath = os.path.join(VIDEOS_DIR, filename)
            if os.path.isfile(filepath):
                total += 1
                age = now - os.path.getmtime(filepath)
                if age > 3600:
                    os.remove(filepath)
                    deleted += 1
                    print(f"Deleted old video: {filename} (age: {int(age/60)} minutes)")
        
        print(f"Cleanup complete: Deleted {deleted}/{total} videos")
    except Exception as e:
        print(f"Cleanup error: {str(e)}")

scheduler = BackgroundScheduler()
scheduler.add_job(cleanup_old_videos, 'interval', minutes=30)
scheduler.start()

@app.on_event("startup")
async def startup_event():
    """Run cleanup on startup"""
    print("Starting up... Running initial cleanup")
    cleanup_old_videos()

@app.post("/trim")
async def trim_video(request: TrimRequest):
    video_id = str(uuid.uuid4())
    input_path = f"/tmp/{video_id}_input.mp4"
    output_path = f"/tmp/{video_id}_output.mp4"
    final_filename = f"{video_id}.mp4"
    final_path = os.path.join(VIDEOS_DIR, final_filename)
    
    try:
        print(f"Downloading: {request.video_url}")
        response = requests.get(request.video_url, timeout=120)
        response.raise_for_status()
        
        with open(input_path, 'wb') as f:
            f.write(response.content)
        print(f"Downloaded: {len(response.content)} bytes")
        
        print(f"Trimming: {request.start_time}s to {request.end_time}s")
        fade_start = request.end_time - request.start_time - request.fade_duration
        
        result = subprocess.run([
            'ffmpeg', '-i', input_path,
            '-ss', str(request.start_time),
            '-t', str(request.end_time - request.start_time),
            '-vf', f'fade=t=out:st={fade_start}:d={request.fade_duration}',
            '-af', f'afade=t=out:st={fade_start}:d={request.fade_duration}',
            '-c:v', 'libx264',
            '-c:a', 'aac',
            '-preset', 'ultrafast',
            '-y',
            output_path
        ], capture_output=True, text=True, timeout=120)
        
        if result.returncode != 0:
            raise Exception(f"FFmpeg failed: {result.stderr}")
        
        shutil.move(output_path, final_path)
        print(f"Saved to: {final_path}")
        
        os.remove(input_path)
        
        video_url = f"https://just-determination-production-fea7.up.railway.app/video/{final_filename}"
        print(f"Video available at: {video_url}")
        
        return {
            "success": True,
            "video_url": video_url,
            "message": "Video trimmed and hosted successfully"
        }
    
    except Exception as e:
        print(f"Error: {str(e)}")
        if os.path.exists(input_path):
            os.remove(input_path)
        if os.path.exists(output_path):
            os.remove(output_path)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/video/{filename}")
async def serve_video(filename: str):
    file_path = os.path.join(VIDEOS_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Video not found")
    return FileResponse(file_path, media_type="video/mp4")

@app.get("/")
async def root():
    return {
        "status": "Video trim service running",
        "version": "3.0 - Self-hosted with auto-cleanup",
        "storage": "Railway filesystem",
        "cleanup": "Every 30 minutes, deletes videos older than 1 hour"
    }

@app.get("/health")
async def health():
    videos = os.listdir(VIDEOS_DIR)
    return {
        "status": "healthy",
        "videos_stored": len(videos),
        "cleanup_schedule": "Every 30 minutes",
        "retention": "1 hour"
    }

@app.get("/cleanup")
async def manual_cleanup():
    """Manually trigger cleanup"""
    cleanup_old_videos()
    return {"message": "Cleanup triggered", "videos_remaining": len(os.listdir(VIDEOS_DIR))}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
