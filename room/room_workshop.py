"""Offline layout drafts; runtime objects retain their identity and private state.

Only placement is patched on existing objects. New objects use RoomObject and
normal room perception/capability paths. Offline Apply queues a one-shot patch;
the editor never writes the running household's persistence file.
"""
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import threading
import uuid
from types import SimpleNamespace

from fastapi import Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from shell.runtime_paths import load_run_state

SCHEMA = 'jnsq-room-layout/1'
PLACEMENT = ('position_m', 'rot_deg', 'size_m', 'y_off_m', 'support_surface', 'support_oid', 'light_settings', 'power')
SEMANTICS = ('name', 'kind', 'description', 'texture', 'capability', 'owner', 'affordances', 'mass_kg')
LOCK = threading.RLock()
OBJECT_TYPES = {entry['id'] for entry in json.loads((Path(__file__).resolve().parents[1]/'assets/jnaiq/island-workshop/object-types.json').read_text(encoding='utf-8'))}


def validate_catalog_types(value):
    if not isinstance(value, list) or len(value)>len(OBJECT_TYPES) or any(not isinstance(v,str) or v not in OBJECT_TYPES for v in value):
        raise ValueError('Choose valid object types')
    return list(dict.fromkeys(value)) or ['other']


def ident(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,100}', value):
        raise ValueError('Invalid identifier')
    return value


def digest(objects):
    stable = {k: {f: v.get(f) for f in (*PLACEMENT, *SEMANTICS)} for k, v in objects.items()}
    return hashlib.sha256(json.dumps(stable, sort_keys=True, allow_nan=False).encode()).hexdigest()


def atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(value, f, ensure_ascii=False, allow_nan=False)
            f.flush(); os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


def validate_objects(objects, *, room_range=True):
    if not isinstance(objects, dict) or len(objects) > 1000:
        raise ValueError('A layout supports up to 1,000 furniture objects')
    result = copy.deepcopy(objects)
    for oid, obj in result.items():
        ident(oid)
        if not isinstance(obj, dict): raise ValueError('Invalid object')
        p = obj.get('position_m')
        if not isinstance(p, list) or len(p) != 2: raise ValueError('An object needs two ground coordinates')
        for v in [*p, obj.get('rot_deg', 0), obj.get('size_m', .6), obj.get('y_off_m', 0)]:
            if type(v) not in (int, float) or not math.isfinite(v): raise ValueError('Object coordinates must be finite numbers')
        # Existing architectural sites are larger than furniture. Preserve
        # them in a draft; the apply path bounds new/edited furniture below.
        if not .02 <= obj.get('size_m', .6) <= 240: raise ValueError('Invalid object size')
        # Room layouts have a deliberately compact editing envelope. Island
        # drafts use terrain-relative heights and enforce their horizontal
        # footprint in validate_world(), so applying this room-only ceiling
        # there rejects otherwise representable authored placements.
        if room_range and (max(abs(p[0]), abs(p[1])) > 240 or not -12 <= obj.get('y_off_m', 0) <= 100):
            raise ValueError('Object is outside the supported world range')
        if obj.get('support_surface', 'yurt_floor') not in ('yurt_floor', 'yurt_wall', 'island_ground', 'object', 'free'):
            raise ValueError('Unknown object support')
        if not isinstance(obj.get('name'), str) or not 1 <= len(obj['name'].strip()) <= 160:
            raise ValueError('Each object needs a name, up to 160 characters')
        for key in ('kind', 'owner', 'capability', 'support_oid'):
            if obj.get(key) is not None and (not isinstance(obj[key], str) or len(obj[key]) > 100):
                raise ValueError('Invalid '+key)
        if obj.get('kind'): ident(obj['kind'])
        for key in ('description', 'texture'):
            if not isinstance(obj.get(key, ''), str) or len(obj.get(key, '')) > 4000: raise ValueError('Invalid '+key)
        if re.fullmatch(r'(fabric_curtain_(pair|closed|cafe)|rug_(rectangle|round|runner))', obj.get('kind') or '') and not (re.fullmatch(r'#[0-9a-fA-F]{6}',obj.get('texture','')) or re.fullmatch(r'custom_[a-f0-9-]{36}',obj.get('texture',''))):
            raise ValueError('Textiles need a colour or uploaded image')
        obj.setdefault('power', 0.0)
        obj.setdefault('light_settings', None)
        if type(obj['power']) not in (int,float) or not math.isfinite(obj['power']) or not 0 <= obj['power'] <= 1: raise ValueError('Invalid light power')
        light = obj.get('light_settings')
        if light is not None:
            if not isinstance(light, dict) or not re.fullmatch(r'#[0-9a-fA-F]{6}', str(light.get('color', ''))): raise ValueError('Invalid light colour')
            for key, low, high in [('intensity',0,100),('range_m',.2,30),('height_m',0,30)]:
                v = light.get(key)
                if type(v) not in (int,float) or not math.isfinite(v) or not low <= v <= high: raise ValueError('Invalid light '+key)
        aff = obj.get('affordances', {})
        if not isinstance(aff, dict) or len(aff) > 80 or any(not isinstance(k, str) or type(v) not in (float, int) or not math.isfinite(v) for k,v in aff.items()):
            raise ValueError('Invalid affordances')
        if type(obj.get('mass_kg', 1)) not in (int,float) or not math.isfinite(obj.get('mass_kg', 1)) or obj.get('mass_kg',1) <= 0:
            raise ValueError('Invalid object mass')
    return result


