import {N,random,heightAt,clamp} from './terrain.mjs?caves=retired';
import {inPond,pondEdge,validatePond} from './pond-shape.mjs';

export function nearestFeature(f,x,z){
  if(f.kind==='pond')return {distance:inPond(f.points,x,z)?0:pondEdge(f.points,x,z),y:f.points[0].y};
  let best={distance:Infinity,y:0};
  for(let i=1;i<f.points.length;i++){
    const a=f.points[i-1],b=f.points[i],dx=b.x-a.x,dz=b.z-a.z;
    const t=clamp(((x-a.x)*dx+(z-a.z)*dz)/(dx*dx+dz*dz||1),0,1);
    const distance=Math.hypot(x-a.x-dx*t,z-a.z-dz*t);
    if(distance<best.distance)best={distance,y:a.y+(b.y-a.y)*t};
  }
  return best;
}
export const featureDistance=(f,x,z)=>nearestFeature(f,x,z).distance;
export function validateFeatures(features,size){
  if(features===undefined)return;
  if(!Array.isArray(features)||features.length>12)throw Error('Invalid landscape features');
  for(const f of features){
    if(!f||!['river','road','pond'].includes(f.kind)||!Number.isFinite(f.width)||f.width<1||f.width>16||!Array.isArray(f.points)||f.points.length<2||f.points.length>256)throw Error('Invalid landscape feature');
    for(const p of f.points)if(!p||![p.x,p.y,p.z].every(Number.isFinite)||Math.abs(p.x)>size/2||Math.abs(p.z)>size/2||p.y< -12||p.y>65)throw Error('Invalid feature route');
    if(f.kind==='river'&&f.points.some((p,i)=>i&&p.y>f.points[i-1].y+.00001))throw Error('River must flow downhill');
    if(f.kind==='pond'){validatePond(f.points);if(f.points.some(p=>Math.abs(p.y-f.points[0].y)>.00001))throw Error('Pond water must be level.');}
  }
}
export function generateFeatures(w,{river=false,road=false}={}){
  if(!river&&!road)return;
  w.features=[];
  const rng=random(w.seed^0x49bc1),phase=rng()*Math.PI*2,angle=rng()*Math.PI*2;
  const rotate=(x,z)=>({x:x*Math.cos(angle)-z*Math.sin(angle),z:x*Math.sin(angle)+z*Math.cos(angle)});
  if(river){
    // Start on an interior rise, then incise a continuous route out to sea.
    let start={x:0,z:0},highest=-Infinity;
    for(let i=0;i<40;i++){const p=rotate((rng()-.5)*w.size*.24,(rng()-.5)*w.size*.24),h=heightAt(w,p.x,p.z);if(h>highest){highest=h;start=p;}}
    const points=[];let level=highest-.5;
    for(let i=0;i<=100;i++){
      const t=i/100,offset=rotate(Math.sin(t*8+phase)*Math.sin(t*Math.PI)*w.size*.045,t*w.size*.53);
      const x=clamp(start.x+offset.x,-w.size*.49,w.size*.49),z=clamp(start.z+offset.z,-w.size*.49,w.size*.49);
      const ground=heightAt(w,x,z);level=Math.max(.06,Math.min(level-.014,ground-.30));points.push({x,z,y:level});
      if(ground<0&&i>8)break;
    }
    const f={kind:'river',width:Math.max(3.2,w.size*.026),points};w.features.push(f);
    // Lower the full channel bed, with a softer transition into existing banks.
    for(let j=1;j<N;j++)for(let i=1;i<N;i++){
      const x=(i/N-.5)*w.size,z=(j/N-.5)*w.size,k=j*(N+1)+i,n=nearestFeature(f,x,z);
      const bank=clamp((f.width*.5+w.size/N*1.5-n.distance)/(w.size/N*1.5),0,1);
      if(bank)w.heights[k]=Math.min(w.heights[k],w.heights[k]+(n.y-.65-w.heights[k])*bank);
    }
    // At a steep lip, a heightfield triangle can bridge over its nearest
    // channel samples. Clear those triangles across the water's full width.
    for(let q=1;q<points.length;q++){
      const a=points[q-1],b=points[q],length=Math.hypot(b.x-a.x,b.z-a.z)||1;
      for(let t=0;t<=1;t+=.25)for(let side=-1;side<=1;side+=.5){
        const x=a.x+(b.x-a.x)*t-(b.z-a.z)/length*side*f.width*.5,z=a.z+(b.z-a.z)*t+(b.x-a.x)/length*side*f.width*.5,y=a.y+(b.y-a.y)*t;
        const delta=heightAt(w,x,z)-(y-.35);if(delta<=0)continue;
        const i=clamp(Math.floor((x/w.size+.5)*N),1,N-2),j=clamp(Math.floor((z/w.size+.5)*N),1,N-2),k=j*(N+1)+i;
        for(const index of [k,k+1,k+N+1,k+N+2])w.heights[index]=Math.max(-12,w.heights[index]-delta);
      }
    }
  }
  if(road){
    // A crescent route around the uplands; split at wet ground and river crossings.
    let points=[];
    const flush=()=>{if(points.length>3)w.features.push({kind:'road',width:3.2,points});points=[];};
    for(let i=0;i<=120;i++){
      const a=angle+i/120*Math.PI*1.65,r=w.size*(.22+.025*Math.sin(a*3+phase)),x=Math.cos(a)*r,z=Math.sin(a)*r,y=heightAt(w,x,z);
      if(y<1||(w.features.filter(f=>f.kind==='river').some(f=>featureDistance(f,x,z)<f.width*.5+3))){flush();continue;}
      points.push({x,z,y});
    }
    flush();w.features=w.features.slice(0,12);
  }
}
