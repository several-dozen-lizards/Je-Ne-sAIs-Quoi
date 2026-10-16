"""Public distribution adapter for existing avatar and destination owners.

Installed only by the public staging tool. This module does not start services
or inspect another installation, and owns no separate presence state.
"""
from pathlib import Path
import json
from fastapi import Request
from fastapi.responses import JSONResponse
from core.body_packages import BodyPackageError


def prepare(app, repo):
    from room.world_destinations import Destinations
    app.state.world_destinations = Destinations(repo, app)
    app.state.world_destinations.sync()


def install(app, repo, candidates):
    from room.avatar_library_routes import install as install_avatars
    from room.island_workshop import IslandStore
    from room.world_destinations import install as install_destinations
    from starlette.middleware.trustedhost import TrustedHostMiddleware
    root = Path(repo)
    store = IslandStore(root/'state/islands')
    install_avatars(app, repo, candidates)
    install_destinations(app, repo, store)
    from fastapi.staticfiles import StaticFiles
    app.mount('/assets/island-workshop', StaticFiles(directory=root/'assets/jnaiq/island-workshop'), name='public-world-assets')

    @app.get('/3d/')
    def current_view(member: str = 'user'):
        from fastapi.responses import RedirectResponse
        from urllib.parse import quote
        room = app.state.rooms.get(app.state.where.get(member))
        destination = getattr(room, 'destination', None)
        if destination:
            return RedirectResponse(destination['url']+'&member='+quote(member, safe=''))
        return RedirectResponse('/?member='+quote(member, safe=''))

    @app.post('/api/public-worlds/travel')
    def travel_between_worlds(values: dict):
        # Host middleware holds its ordinary world mutation lock across both
        # legs. Reuse its travel endpoint rather than maintain another ledger.
        from room.host import TravelReq
        member = values.get('member')
        target = values.get('to')
        current = app.state.where.get(member)
        if current is None or target not in app.state.rooms:
            return JSONResponse({'error':'Join the household and choose an existing destination.'}, status_code=409)
        if values.get('expected_room') not in (None,current):
            return JSONResponse({'error':'Your location changed. Reopen the travel menu.'}, status_code=409)
        if current == target:
            return {'ok':True,'from':current,'to':target}
        try:
            app.state.rooms[target].prepare_join(member)
            route = next(route.endpoint for route in app.routes if getattr(route,'path','')=='/api/travel')
            if target not in app.state.adjacency.get(current,[]):
                result = route(TravelReq(member=member,to='nexus'))
                if isinstance(result,JSONResponse):return result
            return route(TravelReq(member=member,to=target))
        except (ValueError,KeyError,TypeError) as exc:
            return JSONResponse({'error':str(exc)},status_code=409)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', 'testserver'])

    @app.middleware('http')
    async def local_mutations(request, call_next):
        origin = request.headers.get('origin')
        if request.method not in {'GET','HEAD','OPTIONS'} and origin and origin != str(request.base_url).rstrip('/'):
            return JSONResponse({'error':'Open this household locally before making changes.'}, status_code=403)
        response = await call_next(request)
        if request.url.path.startswith('/assets/island-workshop/'):
            response.headers['Cache-Control'] = 'no-cache, must-revalidate'
        return response

    async def bounded(request, limit):
        result = bytearray()
        async for part in request.stream():
            result.extend(part)
            if len(result) > limit:
                raise ValueError('This file is too large.')
        return bytes(result)

    @app.post('/api/public-worlds/avatar')
    async def import_avatar(request: Request, name: str):
        from core.body_candidates import CandidateStager, save_candidate_mapping
        from core.avatar_library import publish
        stager = None
        try:
            if not 1 <= len(name.strip()) <= 64:
                raise ValueError('Use an avatar name of 1–64 characters.')
            raw = await bounded(request, 160*1024*1024)
            stager = CandidateStager(candidates(), 'avatar.glb', 'starter_persona')
            stager.write(raw)
            candidate = stager.finalize()['candidate_id']
            # Imported GLBs retain their geometry and authored morph values.
            # An empty semantic mapping claims no reviewed eyes or rig roles.
            save_candidate_mapping(candidates(), candidate, 'starter_persona', {})
            return publish(app.state.avatar_library_root, candidates(), candidate, name)
        except (BodyPackageError, ValueError, TypeError) as exc:
            if stager:
                stager.abort()
            return JSONResponse({'error':str(exc)}, status_code=422)

    @app.post('/api/public-worlds/world')
    async def import_world(request: Request, replace: str = '', revision: str = ''):
        try:
            if not (root/'PUBLIC_3D_INSTALLED.json').is_file():
                raise ValueError('Run INSTALL_3D_RUNTIME.bat in this public JNAIQ folder before importing worlds.')
            payload = json.loads(await bounded(request, 32*1024*1024))
            if not isinstance(payload, dict):
                raise ValueError('Choose an exported world JSON object.')
            world = payload.get('world', payload)
            from room.world_destinations import PUBLICATION_LOCK
            with PUBLICATION_LOCK:
                manager = app.state.world_destinations
                if replace and manager.load(replace)['revision'] != revision:
                    raise FileExistsError('This world changed. Refresh before importing an update.')
                saved = store.save(world)
                return manager.publish(store.load(saved['id']), replace_ident=replace or None)
        except FileExistsError as exc:
            return JSONResponse({'error':str(exc)}, status_code=409)
        except (ValueError, TypeError, KeyError, OSError) as exc:
            return JSONResponse({'error':str(exc)}, status_code=422)


def snapshot(app, repo, room, member):
    from core.avatar_library import assignments
    from core.avatar_identities import member_keys
    value = room.snapshot(observer=member)
    records = assignments(app.state.avatar_library_root)
    aliases = member_keys(repo)
    for name, body in value['members'].items():
        key = aliases.get(name.casefold(), name.casefold())
        body['avatar_package'] = records.get(key, {}).get('package_id')
    return value