def new_object(oid, record):
    from room.state import RoomObject
    allowed = {k: record[k] for k in (*PLACEMENT, *SEMANTICS) if k in record}
    return RoomObject(oid, **allowed)


def apply_layout(room, draft, commit=True):
    """Validate the entire candidate before changing any live object."""
    from room.host import _object_support_error
    current = {k: o.snapshot() for k,o in room.objects.items()}
    if draft.get('base_revision') != digest(current):
        raise FileExistsError('This room changed since the draft was opened. Reopen the room to make a fresh draft; your saved draft is kept.')
    objects = validate_objects(draft.get('objects'))
    removed = set(current) - set(objects)
    if room.members and any(room.objects[oid].capability == 'portal' for oid in removed) and not any(o.get('capability') == 'portal' for o in objects.values()):
        raise ValueError('Everyone must leave before the last teleporter in this world is removed.')
    for oid in removed:
        obj = room.objects[oid]
        if obj.pages or obj.owner or obj.capability in ('private_writing', 'commons_board'):
            raise ValueError('Keep '+obj.name+': it is an owned object or writing surface. Move it instead.')
    staged = copy.copy(room)
    staged.objects = {oid: copy.copy(obj) for oid,obj in room.objects.items() if oid in objects}
    changed = []
    for oid, rec in objects.items():
        if oid in current:
            obj = staged.objects[oid]
            if any(rec.get(f) != current[oid].get(f) for f in SEMANTICS):
                raise ValueError('Existing object meaning is preserved; edit only its placement: '+oid)
            if all(rec.get(f) == current[oid].get(f) for f in PLACEMENT): continue
            for field in PLACEMENT:
                if field in rec: setattr(obj, field, copy.deepcopy(rec[field]))
        else:
            if oid in room.members: raise ValueError('Object identifier conflicts with a resident')
            if rec.get('capability') not in (None, '', 'sitting', 'writing', 'private_writing', 'light', 'portal'):
                raise ValueError('Choose an ordinary furniture capability for a new object')
            if rec.get('capability') == 'private_writing' and not rec.get('owner'):
                raise ValueError('A private writing desk needs an owner')
            staged.objects[oid] = new_object(oid, rec)
        if not .02 <= staged.objects[oid].size_m <= 6:
            raise ValueError('Edited furniture size must be between 0.02 and 6 metres')
        changed.append(oid)
    # Validate dependants too when their supporting furniture has moved.
    for oid,obj in staged.objects.items():
        if oid not in changed and obj.support_oid not in changed and obj.support_oid not in removed: continue
        error = _object_support_error(staged, oid, obj.position_m, obj.size_m, obj.support_surface, obj.support_oid)
        if error: raise ValueError(error)
        if obj.capability == 'portal':
            from room.teleporters import landing
            landing(staged, oid, '__teleporter_placement__')
    if not commit: return {'ok':True}
    for oid in changed:
        if oid in room.objects:
            # Keep the very same object instance, including pages and readers.
            for field in PLACEMENT: setattr(room.objects[oid], field, copy.deepcopy(getattr(staged.objects[oid], field)))
        else: room.objects[oid] = staged.objects[oid]
    for oid in removed: del room.objects[oid]
    for oid in changed:
        room.emit('world_workshop', 'object_updated' if oid in current else 'object_added',
                  {'oid':oid, 'snapshot':room.object_snapshot(room.objects[oid]), 'position_m':room.objects[oid].position_m})
    for oid in removed: room.emit('world_workshop', 'object_removed', {'oid':oid})
    return {'ok':True, 'changed':changed, 'removed':sorted(removed),
            'base_revision':digest({k:o.snapshot() for k,o in room.objects.items()})}


