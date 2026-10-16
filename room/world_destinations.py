"""Publish workshop revisions as persistent, shared household destinations."""
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time

from fastapi import Request
from fastapi.responses import JSONResponse
from room.island_workshop import IslandStore, validate_world
from room.workshop_navigation import Navigation
from shell.runtime_paths import load_run_state

PUBLICATION_LOCK = threading.RLock()


class Destinations:
    def __init__(self, repo, app=None, root=None):
        self.repo = Path(repo)
        self.app = app
        self.root = Path(root or os.environ.get('JNAIQ_WORLD_DESTINATIONS_DIR') or self.repo/'state'/'world_destinations')
        self.loaded = {}
        self.retired_cache = {}

    def path(self, ident):
        return IslandStore(self.root).path(ident)

    def load(self, ident):
        path = self.path(ident)
        stamp = path.stat().st_mtime_ns
        cached = self.retired_cache.get(ident)
        if cached and cached[0] == stamp:
            return cached[1]
        value = json.loads(path.read_text(encoding='utf-8'))
        from room.island_retired_content import remove_retired_caves
        world = remove_retired_caves(value['world'])
        if world != value['world'] or value.get('collision',{}).get('schema') != 'jnsq-world-collision/2':
            # Retain the published world and revision. Upgrade derived collision
            # data in memory when geometry or traversal rules change.
            collision, digest = self.compile(world)
            arrival = Navigation(world, collision).arrival() if world != value['world'] else value['arrival']
            value.update(world=world, collision=collision, geometry_sha256=digest, arrival=arrival)
            self.retired_cache[ident] = (stamp, value)
        return value

    def compile(self, world):
        node = shutil.which('node')
        if not node:
            raise ValueError('World publishing needs Node.js to compile the builder geometry.')
        compiler = self.repo/'assets/jnaiq/island-workshop/compile-collision.mjs'
        result = subprocess.run([node, str(compiler)], input=json.dumps(world), text=True,
                                capture_output=True, timeout=180, encoding='utf-8')
        if result.returncode:
            raise ValueError('World geometry could not compile: '+result.stderr[-1200:])
        return json.loads(result.stdout), hashlib.sha256(result.stdout.encode()).hexdigest()

    def index(self):
        return [{k:v[k] for k in ('id','revision','room_id','name')} for v in (self.load(p.stem) for p in self.root.glob('*.json'))]

    @staticmethod
    def load_receipt(value):
        world_digest = hashlib.sha256(json.dumps(
            value['world'], sort_keys=True, separators=(',', ':'),
            allow_nan=False).encode('utf-8')).hexdigest()
        revision = value['revision']
        return {'load_ready': True, 'content_sha256': world_digest,
                'load_url': '/assets/island-workshop/visit.html?visit=' +
                value['id'] + '&revision=' + revision}

    def publish(self, source, replace_ident=None):
        world=validate_world(source['world'])
        source_ident=source['id'];self.path(source_ident)
        ident=replace_ident or source_ident;target_path=self.path(ident)
        rid='workshop_'+ident
        with PUBLICATION_LOCK:
            if replace_ident:
                if not target_path.exists():
                    raise FileNotFoundError('The JNAIQ world being replaced no longer exists. Refresh the world list and try again.')
                target=self.load(ident)
                if str(target.get('name','')).strip().casefold()!=str(world['name']).strip().casefold():
                    raise ValueError('The replacement world has a different name. Refresh the destination list before publishing.')
            source_rid='workshop_'+source_ident
            occupied=[]
            if self.app:
                for candidate in {rid,source_rid}:
                    room=self.app.state.rooms.get(candidate)
                    if room and room.members:occupied.append(room.name)
            if occupied:
                raise FileExistsError('This destination is occupied. Save your draft now; update the visited version after everyone has left.')
            if self.app and rid in self.app.state.rooms:
                from room.room_workshop import merge_furniture
                previous = self.load(ident)['world'].get('furniture', {})
                merge_furniture(self.app.state.rooms[rid], previous, world.get('furniture', {}), commit=False)
            collision,digest=self.compile(world)
            navigation=Navigation(world,collision)
            arrival=navigation.arrival()
            # Check every gate against the new geometry before replacing the
            # publication, including gates unchanged by a terrain edit.
            from room.state import Room
            from room.room_workshop import new_object
            from room.teleporters import landing
            staged=Room(rid,world['name'],world['size'],scene='workshop')
            staged.navigation=navigation
            staged.objects={oid:new_object(oid,record) for oid,record in world.get('furniture',{}).items()}
            for oid,obj in staged.objects.items():
                if obj.capability == 'portal':
                    landing(staged,oid,'__teleporter_publication__')
            value={'id':ident,'draft_id':source_ident,'revision':source['revision'],'room_id':rid,'name':world['name'],
                   'world':world,'collision':collision,'arrival':arrival,
                   'geometry_sha256':digest, 'portal_schema': 1}
            self.root.mkdir(parents=True,exist_ok=True)
            fd,tmp=tempfile.mkstemp(dir=self.root,prefix='.publishing-',suffix='.tmp')
            try:
                with os.fdopen(fd,'w',encoding='utf-8') as f:
                    json.dump(value,f,separators=(',',':'),allow_nan=False);f.flush();os.fsync(f.fileno())
                os.replace(tmp,self.path(ident))
            finally:
                if os.path.exists(tmp):os.unlink(tmp)
            self.retired_cache.pop(ident,None)
            readback=self.load(ident)
            if (readback.get('revision') != value['revision'] or
                    readback.get('geometry_sha256') != value['geometry_sha256'] or
                    readback.get('world') != value['world']):
                raise OSError('Published world did not survive canonical read-back')
            retired_duplicate=False
            if source_ident != ident:
                duplicate=self.path(source_ident)
                if duplicate.exists():
                    archive=self.root/'.unpublished';archive.mkdir(parents=True,exist_ok=True)
                    os.replace(duplicate,archive/(source_ident+'-duplicate-'+str(time.time_ns())+'.json'))
                    self.loaded.pop(source_ident,None);self.retired_cache.pop(source_ident,None)
                    retired_duplicate=True
            self.sync()
            return {**{k:value[k] for k in ('id','revision','room_id','name','arrival','geometry_sha256')},
                    **self.load_receipt(readback),
                    'replaced':bool(replace_ident),'source_draft_id':source_ident,
                    'retired_duplicate':retired_duplicate}

    def sync(self):
        if not self.app:return
        from room.state import Room,RoomObject,RoomPlace
        app=self.app
        # Removed publications stop advertising gates. Occupied rooms remain
        # until their occupants leave; unpublish rejects that case explicitly.
        present = {path.stem for path in self.root.glob('*.json')}
        for ident in set(self.loaded) - present:
            rid = 'workshop_' + ident
            room = app.state.rooms.get(rid)
            if room and room.members:
                continue
            app.state.rooms.pop(rid, None)
            app.state.adjacency.pop(rid, None)
            for peers in app.state.adjacency.values():
                if rid in peers: peers.remove(rid)
            self.loaded.pop(ident, None)
        for path in self.root.glob('*.json'):
            stamp=path.stat().st_mtime_ns
            if self.loaded.get(path.stem)==stamp:continue
            value=self.load(path.stem);rid=value['room_id']
            old=app.state.rooms.get(rid)
            if old and old.members:continue
            world=value['world'];x,y,z=value['arrival']
            room=old or Room(rid,value['name'],world['size'],scene='workshop',arrival_m=[x,-z],arrival_heading_deg=0,
                      description=f"{world['style']} landscape, {world['size']} metres across. Solid buildings and stairs; liquid water can be crossed along its bed. Frozen natural water supports walking on ice.")
            room.navigation=Navigation(world,value['collision'])
            room.weather_atmosphere = dict(world.get('atmosphere') or {})
            room.destination={'id':value['id'],'revision':value['revision'],
                              'url':self.load_receipt(value)['load_url']}
            room.arrival_height=y
            room.name=value['name'];room.radius_m=world['size'];room.arrival_m=[x,-z]
            from room.room_workshop import merge_furniture
            previous=getattr(room,'authored_furniture',{})
            merge_furniture(room, previous, world.get('furniture', {}))
            room.authored_furniture=world.get('furniture',{})
            from room.gardening import attach_garden
            attach_garden(room, world, self.root/'gardens'/(value['id']+'.json'), self.repo/'room_tuning.json')
            room.places={}
            room.legacy_return_portal = not value.get('portal_schema')
            if room.legacy_return_portal:
                room.objects['return_portal']=RoomObject('return_portal','Teleporter',[x,-z],capability='portal',kind='teleporter',size_m=1.6,y_off_m=y,support_surface='free',description='Open destinations here to travel to any active teleporter.')
            elif 'return_portal' not in world.get('furniture', {}):
                room.objects.pop('return_portal', None)
            for b in world.get('structures',[]):
                room.places[b['id']]=RoomPlace(b['id'],f"{b.get('architecture','plain')} building",[b['x'],-b['z']],description=f"{b['floors']} floors; {'stairs connect the floors' if b['stairs'] else 'no staircase'}.")
            app.state.rooms[rid]=room
            app.state.adjacency[rid]=['nexus']
            if rid not in app.state.adjacency.setdefault('nexus',[]):app.state.adjacency['nexus'].append(rid)
            # Keep founding IDs, including removed furniture, so persistence
            # can record authored absences instead of resurrecting them.
            app.state.seed_ids.setdefault(rid,set())
            app.state.seed_ids[rid].update({'return_portal', *world.get('furniture',{})})
            app.state.seed_ids[rid].update(b['id'] for b in world.get('garden', {}).get('beds', []))
            if hasattr(app.state,'wire_portals'):app.state.wire_portals()
            self.loaded[path.stem]=stamp

    def unpublish(self, ident):
        with PUBLICATION_LOCK:
            path = self.path(ident)
            value = self.load(ident)
            room = self.app.state.rooms.get(value['room_id']) if self.app else None
            if room and room.members:
                raise FileExistsError('Everyone must leave this world before it can be removed from JNAIQ.')
            archive = self.root / '.unpublished'
            archive.mkdir(parents=True, exist_ok=True)
            import time
            os.replace(path, archive / (ident + '-' + str(time.time_ns()) + '.json'))
            self.sync()
            return {'ok': True, 'room_id': value['room_id'], 'draft_preserved': True}


