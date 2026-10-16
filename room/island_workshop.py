"""Local landscape drafts, independent of occupied resident rooms."""
from __future__ import annotations

import json
import hashlib
import math
import os
from pathlib import Path
import re
import tempfile
import shutil
import threading
import uuid
import base64
import io

from fastapi import Request
from fastapi.responses import JSONResponse
from room.island_columns import validate_columns, validate_pavilion
from room.island_pools import validate_pool

LOCK = threading.Lock()
MAX_BYTES = 4_000_000
SCENERY_KINDS = ('rose_quartz', 'citrine_points', 'emerald_shards', 'glow_crystal_cyan', 'glow_crystal_violet', 'glow_crystal_amber', 'button_mushrooms', 'toadstool_patch', 'chanterelle_patch', 'glowcap_patch', 'meadow_grass', 'meadow_daisies', 'creeping_thyme', 'wildflower_carpet',
                 'woodland_fern', 'lady_fern', 'sword_fern', 'tree_stump', 'fallen_log', 'lavender', 'flowering_heath', 'hibiscus_bush', 'firewheel_bush',
                 'rose_crimson_formal', 'rose_blush_cottage', 'rose_ivory_vase', 'rose_apricot_sprawl', 'rose_yellow_spray', 'rose_magenta_climber',
                 'pampas_grass', 'foxglove', 'giant_rhubarb', 'rainbow_protea',
                 'tree', 'maple', 'pine', 'sycamore', 'palm', 'banana',
                 'staghorn_sumac_summer', 'staghorn_sumac_winter',
                 'bird_of_paradise', 'jungle', 'bare', 'joshua', 'cactus',
                 'baobab', 'shrub', 'rock', 'giant_mushroom', 'glow_shrooms',
                 'shelf_fungus', 'coral_tree', 'lantern_plant', 'spiral_fern',
                 'crystal_lotus', 'star_bloom', 'river_rock', 'slate_rock',
                 'basalt_rock', 'standing_rock', 'rock_cluster', 'amethyst', 'quartz', 'azure_crystal')
FINISHES = ('plaster', 'timber', 'stone', 'brick', 'concrete', 'marble', 'parquet', 'tiles', 'roof', 'copper', 'thatch')
GENERATION_OPTIONS = json.loads((Path(__file__).resolve().parents[1] / 'assets/jnaiq/island-workshop/generation-options.json').read_text(encoding='utf-8'))
TREE_KINDS = ('tree', 'maple', 'pine', 'sycamore', 'palm', 'jungle', 'bare', 'joshua', 'baobab', 'coral_tree', 'staghorn_sumac_summer', 'staghorn_sumac_winter')
PLANT_SIZES = json.loads((Path(__file__).resolve().parents[1] / 'assets/jnaiq/island-workshop/plant-sizes.json').read_text(encoding='utf-8'))