def merge_furniture(room, previous, furniture, commit=True):
    previous=validate_objects(previous)
    furniture=validate_objects(furniture)
    current={k:o.snapshot() for k,o in room.objects.items()}
    candidate=copy.deepcopy(current)
    for oid,record in furniture.items():
        if oid not in previous:
            if oid in current: raise FileExistsError('Furniture identifier already exists: '+oid)
            candidate[oid]=record
        elif record != previous[oid]:
            if any(record.get(f)!=previous[oid].get(f) for f in SEMANTICS):
                raise ValueError('Published furniture keeps its meaning and ownership. Adjust its placement, or add a new object: '+oid)
            if oid not in current or any(current[oid].get(f)!=previous[oid].get(f) for f in PLACEMENT):
                raise FileExistsError('Furniture moved in JNAIQ since this landscape was published: '+oid)
            for f in PLACEMENT:candidate[oid][f]=copy.deepcopy(record.get(f))
    for oid in set(previous)-set(furniture):
        if oid in current and any(current[oid].get(f)!=previous[oid].get(f) for f in PLACEMENT):
            raise FileExistsError('This object moved in JNAIQ. Keep it in this draft: '+oid)
        candidate.pop(oid,None)
    return apply_layout(room,{'objects':candidate,'base_revision':digest(current)},commit=commit)