def install(app,repo,store):
    manager=getattr(app.state,'world_destinations',None) or Destinations(repo)
    app.state.world_destinations=manager

    @app.get('/api/world-walk-clip')
    def walk_clip():
        return json.loads((Path(repo)/'godot-room/studio_motion.json').read_text(encoding='utf-8'))['walk']

    @app.get('/api/world-destinations')
    def index():
        manager.sync()
        return {'destinations':manager.index(),'shared':manager.app is not None}

    @app.get('/api/world-destinations/{ident}')
    def read(ident:str, revision:str=None):
        try:
            value=manager.load(ident)
            if revision and revision != value['revision']:
                return JSONResponse(status_code=409,content={
                    'error':'This destination revision changed. Reopen it from the current destinations menu.'})
            return {**{k:v for k,v in value.items() if k!='collision'},
                    **manager.load_receipt(value)}
        except (ValueError,OSError):return JSONResponse(status_code=404,content={'error':'Destination not found'})

    @app.post('/api/islands/{ident}/publish')
    def publish(ident:str, replace:str=None):
        try:
            # The separate editor shares disk drafts. While a household is
            # running its host owns publication and occupied-room checks.
            if manager.app is None:
                import httpx
                try:
                    port=load_run_state(repo)['room_port']
                    with httpx.Client(timeout=180,trust_env=False) as client:
                        probe=client.get(f'http://127.0.0.1:{int(port)}/api/world-destinations')
                        if probe.status_code==200 and probe.json().get('shared'):
                            if store.load(ident)['world'].get('garden', {}).get('beds'):
                                capabilities=client.get(f'http://127.0.0.1:{int(port)}/api/islands').json().get('capabilities', [])
                                if 'shared-garden-v1' not in capabilities:
                                    raise ValueError('Restart JNAIQ before publishing garden beds. Your saved garden layout is preserved in World Builder.')
                            buildings=store.load(ident)['world'].get('structures', [])
                            if any(b.get('wallEdits') or 'roofSections' in b or any('doorLeaf' in p or 'frames' in p for p in b.get('partitions', [])) for b in buildings):
                                capabilities=client.get(f'http://127.0.0.1:{int(port)}/api/islands').json().get('capabilities', [])
                                if 'building-components-v1' not in capabilities:
                                    raise ValueError('Restart JNAIQ before publishing these building edits. Your saved draft is preserved in World Builder.')
                            if any(any(o.get('doorStyle') for w in b.get('wallEdits', []) for o in w.get('openings', [])) or any(p.get('doorStyle') for p in b.get('partitions', [])) for b in buildings):
                                capabilities=client.get(f'http://127.0.0.1:{int(port)}/api/islands').json().get('capabilities', [])
                                if 'door-styles-v1' not in capabilities:
                                    raise ValueError('Restart JNAIQ before publishing styled doors. Your saved draft is preserved in World Builder.')
                            if any(any(o.get('doorColor') or o.get('doorImage') for w in b.get('wallEdits', []) for o in w.get('openings', [])) or any(p.get('doorColor') or p.get('doorImage') for p in b.get('partitions', [])) for b in buildings):
                                capabilities=client.get(f'http://127.0.0.1:{int(port)}/api/islands').json().get('capabilities', [])
                                if 'door-surfaces-v1' not in capabilities:
                                    raise ValueError('Restart JNAIQ before publishing coloured or image-covered doors. Your saved draft is preserved in World Builder.')
                            if any(re.fullmatch(r'(fabric_curtain_(pair|closed|cafe)|rug_(rectangle|round|runner))', o.get('kind','')) for o in store.load(ident)['world'].get('furniture', {}).values()):
                                capabilities=client.get(f'http://127.0.0.1:{int(port)}/api/islands').json().get('capabilities', [])
                                if 'textile-surfaces-v1' not in capabilities:
                                    raise ValueError('Restart JNAIQ before publishing curtains or rugs. Your saved draft is preserved in World Builder.')
                            response=client.post(f'http://127.0.0.1:{int(port)}/api/islands/{ident}/publish',params={'replace':replace} if replace else None)
                            result=response.json()
                            if response.status_code < 400:
                                published=manager.load(result['id'])
                                if published.get('revision') != result.get('revision'):
                                    raise ValueError('JNAIQ published a different revision. Reopen the destination list before travelling.')
                                result={**result,**manager.load_receipt(published)}
                            return JSONResponse(status_code=response.status_code,content=result)
                        if probe.status_code!=200:
                            raise ValueError('JNAIQ is running an older world host. Restart JNAIQ before adding this destination.')
                except (OSError,KeyError,httpx.ConnectError):pass
            return manager.publish(store.load(ident),replace_ident=replace)
        except FileExistsError as exc:return JSONResponse(status_code=409,content={'error':str(exc)})
        except FileNotFoundError:return JSONResponse(status_code=404,content={'error':'Save this island before adding it to JNAIQ.'})
        except (ValueError,subprocess.SubprocessError) as exc:return JSONResponse(status_code=400,content={'error':str(exc)})
        except OSError as exc:return JSONResponse(status_code=500,content={'error':str(exc)})

    @app.post('/api/islands/{ident}/unpublish')
    def unpublish(ident: str):
        try:
            if manager.app is None:
                import httpx
                try:
                    port=load_run_state(repo)['room_port']
                    with httpx.Client(timeout=15, trust_env=False) as client:
                        response=client.post(f'http://127.0.0.1:{int(port)}/api/islands/{ident}/unpublish')
                        return JSONResponse(status_code=response.status_code,content=response.json())
                except (OSError, KeyError, httpx.ConnectError):
                    pass
            return manager.unpublish(ident)
        except FileExistsError as exc:
            return JSONResponse(status_code=409,content={'error':str(exc)})
        except (ValueError, FileNotFoundError) as exc:
            return JSONResponse(status_code=404,content={'error':str(exc)})
