import * as THREE from './vendor/three.module.js';
import {polyhavenSurface} from './polyhaven-surfaces.mjs';
import {N,heightAt,slopeAt,random,insideStructure} from './terrain.mjs?caves=retired';
import {featureDistance} from './landscape-features.mjs?caves=retired';
import {leafCarpetGeometry,coverKind} from './leaf-carpet.mjs';

export function grassSites(w,budget=18000){
  const rng=random(w.seed^0x4e873),sites=[],arid=['desert','craggy'].includes(w.style),density=arid?.18:1;
  const attempts=Math.min(60000,Math.ceil(w.size*w.size*2)),step=w.size/N;
  // Spatial bins keep exclusions cheap even in densely wooded worlds.
  const bins=new Map();for(const o of w.objects){const k=`${Math.floor(o.x/8)},${Math.floor(o.z/8)}`;if(!bins.has(k))bins.set(k,[]);bins.get(k).push(o);}
  for(let i=0;i<attempts&&sites.length<budget;i++){
    const x=(rng()-.5)*w.size,z=(rng()-.5)*w.size,h=heightAt(w,x,z),roll=rng();
    if(h<.8||slopeAt(w,x,z)>.65||roll>density)continue;
    const cell=Math.round((z/w.size+.5)*N)*(N+1)+Math.round((x/w.size+.5)*N);
    if(w.groundPaint&&w.groundPaint.slice(cell*4+1,cell*4+4).some(v=>v>35))continue;
    if(w.groundPaintExtra&&[0,1,2,4,5].some(channel=>w.groundPaintExtra[cell*8+channel]>35))continue;
    if((w.features||[]).some(f=>featureDistance(f,x,z)<f.width/2+.7))continue;
    if((w.stepRoutes||[]).some(r=>featureDistance({points:[r.a,r.b]},x,z)<r.width/2+.7))continue;
    if((w.structures||[]).some(b=>insideStructure(b,x,z,.4)))continue;
    const bx=Math.floor(x/8),bz=Math.floor(z/8);let blocked=false;
    for(let dx=-1;dx<=1;dx++)for(let dz=-1;dz<=1;dz++)if((bins.get(`${bx+dx},${bz+dz}`)||[]).some(o=>Math.hypot(o.x-x,o.z-z)<o.scale*(o.kind.includes('rock')?1.4:.22)))blocked=true;
    if(blocked)continue;
    sites.push({x,y:h-.035,z,rotation:rng()*Math.PI*2,height:.22+rng()*.26,width:.85+rng()*.65,tint:rng()});
  }
  return sites;
}
export function createGroundCover(scene,invalidate,mount=null){
  const coverSurface=polyhavenSurface('leafy_grass',invalidate);
  let meshes=[],lastWorld=null,enabled=true;
  try{enabled=localStorage.getItem('jnsq-ground-cover')!=='off';}catch{}
  const wrapper=document.createElement('div');wrapper.id='groundCoverControls';
  const control=document.createElement('label'),input=document.createElement('input');input.type='checkbox';input.id='groundCover';input.checked=enabled;
  control.style.cssText='display:flex;align-items:center;gap:8px';input.style.width='auto';
  control.append(input,' Layered groundcover');
  const hint=document.createElement('p');hint.textContent='Grass, leafy carpets and occasional flowers on suitable ground. Uses a fixed detail budget and fades in the distance. Switch off for better performance; placed plants stay intact.';
  wrapper.append(control,hint);if(mount)mount.append(control);else document.getElementById('scatter').after(wrapper);
  const positions=[],colours=[],uvs=[];
  // Overlapping fans with arched tips give a soft clump silhouette, rather
  // than five isolated straight spikes. Keep a single instanced draw call.
  for(let i=0;i<9;i++){
    const a=i*2.399,r=.06+(i%3)*.07,x=Math.cos(a)*r,z=Math.sin(a)*r,wx=Math.cos(a+1.57)*.027,wz=Math.sin(a+1.57)*.027;
    const crown=.52+(i*7%9)*.068,bend=.20+(i%4)*.09;
    const points=[[x-wx,0,z-wz],[x+wx,0,z+wz],[x+wx*.58+Math.cos(a)*bend*.35,crown*.78,z+wz*.58+Math.sin(a)*bend*.35],[x-wx*.58+Math.cos(a)*bend*.35,crown*.78,z-wz*.58+Math.sin(a)*bend*.35],[x+Math.cos(a)*bend,crown*.94,z+Math.sin(a)*bend]];
    for(const index of [0,1,2,0,2,3,3,2,4]){positions.push(...points[index]);const t=points[index][1];uvs.push([0,1,1,0,.5][index],t/crown);colours.push(.58+t*.27,.60+t*.28,.40+t*.28);}
  }
  const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));geometry.setAttribute('color',new THREE.Float32BufferAttribute(colours,3));geometry.setAttribute('uv',new THREE.Float32BufferAttribute(uvs,2));geometry.computeVertexNormals();
  // Rounded clump lighting avoids hard flashes between adjacent blade faces.
  const normals=geometry.attributes.normal,n=new THREE.Vector3();
  for(let i=0;i<normals.count;i++){n.fromBufferAttribute(normals,i);n.y=Math.abs(n.y)+1.2;n.normalize();normals.setXYZ(i,n.x,n.y,n.z);}
  const time={value:0},material=new THREE.MeshStandardMaterial({vertexColors:true,side:THREE.DoubleSide,roughness:1});
  material.onBeforeCompile=s=>{
    s.uniforms.grassTime=time;s.uniforms.groundSurface={value:coverSurface.albedo};
    s.vertexShader=s.vertexShader.replace('#include <common>',`#include <common>
      uniform float grassTime;varying float grassDistance;varying vec2 bladeUV;`);
    s.vertexShader=s.vertexShader.replace('#include <begin_vertex>',`#include <begin_vertex>
      bladeUV=uv;
      vec3 grassOrigin=(modelMatrix*instanceMatrix*vec4(0.,0.,0.,1.)).xyz;
      grassDistance=distance(cameraPosition,grassOrigin);
      transformed.x+=sin(grassTime*.8+grassOrigin.x*.7+grassOrigin.z*.4)*position.y*position.y*.05;
      transformed*=1.-smoothstep(65.,140.,grassDistance);`);
    s.fragmentShader=s.fragmentShader.replace('#include <common>',`#include <common>
      varying float grassDistance;varying vec2 bladeUV;uniform sampler2D groundSurface;`);
    s.fragmentShader=s.fragmentShader.replace('#include <normal_fragment_maps>',`#include <normal_fragment_maps>
      // Authored clump normals point toward the sky on both sides of a blade.
      if(!gl_FrontFacing)normal=-normal;`);
    s.fragmentShader=s.fragmentShader.replace('#include <roughnessmap_fragment>',`#include <roughnessmap_fragment>
      bool leafy=bladeUV.y<-.5;
      vec2 surfaceUV=leafy?vec2(bladeUV.x,-bladeUV.y-1.):bladeUV;
      vec4 blade=texture2D(groundSurface,surfaceUV);
      float tip=smoothstep(.72,1.,bladeUV.y);
      float bladeFold=1.-abs(bladeUV.x*2.-1.);
      diffuseColor.rgb*=(.82+blade.b*.18+bladeFold*.12)*mix(.72,1.08,smoothstep(0.,.75,bladeUV.y));
      diffuseColor.rgb=mix(diffuseColor.rgb,diffuseColor.rgb*vec3(1.12,1.02,.77),tip*(.12+blade.a*.22));
      if(leafy){
        float midrib=1.-smoothstep(.012,.045,abs(surfaceUV.x-.5));
        float branch=abs(fract(surfaceUV.y*7.-abs(surfaceUV.x-.5)*3.)-.5);
        float veins=(1.-smoothstep(.018,.085,branch))*(1.-midrib);
        diffuseColor.rgb*=.78+smoothstep(0.,.5,surfaceUV.y)*.25;
        diffuseColor.rgb*=1.+midrib*.16+veins*.07;
      }
      roughnessFactor=.86+blade.a*.12;`);
    s.fragmentShader=s.fragmentShader.replace('#include <clipping_planes_fragment>',`#include <clipping_planes_fragment>
      if(grassDistance>=140.)discard;
      if(bladeUV.y<-.5){
        float leafV=clamp(-bladeUV.y-1.,0.,1.);
        // Trim the coarse support mesh to a rounded, tapered leaf silhouette.
        // No blended cards or extra geometry; surviving fragments write depth.
        float halfWidth=.34*4.*leafV*(1.-leafV);
        if(abs(bladeUV.x-.5)>halfWidth)discard;
      }`);
  };
  material.customProgramCacheKey=()=> 'jnsq-ground-cover-polyhaven-v6';
  const coverGeometry={grass:geometry,leaves:leafCarpetGeometry(),flowers:leafCarpetGeometry(true)};
  function rebuild(world){
    lastWorld=world;for(const mesh of meshes){scene.remove(mesh);mesh.dispose();}meshes=[];if(!enabled)return;
    const sites=grassSites(world);if(!sites.length)return;
    const groups={grass:[],leaves:[],flowers:[]};for(const site of sites)groups[coverKind(site,world)].push(site);
    const matrix=new THREE.Object3D(),colour=new THREE.Color(),up=new THREE.Vector3(0,1,0),normal=new THREE.Vector3(),turn=new THREE.Quaternion();
    const tint=['desert','savanna'].includes(world.style)?[.62,.56,.29]:world.style==='alien'?[.35,.55,.48]:world.style==='enchanted'?[.40,.57,.47]:[.46,.59,.31];
    for(const [kind,group] of Object.entries(groups)){
      if(!group.length)continue;
      const mesh=new THREE.InstancedMesh(coverGeometry[kind],material,group.length);mesh.userData.walkThrough=true;
      group.forEach((p,i)=>{
        const leafy=kind!=='grass',step=world.size/N;
        matrix.position.set(p.x,p.y+(leafy?.055:0),p.z);
        normal.set(heightAt(world,p.x-step,p.z)-heightAt(world,p.x+step,p.z),2*step,heightAt(world,p.x,p.z-step)-heightAt(world,p.x,p.z+step)).normalize();
        matrix.quaternion.setFromUnitVectors(up,normal);turn.setFromAxisAngle(up,p.rotation);matrix.quaternion.multiply(turn);
        matrix.scale.set(p.width,leafy?.38+p.tint*.16:p.height,p.width);matrix.updateMatrix();mesh.setMatrixAt(i,matrix.matrix);
        const leafTint=world.style==='alien'?[.32,.55,.49]:world.style==='enchanted'?[.55,.38,.61]:[.72,.84,.68];
        colour.setRGB(...(leafy?leafTint:tint)).multiplyScalar(.8+p.tint*.35);mesh.setColorAt(i,colour);
      });
      mesh.receiveShadow=true;mesh.userData.groundCover=true;mesh.raycast=()=>{};mesh.computeBoundingSphere();scene.add(mesh);meshes.push(mesh);
    }
  }
  input.onchange=()=>{enabled=input.checked;try{localStorage.setItem('jnsq-ground-cover',enabled?'on':'off');}catch{}if(lastWorld)rebuild(lastWorld);invalidate();};
  return {rebuild,update(seconds){time.value=seconds;}};
}
