"""Furniture support geometry in the same normalized frame as the renderers."""
import json
import math
from pathlib import Path

PROFILES = json.loads((Path(__file__).resolve().parents[1] / 'assets/jnaiq/island-workshop/furniture-rest-profiles.json').read_text()) if (Path(__file__).resolve().parents[1] / 'assets/jnaiq/island-workshop/furniture-rest-profiles.json').exists() else {}
BED_POSES = ('back', 'left', 'right', 'front', 'elbow_left', 'elbow_right', 'sit_up', 'sit_edge_left', 'sit_edge_right')

def profile(obj):
    return PROFILES.get(obj.id) or PROFILES.get(obj.kind)

def base_height(room, obj, seen=None):
    seen = set(seen or ())
    if obj.id in seen:
        raise ValueError('cyclic furniture support')
    seen.add(obj.id)
    if obj.support_surface == 'free':
        return obj.y_off_m
    if obj.support_surface == 'object' and obj.support_oid in room.objects:
        parent = room.objects[obj.support_oid]
        p = profile(parent)
        if not p:
            raise ValueError('supporting object has no measured geometry')
        return base_height(room, parent, seen) + p['height'] * parent.size_m + obj.y_off_m
    nav = getattr(room, 'navigation', None)
    return (nav.terrain(*[obj.position_m[0], -obj.position_m[1]]) or 0 if nav else 0) + obj.y_off_m

def support(room, obj, pose='seat', offset=0):
    p = profile(obj)
    if not p:
        return None
    h = math.radians(obj.rot_deg)
    facing = obj.rot_deg + p['facing_deg']
    turn = math.radians(p['facing_deg'])
    cross_width = abs(math.cos(turn))*p['width'] + abs(math.sin(turn))*p['depth']
    long_depth = abs(math.sin(turn))*p['width'] + abs(math.cos(turn))*p['depth']
    x, z = [v * obj.size_m for v in p['center']]
    x += math.cos(math.radians(p['facing_deg'])) * offset
    z -= math.sin(math.radians(p['facing_deg'])) * offset
    if pose.startswith('sit_edge'):
        side = -1 if pose.endswith('left') else 1
        x += side * math.cos(turn) * cross_width * obj.size_m * .36
        z -= side * math.sin(turn) * cross_width * obj.size_m * .36
        facing += side * -90
    position = [obj.position_m[0] + math.cos(h)*x + math.sin(h)*z,
                obj.position_m[1] + math.sin(h)*x - math.cos(h)*z]
    return {'object': obj.id, 'variant': pose, 'offset_m': offset, 'position_m': position,
            'heading_deg': facing % 360, 'surface_y_m': base_height(room,obj)+p['surface']*obj.size_m,
            'width_m': cross_width*obj.size_m, 'depth_m': long_depth*obj.size_m}
