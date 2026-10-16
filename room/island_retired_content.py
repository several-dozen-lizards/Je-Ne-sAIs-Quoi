"""Read legacy islands without restoring retired cave geometry or attachments."""
from copy import deepcopy
import math

RETIRED_SCENERY = {'cave_tunnel', 'cave_grotto', 'stalagmite', 'stalactite'}


def remove_retired_caves(world):
    world = deepcopy(world)
    if not isinstance(world.get('objects'), list):
        return world
    world['objects'] = [o for o in world['objects']
                        if not isinstance(o, dict) or o.get('kind') not in RETIRED_SCENERY]
    for o in world['objects']:
        if isinstance(o, dict):
            o.pop('anchorId', None)
    h = world.get('heights')
    for b in world.get('structures', []) if isinstance(world.get('structures', []), list) else []:
        if not isinstance(b, dict):
            continue
        if b.get('supportId') and isinstance(h, list) and len(h) == 129**2:
            x, z, size = b.get('x'), b.get('z'), world.get('size')
            if all(type(v) in (int, float) and math.isfinite(v) for v in (x, z, size)) and size > 0:
                u, v = [max(0, min(128, (p / size + .5) * 128)) for p in (x, z)]
                i, j = min(127, int(u)), min(127, int(v))
                a, c, k = u-i, v-j, j*129+i
                if all(type(h[n]) in (int, float) for n in (k, k+1, k+129, k+130)):
                    b['y'] = (h[k]+a*(h[k+1]-h[k])+c*(h[k+129]-h[k]) if a+c <= 1 else
                              h[k+130]+(1-a)*(h[k+129]-h[k+130])+(1-c)*(h[k+1]-h[k+130])) + .12
        b.pop('supportId', None)
        b.pop('supportSurface', None)
    return world