def validate_world(world):
    if not isinstance(world, dict):
        raise ValueError("Island must be an object")
    if (world.get("schema") != "jnsq-island/1"
            or world.get("resolution") != 128
            or world.get("size") not in (100, 160, 240)
            or world.get("style") not in ("meadow", "craggy", "tropical", "highland", "woodland", "desert", "savanna", "rainforest", "enchanted", "alien", "fungi")):
        raise ValueError("Unsupported island format")
    from room.island_retired_content import remove_retired_caves
    world = remove_retired_caves(world)
    name = world.get("name")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
        raise ValueError("Name must contain 1 to 80 characters")
    seed = world.get("seed")
    if type(seed) is not int or not 0 <= seed <= 4294967295:
        raise ValueError("Invalid island seed")

    def number(value, low, high):
        return type(value) in (int, float) and math.isfinite(value) and low <= value <= high

    heights = world.get("heights")
    if (not isinstance(heights, list) or len(heights) != 129 ** 2
            or not all(number(v, -12, 65) for v in heights)):
        raise ValueError("Invalid terrain heights")
    objects = world.get("objects")
    if not isinstance(objects, list) or len(objects) > 2500:
        raise ValueError("An island supports up to 2500 scenery objects")
    ids = set()
    normalized = []
    for obj in objects:
        if not isinstance(obj, dict):
            raise ValueError("Invalid scenery object")
        oid = obj.get("id")
        half = world["size"] / 2
        if (not isinstance(oid, str) or not 1 <= len(oid) <= 80 or oid in ids
                or obj.get("kind") not in SCENERY_KINDS
                or obj.get("source") not in ("scatter", "manual")
                or not number(obj.get("x"), -half, half)
                or not number(obj.get("z"), -half, half)
                or not number(obj.get("scale"), .03 if obj.get('kind') in TREE_KINDS else .4, 32 if obj.get('kind') in TREE_KINDS else 3)
                or not number(obj.get("rotation"), -math.tau, math.tau)):
            raise ValueError("Invalid scenery geometry or identity")
        ids.add(oid)
        normalized.append({k: obj[k] for k in
                           ("id", "kind", "x", "z", "scale", "rotation", "source")})
    structures = world.get('structures', [])
    textures = world.get('textures', [])
    if not isinstance(textures, list) or len(textures) > 4:
        raise ValueError('Use up to four custom textures')
    texture_ids = set(); normalized_textures = []; texture_bytes = 0
    for t in textures:
        if (not isinstance(t, dict) or not isinstance(t.get('id'), str)
                or not re.fullmatch(r'custom_[a-f0-9-]{36}', t['id']) or t['id'] in texture_ids
                or not isinstance(t.get('name'), str) or not 1 <= len(t['name']) <= 80
                or not isinstance(t.get('data'), str) or len(t['data']) > 300000
                or not t['data'].startswith('data:image/jpeg;base64,')):
            raise ValueError('Invalid custom texture')
        try:
            from PIL import Image
            raw = base64.b64decode(t['data'].split(',', 1)[1], validate=True)
            with Image.open(io.BytesIO(raw)) as img:
                if img.format != 'JPEG' or max(img.size) > 1024: raise ValueError('Texture must be a JPEG up to 1024 pixels')
                img.verify()
        except Exception as exc:
            raise ValueError('Invalid texture image') from exc
        texture_ids.add(t['id']); texture_bytes += len(t['data'])
        normalized_textures.append({k: t[k] for k in ('id', 'name', 'data')})
    if texture_bytes > 1000000: raise ValueError('Custom texture budget exceeded')
    if not isinstance(structures, list) or len(structures) > 80:
        raise ValueError('An island supports up to 80 structures')
    building_ids = set()
    normalized_structures = []
    for b in structures:
        if not isinstance(b, dict):
            raise ValueError('Invalid structure')
        bid = b.get('id')
        minimum = 14 if b.get('shape') == 'round' else 10
        if (not isinstance(bid, str) or not 1 <= len(bid) <= 80 or bid in building_ids
                or b.get('shape') not in ('rectangle', 'round')
                or b.get('roof') not in ('auto', 'flat', 'none')
                or b.get('material') not in (*FINISHES, *texture_ids)
                or type(b.get('stairs')) is not bool
                or type(b.get('floors')) is not int or not 1 <= b['floors'] <= 4
                or not number(b.get('width'), minimum, 40)
                or not number(b.get('depth'), minimum, 40)
                or not number(b.get('x'), -world['size']/2, world['size']/2)
                or not number(b.get('z'), -world['size']/2, world['size']/2)
                or not number(b.get('y'), -12, 65)
                or not number(b.get('rotation'), -math.tau, math.tau)):
            raise ValueError('Invalid structure geometry')
        c, s = abs(math.cos(b['rotation'])), abs(math.sin(b['rotation']))
        if (abs(b['x']) + (c*b['width']+s*b['depth'])/2 > world['size']/2
                or abs(b['z']) + (s*b['width']+c*b['depth'])/2 > world['size']/2):
            raise ValueError('Structure extends beyond island bounds')
        building_ids.add(bid)
        extras = validate_pavilion(b)
        from room.building_components import validate_components
        extras.update(validate_components(b, texture_ids))
        if 'architecture' in b:
            catalogue = json.loads((Path(__file__).resolve().parents[1] / 'assets/jnaiq/island-workshop/architecture.json').read_text(encoding='utf-8'))
            if not isinstance(b['architecture'], str) or b['architecture'] not in catalogue:
                raise ValueError('Invalid architectural style')
            extras['architecture'] = b['architecture']
        for key in ('floorMaterial', 'roofMaterial', 'trimMaterial'):
            if key in b:
                if b[key] not in (*FINISHES, *texture_ids): raise ValueError('Invalid building finish')
                extras[key] = b[key]
        if 'frames' in b:
            if type(b['frames']) is not bool: raise ValueError('Invalid opening frames')
            extras['frames'] = b['frames']
        for key in ('windowShape', 'doorShape'):
            if key in b:
                if b[key] not in ('rectangle','arched','circle','oval','rounded','diamond','triangle','rhomboid'):
                    raise ValueError('Invalid opening shape')
                extras[key] = b[key]
        if 'tileMetres' in b:
            if not number(b['tileMetres'], .25, 12): raise ValueError('Invalid texture repeat')
            extras['tileMetres'] = b['tileMetres']
        if 'partitions' in b:
            walls = b['partitions']; wall_ids = set(); parts = []
            if not isinstance(walls, list) or len(walls) > 60: raise ValueError('Too many interior walls')
            for p in walls:
                if (not isinstance(p, dict) or not isinstance(p.get('id'), str) or not 1 <= len(p['id']) <= 80 or p['id'] in wall_ids
                        or type(p.get('floor')) is not int or not 0 <= p['floor'] < b['floors'] or type(p.get('door')) is not bool
                        or not all(number(p.get(k), -40, 40) for k in ('ax', 'az', 'bx', 'bz'))): raise ValueError('Invalid interior wall')
                if math.hypot(p['bx']-p['ax'], p['bz']-p['az']) < (1.6 if p['door'] else .5): raise ValueError('Interior wall too short')
                for x,z in ((p['ax'], p['az']), (p['bx'], p['bz'])):
                    outside = ((x/(b['width']/2-.18))**2+(z/(b['depth']/2-.18))**2 > 1 if b['shape']=='round' else abs(x)>b['width']/2-.18 or abs(z)>b['depth']/2-.18)
                    if outside: raise ValueError('Interior wall outside building')
                if b['stairs'] and b['floors'] > 1:
                    lo, hi = 0, 1
                    for a,d,low,high in ((p['ax'],p['bx']-p['ax'],.65,2.95),(p['az'],p['bz']-p['az'],-3.3,3.3)):
                        if abs(d)<1e-9:
                            if a<low or a>high: hi=-1; break
                        else:
                            t1,t2=(low-a)/d,(high-a)/d; lo=max(lo,min(t1,t2)); hi=min(hi,max(t1,t2))
                    if lo<=hi: raise ValueError('Interior wall blocks stairs')
                wall_ids.add(p['id']); parts.append({k:p[k] for k in ('id','floor','ax','az','bx','bz','door')})
                for key in ('doorLeaf', 'doorStyle', 'doorColor', 'doorImage', 'doorAngle', 'frames'):
                    if key not in p: continue
                    if (key == 'doorLeaf' and p[key] not in ('none','solid')
                            or key == 'doorStyle' and p[key] not in ('flat','panelled','medieval','glazed')
                            or key == 'doorColor' and not re.fullmatch(r'#[0-9a-fA-F]{6}',str(p[key]))
                            or key == 'doorImage' and p[key] not in texture_ids
                            or key == 'doorAngle' and not number(p[key],0,120)
                            or key == 'frames' and type(p[key]) is not bool):
                        raise ValueError('Invalid interior door')
                    parts[-1][key] = p[key]
            extras['partitions'] = parts
        extras.update(validate_pool(b, world['size']))
        normalized_structures.append({k: b[k] for k in
            ('id', 'shape', 'x', 'z', 'y', 'width', 'depth', 'rotation', 'floors', 'roof', 'material', 'stairs')})
        normalized_structures[-1].update(extras)
    result = {"schema": "jnsq-island/1", "name": name.strip(),
            "style": world["style"], "seed": seed, "size": world["size"],
            "resolution": 128, "heights": list(heights), "objects": normalized}
    if 'furniture' in world:
        from room.room_workshop import validate_objects
        furniture = validate_objects(world['furniture'], room_range=False)
        # The world includes ocean and air beyond the dry-land mesh, but an
        # object dragged past twice the island width is no longer reachable in
        # the ordinary editor. Discard those runaway records (and anything
        # supported by them) rather than letting one object hold the entire
        # island save hostage. The browser keeps the same operation undoable.
        furniture_range = world['size'] * 2
        for obj in furniture.values():
            if obj.get('size_m', .6) > 6 or obj.get('capability') not in (None,'','sitting','writing','private_writing','light','portal'):
                raise ValueError('Choose ordinary furniture up to 6 metres across')
            if re.fullmatch(r'(fabric_curtain_(pair|closed|cafe)|rug_(rectangle|round|runner))', obj.get('kind') or '') and obj.get('texture','').startswith('custom_') and obj['texture'] not in texture_ids:
                raise ValueError('Choose an uploaded island image for this textile')
            if obj.get('capability') == 'private_writing' and not obj.get('owner'):
                raise ValueError('A private writing desk needs an owner')
        removed = {oid for oid, obj in furniture.items()
                   if max(abs(v) for v in obj['position_m']) > furniture_range}
        changed = True
        while changed:
            changed = False
            for oid, obj in furniture.items():
                if oid not in removed and obj.get('support_oid') in removed:
                    removed.add(oid); changed = True
        result['furniture'] = {oid: obj for oid, obj in furniture.items() if oid not in removed}
    if 'features' in world:
        features = world['features']
        if not isinstance(features, list) or len(features) > 12:
            raise ValueError('Invalid landscape features')
        normalized_features = []
        for f in features:
            if (not isinstance(f, dict) or f.get('kind') not in ('river', 'road', 'pond')
                    or not number(f.get('width'), 1, 16)
                    or not isinstance(f.get('points'), list) or not 2 <= len(f['points']) <= 256):
                raise ValueError('Invalid landscape feature')
            points = []
            for p in f['points']:
                if (not isinstance(p, dict)
                        or not number(p.get('x'), -world['size']/2, world['size']/2)
                        or not number(p.get('z'), -world['size']/2, world['size']/2)
                        or not number(p.get('y'), -12, 65)):
                    raise ValueError('Invalid feature route')
                if f['kind'] == 'river' and points and p['y'] > points[-1]['y'] + .00001:
                    raise ValueError('River must flow downhill')
                points.append({k: p[k] for k in ('x', 'y', 'z')})
            if f['kind'] == 'pond':
                if len(points)<3 or any(abs(p['y']-points[0]['y'])>.00001 for p in points):
                    raise ValueError('Invalid pond outline or water level')
                area=sum(a['x']*b['z']-b['x']*a['z'] for a,b in zip(points,points[1:]+points[:1]))
                if abs(area)<32:
                    raise ValueError('Pond outline is too small')
                def cross(a,b,c):
                    return (b['x']-a['x'])*(c['z']-a['z'])-(b['z']-a['z'])*(c['x']-a['x'])
                for i,a in enumerate(points):
                    b=points[(i+1)%len(points)]
                    if math.hypot(a['x']-b['x'],a['z']-b['z'])<.2:
                        raise ValueError('Overlapping pond points')
                    for j in range(i+2,len(points)):
                        if i==0 and j==len(points)-1:
                            continue
                        c,d=points[j],points[(j+1)%len(points)]
                        boxes_overlap=(max(a['x'],b['x'])>=min(c['x'],d['x']) and max(c['x'],d['x'])>=min(a['x'],b['x'])
                                       and max(a['z'],b['z'])>=min(c['z'],d['z']) and max(c['z'],d['z'])>=min(a['z'],b['z']))
                        if boxes_overlap and cross(a,b,c)*cross(a,b,d)<=0 and cross(c,d,a)*cross(c,d,b)<=0:
                            raise ValueError('Pond edges cross')
            normalized_features.append({'kind': f['kind'], 'width': f['width'], 'points': points})
        result['features'] = normalized_features
    if 'groundPaint' in world:
        paint = world['groundPaint']
        if (not isinstance(paint, list) or len(paint) != 129*129*4
                or any(type(v) is not int or v < 0 or v > 255 for v in paint)
                or any(sum(paint[i:i+4]) > 255 for i in range(0, len(paint), 4))):
            raise ValueError('Invalid ground paint')
        result['groundPaint'] = list(paint)
    if 'groundPaintExtra' in world:
        extra = world['groundPaintExtra']
        if (not isinstance(extra, list) or len(extra) != 129*129*8
                or any(type(v) is not int or v < 0 or v > 255 for v in extra)):
            raise ValueError('Invalid extended ground paint')
        base = result.get('groundPaint', [])
        if any(sum(extra[i:i+8]) + sum(base[i//2:i//2+4]) > 255 for i in range(0, len(extra), 8)):
            raise ValueError('Invalid paint blend')
        result['groundPaintExtra'] = list(extra)
    if 'rockSculpt' in world:
        points = world['rockSculpt']
        if not isinstance(points, list) or len(points) > 16000:
            raise ValueError('Invalid sculpted rock budget')
        seen = set()
        for p in points:
            if (not isinstance(p, list) or len(p) not in (4, 5)
                    or any(type(v) not in (int, float) or not math.isfinite(v) for v in p)
                    or (len(p) == 5 and (type(p[4]) is not int or not 0 <= p[4] < 6))
                    or any(v != int(v) for v in p[:3])
                    or abs(p[0]) > world['size']/2 or abs(p[2]) > world['size']/2
                    or not -8 <= p[1] <= 72 or not -1 < p[3] <= 1
                    or tuple(p[:3]) in seen):
                raise ValueError('Invalid sculpted rock')
            seen.add(tuple(p[:3]))
        result['rockSculpt'] = [list(p) for p in points]
    if 'vines' in world:
        from room.island_vines import validate_vines
        result['vines'] = validate_vines(world['vines'], world['size'])
    if 'structures' in world:
        result['structures'] = normalized_structures
    if 'columns' in world:
        result['columns'] = validate_columns(world['columns'],world['size'])
    if 'stepRoutes' in world:
        from room.island_steps import validate_step_routes
        result['stepRoutes'] = validate_step_routes(world['stepRoutes'], world['size'])
    if 'textures' in world:
        result['textures'] = normalized_textures
    if 'generation' in world:
        recipe=world['generation']
        if not isinstance(recipe,dict) or not number(recipe.get('density'),0,1):
            raise ValueError('Invalid generation recipe')
        for key in ('landforms','communities','rocks'):
            values=recipe.get(key)
            if (not isinstance(values,list) or len(values)>len(GENERATION_OPTIONS[key])
                    or any(not isinstance(v,str) or v not in GENERATION_OPTIONS[key] for v in values)
                    or len(set(values))!=len(values) or key=='landforms' and not values):
                raise ValueError('Invalid generation '+key)
        result['generation']={k:recipe[k] for k in ('landforms','communities','rocks','density')}
        if 'plantLayers' in recipe:
            layers=recipe['plantLayers']
            if not isinstance(layers,dict) or set(layers)!=set(PLANT_SIZES):raise ValueError('Invalid plant layers')
            union=set();total=0;normalized_layers={}
            for layer,plants in PLANT_SIZES.items():
                value=layers[layer]
                if not isinstance(value,dict):raise ValueError('Invalid plant layer')
                ids=value.get('communities');share=value.get('percentage')
                if (type(share) is not int or not 0<=share<=100 or not isinstance(ids,list)
                        or any(not isinstance(c,str) or c not in GENERATION_OPTIONS['communities'] or not set(GENERATION_OPTIONS['communities'][c]['plants']).intersection(plants) for c in ids)
                        or len(set(ids))!=len(ids) or not ids and share!=0):raise ValueError('Invalid plant layer')
                total+=share;union.update(ids);normalized_layers[layer]={'communities':ids,'percentage':share}
            if union!=set(recipe['communities']) or total!=(100 if union else 0):raise ValueError('Invalid plant layer percentages')
            result['generation']['plantLayers']=normalized_layers
        for key, low, high in [('maxTreeHeight', 5, 120), ('treeHeightVariation', 0, 1)]:
            if key in recipe:
                if not number(recipe[key],low,high):raise ValueError('Invalid generation '+key)
                result['generation'][key]=recipe[key]
        if 'clustering' in recipe:
            if not number(recipe['clustering'],0,1):raise ValueError('Invalid scenery clustering')
            result['generation']['clustering']=recipe['clustering']
    if 'atmosphere' in world:
        sky=world['atmosphere']
        if 'nebulaClouds' in sky and type(sky['nebulaClouds']) is not bool:
            raise ValueError('Invalid nebula clouds')
        if (not isinstance(sky,dict) or sky.get('environment') not in ('clouds','ocean','planet','asteroids','space','aurora','alien','cavern','cavern-glow','lava','cavern-lava')
                or sky.get('weather') not in ('clear','scattered','overcast','rain','storm','snow','fog','meteors')
                or not number(sky.get('hour'),0,24) or not number(sky.get('strength'),.1,1)
                or any(type(sky.get(k)) is not bool for k in ('followLocalTime','cloudShadows','sunRays'))):
            raise ValueError('Invalid world atmosphere')
        result['atmosphere']={k:sky[k] for k in ('environment','weather','hour','strength','followLocalTime','cloudShadows','sunRays')}
        if 'followLocalWeather' in sky:
            if type(sky['followLocalWeather']) is not bool:
                raise ValueError('Invalid local weather setting')
            result['atmosphere']['followLocalWeather'] = sky['followLocalWeather']
        if 'landBrightness' in sky:
            if not number(sky['landBrightness'],0,2): raise ValueError('Invalid land brightness')
            result['atmosphere']['landBrightness']=sky['landBrightness']
        if 'skyBrightness' in sky:
            if not number(sky['skyBrightness'],.1,2): raise ValueError('Invalid sky brightness')
            result['atmosphere']['skyBrightness']=sky['skyBrightness']
        if 'lightingColor' in sky:
            if not isinstance(sky['lightingColor'],str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',sky['lightingColor']):
                raise ValueError('Invalid lighting color')
            result['atmosphere']['lightingColor']=sky['lightingColor']
        if 'skyColors' in sky:
            colors=sky['skyColors']
            keys=('horizon','zenith','nightHorizon','nightZenith')
            if (not isinstance(colors,dict) or type(colors.get('enabled')) is not bool
                    or any(not isinstance(colors.get(k),str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',colors[k]) for k in keys)):
                raise ValueError('Invalid generated sky colors')
            result['atmosphere']['skyColors']={k:colors[k] for k in ('enabled',*keys)}
        if 'nebulaClouds' in sky: result['atmosphere']['nebulaClouds']=sky['nebulaClouds']
        if 'cavernLighting' in sky:
            if sky['cavernLighting'] not in ('natural','bio','amber','cool'):
                raise ValueError('Invalid cavern lighting')
            result['atmosphere']['cavernLighting']=sky['cavernLighting']
        if 'water' in sky:
            water=sky['water']
            if (not isinstance(water,dict) or water.get('surface') not in ('visible','none')
                    or not isinstance(water.get('color'),str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',water['color'])
                    or not number(water.get('glow'),0,2) or not number(water.get('ripples'),0,2)):
                raise ValueError('Invalid ocean settings')
            result['atmosphere']['water']={k:water[k] for k in ('surface','color','glow','ripples')}
        if 'customSky' in sky:
            custom=sky['customSky']
            if custom is not None:
                if (not isinstance(custom,dict) or not isinstance(custom.get('name'),str) or not 1<=len(custom['name'])<=80
                        or not isinstance(custom.get('data'),str) or len(custom['data'])>1200000 or not custom['data'].startswith('data:image/jpeg;base64,')
                        or type(custom.get('width')) is not int or not 512<=custom['width']<=4096
                        or type(custom.get('height')) is not int or custom['height']*2!=custom['width']
                        or not number(custom.get('rotation'),-180,180) or not number(custom.get('brightness'),.1,2)):
                    raise ValueError('Invalid custom sky panorama')
                try:
                    from PIL import Image
                    raw=base64.b64decode(custom['data'].split(',',1)[1],validate=True)
                    with Image.open(io.BytesIO(raw)) as img:
                        if img.format!='JPEG' or img.size!=(custom['width'],custom['height']):raise ValueError('Sky image dimensions do not match')
                        img.verify()
                except Exception as exc:
                    raise ValueError('Invalid custom sky image') from exc
                result['atmosphere']['customSky']={k:custom[k] for k in ('name','data','width','height','rotation','brightness')}
            else:
                result['atmosphere']['customSky']=None
    if 'frozenWater' in world:
        if type(world['frozenWater']) is not bool: raise ValueError('Invalid ice setting')
        result['frozenWater']=world['frozenWater']
    if 'garden' in world:
        from room.gardening import validate_garden
        result['garden'] = validate_garden(world['garden'], world)
    return result


class IslandStore:
    def __init__(self, root):
        self.root = Path(root)

    def path(self, island_id):
        if not re.fullmatch(r"[0-9a-f]{32}", island_id):
            raise ValueError("Invalid island ID")
        return self.root / (island_id + ".json")

    def load(self, island_id):
        value = json.loads(self.path(island_id).read_text(encoding="utf-8"))
        from room.island_retired_content import remove_retired_caves
        if 'world' in value:
            value['world'] = remove_retired_caves(value['world'])
        return value

    def index(self):
        result = []
        for path in sorted(self.root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                value = self.load(path.stem)
                result.append({"id": value["id"], "revision": value["revision"],
                               **{k: value["world"][k] for k in ("name", "style", "size")}})
            except (ValueError, KeyError, OSError):
                continue
        return result

    def save(self, world, island_id=None, revision=None):
        world = validate_world(world)
        with LOCK:
            if island_id and self.load(island_id)["revision"] != revision:
                raise FileExistsError("This island changed in another window. Export your edits, then reopen it.")
            island_id = island_id or uuid.uuid4().hex
            value = {"id": island_id, "revision": uuid.uuid4().hex, "world": world}
            self.root.mkdir(parents=True, exist_ok=True)
            existing = self.path(island_id)
            if existing.exists():
                from room.island_retired_content import remove_retired_caves
                original = json.loads(existing.read_text(encoding='utf-8'))
                if original['world'] != remove_retired_caves(original['world']):
                    backup = self.root / 'before-cave-retirement' / (island_id + '-' + original['revision'] + '.json')
                    backup.parent.mkdir(exist_ok=True)
                    if not backup.exists():
                        shutil.copy2(existing, backup)
            fd, temp = tempfile.mkstemp(prefix=".island-", suffix=".tmp", dir=self.root)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(value, handle, separators=(",", ":"), allow_nan=False)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp, self.path(island_id))
            finally:
                if os.path.exists(temp):
                    os.unlink(temp)
            # A successful write is not yet a successful save contract. Read
            # the canonical file back through the same loader used by Open so
            # the UI never reports success for bytes it cannot load.
            loaded = self.load(island_id)
            if loaded != value:
                raise OSError("Saved island did not survive canonical read-back")
            digest = hashlib.sha256(json.dumps(
                loaded, sort_keys=True, separators=(",", ":"),
                allow_nan=False).encode("utf-8")).hexdigest()
            return {"id": island_id, "revision": value["revision"],
                    "load_ready": True, "content_sha256": digest,
                    "load_url": "/api/islands/" + island_id +
                    "?revision=" + value["revision"]}


def install(app, repo, root=None, *, standalone=False):
    from room.room_workshop import install as install_room_workshop
    install_room_workshop(app, repo)
    store = IslandStore(root or os.environ.get('JNAIQ_ISLANDS_DIR') or Path(repo) / "state" / "islands")
    if not standalone:
        from room.world_destinations import install as install_destinations
        install_destinations(app, repo, store)

    @app.get("/island-workshop")
    def workshop():
        # Redirect keeps all module/import-map URLs relative to the static folder.
        from fastapi.responses import RedirectResponse
        return RedirectResponse("/assets/island-workshop/index.html")

    @app.get("/api/islands")
    def index():
        return {"islands": store.index(), "capabilities": ["verified-save-readback-v1", "clinging-vines-v1", "shared-garden-v1", "generated-sky-colors-v1", "building-components-v1", "door-styles-v1", "door-surfaces-v1", "textile-surfaces-v1", "sky-water-authoring-v1", "clustered-scenery-v1", "generation-recipe-v1", "land-lighting-v1", "step-routes-v1", "pools-v1", "columns-v1", "structures-v1", "landscape-features-v1", "building-interiors-v1", "crystals-v1", "garden-plants-v1", "landscape-paint-v1", "ponds-v1", "ground-surfaces-v1", "architecture-v1", "opening-shapes-v1", "rock-sculpt-v1"]}

    @app.get("/api/islands/{island_id}")
    def load(island_id: str):
        try:
            return store.load(island_id)
        except (ValueError, FileNotFoundError):
            return JSONResponse(status_code=404, content={"error": "Island not found"})

    async def write(request, island_id=None):
        try:
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > MAX_BYTES:
                    return JSONResponse(status_code=413, content={"error": "Island exceeds 4 MB"})
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise ValueError("Invalid save request")
            return store.save(payload.get("world"), island_id, payload.get("revision"))
        except FileExistsError as exc:
            return JSONResponse(status_code=409, content={"error": str(exc)})
        except FileNotFoundError:
            return JSONResponse(status_code=404, content={"error": "Island not found"})
        except (ValueError, TypeError) as exc:
            return JSONResponse(status_code=400, content={"error": str(exc)})
        except OSError:
            return JSONResponse(status_code=500, content={"error": "Could not save to disk. Export your island to preserve it."})

    @app.post("/api/islands")
    async def create(request: Request):
        return await write(request)

    @app.put("/api/islands/{island_id}")
    async def update(island_id: str, request: Request):
        return await write(request, island_id)
