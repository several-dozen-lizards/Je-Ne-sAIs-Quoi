"""Shared, local game gardens. Geometry is authored; living state belongs to the host.

Growth integrates water availability over elapsed garden hours. The water reservoir
has a closed-form solution, so observing more often never grows a crop faster.
These are adjustable game relationships, not a biological crop model. Conditions
are held at their last observation between visits, including while JNAIQ is off.
"""
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import re
import tempfile
import threading
import time

CROPS = json.loads((Path(__file__).resolve().parents[1] / 'assets/jnaiq/island-workshop/garden-crops.json').read_text())
LOCK = threading.RLock()
WIDTH, DEPTH = 2.4, 1.6


def validate_garden(value, world):
    if not isinstance(value, dict) or set(value) - {'beds', 'pace'}:
        raise ValueError('Invalid garden layout')
    beds, pace = value.get('beds'), value.get('pace', 12)
    if type(pace) not in (float, int) or not math.isfinite(pace) or not 1 <= pace <= 24:
        raise ValueError('Garden pace must be 1 to 24 garden hours per real hour')
    if not isinstance(beds, list) or len(beds) > 32:
        raise ValueError('An island supports up to 32 garden beds')
    ids = set(world.get('furniture', {}))
    result = []
    for bed in beds:
        if (not isinstance(bed, dict) or set(bed) != {'id', 'name', 'x', 'z', 'rotation'}
                or not isinstance(bed.get('id'), str) or not re.fullmatch(r'garden_[a-zA-Z0-9_-]{1,60}', bed['id'])
                or bed['id'] in ids or not isinstance(bed.get('name'), str) or not 1 <= len(bed['name'].strip()) <= 60
                or not all(type(bed.get(k)) in (int, float) and math.isfinite(bed[k]) for k in ('x', 'z', 'rotation'))
                or abs(bed['x']) + 1.5 > world['size']/2 or abs(bed['z']) + 1.5 > world['size']/2
                or abs(bed['rotation']) > math.tau):
            raise ValueError('Invalid garden bed geometry or identity')
        ids.add(bed['id'])
        result.append({**bed, 'name': bed['name'].strip()})
    # Terrain and surrounding buildings remain editable. A submerged or shaded
    # bed is retained; its suitability affects growth instead of erasing it.
    return {'beds': result, 'pace': pace}


def conditions(room, world, bed, observed=None):
    """Translate the room's observed weather and bed site into game inputs."""
    a = observed if observed is not None else (getattr(room, 'weather_atmosphere', None) or world.get('atmosphere') or {})
    weather = a.get('weather', 'scattered')
    rain = {'rain': .16, 'rainy': .16, 'storm': .28, 'stormy': .28, 'thunderstorm': .28, 'drizzle': .08}.get(weather, 0)
    light = {'clear': 1., 'scattered': .85, 'overcast': .55, 'cloudy': .55, 'rain': .45, 'storm': .3, 'snow': .45}.get(weather, .75)
    # Daily exposure is deliberately independent of the renderer's accelerated
    # sky clock. A pinned midnight sky still permits an ordinary garden cycle.
    nav = getattr(room, 'navigation', None)
    submerged = bool(nav and nav.water(bed['x'], bed['z']) > bed.get('y_m', nav.terrain(bed['x'], bed['z'])) + .05)
    sheltered = False
    for b in world.get('structures', []):
        dx, dz = bed['x']-b['x'], bed['z']-b['z']; c, s = math.cos(b['rotation']), math.sin(b['rotation'])
        x, z = c*dx-s*dz, s*dx+c*dz
        if abs(x) < b['width']/2 and abs(z) < b['depth']/2:
            sheltered = b.get('roof') != 'none'
            if sheltered: break
    # Ordinary rooms supply a sheltered, modest-light site. Indoor beds still
    # grow; residents supply the water rather than rain passing through a roof.
    if not nav and room.scene != 'island': sheltered = True
    if sheltered: light *= .15; rain = 0
    frozen = bool(world.get('frozenWater')) or weather in ('snow', 'blizzard')
    return {'rain': rain, 'light': light, 'evaporation': .025 + .025*light,
            'growth': 0. if submerged or frozen else 1., 'weather': weather,
            'sheltered': sheltered, 'submerged': submerged, 'frozen': frozen}


