import {featureDistance} from './landscape-features.mjs?caves=retired';
import {bedPoint} from './garden.mjs';

// Sample complete segments, including imported routes with widely spaced points.
function along(points,closed,hit,radius=0){
  for(let i=0;i<points.length-(closed?0:1);i++){
    const a=points[i],b=points[(i+1)%points.length],n=Math.max(1,Math.ceil(Math.hypot(b.x-a.x,b.z-a.z)/.5));
    for(let j=0;j<=n;j++)if(hit(a.x+(b.x-a.x)*j/n,a.z+(b.z-a.z)*j/n,radius))return true;
  }
  return false;
}
export function placementClearance(w,feature,margin=0){
  const hit=(x,z,r=0)=>featureDistance(feature,x,z)<=margin+r+(feature.kind==='pond'?0:feature.width/2);
  const features=(w.features||[]).filter(f=>{
    // Dirt paths can meet and cross without deleting the earlier path.
    if(feature.kind==='road'&&f.kind==='road')return true;
    const radius=f.kind==='pond'?0:f.width/2;
    return !along(f.points,f.kind==='pond',hit,radius)&&
      !along(feature.points,feature.kind==='pond',(x,z)=>featureDistance(f,x,z)<=radius+margin+(feature.kind==='pond'?0:feature.width/2));
  });
  const structures=(w.structures||[]).filter(b=>{
    const c=Math.cos(b.rotation||0),s=Math.sin(b.rotation||0);
    // Test the real rotated footprint, not its oversized bounding circle.
    const nx=Math.ceil(b.width/.5),nz=Math.ceil(b.depth/.5);
    for(let i=0;i<=nx;i++)for(let j=0;j<=nz;j++){
      const x=b.width*(i/nx-.5),z=b.depth*(j/nz-.5);
      if(b.shape==='round'&&(x/(b.width/2))**2+(z/(b.depth/2))**2>1)continue;
      if(hit(b.x+c*x+s*z,b.z-s*x+c*z))return false;
    }
    return true;
  });
  const objects=w.objects.filter(o=>!hit(o.x,o.z,Math.max(.6,1.5*(o.scale||1))));
  const stepRoutes=(w.stepRoutes||[]).filter(r=>!along([r.a,r.b],false,hit,r.width/2));
  const columns=(w.columns||[]).filter(c=>{
    const n=c.length?Math.max(1,Math.ceil(c.length/c.spacing)):0;
    for(let i=0;i<=n;i++){const t=n?i/n-.5:0;if(hit(c.x+Math.cos(c.rotation)*c.length*t,c.z-Math.sin(c.rotation)*c.length*t,c.radius*1.8))return false;}
    return true;
  });
  const garden=w.garden?{...w.garden,beds:w.garden.beds.filter(b=>{
    for(let i=0;i<=6;i++)for(let j=0;j<=4;j++){const p=bedPoint(b,(i/6-.5)*2.4,(j/4-.5)*1.6);if(hit(p.x,p.z,.3))return false;}return true;
  })}:null;
  return {features,structures,objects,stepRoutes,columns,...(garden?{garden}:{})};
}
export function applyClearance(w,clearance){
  for(const [key,value] of Object.entries(clearance))if(key in w||value.length)w[key]=value;
}
