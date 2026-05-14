import static_ffmpeg
static_ffmpeg.add_paths()
from static_ffmpeg.run import get_or_fetch_platform_executables_else_raise

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from fastapi.background import BackgroundTasks
from pydantic import BaseModel
import os
import hmac
import httpx
import urllib.parse
import tempfile
import shutil
import asyncio
import subprocess
import threading
import time
import socket
import logging
from downloader import extract_video_info, strip_ansi
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

app = FastAPI(title="Video Downloader API")
logger = logging.getLogger(__name__)

ACCESS_CODE = os.getenv("ACCESS_CODE", "hua").strip()
DAILY_DOWNLOAD_LIMIT = int(os.getenv("DAILY_DOWNLOAD_LIMIT", "5"))
MAX_DOWNLOAD_BYTES = int(os.getenv("MAX_DOWNLOAD_BYTES", str(300 * 1024 * 1024)))
MERGE_TIMEOUT_SECONDS = int(os.getenv("MERGE_TIMEOUT_SECONDS", "180"))
download_counter_lock = threading.Lock()
download_counter: dict[tuple[str, str], int] = {}
merge_semaphore = threading.BoundedSemaphore(int(os.getenv("MERGE_CONCURRENCY", "1")))

def is_local_port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.25) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False

def get_real_ip(request: Request) -> str:
    """获取穿透代理后的真实 IP"""
    # 优先从 Cloudflare 特有头读取
    cf_ip = request.headers.get("cf-connecting-ip")
    if cf_ip:
        return cf_ip
    # 其次从标准代理头读取
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"

def require_access_code(request: Request) -> None:
    provided = (
        request.headers.get("x-access-code")
        or request.cookies.get("access_code")
        or request.query_params.get("access_code")
        or ""
    ).strip()
    if not ACCESS_CODE or not hmac.compare_digest(provided, ACCESS_CODE):
        raise HTTPException(status_code=401, detail="Invalid access code.")

def today_key() -> str:
    return time.strftime("%Y-%m-%d", time.localtime())

def reserve_download_quota(request: Request) -> None:
    ip = get_real_ip(request)
    key = (ip, today_key())
    with download_counter_lock:
        used = download_counter.get(key, 0)
        if used >= DAILY_DOWNLOAD_LIMIT:
            raise HTTPException(status_code=429, detail=f"Daily download limit reached. Each IP can download {DAILY_DOWNLOAD_LIMIT} files per day.")
        download_counter[key] = used + 1

def enforce_known_size(headers) -> None:
    raw_size = headers.get("content-length") or headers.get("Content-Length")
    if not raw_size:
        return
    try:
        size = int(raw_size)
    except ValueError:
        return
    if size > MAX_DOWNLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File is larger than the 300 MB limit.")

# 使用自定义的获取真实 IP 的函数
limiter = Limiter(key_func=get_real_ip)
app.state.limiter = limiter

@app.exception_handler(RateLimitExceeded)
async def custom_rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"success": False, "error": "今天的 5 次提取配额满啦~ 设置限额是为了把服务器资源留给真正需要的人。如果您有更多的下载需求或灵感碰撞，随时欢迎给我写信：li923745997@gmail.com"}
    )

# 静态资源目录（不使用 StaticFiles mount，因为其底层 sendfile 在 Oracle ARM 实例上对大文件传输不兼容）
os.makedirs("static", exist_ok=True)
import mimetypes

@app.get("/static/{file_path:path}")
def serve_static(file_path: str):
    """手动读取静态文件内容并返回，绕过 sendfile 系统调用兼容性问题"""
    full_path = os.path.join("static", file_path)
    if not os.path.isfile(full_path):
        raise HTTPException(status_code=404, detail="Static file not found")
    with open(full_path, "rb") as f:
        content = f.read()
    media_type, _ = mimetypes.guess_type(full_path)
    if not media_type:
        media_type = "application/octet-stream"
    return Response(content=content, media_type=media_type)

from typing import Optional

class ExtractRequest(BaseModel):
    url: str
    platform: Optional[str] = None

@app.get("/")
async def root():
    return FileResponse("static/index.html")