def advance(bed, now, pace):
    """Exact integration of moisture and hydrated growth for one climate segment."""
    elapsed = max(0., now-bed['at']) / 3600 * pace
    if not elapsed: return
    env = bed['conditions']; rain, evaporation = env['rain'], env['evaporation']
    k = rain + evaporation; equilibrium = rain / k
    start = bed['moisture']; end = equilibrium + (start-equilibrium)*math.exp(-k*elapsed)
    # max(0, m - dry) / (m + half) is smoothly water-limited. Integrate using the ODE
    # m' = rain*(1-m) - evaporation*m; log arguments stay strictly positive.
    half, dry = .22, .15; a = equilibrium + half
    lo, hi = 0., elapsed
    if start <= dry:
        lo = min(elapsed, math.log((equilibrium-start)/(equilibrium-dry))/k) if equilibrium > dry else elapsed
    elif equilibrium < dry:
        hi = min(elapsed, math.log((start-equilibrium)/(dry-equilibrium))/k)
    wet_start = equilibrium + (start-equilibrium)*math.exp(-k*lo)
    wet_end = equilibrium + (start-equilibrium)*math.exp(-k*hi)
    hydrated = ((equilibrium-dry)/a*(hi-lo) + (half+dry)/(a*k)*math.log((wet_start+half)/(wet_end+half))) if hi > lo else 0.
    if bed['crop']:
        bed['progress'] = min(1., bed['progress'] + max(0., hydrated)*env['light']*env['growth']
                              *(.3+.7*bed['fertility'])/CROPS[bed['crop']]['growthHours'])
    bed['moisture'] = max(0., min(1., end))
    bed['at'] = max(now, bed['at'])


def phase(bed):
    if not bed['crop']: return 'Empty'
    if bed['progress'] >= 1: return 'Ready to harvest'
    return 'Seeded' if bed['progress'] < .12 else 'Seedlings' if bed['progress'] < .35 else 'Growing' if bed['progress'] < .72 else 'Ripening'