class RoomWorkshop:
    def __init__(self, repo, app=None, root=None):
        self.repo = Path(repo); self.app = app
        self.root = Path(root or os.environ.get('JNAIQ_ROOM_DRAFTS') or self.repo/'state'/'room_layouts')

    def offline_rooms(self):
        # Read saved records through the canonical restoration code without
        # launching any host lifespan, weather worker, or resident process.
        from room import host
        from room.layout import build_world, build_persona_den
        from room.world_destinations import Destinations
        world = build_world()
        context = SimpleNamespace(state=SimpleNamespace(rooms=world['rooms'], adjacency=world['adjacency'], where={},seed_ids={}))
        saved = json.loads(Path(host.STATE_FILE).read_text(encoding='utf-8')) if Path(host.STATE_FILE).exists() else {}
        for rid in saved.get('rooms', {}):
            if rid.endswith('_den') and rid not in context.state.rooms:
                context.state.rooms[rid] = build_persona_den(rid[:-4], rid[:-4].replace('_',' ').title())
        Destinations(self.repo, context).sync()
        context.state.seed_ids = {rid:set(r.objects) for rid,r in context.state.rooms.items()}
        if saved and not host._load_world(context): raise ValueError('The saved household could not be restored. No changes were made.')
        return context.state.rooms

    def snapshot(self, room):
        objects = {oid:o.snapshot() for oid,o in room.objects.items()}
        base = []
        names = [] if room.scene == 'workshop' else ['island_world.glb','island_scatter.glb','nexus_stones.glb','yurt_den.glb'] if room.scene == 'island' else [room.id+'.glb'] if room.walkable else ['yurt_den.glb']
        for name in names:
            if (self.repo/'godot-room'/'assets'/name).is_file(): base.append('/api/room-workshop/assets/world/'+name)
        return {'schema':SCHEMA, 'room_id':room.id, 'name':room.name, 'scene':room.scene,
                'radius_m':room.radius_m, 'walkable':room.walkable, 'base_models':base,
                'destination':getattr(room,'destination',None), 'objects':objects,
                'base_revision':digest(objects)}

    def proxy(self, method, path, payload=None):
        if self.app is not None: return None
        import httpx
        try:
            port = int(load_run_state(self.repo)['room_port'])
            if not 1 <= port <= 65535: raise ValueError('Invalid room host port')
            with httpx.Client(timeout=15, trust_env=False) as client:
                probe = client.get(f'http://127.0.0.1:{port}/api/room-workshop/health')
                if probe.status_code != 200 or not probe.json().get('shared'):
                    if method != 'GET': raise ValueError('Restart JNAIQ once to load the workshop object bridge. Save your draft in the meantime.')
                    return None
                response = client.request(method, f'http://127.0.0.1:{port}'+path, json=payload)
                return JSONResponse(status_code=response.status_code, content=response.json())
        except (OSError, KeyError, httpx.ConnectError): return None

    def save(self, draft, draft_id=None, revision=None):
        if draft.get('schema') != SCHEMA: raise ValueError('Unsupported room layout file')
        ident(draft.get('room_id')); validate_objects(draft.get('objects'))
        if not isinstance(draft.get('base_revision'), str): raise ValueError('Layout has no source revision')
        key = ident(draft_id) if draft_id else uuid.uuid4().hex
        path = self.root/'drafts'/(key+'.json')
        with LOCK:
            if draft_id:
                old = json.loads(path.read_text(encoding='utf-8'))
                if old['revision'] != revision: raise FileExistsError('This draft changed in another window. Save a copy to keep your version.')
            value = {'id':key, 'revision':uuid.uuid4().hex, 'world':draft}
            atomic(path, value)
        return value


def apply_pending(app, repo):
    manager = RoomWorkshop(repo, app)
    for path in (manager.root/'pending').glob('*.json'):
        draft = json.loads(path.read_text(encoding='utf-8'))
        try:
            room = app.state.rooms[draft['room_id']]
            result = apply_layout(room, draft)
            from room.host import _save_world
            _save_world(app)
        except (ValueError, KeyError, FileExistsError) as exc:
            result = {'ok':False,'error':str(exc)}
        atomic(manager.root/'receipts'/path.name, result)
        path.unlink()


