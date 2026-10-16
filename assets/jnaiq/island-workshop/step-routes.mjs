import * as THREE from './vendor/three.module.js';
import {N,heightAt,insideStructure,clamp} from './terrain.mjs?caves=retired';
import {featureDistance} from './landscape-features.mjs?caves=retired';

export function routeFrame(r,x,z){
  const dx=r.b.x-r.a.x,dz=r.b.z-r.a.z,length=Math.hypot(dx,dz);
  return {length,along:((x-r.a.x)*dx+(z-r.a.z)*dz)/length,across:((x-r.a.x)*-dz+(z-r.a.z)*dx)/length};
}
export function validateStepRoutes(routes,size){
  if(routes===undefined)return;
  if(!Array.isArray(routes)||routes.length>64)throw Error('An island supports up to 64 stair or slope runs.');
  for(const r of routes){
    if(!r||!['built','rock','slope'].includes(r.kind)||!Number.isFinite(r.width)||r.width<1.5||r.width>12)throw Error('Invalid stair width or finish.');
    for(const p of [r.a,r.b])if(!p||![p.x,p.y,p.z].every(Number.isFinite)||Math.abs(p.x)>size/2-r.width/2||Math.abs(p.z)>size/2-r.width/2||p.y<.3||p.y>65)throw Error('Keep the whole run on dry land inside the island.');
    const length=routeFrame(r,r.b.x,r.b.z).length,rise=r.b.y-r.a.y,count=Math.max(1,Math.ceil(rise/.18));
    if(length<2||rise<0||count>256||rise/length>.5||(r.kind!=='slope'&&length/(count+1)<.3))throw Error('Drag a longer run for this height change (at least twice the rise).');
  }
}
export function planStepRoute(world,start,end,kind,width){
  let a={x:start.x,y:heightAt(world,start.x,start.z),z:start.z},b={x:end.x,y:heightAt(world,end.x,end.z),z:end.z};
  if(a.y>b.y)[a,b]=[b,a];
  const r={kind,width,a,b};validateStepRoutes([...(world.stepRoutes||[]),r],world.size);
  const length=routeFrame(r,b.x,b.z).length,spacing=Math.min(.4,world.size/N/2);
  for(let i=0;i<=Math.ceil(length/spacing);i++){
    const t=i/Math.ceil(length/spacing),x=a.x+(b.x-a.x)*t,z=a.z+(b.z-a.z)*t;
    if(heightAt(world,x,z)<.3||(world.features||[]).some(f=>f.kind!=='road'&&featureDistance(f,x,z)<width/2+f.width/2))throw Error('Choose a dry route clear of rivers and ponds.');
    if((world.structures||[]).some(s=>insideStructure(s,x,z,width/2+1)))throw Error('Keep this run clear of buildings.');
    if((world.objects||[]).some(o=>o.source!=='scatter'&&Math.hypot(o.x-x,o.z-z)<width/2+o.scale*2))throw Error('Move hand-placed scenery out of this run first.');
    if((world.columns||[]).some(c=>Math.hypot(c.x-x,c.z-z)<width/2+(c.length||0)/2+c.radius+1)||(world.rockSculpt||[]).some(p=>p[3]>0&&Math.hypot(p[0]-x,p[2]-z)<width/2+2))throw Error('Keep steps clear of columns and sculpted rock.');
    if((world.stepRoutes||[]).some(s=>{const f=routeFrame(s,x,z);return f.along>-.5&&f.along<f.length+.5&&Math.abs(f.across)<(s.width+width)/2;}))throw Error('This run overlaps existing steps. Undo or choose a clear route.');
  }
  return r;
}
export function applyStepRoute(world,r){
  const grid=world.size/N,padding=grid*1.5;
  // Lower intersecting terrain vertices beneath the precise tread mesh. A
  // feathered shoulder joins the cut to the surrounding coarse height field.
  for(let j=1;j<N;j++)for(let i=1;i<N;i++){
    const x=(i/N-.5)*world.size,z=(j/N-.5)*world.size,f=routeFrame(r,x,z);
    if(f.along< -padding||f.along>f.length+padding)continue;
    const edge=Math.max(Math.abs(f.across)-r.width/2, -f.along,f.along-f.length,0);
    if(edge>=padding)continue;
    const t=clamp(f.along/f.length,0,1),join=Math.min(clamp(f.along/2,0,1),clamp((f.length-f.along)/2,0,1));
    const target=r.a.y+(r.b.y-r.a.y)*t-(r.kind==='slope'?.035:.2)*join-.005;
    const k=j*(N+1)+i,weight=1-clamp((edge-grid)/Math.max(.01,padding-grid),0,1);
    world.heights[k]+=Math.min(0,target-world.heights[k])*weight;
  }
  world.objects=world.objects.filter(o=>{const f=routeFrame(r,o.x,o.z);return o.source!=='scatter'||f.along< -padding||f.along>f.length+padding||Math.abs(f.across)>r.width/2+o.scale*2+padding;});
  (world.stepRoutes??=[]).push(r);
}
export function stepRouteGeometry(r){
  const length=routeFrame(r,r.b.x,r.b.z).length,rise=r.b.y-r.a.y;
  const steps=Math.max(1,Math.ceil(rise/.18)),count=r.kind==='slope'?1:steps+1,vertices=[],colours=[];
  const dx=(r.b.x-r.a.x)/length,dz=(r.b.z-r.a.z)/length;
  function point(x,y,s){return [r.a.x+dx*s-dz*x,y,r.a.z+dz*s+dx*x];}
  function quad(a,b,c,d,tone){for(const p of [a,b,c,a,c,d]){vertices.push(...p);colours.push(...tone);}}
  for(let i=0;i<count;i++){
    const s0=i/count*length,s1=(i+1)/count*length;
    const y0=r.a.y+rise*(r.kind==='slope'?0:i/steps),y1=r.kind==='slope'?r.b.y:y0;
    // Irregular outer edges, with level, full-width walkable stone treads.
    const edge=r.kind==='rock'?.08*(.5+.5*Math.sin(i*2.399)):0,w=r.width/2+edge;
    const a=point(-w,y0,s0),b=point(w,y0,s0),c=point(w,y1,s1),d=point(-w,y1,s1);
    const low=-12,aa=point(-w,low,s0),bb=point(w,low,s0),cc=point(w,low,s1),dd=point(-w,low,s1);
    const shade=r.kind==='built'?.48+.035*(i%2):r.kind==='rock'?.36+.08*Math.sin(i*1.71):.40;
    const tone=r.kind==='slope'?[shade*.85,shade,shade*.67]:[shade,shade*.97,shade*.9];
    const side=tone.map(v=>v*.72);
    quad(a,b,c,d,tone);quad(aa,bb,b,a,side);quad(bb,cc,c,b,side);quad(cc,dd,d,c,side);quad(dd,aa,a,d,side);
  }
  const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.Float32BufferAttribute(vertices,3));geometry.setAttribute('color',new THREE.Float32BufferAttribute(colours,3));geometry.computeVertexNormals();return geometry;
}
export function createStepSurfaces(scene,terrainMaterial){
  const root=new THREE.Group(),material=new THREE.MeshStandardMaterial({vertexColors:true,roughness:1});scene.add(root);
  return {rebuild(world){for(const child of [...root.children]){child.geometry.dispose();root.remove(child);}for(const r of world.stepRoutes||[]){
    const geometry=stepRouteGeometry(r),natural=r.kind!=='built'&&terrainMaterial;
    if(natural){const count=geometry.attributes.position.count,paint=new Float32Array(count*4);if(r.kind==='rock')for(let i=0;i<count;i++)paint[i*4+2]=1;
      geometry.setAttribute('groundPaint',new THREE.BufferAttribute(paint,4));
      for(const key of ['groundExtra0','groundExtra1'])geometry.setAttribute(key,new THREE.BufferAttribute(new Float32Array(count*4),4));}
    const mesh=new THREE.Mesh(geometry,natural?terrainMaterial:material);mesh.castShadow=mesh.receiveShadow=true;root.add(mesh);
  }}};
}