class Garden:
    def __init__(self, path, world, room, clock=time.time, settings_path=None):
        self.path, self.world, self.room, self.clock = Path(path), world, room, clock
        self.settings_path = Path(settings_path) if settings_path else None
        self.settings_stamp, self.settings = None, {}
        self.pace = world.get('garden', {}).get('pace', 12)
        self.last_phases = {}
        with LOCK:
            self.state = json.loads(self.path.read_text()) if self.path.exists() else {
                'schema': 'jnsq-garden/1', 'revision': 0, 'pace': self.layout['pace'], 'beds': {},
                'basket': {k: 0 for k in CROPS}, 'compost': 0, 'history': []}
            now = clock()
            # Settle at the previous pace before applying an authored pace change.
            for bed in self.state['beds'].values(): advance(bed, now, self.state['pace'])
            self.state['pace'] = self.layout['pace']
            observed = self._weather()
            for b in self.layout['beds']:
                self.state['beds'].setdefault(b['id'], dict(crop=None, progress=0., moisture=.55,
                    fertility=.8, at=now, conditions=conditions(room, world, b, observed)))
                self.state['beds'][b['id']]['conditions'] = conditions(room, world, b, observed)
            self._write(self.state)

    @property
    def layout(self):
        # The room owns placement, including direct edits, deletes and Undo.
        # Growing state is keyed by object identity and survives those edits.
        return {'pace': self.pace, 'beds': [dict(id=o.id, name=o.name,
            x=o.position_m[0], z=-o.position_m[1], rotation=math.radians(o.rot_deg),
            y_m=self.room.object_elevation(o.id), scale=o.size_m/2.4)
            for o in self.room.objects.values() if o.capability == 'garden']}

    def _write(self, value):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix='.garden-', suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(value, f, separators=(',', ':'), allow_nan=False); f.flush(); os.fsync(f.fileno())
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp): os.unlink(tmp)

    def _weather(self):
        if self.settings_path and self.settings_path.exists():
            stamp = self.settings_path.stat().st_mtime_ns
            if stamp != self.settings_stamp:
                data = json.loads(self.settings_path.read_text(encoding='utf-8'))
                self.settings = data.get('rooms', {}).get(self.room.id, {})
                self.settings_stamp = stamp
        return {**(getattr(self.room, 'weather_atmosphere', None) or self.world.get('atmosphere') or {}), **self.settings}

    def _project(self):
        value = deepcopy(self.state); now = self.clock(); climate_changed = False
        observed = self._weather()
        for b in self.layout['beds']:
            if b['id'] not in value['beds']:
                value['beds'][b['id']] = dict(crop=None, progress=0., moisture=.55,
                    fertility=.8, at=now, conditions=conditions(self.room, self.world, b, observed))
                climate_changed = True
            bed = value['beds'][b['id']]; advance(bed, now, value['pace'])
            env = conditions(self.room, self.world, b, observed)
            if env != bed['conditions']: bed['conditions'] = env; climate_changed = True
        if climate_changed:
            # The new observation applies forward; never rain on the whole past.
            self._write(value); self.state = deepcopy(value)
        return value

    def snapshot(self):
        with LOCK:
            value = self._project()
            beds = []
            for layout in self.layout['beds']:
                bed = {**layout, **value['beds'][layout['id']]}; bed['phase'] = phase(bed)
                bed['modes'] = (['plant_'+k for k in CROPS] if not bed['crop'] else ['harvest'] if bed['progress'] >= 1 else [])
                if bed['moisture'] < .95: bed['modes'].append('water')
                if value['compost'] > 0 and bed['fertility'] < .99: bed['modes'].append('compost')
                crop = CROPS[bed['crop']]['name'] if bed['crop'] else 'Unplanted'
                condition = ('frozen' if bed['conditions']['frozen'] else 'flooded' if bed['conditions']['submerged'] else
                             'dry' if bed['moisture'] < .15 else 'moist' if bed['moisture'] > .4 else 'drying')
                bed['description'] = (f"{crop}; {bed['phase'].lower()}; soil {condition} ({bed['moisture']:.0%}); "
                                      f"fertility {bed['fertility']:.0%}; development {bed['progress']:.0%}.")
                if bed['conditions']['sheltered']: bed['description'] += ' Little light under this roof.'
                marker = (bed['phase'], condition)
                if layout['id'] in self.last_phases and self.last_phases[layout['id']] != marker:
                    self.room.emit('world', 'garden_changed', {'object': layout['id'], 'description': bed['description']})
                self.last_phases[layout['id']] = marker
                beds.append(bed)
            return {'beds': beds, 'pace': value['pace'], 'basket': value['basket'], 'compost': value['compost'],
                    'revision': value['revision'], 'history': value['history'][-8:], 'crops': CROPS}

    def use(self, member, oid, mode):
        with LOCK:
            layout = next((b for b in self.layout['beds'] if b['id'] == oid), None)
            if not layout or member not in self.room.members: return {'error': 'This garden bed is not here.'}
            if not self.room.near(member, oid): return {'error': 'Walk closer to the garden bed to tend it.'}
            value = self._project(); bed = value['beds'][oid]
            if mode.startswith('plant_'):
                crop = mode[6:]
                if crop not in CROPS: return {'error': 'Choose radishes, lettuce, or tomatoes.'}
                if bed['crop']: return {'error': 'This bed already has a crop. Harvest it before planting again.'}
                bed.update(crop=crop, progress=0.)
                description = f"{member} planted {CROPS[crop]['name'].lower()} in {layout['name']}."
            elif mode == 'water':
                if bed['moisture'] >= .95: return {'error': 'This bed already has plenty of water.'}
                bed['moisture'] = 1.
                description = f"{member} watered {layout['name']}."
            elif mode == 'harvest':
                if not bed['crop'] or bed['progress'] < 1: return {'error': 'This bed is not ready to harvest.'}
                crop = bed['crop']; amount = max(1, round(CROPS[crop]['yield']*(.5+.5*bed['fertility'])))
                value['basket'][crop] += amount; value['compost'] += 1
                bed.update(crop=None, progress=0., fertility=max(0., bed['fertility']-.18))
                description = f"{member} harvested {amount} {CROPS[crop]['name'].lower()} into the shared basket; plant remains added one compost portion."
            elif mode == 'compost':
                if value['compost'] < 1: return {'error': 'Harvest a crop to collect plant remains for compost.'}
                if bed['fertility'] >= .99: return {'error': 'The soil is already fertile.'}
                value['compost'] -= 1; bed['fertility'] = min(1., bed['fertility']+.25)
                description = f"{member} worked compost into {layout['name']}."
            else: return {'error': 'Use plant_radish, plant_lettuce, plant_tomato, water, harvest, or compost.'}
            value['revision'] += 1
            receipt = {'revision': value['revision'], 'at': self.clock(), 'member': member, 'object': oid, 'mode': mode, 'description': description}
            value['history'] = (value['history'] + [receipt])[-64:]
            self._write(value); self.state = value
            self.room.emit(member, 'garden_tended', receipt)
            return {'ok': True, 'description': description, 'garden': self.snapshot()}


