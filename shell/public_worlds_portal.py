"""Local public UI bridge to the same room host used by Chat."""
import httpx
from fastapi import Request
from fastapi.responses import JSONResponse, FileResponse
from pathlib import Path
from urllib.parse import quote


def install(app, root, base, allowed, local_member):
    @app.get('/public-worlds.mjs')
    def script():
        return FileResponse(Path(root)/'shell/public-worlds.mjs', media_type='text/javascript')

    @app.post('/api/3d/import/{kind}')
    async def import_creation(kind: str, request: Request, name: str = 'My avatar'):
        if not allowed(request, True):
            return JSONResponse({'error':'Reopen Worlds before importing.'}, status_code=403)
        if not base or kind not in {'avatar','world'}:
            return JSONResponse({'error':'The household runtime is unavailable.'}, status_code=503)
        content = bytearray()
        async for block in request.stream():
            content.extend(block)
            if len(content) > (160 if kind == 'avatar' else 32)*1024*1024:
                return JSONResponse({'error':'This file is too large.'}, status_code=413)
        try:
            async with httpx.AsyncClient(timeout=190, trust_env=False, follow_redirects=False) as client:
                response = await client.post(base+'/api/public-worlds/'+kind,
                    params={'name':name,'replace':request.query_params.get('replace',''),'revision':request.query_params.get('revision','')}, content=bytes(content))
                return JSONResponse(response.json(), status_code=response.status_code)
        except (httpx.HTTPError, ValueError):
            return JSONResponse({'error':'Import did not complete. Refresh the library before trying again.'}, status_code=503)

    @app.post('/api/3d/travel')
    async def travel(request: Request):
        if not allowed(request, True):
            return JSONResponse({'error':'Reopen Worlds before travelling.'}, status_code=403)
        if not base:
            return JSONResponse({'error':'The household runtime is unavailable.'}, status_code=503)
        try:
            data = await request.json()
            destination = data['destination']
            member = local_member()
            async with httpx.AsyncClient(timeout=20, trust_env=False, follow_redirects=False) as client:
                state = await client.get(base+'/api/world')
                state.raise_for_status()
                world = state.json()
                if destination not in world['rooms']:
                    return JSONResponse({'error':'Refresh the destination list.'}, status_code=409)
                current = world['where'].get(member)
                if current is None:
                    response = await client.post(base+'/api/join', json={'member':member,'room':'nexus'})
                    response.raise_for_status()
                    current = 'nexus'
                if current != destination:
                    response = await client.post(base+'/api/public-worlds/travel', json={'member':member,'to':destination,'expected_room':current})
                    if response.status_code >= 400:
                        return JSONResponse(response.json(), status_code=response.status_code)
                return {'ok':True, 'room':destination, 'member':member}
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return JSONResponse({'error':'Travel did not complete. Refresh before trying again.'}, status_code=503)