@app.post("/api/extract")
async def extract_video(body: ExtractRequest, request: Request):
    if not body.url:
        raise HTTPException(status_code=400, detail="Missing url")
        
    url = body.url.lower()
    detected_platform = None
    
    try:
        parsed_url = urllib.parse.urlparse(url)
        domain = parsed_url.netloc
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid URL format")
    
    if domain.endswith('youtube.com') or domain.endswith('youtu.be'):
        detected_platform = 'youtube'
    elif domain.endswith('instagram.com'):
        detected_platform = 'instagram'
    elif domain.endswith('facebook.com') or domain.endswith('fb.watch') or domain.endswith('fb.com'):
        detected_platform = 'facebook'
    elif domain.endswith('tiktok.com'):
        detected_platform = 'tiktok'
    elif domain.endswith('x.com') or domain.endswith('twitter.com'):
        detected_platform = 'twitter'
        
    if not detected_platform:
        raise HTTPException(status_code=400, detail="Unsupported URL. Only YouTube, Instagram, Facebook, TikTok, and X (Twitter) are supported.")
        
    # 调用 yt-dlp/特定API 封装提取视频信息
    result = extract_video_info(body.url, detected_platform)
    
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Unknown error extracting video"))
        
    return result

@app.get("/api/download")
async def download_video(request: Request, url: str, ext: str = "mp4"):
    """
    通过流式代理解决跨域双击或只能在新标签页打开不能直接下载的问题
    """
    require_access_code(request)
    if not url:
        raise HTTPException(status_code=400, detail="Missing url")
        
    # 根据视频 CDN 域名动态注入对应平台的完整防盗链请求头
    # TikTok CDN (tiktokcdn.com) 和 tikwm CDN 以及 Instagram CDN 均对 Referer/Cookie 做强校验
    proxy_headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        'Accept': '*/*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'identity;q=1, *;q=0',
    }
    
    url_lower = url.lower()
    if 'tiktok' in url_lower or 'tiktokcdn' in url_lower:
        proxy_headers['Referer'] = 'https://www.tiktok.com/'
        proxy_headers['Cookie'] = 'tt_csrf_token=none; tt_webid=1'
    elif 'tikwm' in url_lower:
        proxy_headers['Referer'] = 'https://www.tikwm.com/'
    elif 'instagram' in url_lower or 'cdninstagram' in url_lower:
        proxy_headers['Referer'] = 'https://www.instagram.com/'
    elif 'facebook' in url_lower or 'fbcdn' in url_lower:
        proxy_headers['Referer'] = 'https://www.facebook.com/'
    elif 'youtube' in url_lower or 'googlevideo' in url_lower:
        proxy_headers['Referer'] = 'https://www.youtube.com/'
    
    client = httpx.AsyncClient(follow_redirects=True, headers=proxy_headers, timeout=60.0)
    
    upstream_request = client.build_request("GET", url)
    try:
        response = await client.send(upstream_request, stream=True)
        if response.status_code not in (200, 206):
            await response.aclose()
            await client.aclose()
            raise HTTPException(status_code=400, detail="Forbidden or Error from upstream")
        try:
            enforce_known_size(response.headers)
        except HTTPException:
            await response.aclose()
            await client.aclose()
            raise
    except Exception as e:
        await client.aclose()
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(status_code=400, detail=str(e))
        
    async def iterfile():
        bytes_sent = 0
        try:
            async for chunk in response.aiter_bytes(chunk_size=65536):
                bytes_sent += len(chunk)
                if bytes_sent > MAX_DOWNLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="File is larger than the 300 MB limit.")
                yield chunk
        finally:
            await response.aclose()
            await client.aclose()
            
    media_type = "video/mp4" if ext == "mp4" else f"audio/{ext}" if ext in ["m4a", "mp3"] else "application/octet-stream"
                    
    reserve_download_quota(request)
    return StreamingResponse(iterfile(), media_type=media_type, headers={
        "Content-Disposition": f"attachment; filename=\"downloaded_file.{ext}\"",
        "X-Accel-Buffering": "no"
    })

