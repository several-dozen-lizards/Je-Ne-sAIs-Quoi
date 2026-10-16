"""Optional local creative editors; no household data or process launch."""
from pathlib import Path
import ipaddress

import httpx
from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

def local_request(request):
    host = request.client.host if request.client else ''
    origin = request.headers.get('origin')
    same_origin = (request.headers.get('sec-fetch-site', 'none') in {'same-origin', 'none'}
                   and (not origin or origin == str(request.base_url).rstrip('/')))
    if host == 'testclient':
        return request.url.hostname == 'testserver' and same_origin
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False
    return (loopback and request.url.hostname in {'127.0.0.1', 'localhost', '::1'}
            and same_origin)


def probe(port):
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError('Use the port shown in your Builders window (1–65535).')
    base = f'http://127.0.0.1:{port}'
    try:
        with httpx.Client(timeout=2, trust_env=False, follow_redirects=False) as client:
            response = client.get(base + '/api/builders-health')
            response.raise_for_status()
            info = response.json()
        if (not isinstance(info, dict) or info.get('application') not in
                {'jnaiq-builders', 'jnsq-builders'} or info.get('standalone') is not True):
            return {'ready': False, 'message': 'This port is not a standalone JNAIQ Builders server.'}
    except (httpx.HTTPError, ValueError):
        return {'ready': False, 'message': 'Start Builders, then check the port shown in its window.'}
    # Construct URLs ourselves. Never forward server-supplied URLs or paths.
    return {'ready': True, 'avatar_url': base + '/body-workshop',
            'world_url': base + '/island-workshop',
            'message': 'Builders is running. Open either editor below.'}


def install(app, root):
    @app.get('/builder-theme.mjs')
    def theme_script():
        return Response((Path(root)/'assets/jnaiq/island-workshop/builder-theme.mjs').read_text(encoding='utf-8'),media_type='text/javascript')

    @app.get('/builder-guide.mjs')
    def guide_script():
        return Response((Path(root)/'assets/jnaiq/island-workshop/getting-started.mjs').read_text(encoding='utf-8'),media_type='text/javascript')

    @app.get('/builders', response_class=HTMLResponse)
    def page():
        return (Path(root) / 'shell/builders.html').read_text(encoding='utf-8')

    @app.get('/api/builders/status')
    def status(request: Request, port: int = 61420):
        if not local_request(request):
            return JSONResponse({'error': 'Open Builders from the local JNAIQ window.'}, status_code=403)
        try:
            result = probe(port)
        except ValueError as exc:
            return JSONResponse({'error': str(exc)}, status_code=422)
        return JSONResponse(result, headers={'Cache-Control': 'no-store'})
