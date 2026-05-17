import os
import uuid
import time
import threading
import tempfile
import shutil
import json
from pathlib import Path
from flask import Flask, render_template, request, jsonify, Response, send_file, url_for
import yt_dlp

app = Flask(__name__)
app.secret_key = 'vidfetch-secret-key-change-in-production'
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

# In-memory job storage
jobs = {}
jobs_lock = threading.Lock()

# Temporary directory for downloads
TEMP_DIR = tempfile.mkdtemp(prefix='vidfetch_')
print(f"Temporary directory created: {TEMP_DIR}")

# Cleanup old temp files on exit
import atexit
def cleanup_temp():
    shutil.rmtree(TEMP_DIR, ignore_errors=True)
atexit.register(cleanup_temp)

# Realistic browser headers for yt-dlp
DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'DNT': '1',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1'
}

def get_ydl_opts_common():
    """Base yt-dlp options without download."""
    return {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
        'headers': DEFAULT_HEADERS,
        'ignoreerrors': True,
        'no_check_certificate': True,
        'prefer_insecure': False,
    }

def extract_video_info(url):
    """Extract video metadata and available combined formats."""
    ydl_opts = get_ydl_opts_common()
    ydl_opts['skip_download'] = True
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info is None:
                raise ValueError("Could not extract video information")
            
            # Check for Instagram login requirement
            if info.get('extractor', '').lower() == 'instagram':
                if 'login' in str(info).lower() or 'private' in str(info).lower():
                    raise Exception("instagram_login_required")
            
            # Extract combined formats (video + audio together)
            formats = info.get('formats', [])
            combined_formats = []
            for f in formats:
                vcodec = f.get('vcodec', 'none')
                acodec = f.get('acodec', 'none')
                protocol = f.get('protocol', '')
                if vcodec != 'none' and acodec != 'none' and 'm3u8' not in protocol and 'ism' not in protocol:
                    if f.get('ext') in ['mp4', 'webm', 'mkv', 'flv']:
                        combined_formats.append(f)
            
            combined_formats.sort(key=lambda x: x.get('height', 0) or 0, reverse=True)
            
            qualities = []
            for f in combined_formats:
                height = f.get('height')
                if not height:
                    continue
                label = f"{height}p"
                if f.get('fps') and f.get('fps') > 30:
                    label += f" {f.get('fps')}fps"
                if f.get('ext'):
                    label += f" - {f.get('ext').upper()}"
                qualities.append({
                    'format_id': f['format_id'],
                    'label': label,
                    'height': height,
                    'ext': f.get('ext', 'mp4'),
                    'filesize': f.get('filesize') or f.get('filesize_approx') or 0,
                    'bitrate': f.get('tbr')
                })
            
            # Fallback to best combined format if none found
            if not qualities and info.get('formats'):
                for f in info['formats']:
                    if f.get('vcodec') != 'none' and f.get('acodec') != 'none':
                        qualities.append({
                            'format_id': f['format_id'],
                            'label': f"{f.get('height', 'Unknown')}p",
                            'height': f.get('height', 0),
                            'ext': f.get('ext', 'mp4'),
                            'filesize': f.get('filesize') or 0,
                            'bitrate': f.get('tbr')
                        })
                        break
            
            thumbnail = info.get('thumbnail') or (info.get('thumbnails', [{}])[-1].get('url') if info.get('thumbnails') else None)
            if thumbnail and not thumbnail.startswith('http'):
                thumbnail = None
            
            platform = info.get('extractor', 'Unknown').lower()
            platform_map = {'youtube': 'YouTube', 'tiktok': 'TikTok', 'instagram': 'Instagram',
                            'facebook': 'Facebook', 'twitter': 'Twitter', 'vimeo': 'Vimeo'}
            platform_display = platform_map.get(platform, platform.capitalize())
            
            return {
                'success': True,
                'title': info.get('title', 'Unknown Title'),
                'thumbnail': thumbnail,
                'duration': info.get('duration', 0) or 0,
                'uploader': info.get('uploader') or info.get('channel') or 'Unknown',
                'view_count': info.get('view_count', 0) or 0,
                'platform': platform_display,
                'qualities': qualities,
                'has_audio': any(f.get('acodec') != 'none' for f in info.get('formats', [])),
                'file_sizes': {q['height']: q['filesize'] for q in qualities if q['filesize']}
            }
    except Exception as e:
        error_msg = str(e).lower()
        if 'login' in error_msg or 'private' in error_msg or 'instagram' in error_msg:
            return {'success': False, 'error': 'Instagram requires login. Try YouTube or TikTok instead.'}
        elif 'ffmpeg' in error_msg or 'merge' in error_msg:
            return {'success': False, 'error': 'Server configuration error. Please try another video.'}
        elif '403' in error_msg or 'forbidden' in error_msg:
            return {'success': False, 'error': 'Access forbidden. The video may be private or region-restricted.'}
        elif 'unavailable' in error_msg:
            return {'success': False, 'error': 'Video unavailable. It may have been removed.'}
        else:
            return {'success': False, 'error': f"Extraction failed: {str(e)[:100]}"}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/download')
