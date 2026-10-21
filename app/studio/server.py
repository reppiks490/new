"""Private/local browser launch: uvicorn app.studio.server:app --port 8000."""
from contextlib import asynccontextmanager
import hmac
import os
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from app.studio.parameters import WEB
from app.studio.router import router
from app.video.router import router as video_router
from app.video.jobs import interrupt_active_video_jobs
from app.studio import storage

@asynccontextmanager
async def lifespan(app):
    storage.interrupt_active_jobs()
    interrupt_active_video_jobs()
    yield

app = FastAPI(title='Forma 3D Studio', version='1.6.0', lifespan=lifespan)
origins = [o.strip() for o in os.getenv('CHARACTER3D_STUDIO_ORIGINS','').split(',') if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins,
                   allow_methods=['GET','POST','PUT'], allow_headers=['Authorization','Content-Type'])

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
        elif not request.client or request.client.host not in {'127.0.0.1','::1','testclient'}:
            return JSONResponse({'detail':'Remote API access requires CHARACTER3D_STUDIO_TOKEN'},status_code=403)
        if request.method not in {'GET','HEAD'}:
            origin = request.headers.get('Origin')
            if origin and origin not in origins and origin.rstrip('/') != str(request.base_url).rstrip('/'):
                return JSONResponse({'detail':'Origin is not allowed'},status_code=403)
    return await call_next(request)

app.include_router(router)
app.include_router(video_router)
app.mount('/studio', StaticFiles(directory=WEB), name='studio')

@app.get('/')
def index():
    return FileResponse(WEB/'index.html')

@app.get('/health')
def health():
    return {'ok':True,'version':'1.6.0','studio':True}
