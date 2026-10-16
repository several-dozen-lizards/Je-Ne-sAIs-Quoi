import {N,heightAt,clamp} from './terrain.mjs?caves=retired';
import {nearestFeature,featureDistance,validateFeatures} from './landscape-features.mjs?caves=retired';
import {placementClearance,applyClearance} from './placement-clearance.mjs';
export const GROUND_SURFACES=['Grass','Sand','Natural rock','Earth / dirt','Red clay','Snow','Volcanic basalt','Moss','Gravel','Volcanic ash','Alien turquoise crust','Enchanted violet ground'];
export function validatePaint(p,extra){
  if(p!==undefined&&(!Array.isArray(p)||p.length!==(N+1)**2*4||p.some(v=>!Number.isInteger(v)||v<0||v>255)))throw Error('Invalid ground paint');
  if(p)for(let i=0;i<p.length;i+=4)if(p[i]+p[i+1]+p[i+2]+p[i+3]>255)throw Error('Invalid paint blend');
  if(extra!==undefined){
    if(!Array.isArray(extra)||extra.length!==(N+1)**2*8||extra.some(v=>!Number.isInteger(v)||v<0||v>255))throw Error('Invalid extended ground paint');
    for(let i=0;i<extra.length;i+=8){let total=0;for(let c=0;c<8;c++)total+=extra[i+c];for(let c=0;c<4;c++)total+=p?.[i/2+c]||0;if(total>255)throw Error('Invalid paint blend');}
  }
}
export function paintGround(w,x,z,radius,channel,strength){
  if(!Number.isInteger(channel)||channel< -1||channel>=GROUND_SURFACES.length)throw Error('Unknown ground surface');
  w.groundPaint??=Array((N+1)**2*4).fill(0);
  if(channel>=4)w.groundPaintExtra??=Array((N+1)**2*8).fill(0);
  for(let j=0;j<=N;j++)for(let i=0;i<=N;i++){
    const distance=Math.hypot((i/N-.5)*w.size-x,(j/N-.5)*w.size-z);
    if(distance>=radius)continue;
    const a=clamp(strength*.18*(1-distance/radius)**2,0,1),k=(j*(N+1)+i)*4;
    for(let c=0;c<4;c++)w.groundPaint[k+c]=Math.floor(w.groundPaint[k+c]*(1-a)+(c===channel?255*a:0));
    if(w.groundPaintExtra)for(let c=0;c<8;c++)w.groundPaintExtra[k*2+c]=Math.floor(w.groundPaintExtra[k*2+c]*(1-a)+(c+4===channel?255*a:0));
  }
}
export function applyGroundSurface(w,channel){
  if(!Number.isInteger(channel)||channel< -1||channel>=GROUND_SURFACES.length)throw Error('Unknown ground surface');
  const protectedVertices=new Set(),step=w.size/N;
  // Rock dominates halfway through the renderer's .55–.88 normal-Y blend.
  // Protect every corner of a cliff triangle so paint cannot bleed across it.
  const protect=(a,b,c,dx,dz)=>{
    const normalY=1/Math.sqrt(1+(dx/step)**2+(dz/step)**2);
    if(normalY<(.55+.88)/2){protectedVertices.add(a);protectedVertices.add(b);protectedVertices.add(c);}
  };
  for(let j=0;j<N;j++)for(let i=0;i<N;i++){
    const a=j*(N+1)+i,b=a+1,c=a+N+1,d=c+1,h=w.heights;
    protect(a,b,c,h[b]-h[a],h[c]-h[a]);protect(b,c,d,h[d]-h[c],h[d]-h[b]);
  }
  w.groundPaint??=Array((N+1)**2*4).fill(0);
  if(channel>=4)w.groundPaintExtra??=Array((N+1)**2*8).fill(0);
  let changed=0;
  for(let k=0;k<(N+1)**2;k++){
    if(protectedVertices.has(k))continue;
    let different=false;
    for(let c=0;c<12;c++){
      const values=c<4?w.groundPaint:w.groundPaintExtra;if(!values)continue;
      const index=c<4?k*4+c:k*8+c-4,value=c===channel?255:0;
      different||=values[index]!==value;values[index]=value;
    }
    if(different)changed++;
  }
  return changed;
}
export function addRoute(w,kind,route,width){
  if(route.length<2)throw Error('Mark at least two points.');
  const points=[];
  for(let i=1;i<route.length;i++){
    const a=route[i-1],b=route[i],steps=Math.max(1,Math.ceil(Math.hypot(b.x-a.x,b.z-a.z)/1.5));
    for(let j=0;j<steps;j++){const t=j/steps;points.push({x:a.x+(b.x-a.x)*t,z:a.z+(b.z-a.z)*t});}
  }
  points.push({...route.at(-1)});
  if(points.length>256)throw Error('This route is too long. Finish a shorter section first.');
  let level=heightAt(w,points[0].x,points[0].z)-.25;
  for(const p of points){
    const h=heightAt(w,p.x,p.z);
    if(kind==='river'&&(w.features||[]).some(f=>f.kind==='pond'&&featureDistance(f,p.x,p.z)<width*.5+1))throw Error('Keep routes clear of ponds.');
    if(kind==='road'&&h<.2)throw Error('Paths need dry land; raise ground above sea level first.');
    p.y=kind==='river'?level=Math.max(.06,Math.min(level,h-.25)):h;
    if(kind==='river'&&(w.structures||[]).some(b=>Math.hypot(p.x-b.x,p.z-b.z)<Math.hypot(b.width,b.depth)*.5+width))throw Error('Keep routes clear of buildings.');
  }
  const f={kind,width,points};validateFeatures([f],w.size);
  const clearance=kind==='road'?placementClearance(w,f,.6):null;
  if((clearance?.features||w.features||[]).length>=12)throw Error('This island has 12 routes. Remove one before adding another.');
  if(kind==='river'){
    for(let j=1;j<N;j++)for(let i=1;i<N;i++){
      const k=j*(N+1)+i,n=nearestFeature(f,(i/N-.5)*w.size,(j/N-.5)*w.size);
      const blend=clamp((width*.5+w.size/N*2-n.distance)/(w.size/N*2),0,1);
      if(blend)w.heights[k]=Math.max(-12,Math.min(w.heights[k],w.heights[k]+(n.y-.8-w.heights[k])*blend));
    }
  }
  if(clearance)applyClearance(w,clearance);
  w.features??=[];w.features.push(f);
  w.objects=w.objects.filter(o=>featureDistance(f,o.x,o.z)>width*.5+.6);
  return f;
}
export function removeRoute(w,x,z,radius){
  let best=null,distance=Infinity;
  for(const f of w.features||[]){const d=featureDistance(f,x,z)-f.width*.5;if(d<distance){best=f;distance=d;}}
  if(!best||distance>radius)return false;
  w.features=w.features.filter(f=>f!==best);return true;
}