def download_page():
    url = request.args.get('url')
    if not url:
        return render_template('index.html', error="No URL provided")
    
    info = extract_video_info(url)
    if not info.get('success'):
        return render_template('download.html', error=info.get('error', 'Failed to fetch video info'), url=url)
    
    return render_template('download.html',
                         url=url,
                         video=info,
                         qualities=info.get('qualities', []),
                         title=info.get('title'),
                         thumbnail=info.get('thumbnail'),
                         duration=info.get('duration'),
                         uploader=info.get('uploader'),
                         views=info.get('view_count'),
                         platform=info.get('platform'))

@app.route('/vid/info', methods=['POST'])
def video_info():
    data = request.get_json()
    url = data.get('url')
    if not url:
        return jsonify({'success': False, 'error': 'URL required'}), 400
    
    info = extract_video_info(url)
    return jsonify(info)

@app.route('/vid/start', methods=['POST'])
def start_download():
    data = request.get_json()
    url = data.get('url')
    format_id = data.get('format_id')
    audio_only = data.get('audio_only', False)
    
    if not url:
        return jsonify({'error': 'URL required'}), 400
    
    job_id = str(uuid.uuid4())
    
    with jobs_lock:
        jobs[job_id] = {
            'status': 'connecting',
            'progress': 0,
            'phase': 'Connecting...',
            'error': None,
            'file_path': None,
            'title': 'Unknown',
            'format_id': format_id,
            'audio_only': audio_only,
            'url': url
        }
    
    thread = threading.Thread(target=download_video, args=(job_id, url, format_id, audio_only))
    thread.daemon = True
    thread.start()
    
    return jsonify({'job_id': job_id})

