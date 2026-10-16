import * as THREE from './vendor/three.module.js';
import {wallSegments,wallSpec,validateComponents,sectionRoofGeometry,openingInsert,defaultOpeningShape} from './building-components.mjs';
import {validatePool,poolHole,renderPool} from './pools.mjs?caves=retired';
import {OPENING_SHAPES,shapedOpening} from './opening-shapes.mjs?frame-seams=1';
import {COLUMN_STYLES,columnGeometry,pavilionPositions,validateColumnBuilding} from './columns.mjs';
import {buildingMaterial} from './building-materials.mjs';
import {validFinish,validatePartitions} from './building-finishes.mjs';
import {ARCHITECTURES} from './architecture.mjs';
import {architectureRenderer} from './architecture-render.mjs';
import {doorLeafParts} from './door-leaves.mjs';
import {N,clamp,localPoint,insideStructure} from './terrain.mjs?caves=retired';
export {localPoint,insideStructure} from './terrain.mjs?caves=retired';
import {FLOOR_HEIGHT} from './building-dimensions.mjs';
export {FLOOR_HEIGHT};
export function validateStructures(items=[],size=160){
  if(!Array.isArray(items)||items.length>80)throw Error('An island supports up to 80 structures.');
  const ids=new Set();
  for(const b of items){
    if(!b||typeof b.id!=='string'||!b.id.length||b.id.length>80||ids.has(b.id)||!['rectangle','round'].includes(b.shape)||!['auto','flat','none'].includes(b.roof)||!validFinish(b.material)||typeof b.stairs!=='boolean'||!Number.isInteger(b.floors)||b.floors<1||b.floors>4||![b.x,b.z,b.y,b.width,b.depth,b.rotation].every(Number.isFinite)||b.width<(b.shape==='round'?14:10)||b.depth<(b.shape==='round'?14:10)||b.width>40||b.depth>40||b.y< -12||b.y>(b.supportId?128:65)||Math.abs(b.rotation)>Math.PI*2)throw Error('Invalid structure geometry.');
    for(const key of ['floorMaterial','roofMaterial','trimMaterial'])if(b[key]!==undefined&&!validFinish(b[key]))throw Error('Invalid building finish.');
    if(b.architecture!==undefined&&!Object.hasOwn(ARCHITECTURES,b.architecture))throw Error('Invalid architectural style.');
    if(b.tileMetres!==undefined&&(!Number.isFinite(b.tileMetres)||b.tileMetres<.25||b.tileMetres>12))throw Error('Texture repeat must be 0.25–12 metres.');
    if(b.frames!==undefined&&typeof b.frames!=='boolean')throw Error('Invalid opening frames.');
    for(const key of ['windowShape','doorShape'])if(b[key]!==undefined&&!OPENING_SHAPES.includes(b[key]))throw Error('Invalid opening shape.');
    validatePartitions(b);
    validateComponents(b);
    validateColumnBuilding(b);
    validatePool(b,size);
    const c=Math.abs(Math.cos(b.rotation)),s=Math.abs(Math.sin(b.rotation));
    if(Math.abs(b.x)+(c*b.width+s*b.depth)/2>size/2||Math.abs(b.z)+(s*b.width+c*b.depth)/2>size/2)throw Error('Keep the whole structure inside the island bounds.');
    ids.add(b.id);
  }
  return items;
}
export function prepareSite(w,b){
  for(let j=1;j<N;j++)for(let i=1;i<N;i++){
    const x=(i/N-.5)*w.size,z=(j/N-.5)*w.size;if(!insideStructure(b,x,z,3))continue;
    const p=localPoint(b,x,z),distance=b.shape==='round'?(Math.hypot(p.x/(b.width/2),p.z/(b.depth/2))-1)*Math.min(b.width,b.depth)/2:Math.max(Math.abs(p.x)-b.width/2,Math.abs(p.z)-b.depth/2);
    const weight=1-clamp((distance-1)/2,0,1),k=j*(N+1)+i;w.heights[k]+=(b.y-.12-w.heights[k])*weight;
  }
  w.objects=w.objects.filter(o=>!insideStructure(b,o.x,o.z,4*o.scale));
}
export function squareFootprintCorner(a,p){
  const side=Math.max(Math.abs(p.x-a.x),Math.abs(p.z-a.z));
  return {...p,x:a.x+(p.x<a.x?-side:side),z:a.z+(p.z<a.z?-side:side)};
}
export function footprint(a,p,shape,options={}){
  const min=shape==='round'?14:10,width=Math.abs(p.x-a.x),depth=Math.abs(p.z-a.z);
  if(width<min||depth<min||width>40||depth>40)throw Error(`Footprint is ${width.toFixed(1)} × ${depth.toFixed(1)} m. Each side needs ${min}–40 m.`);
  return {id:crypto.randomUUID(),shape,x:(a.x+p.x)/2,z:(a.z+p.z)/2,width,depth,y:0,rotation:0,floors:1,roof:'auto',material:'plaster',stairs:true,...options};
}
export function stairLayout(){return {x:1.8,z:-2.7,width:1.4,run:5.4,steps:18};}
export function makeStructure(b,textures=[]){
  const group=new THREE.Group();group.position.set(b.x,b.y,b.z);group.rotation.y=b.rotation;
  const finish=(kind,r=0)=>buildingMaterial(kind,r,textures.find(t=>t.id===kind),b.tileMetres||2);
  const materials={wall:finish(b.material,b.shape==='round'?(b.width+b.depth)/4:0),inner:finish(b.material),floor:finish(b.floorMaterial||'timber'),roof:finish(b.roofMaterial||'roof'),trim:finish(b.trimMaterial||'timber'),iron:new THREE.MeshStandardMaterial({color:0x242320,roughness:.6,metalness:.72}),doorGlass:new THREE.MeshPhysicalMaterial({color:0x9edff1,transparent:true,opacity:.42,roughness:.08,metalness:0,side:THREE.DoubleSide,depthWrite:false})};
  if(b.enclosure==='columns')materials.column=finish(COLUMN_STYLES[b.columnStyle||'doric'].material);
  if(b.pool){materials.pool=finish(b.pool.finish);materials.poolWater=new THREE.MeshPhongMaterial({color:0x43bfd2,transparent:true,opacity:.48,shininess:110,depthWrite:false,side:THREE.DoubleSide});}
  materials.roof.side=THREE.DoubleSide;materials.wall.side=THREE.DoubleSide;
  function add(g,m,level=0,roof=false){const mesh=new THREE.Mesh(g,typeof m==='string'?materials[m]:m);mesh.castShadow=true;mesh.receiveShadow=true;mesh.userData={level,roof};group.add(mesh);return mesh;}
  function box(w,h,d,x,y,z,m='wall',level=0){const mesh=add(new THREE.BoxGeometry(w,h,d),m,level);mesh.position.set(x,y,z);return mesh;}
  function openingFrame(cx,cz,angle,width,bottom,top,y,level,o=null){
    const kind=o?.shape||defaultOpeningShape(b,bottom===0),frames=o?.frames??(b.frames!==false);
    if(o?.kind==='door'&&o.door==='solid'){
      const leafAngle=angle+o.angle*Math.PI/180,hingeX=cx-Math.cos(angle)*width/2,hingeZ=cz+Math.sin(angle)*width/2;
      const source=textures.find(t=>t.id===o.doorImage),doorMaterial=new THREE.MeshStandardMaterial({color:source?0xffffff:(/^#[0-9a-f]{6}$/i.test(o.doorColor||'')?o.doorColor:'#9a5d31'),roughness:.72,metalness:0});
      if(source){doorMaterial.map=new THREE.TextureLoader().load(source.data,()=>globalThis.dispatchEvent?.(new Event('island-texture-ready')));doorMaterial.map.colorSpace=THREE.SRGBColorSpace;}
      for(const part of doorLeafParts({shape:kind,style:o.doorStyle||'flat',width,height:top-bottom})){
        const leaf=add(part.geometry,part.material==='door'?doorMaterial:part.material,level);leaf.position.set(hingeX,y+bottom,hingeZ);leaf.rotation.y=leafAngle;leaf.userData={...leaf.userData,solid:part.solid,doorStyle:o.doorStyle||'flat',doorFeature:part.feature};
      }
    }else if(o&&o.glass!=='none'){const pane=openingInsert(o,textures);pane.position.set(cx,y+bottom,cz);pane.rotation.y=angle;pane.userData={level,roof:false,solid:true};group.add(pane);}
    if(kind!=='rectangle'){
      const parts=shapedOpening(kind,width,top-bottom);
      const wall=add(parts.wall,'wall',level);wall.position.set(cx,y+bottom,cz);wall.rotation.y=angle;
      if(frames){const trim=add(parts.trim,'trim',level);trim.position.copy(wall.position);trim.rotation.y=angle;}else parts.trim.dispose();
      return;
    }
    if(!frames)return;
    const span=(w,h,offset,cy,depth=.34)=>{const m=box(w,h,depth,cx+Math.cos(angle)*offset,y+cy,cz-Math.sin(angle)*offset,'trim',level);m.rotation.y=angle;};
    span(.12,top-bottom+.12,-width/2,(top+bottom)/2);span(.12,top-bottom+.12,width/2,(top+bottom)/2);span(width+.24,.14,0,top);
    if(bottom>0)span(width+.32,.14,0,bottom,.44);
    architecture.opening(cx,cz,angle,width,bottom,top,y,level);
  }
  const w=b.width,d=b.depth,H=FLOOR_HEIGHT,stair=stairLayout();
  const architecture=architectureRenderer(b,{add,box,H}),styled=(b.architecture||'plain')!=='plain';
  for(let level=0;level<b.floors;level++){
    const y=level*H,shape=new THREE.Shape();
    if(b.shape==='round')shape.absellipse(0,0,w/2,d/2,0,Math.PI*2,false,0);
    else{shape.moveTo(-w/2,-d/2);shape.lineTo(w/2,-d/2);shape.lineTo(w/2,d/2);shape.lineTo(-w/2,d/2);shape.closePath();}
    // Shape Y becomes negative world Z when the slab rotates flat.
    if(level===0)poolHole(shape,b.pool);
    if(level>0&&b.stairs){const hole=new THREE.Path();hole.moveTo(1,-2.7);hole.lineTo(1,2.9);hole.lineTo(2.6,2.9);hole.lineTo(2.6,-2.7);hole.closePath();shape.holes.push(hole);}
    const slab=add(new THREE.ExtrudeGeometry(shape,{depth:.18,bevelEnabled:false,curveSegments:40}),'floor',level);slab.rotation.x=-Math.PI/2;slab.position.y=y-.18;
    if(b.enclosure==='columns'){
      const points=pavilionPositions(b),g=columnGeometry(b.columnStyle||'doric',H-.2,.24),columns=new THREE.InstancedMesh(g,materials.column,points.length);
      points.forEach((p,i)=>columns.setMatrixAt(i,new THREE.Matrix4().makeTranslation(p.x,y,p.z)));columns.userData={level,roof:false};columns.castShadow=true;columns.receiveShadow=true;group.add(columns);
      if(b.shape==='round'){const ring=add(new THREE.TorusGeometry(1,.025,6,64),'column',level);ring.rotation.x=Math.PI/2;ring.scale.set(w/2,d/2,4);ring.position.y=y+H-.1;}
      else{box(w+.6,.2,.6,0,y+H-.1,-d/2,'column',level);box(w+.6,.2,.6,0,y+H-.1,d/2,'column',level);box(.6,.2,d-.6,-w/2,y+H-.1,0,'column',level);box(.6,.2,d-.6,w/2,y+H-.1,0,'column',level);}
    }
    if(b.enclosure!=='columns')wallSegments(b).forEach(({length,angle,cx,cz},i)=>{
      const spec=wallSpec(b,level,i);if(spec.removed)return;
      function span(width,height,offset,cy){if(width<=.0001||height<=.0001)return;const m=box(width,height,.22,cx+Math.cos(angle)*offset,y+cy,cz-Math.sin(angle)*offset,'wall',level);m.rotation.y=angle;}
      let left=-length/2;
      for(const o of [...spec.openings].sort((a,b)=>a.offset-b.offset)){
        const start=o.offset-o.width/2;span(start-left,H,(left+start)/2,H/2);
        span(o.width,o.bottom,o.offset,o.bottom/2);span(o.width,H-o.top,o.offset,o.top+(H-o.top)/2);
        openingFrame(cx+Math.cos(angle)*o.offset,cz-Math.sin(angle)*o.offset,angle,o.width,o.bottom,o.top,y,level,o);
        left=o.offset+o.width/2;
      }
      span(length/2-left,H,(left+length/2)/2,H/2);
    });
    if(b.stairs&&level<b.floors-1){
      for(let i=0;i<stair.steps;i++){const height=(i+1)*H/stair.steps;box(stair.width,height,stair.run/stair.steps,stair.x,y+height/2,stair.z+(i+.5)*stair.run/stair.steps,'floor',level);}
      // Rails follow the flight; upper-floor openings remain clear.
      for(const x of [1.02,2.58]){const rail=box(.065,Math.hypot(stair.run,H),.065,x,y+H/2+.95,0,'trim',level);rail.rotation.x=Math.atan2(stair.run,H);}
      for(let i=0;i<stair.steps;i+=3)for(const x of [1.02,2.58])box(.065,.95,.065,x,y+(i+1)*H/stair.steps+.475,stair.z+(i+.5)*stair.run/stair.steps,'trim',level);
    }
  }
  for(const p of b.partitions||[]){
    const length=Math.hypot(p.bx-p.ax,p.bz-p.az),angle=-Math.atan2(p.bz-p.az,p.bx-p.ax),cx=(p.ax+p.bx)/2,cz=(p.az+p.bz)/2,y=p.floor*H;
    const span=(width,height,offset,cy)=>{const m=box(width,height,.18,cx+Math.cos(angle)*offset,y+cy,cz-Math.sin(angle)*offset,'inner',p.floor);m.rotation.y=angle;};
    if(p.door){const pier=(length-1.1)/2;span(pier,H,-(1.1+pier)/2,H/2);span(pier,H,(1.1+pier)/2,H/2);span(1.1,H-2.3,0,2.3+(H-2.3)/2);openingFrame(cx,cz,angle,1.1,0,2.3,y,p.floor,{kind:'door',shape:defaultOpeningShape(b,true),frames:p.frames??(b.frames!==false),door:p.doorLeaf||'none',doorStyle:p.doorStyle||'flat',doorColor:p.doorColor,doorImage:p.doorImage,angle:p.doorAngle||0,glass:'none'});}else span(length,H,0,H/2);
  }
  if(b.enclosure!=='columns')architecture.facade();
  if(styled)architecture.roof();
  else if(b.roof!=='none'){
    const y=b.floors*H;
    if(b.roof==='flat'){
      const g=b.shape==='round'?new THREE.CylinderGeometry(1,1,.25,48):new THREE.BoxGeometry(2,.25,2),m=add(g,'roof',b.floors,true);m.scale.set(w/2+.4,1,d/2+.4);m.position.y=y+.12;
    }else{
      const height=Math.min(w,d)*.28,round=b.shape==='round';const g=new THREE.ConeGeometry(1,height,round?48:4);if(!round)g.rotateY(Math.PI/4);
      const m=add(g,'roof',b.floors,true);m.scale.set((w/2+.55)*(round?1:Math.SQRT2),1,(d/2+.55)*(round?1:Math.SQRT2));m.position.y=y+height/2;
    }
  }
  // Batch wall spans and steps by storey and material; cutaways retain their levels.
  renderPool(b.pool,{box,add});
  const batches=new Map();
  for(const mesh of [...group.children]){
    if(mesh.isInstancedMesh||mesh.material.transparent||(mesh.geometry.type==='ExtrudeGeometry'&&mesh.material===materials.floor)||mesh.userData.roof)continue;
    const key=mesh.material.uuid+':'+mesh.userData.level;if(!batches.has(key))batches.set(key,[]);batches.get(key).push(mesh);
  }
  for(const meshes of batches.values()){
    const geometries=meshes.map(m=>{m.updateMatrix();return (m.geometry.index?m.geometry.toNonIndexed():m.geometry.clone()).applyMatrix4(m.matrix);}),g=new THREE.BufferGeometry();
    for(const name of ['position','normal','uv']){const arrays=geometries.map(g=>g.attributes[name].array),out=new Float32Array(arrays.reduce((n,a)=>n+a.length,0));let offset=0;for(const a of arrays){out.set(a,offset);offset+=a.length;}g.setAttribute(name,new THREE.BufferAttribute(out,name==='uv'?2:3));}
    const merged=new THREE.Mesh(g,meshes[0].material);merged.userData={...meshes[0].userData};merged.castShadow=true;merged.receiveShadow=true;group.add(merged);
    for(const m of meshes){group.remove(m);m.geometry.dispose();}geometries.forEach(g=>g.dispose());
  }
  // Bake per-piece transforms so the shader projects in building-local metres.
  for(const mesh of group.children){mesh.updateMatrix();mesh.geometry.applyMatrix4(mesh.matrix);if(mesh.userData.roof&&b.roofSections?.some(v=>!v)){const previous=mesh.geometry;mesh.geometry=sectionRoofGeometry(previous,b.roofSections);previous.dispose();}mesh.position.set(0,0,0);mesh.rotation.set(0,0,0);mesh.scale.set(1,1,1);mesh.updateMatrix();}
  // Editing proxies retain semantic identity after the visible wall spans are
  // batched. They participate in raycasting but write no colour or depth, so
  // direct selection does not add rendered draw calls.
  const proxyMaterial=new THREE.MeshBasicMaterial({transparent:true,opacity:0,depthWrite:false,colorWrite:false,visible:false});
  const proxy=(geometry,data,position,angle=0)=>{const mesh=new THREE.Mesh(geometry,proxyMaterial);mesh.position.copy(position);mesh.rotation.y=angle;mesh.layers.set(2);mesh.userData={...data,editorProxy:true,level:data.floor,roof:false};group.add(mesh);return mesh;};
  for(const p of b.partitions||[]){
    const length=Math.hypot(p.bx-p.ax,p.bz-p.az),angle=-Math.atan2(p.bz-p.az,p.bx-p.ax);
    proxy(new THREE.BoxGeometry(length,FLOOR_HEIGHT,.36),{editorKind:'partition',partitionId:p.id,floor:p.floor},new THREE.Vector3((p.ax+p.bx)/2,p.floor*FLOOR_HEIGHT+FLOOR_HEIGHT/2,(p.az+p.bz)/2),angle);
  }
  for(let floor=0;floor<b.floors;floor++)wallSegments(b).forEach(({angle,cx,cz},segment)=>{
    for(const o of wallSpec(b,floor,segment).openings){
      proxy(new THREE.BoxGeometry(o.width,Math.max(.2,o.top-o.bottom),.46),{editorKind:'opening',openingId:o.id,floor,segment},new THREE.Vector3(cx+Math.cos(angle)*o.offset,floor*FLOOR_HEIGHT+(o.bottom+o.top)/2,cz-Math.sin(angle)*o.offset),angle);
    }
  });
  const used=new Set(group.children.map(m=>m.material));for(const material of Object.values(materials))if(!used.has(material))material.dispose();
  return group;
}
export function disposeStructure(group){const materials=new Set();group.traverse(o=>{if(o.geometry)o.geometry.dispose();if(o.material)materials.add(o.material);});materials.forEach(m=>{m.map?.dispose();m.dispose();});}