@app.get("/api/proxy_image")
async def proxy_image(url: str):
    """
    专门用来突破 Instagram/Facebook 等平台对前端浏览器施加的图片防盗链和跨域拦截。
    服务器会在后台帮前端把缩略图拉好然后直接推流，对前端来说这就是同源的图。
    """
    if not url:
        raise HTTPException(status_code=400, detail="Missing image url")
        
    client = httpx.AsyncClient(follow_redirects=True, timeout=10.0, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
    })
    
    # 根据目标 URL 的域名，智能补充 Referer 头来通过 CDN 防盗链检查
    referer_map = {
        'cdninstagram.com': 'https://www.instagram.com/',
        'instagram.com': 'https://www.instagram.com/',
        'fbcdn.net': 'https://www.facebook.com/',
        'facebook.com': 'https://www.facebook.com/',
    }
    for domain, referer in referer_map.items():
        if domain in url:
            client.headers['Referer'] = referer
            client.headers['Origin'] = referer.rstrip('/')
            break
    
    try:
        response = await client.get(url)
        if response.status_code != 200:
            await client.aclose()
            # 如果源网站都拒绝给代理图，返回 404 让前端走降级
            raise HTTPException(status_code=404, detail="Image not found")
            
        content_type = response.headers.get('content-type', 'image/jpeg')
        # 一定要关闭 client
        content = response.content
        await client.aclose()
        
        return Response(content=content, media_type=content_type, headers={
            "Cache-Control": "public, max-age=86400"
        })
        
    except Exception as e:
        await client.aclose()
        raise HTTPException(status_code=404, detail="Proxy image failed")

@app.get("/api/download_merged")
def download_merged_video(request: Request, url: str, format_id: str, background_tasks: BackgroundTasks):
    """
    专门针对高画质（音画分离）视频的服务端合成接口。
    会通过 yt-dlp 拉取并在服务器合并，之后回传给客户端并自动删除。
    """
    require_access_code(request)
    if not url or not format_id:
        raise HTTPException(status_code=400, detail="Missing url or format_id")
    if not merge_semaphore.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="Another merge is already running. Please try again in a few minutes.")
        
    temp_dir = tempfile.mkdtemp(prefix="video_merge_")
    out_path = os.path.join(temp_dir, "video.mp4")
    release_in_background = False
    
    # 寻找 ffmpeg 的具体路径
    ffmpeg_exe, _ = get_or_fetch_platform_executables_else_raise()
    
    # 构建包含合并指令的 yt-dlp 进程
    cookies_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cookies.txt')
    cmd = [
        "yt-dlp",
        "-f", format_id,
        "--merge-output-format", "mp4",
        "--ffmpeg-location", ffmpeg_exe,
        "-o", out_path,
    ]
    
    # 强制将下载流体的外发流量推入代理隧道，避免传输大文件时遭阻击
    if 'youtube.com' in url.lower() or 'youtu.be' in url.lower():
        if is_local_port_open(40000):
            cmd.extend(["--proxy", "socks5://127.0.0.1:40000"])
        
    # 添加 cookies 参数（如果有 cookies.txt 文件就使用，没有就跳过）
    if os.path.exists(cookies_file):
        cmd.extend(["--cookies", cookies_file])
    cmd.append(url)
    
    # 在 FastAPI 默认的同步路由中，代码会自动抛到线程池执行，不会阻塞主线程！
    try:
        process = subprocess.run(cmd, capture_output=True, text=True, timeout=MERGE_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        shutil.rmtree(temp_dir, ignore_errors=True)
        merge_semaphore.release()
        raise HTTPException(status_code=504, detail="Merge timed out after 3 minutes.")
    
    if process.returncode != 0:
        # 合成失败时清理
        logger.warning("Merge failed for url=%s format_id=%s stderr=%s", url, format_id, strip_ansi(process.stderr)[-2000:])
        shutil.rmtree(temp_dir, ignore_errors=True)
        merge_semaphore.release()
        raise HTTPException(status_code=500, detail=f"Merge failed on server: {process.stderr}")
        
    # 如果找不到预期的输出文件
    if not os.path.exists(out_path):
        # 也许 yt-dlp 输出了其他拓展名或者名字变了，尝试寻找里面的文件
        files = os.listdir(temp_dir)
        if files:
            out_path = os.path.join(temp_dir, files[0])
        else:
            shutil.rmtree(temp_dir, ignore_errors=True)
            merge_semaphore.release()
            raise HTTPException(status_code=500, detail="Merged file not found on server")

    # 分配后台任务去删除临时目录
    if os.path.getsize(out_path) > MAX_DOWNLOAD_BYTES:
        shutil.rmtree(temp_dir, ignore_errors=True)
        merge_semaphore.release()
        raise HTTPException(status_code=413, detail="File is larger than the 300 MB limit.")

    reserve_download_quota(request)

    def cleanup_temp_dir():
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        finally:
            merge_semaphore.release()
        
    background_tasks.add_task(cleanup_temp_dir)
    release_in_background = True
    
    return FileResponse(
        out_path, 
        media_type="video/mp4", 
        headers={
            "Content-Disposition": "attachment; filename=\"downloaded_merged_video.mp4\"",
            "X-Accel-Buffering": "no"
        }
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
