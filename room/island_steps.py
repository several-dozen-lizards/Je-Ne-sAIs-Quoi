"""Bounded saved stair runs; rendering and collision share the JS constructor."""
import math


def validate_step_routes(routes, size):
    def number(v, low, high):
        return type(v) in (int, float) and math.isfinite(v) and low <= v <= high
    if not isinstance(routes, list) or len(routes) > 64:
        raise ValueError('An island supports up to 64 stair or slope runs')
    result = []
    for r in routes:
        if not isinstance(r, dict) or r.get('kind') not in ('built', 'rock', 'slope') or not number(r.get('width'), 1.5, 12):
            raise ValueError('Invalid stair width or finish')
        width = r['width']
        for p in (r.get('a'), r.get('b')):
            if not isinstance(p, dict) or not number(p.get('y'), .3, 65) or any(not number(p.get(k), -size/2+width/2, size/2-width/2) for k in ('x', 'z')):
                raise ValueError('Invalid stair endpoint')
        a, b = r['a'], r['b']
        length = math.hypot(b['x']-a['x'], b['z']-a['z'])
        rise = b['y']-a['y']
        count = max(1, math.ceil(rise/.18))
        if length < 2 or rise < 0 or count > 256 or rise/length > .5 or (r['kind'] != 'slope' and length/(count+1) < .3):
            raise ValueError('Stair run is too steep or too short')
        result.append(dict(kind=r['kind'], width=width, a={k:a[k] for k in ('x','y','z')}, b={k:b[k] for k in ('x','y','z')}))
    return result