def attach_garden(room, world, path, settings_path=None):
    """Merge authored beds without resetting beds placed or moved in the room."""
    from room.state import RoomObject
    previous = getattr(room, 'authored_garden', {})
    authored = {b['id']: b for b in world.get('garden', {}).get('beds', [])}
    for oid, b in authored.items():
        obj = room.objects.get(oid)
        if obj:
            if oid in previous and b != previous[oid]:
                old = previous[oid]
                # Preserve live placement; an authored name change is harmless.
                if obj.position_m == [old['x'], -old['z']] and math.isclose(obj.rot_deg % 360, math.degrees(old['rotation']) % 360):
                    obj.position_m = [b['x'], -b['z']]; obj.rot_deg = math.degrees(b['rotation'])
                if obj.name == old['name']: obj.name = b['name']
            continue
        if oid in previous: continue  # A live deletion is an authored absence.
        room.objects[oid] = RoomObject(oid, b['name'], [b['x'], -b['z']],
            capability='garden', kind='garden_bed', size_m=2.4, rot_deg=math.degrees(b['rotation']), y_off_m=0., support_surface='island_ground',
            description='Shared garden bed. Seeds and water are available here.', affordances={'gardening': 1.})
    for oid in set(previous) - set(authored):
        obj = room.objects.get(oid); old = previous[oid]
        if obj and obj.position_m == [old['x'], -old['z']] and obj.name == old['name']:
            del room.objects[oid]
    room.authored_garden = authored
    room.garden_config = (path, world, settings_path)
    room.garden = Garden(path, world, room, settings_path=settings_path) if any(o.capability == 'garden' for o in room.objects.values()) else None


def configure_room(room, root, settings_path=None):
    """Give ordinary rooms a local garden store, without creating empty files."""
    if not hasattr(room, 'garden_config'):
        import hashlib
        key = hashlib.sha256(room.id.encode('utf-8')).hexdigest()[:24]
        room.garden_config = (Path(root)/(key+'.json'), {}, settings_path)


def room_garden(room):
    garden = getattr(room, 'garden', None)
    if not garden and hasattr(room, 'garden_config') and any(o.capability == 'garden' for o in room.objects.values()):
        with LOCK:
            garden = getattr(room, 'garden', None)
            if not garden:
                path, world, settings = room.garden_config
                garden = room.garden = Garden(path, world, room, settings_path=settings)
    return garden


def live_site_error(room, spec):
    """Check a new bed's footprint without clearing any existing world objects."""
    x, z = float(spec.position_m[0]), -float(spec.position_m[1])
    if not all(math.isfinite(v) for v in (x, z, spec.rot_deg, spec.y_off_m, spec.size_m)):
        return 'Choose a finite garden bed position and size.'
    if spec.support_surface in ('yurt_wall', 'object'):
        return 'Place a garden bed on the ground or a floor.'
    nav = getattr(room, 'navigation', None)
    heights = []
    turn = math.radians(spec.rot_deg); c, s = math.cos(turn), math.sin(turn)
    for ix in range(5):
        for iz in range(5):
            dx, dz = (ix/4-.5)*spec.size_m, (iz/4-.5)*spec.size_m*DEPTH/WIDTH
            px, pz = x+c*dx+s*dz, z-s*dx+c*dz
            if not room.object_position_supported([px, -pz], .02, spec.support_surface):
                return 'Keep the whole garden bed on its floor.'
            if nav and spec.support_surface != 'free':
                y = nav.terrain(px, pz)
                if y is None or nav.water(px, pz) > y:
                    return 'Choose dry ground for the garden bed.'
                heights.append(y)
    if heights and max(heights)-min(heights) > .3:
        return 'Choose flatter ground so the bed rests on its soil.'
    elevation = spec.y_off_m + ((nav.terrain(x,z) or 0) if nav and spec.support_surface != 'free' else 0)
    for obj in room.objects.values():
        if abs(room.object_elevation(obj.id)-elevation) > .6: continue
        dx, dz = obj.position_m[0]-x, -obj.position_m[1]-z
        local_x, local_z = c*dx-s*dz, s*dx+c*dz
        distance = math.hypot(max(0,abs(local_x)-spec.size_m/2), max(0,abs(local_z)-spec.size_m*DEPTH/WIDTH/2))
        if distance < room._footprint_r(obj)+.1:
            return 'Leave space around '+obj.name+'.'
    return None
