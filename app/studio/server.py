"""Private/local browser launch: uvicorn app.studio.server:app --port 8000."""
from contextlib import asynccontextmanager
import hmac
import os
import re
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from app.studio.parameters import WEB
from app.studio.router import router
from app.video.router import router as video_router
from app.video.jobs import interrupt_active_video_jobs
from app.video.cinematic_assembly_jobs import recover_assembly_queue
from app.image.router import router as image_router
from app.image.jobs import interrupt_active_image_jobs
from app.studio import storage

@asynccontextmanager
async def lifespan(app):
    storage.interrupt_active_jobs()
    interrupt_active_video_jobs()
    interrupt_active_image_jobs()
    recover_assembly_queue()
    yield

app = FastAPI(title='Forma 3D Studio', version='1.6.0', lifespan=lifespan)
origins = [o.strip() for o in os.getenv('CHARACTER3D_STUDIO_ORIGINS','').split(',') if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins,
                   allow_methods=['GET','POST','PUT'], allow_headers=['Authorization','Content-Type'])

# A loopback TCP peer alone does not authenticate the browser's HTTP Host.
# Only literal local names are trusted when no studio bearer token is set.
# The synthetic TestClient host is restricted to the ASGI test peer.
_LOCAL_HOST = re.compile(r"(?:localhost|127\.0\.0\.1|\[::1\])(?::([0-9]{1,5}))?", re.I)
_TEST_HOST = re.compile(r"testserver(?::([0-9]{1,5}))?", re.I)


def _trusted_tokenless_host(request: Request) -> bool:
    hosts = request.headers.getlist('host')
    if len(hosts) != 1:
        return False
    host = hosts[0]
    peer = request.client.host if request.client else None
    match = _LOCAL_HOST.fullmatch(host)
    if match is None and peer == 'testclient':
        match = _TEST_HOST.fullmatch(host)
    if match is None:
        return False
    port = match.group(1)
    return port is None or 1 <= int(port) <= 65535


@app.middleware('http')
async def private_api(request: Request, call_next):
    if request.url.path.startswith('/api/'):
        if request.method == 'OPTIONS':
            return await call_next(request)
        secret = os.getenv('CHARACTER3D_STUDIO_TOKEN')
        supplied = request.headers.get('Authorization','').removeprefix('Bearer ')
        if secret:
            if not hmac.compare_digest(secret.encode(), supplied.encode()):
                return JSONResponse({'detail':'Studio access token required'},status_code=401)
        elif (not request.client
              or request.client.host not in {'127.0.0.1', '::1', 'testclient'}
              or not _trusted_tokenless_host(request)):
            return JSONResponse({'detail':'Tokenless API requires trusted local peer and Host'},status_code=403)
        if request.method not in {'GET','HEAD'}:
            origin = request.headers.get('Origin')
            if origin and origin not in origins and origin.rstrip('/') != str(request.base_url).rstrip('/'):
                return JSONResponse({'detail':'Origin is not allowed'},status_code=403)
    return await call_next(request)

app.include_router(router)
app.include_router(video_router)
app.include_router(image_router)
app.mount('/studio', StaticFiles(directory=WEB), name='studio')

@app.get('/')
def index():
    return FileResponse(WEB/'index.html')

@app.get('/health')
def health():
    return {'ok':True,'version':'1.6.0','studio':True}
