import {localPoint} from './terrain.mjs?caves=retired';

// Clicking the visible exterior wall should join its inner face, rather than
// fail the partition validator's wall-thickness clearance.
export function interiorSurfacePoint(building,point){
  const p=localPoint(building,point.x,point.z),rx=building.width/2,rz=building.depth/2;
  if(building.shape==='round'){
    if((p.x/(rx+.3))**2+(p.z/(rz+.3))**2>1)throw Error('Click inside the selected building.');
    const r=Math.hypot(p.x/(rx-.2),p.z/(rz-.2));if(r>1){p.x/=r;p.z/=r;}
  }else{
    if(Math.abs(p.x)>rx+.3||Math.abs(p.z)>rz+.3)throw Error('Click inside the selected building.');
    p.x=Math.max(-rx+.2,Math.min(rx-.2,p.x));p.z=Math.max(-rz+.2,Math.min(rz-.2,p.z));
  }
  const c=Math.cos(building.rotation),s=Math.sin(building.rotation);
  return {x:building.x+c*p.x+s*p.z,y:point.y,z:building.z-s*p.x+c*p.z};
}

// Snap along the building's own axes, including rotated buildings.
export function snapInteriorEndpoint(building,anchor,point){
  const a=localPoint(building,anchor.x,anchor.z),b=localPoint(building,point.x,point.z);
  if(Math.abs(b.x-a.x)>=Math.abs(b.z-a.z))b.z=a.z;else b.x=a.x;
  const c=Math.cos(building.rotation),s=Math.sin(building.rotation);
  return {x:building.x+c*b.x+s*b.z,y:point.y,z:building.z-s*b.x+c*b.z};
}
