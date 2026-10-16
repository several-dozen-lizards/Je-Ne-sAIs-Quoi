import * as THREE from './vendor/three.module.js';
import {mergeGeometries} from './vendor/BufferGeometryUtils.js';
import {heightAt,N} from './terrain.mjs';
import {BED_WIDTH as W,BED_DEPTH as D,bedPoint} from './garden.mjs';

// One mesh per material across the whole garden, with no per-plant draw calls.
export function createGardenLayer(scene,invalidate=()=>{}){
  const root=new THREE.Group();root.userData.garden=true;scene.add(root);let signature='';
  const palette={wood:0x967251,end:0xb5936d,soil:0x544033,wet:0x3a3026,leaf:0x477647,lightLeaf:0x80a54c,radish:0xc64c6f,tomato:0xdc5536,unripe:0x8a9f43,stem:0x567445};
  const materials=Object.fromEntries(Object.entries(palette).map(([k,color])=>[k,new THREE.MeshStandardMaterial({color,roughness:.94})]));
  const bases={box:new THREE.BoxGeometry(1,1,1),sphere:new THREE.SphereGeometry(1,8,5),stem:new THREE.CylinderGeometry(1,1,1,6)};
  function clear(){for(const m of [...root.children]){m.geometry.dispose();root.remove(m);}}
  function sync(world,beds=world.garden?.beds||[]){
    const terrainKey=b=>{if(Number.isFinite(b.y_m))return b.y_m;const values=[];const cell=v=>(v/world.size+.5)*N;
      for(let z=Math.max(0,Math.floor(cell(b.z-1.6)));z<=Math.min(N,Math.ceil(cell(b.z+1.6)));z++)for(let x=Math.max(0,Math.floor(cell(b.x-1.6)));x<=Math.min(N,Math.ceil(cell(b.x+1.6)));x++)values.push(world.heights[z*(N+1)+x]);return values;};
    const key=JSON.stringify(beds.map(b=>[b.id,b.x,b.z,b.rotation,b.scale,b.crop,Math.min(4,Math.floor((b.progress||0)*4)),(b.moisture??.5)>.4,terrainKey(b)]));
    if(key===signature)return;signature=key;clear();const groups={};
    function part(b,shape,mat,x,y,z,sx,sy,sz,rx=0,ry=0,rz=0){
      const scale=b.scale??1,p=bedPoint(b,x*scale,z*scale),g=bases[shape].clone(),matrix=new THREE.Matrix4();
      const turn=new THREE.Quaternion().setFromEuler(new THREE.Euler(rx,ry,rz));
      turn.premultiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0,1,0),b.rotation));
      matrix.compose(new THREE.Vector3(p.x,(b.y_m??heightAt(world,p.x,p.z))+y*scale,p.z),turn,new THREE.Vector3(sx*scale,sy*scale,sz*scale));g.applyMatrix4(matrix);(groups[mat]??=[]).push(g);
    }
    for(const b of beds){
      part(b,'box',(b.moisture??.5)>.4?'wet':'soil',0,.055,0,W,.1,D);
      for(const z of [-D/2,D/2])part(b,'box','wood',0,.13,z,W+.15,.23,.09);
      for(const x of [-W/2,W/2])part(b,'box','end',x,.13,0,.1,.23,D);
      for(const x of [-W/2,W/2])for(const z of [-D/2,D/2])part(b,'box','end',x,.16,z,.14,.32,.14);
      // Furrows and small clods give the empty bed texture without a bitmap.
      for(let i=0;i<6;i++)part(b,'box','soil',-.96+i*.38,.115,0,.04,.025,D-.24);
      if(!b.crop)continue;
      const stage=Math.min(4,Math.floor((b.progress||0)*4)),growth=.2+stage*.2;
      for(let i=0;i<8;i++){
        const x=(i%4-1.5)*.51,z=(Math.floor(i/4)-.5)*.77,angle=i*2.399;
        const tall=b.crop==='tomato',h=tall?.15+growth*.78:.1+growth*.18;
        part(b,'stem','stem',x,.12+h/2,z,.018,h,.018);
        const leaves=b.crop==='lettuce'?9:5;
        for(let l=0;l<leaves;l++){
          const a=angle+l*Math.PI*2/leaves,r=(b.crop==='lettuce'?.13:.1)*growth;
          part(b,'sphere',l%2?'lightLeaf':'leaf',x+Math.cos(a)*r,.12+h*(tall?.55:1)+l*(tall?.065:0),z+Math.sin(a)*r,
            (b.crop==='lettuce'?.14:.065)*growth,.025+growth*.025,(b.crop==='lettuce'?.24:.18)*growth,.35,a,tall?.5:0);
        }
        if(stage>=2&&b.crop==='radish')part(b,'sphere','radish',x,.13,z,.105*growth,.1*growth,.105*growth);
        if(stage>=2&&tall)for(let f=0;f<3;f++){
          const a=angle+f*2.1;
          part(b,'sphere',stage>=4?'tomato':'unripe',x+Math.cos(a)*.12,.12+h*.63+f*.07,z+Math.sin(a)*.12,.075*growth,.08*growth,.075*growth);
        }
      }
    }
    for(const [mat,geometries] of Object.entries(groups)){
      const mesh=new THREE.Mesh(mergeGeometries(geometries),materials[mat]);geometries.forEach(g=>g.dispose());
      mesh.castShadow=true;mesh.receiveShadow=true;mesh.userData.walkThrough=true;mesh.userData.garden=true;root.add(mesh);
    }
    invalidate(true);
  }
  return {root,sync,dispose(){clear();Object.values(materials).forEach(m=>m.dispose());Object.values(bases).forEach(g=>g.dispose());scene.remove(root);}};
}