def install(app, repo):
    manager = RoomWorkshop(repo, app if hasattr(app.state,'rooms') else None)

    def guarded(fn):
        try: return fn()
        except FileExistsError as e: return JSONResponse(status_code=409,content={'error':str(e)})
        except FileNotFoundError: return JSONResponse(status_code=404,content={'error':'Layout or asset not found'})
        except (ValueError,TypeError,KeyError) as e: return JSONResponse(status_code=400,content={'error':str(e)})

    @app.get('/room-workshop')
    def page(room: str = ''):
        return RedirectResponse('/assets/island-workshop/room.html'+('?room='+ident(room) if room else ''))

    @app.get('/api/room-workshop/health')
    def health(): return {'shared':manager.app is not None,'schema':SCHEMA}

    @app.get('/api/room-workshop/asset-delivery')
    def asset_delivery():
        return {'schema': 'jnaiq-asset-delivery/1', 'quality': 'standard'}

    @app.get('/api/room-workshop/asset-delivery')
    def asset_delivery():
        return {'schema': 'jnaiq-asset-delivery/1', 'quality': 'standard'}

    @app.get('/api/room-workshop/rooms')
    def rooms():
        def run():
            proxy = manager.proxy('GET','/api/room-workshop/rooms')
            if proxy is not None:return proxy
            source = app.state.rooms if manager.app is not None else manager.offline_rooms()
            return {'rooms':[{'id':r.id,'name':r.name} for r in source.values()], 'live':manager.app is not None}
        return guarded(run)

    @app.get('/api/room-workshop/rooms/{rid}')
    def read(rid:str):
        def run():
            ident(rid)
            proxy=manager.proxy('GET','/api/room-workshop/rooms/'+rid)
            if proxy is not None:return proxy
            source=app.state.rooms if manager.app is not None else manager.offline_rooms()
            return manager.snapshot(source[rid])
        return guarded(run)

    @app.get('/api/room-workshop/drafts')
    def drafts():
        values=[json.loads(p.read_text(encoding='utf-8')) for p in (manager.root/'drafts').glob('*.json')]
        receipts={p.stem:json.loads(p.read_text(encoding='utf-8')) for p in (manager.root/'receipts').glob('*.json')}
        return {'drafts':[{'id':v['id'],'name':v['world']['name'],'room_id':v['world']['room_id']} for v in values], 'receipts':receipts}

    @app.get('/api/room-workshop/drafts/{key}')
    def draft(key:str):
        return guarded(lambda:json.loads((manager.root/'drafts'/(ident(key)+'.json')).read_text(encoding='utf-8')))

    @app.post('/api/room-workshop/drafts')
    async def save(request:Request):
        body=await request.body()
        if len(body)>4_000_000:return JSONResponse(status_code=413,content={'error':'Layout exceeds 4 MB'})
        return guarded(lambda:manager.save(**json.loads(body)))

    @app.post('/api/room-workshop/apply')
    async def apply(request:Request):
        body=await request.body()
        if len(body)>4_000_000:return JSONResponse(status_code=413,content={'error':'Layout exceeds 4 MB'})
        def run():
            draft=json.loads(body); rid=ident(draft['room_id'])
            if draft.get('schema') != SCHEMA:raise ValueError('Unsupported layout')
            proxy=manager.proxy('POST','/api/room-workshop/apply',draft)
            if proxy is not None:return proxy
            if manager.app is not None:
                return apply_layout(app.state.rooms[rid],draft)
            # Validate against a read-only reconstruction before scheduling.
            apply_layout(manager.offline_rooms()[rid],draft)
            atomic(manager.root/'pending'/(rid+'.json'),draft)
            return {'ok':True,'queued':True,'message':'Layout will apply when JNAIQ next starts.'}
        return guarded(run)

    @app.get('/api/room-workshop/catalog')
    def catalog():
        from room.host import _object_asset_root, _catalog_item
        root=Path(_object_asset_root())
        files=sorted(p.name for p in root.glob('*') if p.suffix.lower() in ('.glb','.png','.jpg','.jpeg'))
        models={Path(f).stem for f in files if f.lower().endswith('.glb')}
        items=[]
        for f in files:
            stem=Path(f).stem
            if not f.lower().endswith('.glb') and (stem in models or any(stem.startswith(m+'_') for m in models)):continue
            try:metadata=json.loads((root/(f+'.scenery.json')).read_text(encoding='utf-8')).get('metadata',{})
            except (OSError,ValueError):metadata={}
            item=_catalog_item(stem,{'format':Path(f).suffix[1:],'filename':f,'metadata':metadata})
            if f.lower().endswith('.glb') and item.get('thumbnail_ready'):
                item['thumbnail_url']='/api/room-workshop/thumbnails/'+stem+'.png'
            if f.lower().endswith('.glb') and item.get('thumbnail_ready'):
                item['thumbnail_url']='/api/room-workshop/thumbnails/'+stem+'.png'
            if isinstance(metadata,dict) and 'categories' in metadata:
                try:item['categories']=validate_catalog_types(metadata['categories'])
                except ValueError:pass
            items.append(item)
        return {'files':files,'items':items,'multi_category_import':True}

    @app.post('/api/room-workshop/import-model')
    async def import_model(request:Request):
        from urllib.parse import unquote
        from room.host import _object_asset_root
        from core.body_packages import inspect_glb
        name=Path(unquote(request.headers.get('x-jnaiq-filename') or request.headers.get('x-jnsq-filename',''))).name
        suffix=Path(name).suffix.lower();stem=re.sub(r'[^a-z0-9]+','_',Path(name).stem.lower()).strip('_')[:90]
        if not stem or suffix not in ('.glb','.png','.jpg','.jpeg'):
            return JSONResponse(status_code=400,content={'error':'Choose a GLB model or PNG/JPEG picture'})
        try:
            raw_types=request.headers.get('x-jnaiq-categories') or request.headers.get('x-jnsq-categories')
            categories=validate_catalog_types(json.loads(raw_types)) if raw_types is not None else None
        except (ValueError,TypeError):
            return JSONResponse(status_code=400,content={'error':'Choose valid object types'})
        data=bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data)>160*1024*1024:return JSONResponse(status_code=413,content={'error':'Model exceeds 160 MB'})
        def run():
            root=Path(_object_asset_root());root.mkdir(parents=True,exist_ok=True)
            with LOCK:
                target=root/(stem+suffix)
                if target.exists():raise FileExistsError('That model already exists. Choose it from the catalog, or rename the file to import a new version.')
                fd,tmp=tempfile.mkstemp(dir=root,suffix=suffix)
                try:
                    with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
                    if suffix=='.glb':
                        inspect_glb(tmp)
                        import struct
                        length=struct.unpack_from('<I',data,12)[0]
                        doc=json.loads(data[20:20+length])
                        for resource in doc.get('images',[])+doc.get('buffers',[]):
                            uri=resource.get('uri','')
                            if uri and not uri.startswith('data:'):raise ValueError('Export a self-contained GLB with embedded textures before importing it')
                    else:
                        from PIL import Image
                        try:
                            with Image.open(tmp) as picture:picture.verify()
                        except OSError as exc:
                            raise ValueError('Choose a valid PNG/JPEG picture') from exc
                    sidecar=root/(target.name+'.scenery.json')
                    if categories is not None:
                        if sidecar.exists():raise FileExistsError('Object metadata already exists; rename this import')
                        atomic(sidecar,{'metadata':{'categories':categories}})
                    try:os.rename(tmp,target)
                    except Exception:
                        if categories is not None:sidecar.unlink(missing_ok=True)
                        raise
                finally:
                    if os.path.exists(tmp):os.unlink(tmp)
            return {'ok':True,'kind':stem,'filename':target.name}
        return guarded(run)

    @app.get('/api/room-workshop/thumbnails/{filename}')
    def thumbnail(filename:str):
        def run():
            from room.host import _object_asset_root
            if Path(filename).name != filename or Path(filename).suffix.lower()!='.png':raise ValueError('Unsupported thumbnail')
            root=(Path(_object_asset_root())/'.thumbnails').resolve();path=(root/filename).resolve()
            if path.parent!=root or not path.is_file():raise FileNotFoundError()
            return FileResponse(path)
        return guarded(run)

    @app.get('/api/room-workshop/thumbnails/{filename}')
    def thumbnail(filename:str):
        def run():
            from room.host import _object_asset_root
            if Path(filename).name != filename or Path(filename).suffix.lower()!='.png':raise ValueError('Unsupported thumbnail')
            root=(Path(_object_asset_root())/'.thumbnails').resolve();path=(root/filename).resolve()
            if path.parent!=root or not path.is_file():raise FileNotFoundError()
            return FileResponse(path)
        return guarded(run)

    @app.get('/api/room-workshop/assets/{category}/{filename}')
    def asset(category:str,filename:str):
        def run():
            from room.host import _object_asset_root
            if Path(filename).name != filename or Path(filename).suffix.lower() not in ('.glb','.png','.jpg','.jpeg'):raise ValueError('Unsupported asset')
            root=Path(_object_asset_root()) if category=='objects' else manager.repo/'godot-room'/'assets' if category=='world' else None
            if root is None:raise ValueError('Unknown asset category')
            path=(root/filename).resolve()
            if path.parent != root.resolve() or not path.is_file():raise FileNotFoundError()
            if category == 'objects' and path.suffix.lower() == '.glb':
                from core.asset_delivery import model_path
                path = Path(model_path(path))
            return FileResponse(path)
        return guarded(run)