def download_video(job_id, url, format_id, audio_only):
    try:
        with jobs_lock:
            jobs[job_id]['phase'] = 'Initializing...'
        
        output_template = os.path.join(TEMP_DIR, f"{job_id}_%(title)s.%(ext)s")
        
        if audio_only:
            format_spec = 'bestaudio/best'
            ydl_opts = {
                'format': format_spec,
                'outtmpl': output_template,
                'quiet': True,
                'no_warnings': True,
                'headers': DEFAULT_HEADERS,
                'ignoreerrors': True,
                'progress_hooks': [lambda d: progress_hook(job_id, d)],
                'postprocessors': [],
            }
        else:
            if not format_id:
                format_spec = 'best[ext=mp4]/best[ext=webm]/best'
            else:
                format_spec = format_id
            ydl_opts = {
                'format': format_spec,
                'outtmpl': output_template,
                'quiet': True,
                'no_warnings': True,
                'headers': DEFAULT_HEADERS,
                'ignoreerrors': True,
                'progress_hooks': [lambda d: progress_hook(job_id, d)],
            }
        
        with jobs_lock:
            jobs[job_id]['phase'] = 'Downloading...'
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info is None:
                raise Exception("Download failed: No video data")
            
            if 'requested_downloads' in info and info['requested_downloads']:
                file_path = info['requested_downloads'][0]['filepath']
            else:
                filename = ydl.prepare_filename(info)
                if audio_only and not os.path.exists(filename):
                    for ext in ['.webm', '.m4a', '.opus', '.mp4']:
                        test_path = filename.rsplit('.', 1)[0] + ext
                        if os.path.exists(test_path):
                            filename = test_path
                            break
                file_path = filename
            
            if not file_path or not os.path.exists(file_path):
                raise Exception("Downloaded file not found")
            
            with jobs_lock:
                jobs[job_id]['file_path'] = file_path
                jobs[job_id]['status'] = 'ready'
                jobs[job_id]['phase'] = 'Ready!'
                jobs[job_id]['progress'] = 100
                jobs[job_id]['title'] = info.get('title', 'video')
    
    except Exception as e:
        error_msg = str(e).lower()
        user_error = "Download failed"
        if 'login' in error_msg or 'private' in error_msg:
            user_error = "This video requires login or is private. Try YouTube/TikTok instead."
        elif 'ffmpeg' in error_msg or 'merge' in error_msg:
            user_error = "This format would require FFmpeg. Please select another quality or use Audio Only."
        elif '403' in error_msg:
            user_error = "Access forbidden (403). The video might be region-restricted."
        else:
            user_error = f"Download error: {str(e)[:100]}"
        
        with jobs_lock:
            jobs[job_id]['error'] = user_error
            jobs[job_id]['status'] = 'error'
            jobs[job_id]['phase'] = 'Error'

def progress_hook(job_id, d):
    with jobs_lock:
        if job_id not in jobs:
            return
        
        if d['status'] == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate')
            if total and total > 0:
                downloaded = d.get('downloaded_bytes', 0)
                percent = (downloaded / total) * 100
                jobs[job_id]['progress'] = min(round(percent, 1), 100)
                jobs[job_id]['phase'] = 'Downloading...'
                jobs[job_id]['status'] = 'downloading'
            else:
                jobs[job_id]['phase'] = 'Connecting...'
        
        elif d['status'] == 'finished':
            jobs[job_id]['phase'] = 'Finalizing...'
            jobs[job_id]['progress'] = 99

@app.route('/vid/progress/<job_id>')
def progress_stream(job_id):
    """Server-Sent Events for download progress using pure JSON (no jsonify)."""
    def generate():
        last_progress = -1
        last_status = None
        while True:
            with jobs_lock:
                job = jobs.get(job_id)
                if not job:
                    yield f"data: {json.dumps({'error': 'Job not found'})}\n\n"
                    break
                
                data = {
                    'status': job.get('status'),
                    'progress': job.get('progress', 0),
                    'phase': job.get('phase', ''),
                    'error': job.get('error')
                }
                
                if (data['progress'] != last_progress or data['status'] != last_status) or data.get('error'):
                    yield f"data: {json.dumps(data)}\n\n"
                    last_progress = data['progress']
                    last_status = data['status']
                
                if job.get('status') in ['ready', 'error']:
                    break
            
            time.sleep(0.5)
    
    return Response(generate(), mimetype='text/event-stream')

@app.route('/vid/file/<job_id>')
def download_file(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
        if not job or not job.get('file_path'):
            return "File not found", 404
        
        file_path = job['file_path']
        title = job.get('title', 'download')
        audio_only = job.get('audio_only', False)
        
        ext = Path(file_path).suffix
        if not ext:
            ext = '.mp4' if not audio_only else '.m4a'
        
        safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).rstrip()
        if not safe_title:
            safe_title = "vidfetch_download"
        
        download_name = f"{safe_title}{ext}"
    
    try:
        response = send_file(
            file_path,
            as_attachment=True,
            download_name=download_name,
            mimetype='application/octet-stream'
        )
        
        @response.call_on_close
        def cleanup_file():
            try:
                os.remove(file_path)
            except:
                pass
            with jobs_lock:
                if job_id in jobs:
                    del jobs[job_id]
        
        return response
    except Exception as e:
        return f"Error sending file: {str(e)}", 500

if __name__ == '__main__':
    app.run(debug=True, threaded=True, host='0.0.0.0', port=5000)