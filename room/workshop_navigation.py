"""Continuous body traversal over editor triangles, with layered support.

Coordinates here are editor x/up/z; room x/y maps to x/-z. Spatial buckets
bound local work. Sweeps subdivide by body radius and stair tread spacing,
not by time, so a long requested move cannot tunnel through a wall.
"""
import math
from array import array
from collections import OrderedDict

RADIUS = .22
HEIGHT = 1.75
STEP = .24
STRIDE = .10
BUCKET = 4.


def inside(points, x, z):
    yes = False
    for a, b in zip(points, points[1:] + points[:1]):
        if (a['z'] > z) != (b['z'] > z) and x < (b['x']-a['x'])*(z-a['z'])/(b['z']-a['z'])+a['x']:
            yes = not yes
    return yes


class Navigation:
    def __init__(self, world, collision):
        self.world = world
        self.buckets = {}
        self.packed = array('f')
        self.cache = OrderedDict()
        for raw in collision['triangles']:
            a, b, c = [raw[i:i+3] for i in (0, 3, 6)]
            u, v = [b[i]-a[i] for i in range(3)], [c[i]-a[i] for i in range(3)]
            normal = [u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0]]
            length = math.sqrt(sum(n*n for n in normal))
            if length < 1e-8:
                continue
            index = len(self.packed)//12
            self.packed.extend([*a,*b,*c,*[n/length for n in normal]])
            for ix in range(math.floor(min(a[0], b[0], c[0])/BUCKET), math.floor(max(a[0], b[0], c[0])/BUCKET)+1):
                for iz in range(math.floor(min(a[2], b[2], c[2])/BUCKET), math.floor(max(a[2], b[2], c[2])/BUCKET)+1):
                    self.buckets.setdefault((ix, iz), []).append(index)

    def terrain(self, x, z):
        w = self.world
        gx, gz = (x/w['size']+.5)*128, (z/w['size']+.5)*128
        if not 0 <= gx < 128 or not 0 <= gz < 128:
            return None
        i, j = math.floor(gx), math.floor(gz)
        fx, fz = gx-i, gz-j
        a, b, c, d = [w['heights'][k] for k in (j*129+i, j*129+i+1, (j+1)*129+i, (j+1)*129+i+1)]
        # Match the rendered triangle diagonal; bilinear interpolation does not.
        return a+(b-a)*fx+(c-a)*fz if fx+fz <= 1 else d+(c-d)*(1-fx)+(b-d)*(1-fz)

    def water(self, x, z, include_pools=True):
        atmosphere=self.world.get('atmosphere',{})
        environment=atmosphere.get('environment','ocean')
        ocean_visible=atmosphere.get('water',{}).get('surface','visible')!='none'
        level = 0. if ocean_visible and environment in ('ocean','aurora','alien','cavern','cavern-glow') else -math.inf
        for f in self.world.get('features', []):
            points = f['points']
            if f['kind'] == 'pond' and inside(points, x, z):
                level = max(level, points[0]['y'])
            elif f['kind'] == 'river':
                for a,b in zip(points,points[1:]):
                    dx,dz=b['x']-a['x'],b['z']-a['z']
                    t=max(0,min(1,((x-a['x'])*dx+(z-a['z'])*dz)/(dx*dx+dz*dz or 1)))
                    if math.hypot(x-a['x']-dx*t,z-a['z']-dz*t)<f['width']/2:
                        level=max(level,a['y']+(b['y']-a['y'])*t)
        for b in self.world.get('structures', []) if include_pools else []:
            p = b.get('pool')
            if not p:
                continue
            dx,dz=x-b['x'],z-b['z'];c,s=math.cos(b['rotation']),math.sin(b['rotation'])
            lx,lz=c*dx-s*dz,s*dx+c*dz
            if abs(lx-p['x'])<p['width']/2 and abs(lz-p['z'])<p['length']/2:
                level=max(level,b['y']-.18)
        return level

    def triangles(self, x, z):
        result=[]
        for index in self.buckets.get((math.floor(x/BUCKET),math.floor(z/BUCKET)), []):
            if index not in self.cache:
                p=self.packed[index*12:index*12+12]
                self.cache[index]=(p[:3],p[3:6],p[6:9],p[9:12],index)
                if len(self.cache)>4096:self.cache.popitem(last=False)
            result.append(self.cache[index])
        return result

    @staticmethod
    def ray_height(t, x, z):
        a,b,c,n=t[:4]
        det=(b[2]-c[2])*(a[0]-c[0])+(c[0]-b[0])*(a[2]-c[2])
        if abs(det)<1e-9:return None
        u=((b[2]-c[2])*(x-c[0])+(c[0]-b[0])*(z-c[2]))/det
        v=((c[2]-a[2])*(x-c[0])+(a[0]-c[0])*(z-c[2]))/det
        if min(u,v,1-u-v)<-1e-7:return None
        return u*a[1]+v*b[1]+(1-u-v)*c[1]

    def support(self, x, z, previous):
        candidates=[]
        terrain=self.terrain(x,z)
        if terrain is not None:
            # A step is a discrete riser; a cliff face is not a long staircase.
            side=[self.terrain(x+dx,z+dz) for dx,dz in ((.05,0),(-.05,0),(0,.05),(0,-.05))]
            if all(v is not None for v in side) and math.hypot((side[0]-side[1])/.1,(side[2]-side[3])/.1)<=1:
                candidates.append(terrain)
        for tri in self.triangles(x,z):
            if tri[3][1]<.70:continue
            y=self.ray_height(tri,x,z)
            if y is not None:candidates.append(y)
        if self.world.get('frozenWater'):
            ice=self.water(x,z,include_pools=False)
            if terrain is not None and terrain<ice:candidates.append(ice)
        candidates=[y for y in candidates if previous-STEP-1e-5<=y<=previous+STEP+1e-5]
        return max(candidates) if candidates else None

    def clear(self, x, y, z):
        # A ring of support and headroom probes supplies a finite body footprint.
        for dx,dz in [(0,0)]+[(math.cos(i*math.tau/8)*RADIUS,math.sin(i*math.tau/8)*RADIUS) for i in range(8)]:
            px,pz=x+dx,z+dz
            if self.support(px,pz,y) is None:return False
            for tri in self.triangles(px,pz):
                h=self.ray_height(tri,px,pz)
                if h is not None and y+STEP+.015<h<y+HEIGHT:return False
        # Vertical faces have zero projected area. Intersect horizontal body
        # slices with their edges and test the resulting line against the radius.
        seen=set()
        for dx in (-RADIUS,0,RADIUS):
            for dz in (-RADIUS,0,RADIUS):
                for tri in self.triangles(x+dx,z+dz):
                    if tri[4] in seen:continue
                    seen.add(tri[4])
                    if abs(tri[3][1])>.7:continue
                    for h in (y+STEP+.025,y+.8,y+HEIGHT):
                        points=[]
                        for a,b in zip(tri[:3],(tri[1],tri[2],tri[0])):
                            if (a[1]<=h<b[1]) or (b[1]<=h<a[1]):
                                f=(h-a[1])/(b[1]-a[1]);points.append((a[0]+(b[0]-a[0])*f,a[2]+(b[2]-a[2])*f))
                        if len(points)<2:continue
                        a,b=points[:2];vx,vz=b[0]-a[0],b[1]-a[1]
                        f=max(0,min(1,((x-a[0])*vx+(z-a[1])*vz)/(vx*vx+vz*vz or 1)))
                        if math.hypot(x-a[0]-vx*f,z-a[1]-vz*f)<RADIUS-.001:return False
        return True

    def trace(self, start, target):
        x,y,z=start;tx,tz=target
        distance=math.hypot(tx-x,tz-z)
        count=max(1,math.ceil(min(distance,self.world['size']*2)/STRIDE))
        if distance>self.world['size']*2:return [list(start)],'outside_world'
        path=[list(start)]
        for i in range(1,count+1):
            px,pz=x+(tx-x)*i/count,z+(tz-z)*i/count
            py=self.support(px,pz,path[-1][1])
            if py is None:return path,'unsupported_ground'
            if not self.clear(px,py,pz):return path,'body_clearance'
            path.append([px,py,pz])
        return path,''

    def arrival(self):
        # Search nearest the origin, using the actual terrain cell spacing.
        step=self.world['size']/128
        candidates=sorted(((i*step,j*step) for i in range(-63,64) for j in range(-63,64)),key=lambda p:p[0]**2+p[1]**2)
        for x,z in candidates:
            y=self.terrain(x,z)
            if y is not None:
                if self.world.get('frozenWater'):y=max(y,self.water(x,z,include_pools=False))
                elif y<=self.water(x,z)+.025:continue
                y=self.support(x,z,y)
                if y is not None and self.clear(x,y,z):return [x,y,z]
        raise ValueError('This world has no dry arrival with body clearance. Create a dry landing area before adding it to JNAIQ.')
