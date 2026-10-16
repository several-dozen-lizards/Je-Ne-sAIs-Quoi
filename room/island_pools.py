import math

def validate_pool(b, size):
    p = b.get('pool')
    if p is None:
        return {'pool': None} if 'pool' in b else {}
    def number(v, low, high):
        return type(v) in (int, float) and math.isfinite(v) and low <= v <= high
    if (not isinstance(p, dict) or not all(number(p.get(k), -40, 40) for k in ('x', 'z'))
            or not all(number(p.get(k), 3, 24) for k in ('width', 'length'))
            or not number(p.get('depth'), .6, 2.4)
            or p.get('finish') not in ('marble', 'tiles', 'concrete', 'stone')
            or p.get('steps') not in ('none', 'north', 'south', 'east', 'west')):
        raise ValueError('Invalid pool dimensions, steps or finish')
    clearance = max(1, size / 128 * 1.5 + .25)
    for x in (p['x']-p['width']/2, p['x']+p['width']/2):
        for z in (p['z']-p['length']/2, p['z']+p['length']/2):
            outside = ((x/(b['width']/2-clearance))**2+(z/(b['depth']/2-clearance))**2 > 1 if b['shape']=='round' else abs(x)>b['width']/2-clearance or abs(z)>b['depth']/2-clearance)
            if outside:
                raise ValueError('Leave surrounding floor for the pool excavation')
    length = p['width'] if p['steps'] in ('north', 'south') else p['length']
    if p['steps'] != 'none' and math.ceil(p['depth']/.22)*.32 > length-.8:
        raise ValueError('Pool wall is too short for steps at this depth')
    xmin, xmax = p['x']-p['width']/2-.3, p['x']+p['width']/2+.3
    zmin, zmax = p['z']-p['length']/2-.3, p['z']+p['length']/2+.3
    if b['stairs'] and b['floors']>1 and xmax>=.65 and xmin<=2.95 and zmax>=-3.3 and zmin<=3.3:
        raise ValueError('Pool blocks staircase or landings')
    for wall in b.get('partitions', []):
        if wall['floor'] != 0:
            continue
        lo, hi = 0, 1
        for a,d,low,high in ((wall['ax'],wall['bx']-wall['ax'],xmin,xmax),(wall['az'],wall['bz']-wall['az'],zmin,zmax)):
            if abs(d)<1e-9:
                if a<low or a>high:
                    hi=-1
                    break
            else:
                t1,t2=(low-a)/d,(high-a)/d
                lo=max(lo,min(t1,t2)); hi=min(hi,max(t1,t2))
        if lo<=hi:
            raise ValueError('Pool crosses a ground-floor partition')
    return {'pool': {k:p[k] for k in ('x','z','width','length','depth','steps','finish')}}
