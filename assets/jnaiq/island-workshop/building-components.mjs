import * as THREE from './vendor/three.module.js';
import {OPENING_SHAPES,openingOutline} from './opening-shapes.mjs';
import {architectureFor} from './architecture.mjs';

export function defaultOpeningShape(b,door=false){
  return b[door?'doorShape':'windowShape']||(['arches','mission'].includes(architectureFor(b).detail)?'arched':'rectangle');
}
export function wallSegments(b){
  const count=b.shape==='round'?32:4,w=b.width,d=b.depth;
  return Array.from({length:count},(_,i)=>{
    const corners=[[-w/2,d/2],[w/2,d/2],[w/2,-d/2],[-w/2,-d/2]];
    const [ax,az]=b.shape==='round'?[Math.cos(i/count*Math.PI*2)*w/2,Math.sin(i/count*Math.PI*2)*d/2]:corners[i];
    const [bx,bz]=b.shape==='round'?[Math.cos((i+1)/count*Math.PI*2)*w/2,Math.sin((i+1)/count*Math.PI*2)*d/2]:corners[(i+1)%4];
    return {length:Math.hypot(bx-ax,bz-az),angle:-Math.atan2(bz-az,bx-ax),cx:(ax+bx)/2,cz:(az+bz)/2};
  });
}
export function wallSpec(b,floor,segment){
  const {length}=wallSegments(b)[segment],override=(b.wallEdits||[]).find(p=>p.floor===floor&&p.segment===segment);
  if(override)return structuredClone(override);
  const door=floor===0&&(b.shape==='rectangle'?segment===0:segment===7||segment===8),styled=(b.architecture||'plain')!=='plain'&&b.shape==='rectangle';
  const count=styled?Math.max(3,Math.round(length/4.5)|1):1,bay=length/count,openings=[];
  if(styled||door||b.shape==='rectangle'||segment%4===1)for(let j=0;j<count;j++){
    const isDoor=door&&j===Math.floor(count/2),width=styled?(isDoor?1.8:Math.min(bay*.6,b.architecture==='modern'?3.6:2.4)):b.shape==='round'?(door?length:length*.72):Math.min(door?1.8:2.4,length*.5);
    openings.push({id:`opening-${j}`,kind:isDoor?'door':'window',offset:(j+.5)*bay-length/2,width,bottom:isDoor?0:.95,top:2.3,shape:defaultOpeningShape(b,isDoor),frames:b.frames!==false,glass:'none',color:'#a4d8ef',opacity:.4,door:'none',angle:0,...(isDoor?{doorStyle:'flat',doorColor:'#9a5d31'}:{})});
  }
  return {floor,segment,removed:false,openings};
}
export function resizeStoreys(b,floors){
  return {...b,floors,partitions:(b.partitions||[]).filter(p=>p.floor<floors),wallEdits:(b.wallEdits||[]).filter(p=>p.floor<floors)};
}
export function validateComponents(b){
  if(b.roofSections!==undefined&&(!Array.isArray(b.roofSections)||b.roofSections.length!==4||b.roofSections.some(v=>typeof v!=='boolean')))throw Error('Choose four roof sections.');
  if(b.wallEdits===undefined)return;
  if(!Array.isArray(b.wallEdits)||b.wallEdits.length>b.floors*(b.shape==='round'?32:4))throw Error('Too many wall edits.');
  const keys=new Set(),segments=wallSegments(b);
  for(const wall of b.wallEdits){
    const key=wall.floor+':'+wall.segment;
    if(!Number.isInteger(wall.floor)||wall.floor<0||wall.floor>=b.floors||!Number.isInteger(wall.segment)||!segments[wall.segment]||keys.has(key)||typeof wall.removed!=='boolean'||!Array.isArray(wall.openings)||wall.openings.length>12)throw Error('Invalid exterior wall.');
    keys.add(key);const length=segments[wall.segment].length,ids=new Set();let edge=-length/2-.001;
    for(const o of [...wall.openings].sort((a,b)=>a.offset-b.offset)){
      if(typeof o.id!=='string'||!o.id||o.id.length>80||ids.has(o.id)||!['door','window'].includes(o.kind)||!OPENING_SHAPES.includes(o.shape)||typeof o.frames!=='boolean'||![o.offset,o.width,o.bottom,o.top,o.opacity,o.angle].every(Number.isFinite)||o.width<.2||o.bottom<0||o.top>3.05||o.top-o.bottom<.2||o.offset-o.width/2<edge||o.offset+o.width/2>length/2+.001||!['none','clear','stained','image'].includes(o.glass)||!/^#[a-f\d]{6}$/i.test(o.color)||o.opacity<.05||o.opacity>1||!['none','solid'].includes(o.door)||o.doorStyle!==undefined&&!['flat','panelled','medieval','glazed'].includes(o.doorStyle)||o.doorColor!==undefined&&!/^#[a-f\d]{6}$/i.test(o.doorColor)||o.doorImage!==undefined&&!/^custom_[a-f0-9-]{36}$/.test(o.doorImage)||o.angle<0||o.angle>120||o.kind==='door'&&o.bottom!==0||o.kind==='window'&&(o.door!=='none'||o.doorStyle!==undefined||o.doorColor!==undefined||o.doorImage!==undefined)||o.image!==undefined&&!/^custom_[a-f0-9-]{36}$/.test(o.image))throw Error('Invalid or overlapping opening. Keep openings within the wall and apart.');
      if(o.glass==='image'&&!o.image)throw Error('Choose an uploaded image for the glass.');
      ids.add(o.id);edge=o.offset+o.width/2+.08;
    }
  }
}

// Clip roof triangles against building-local quadrants, retaining interpolated UVs.
export function sectionRoofGeometry(geometry,enabled){
  const src=geometry.index?geometry.toNonIndexed():geometry.clone(),out={position:[],normal:[],uv:[]};
  for(let i=0;i<src.attributes.position.count;i+=3)for(let q=0;q<4;q++){
    if(!enabled[q])continue;
    let poly=Array.from({length:3},(_,j)=>Object.fromEntries(Object.entries(out).map(([k])=>[k,Array.from({length:k==='uv'?2:3},(_,c)=>src.attributes[k].array[(i+j)*(k==='uv'?2:3)+c])])));
    for(const [axis,sign] of [[0,q%2?1:-1],[2,q<2?1:-1]]){
      const next=[];for(let j=0;j<poly.length;j++){
        const a=poly[j],b=poly[(j+1)%poly.length],da=a.position[axis]*sign,db=b.position[axis]*sign;
        if(da>=0)next.push(a);
        if((da>=0)!==(db>=0)){const t=da/(da-db);next.push(Object.fromEntries(Object.keys(out).map(k=>[k,a[k].map((v,c)=>v+(b[k][c]-v)*t)])));}
      }poly=next;
    }
    for(let j=1;j<poly.length-1;j++)for(const p of [poly[0],poly[j],poly[j+1]])for(const k of Object.keys(out))out[k].push(...p[k]);
  }
  src.dispose();const g=new THREE.BufferGeometry();for(const k of Object.keys(out))g.setAttribute(k,new THREE.Float32BufferAttribute(out[k],k==='uv'?2:3));return g;
}

export function openingInsert(o,textures=[]){
  const shape=new THREE.Shape(openingOutline(o.shape,o.width,o.top-o.bottom));shape.closePath();
  const geometry=new THREE.ShapeGeometry(shape),uv=geometry.attributes.uv;
  for(let i=0;i<uv.count;i++)uv.setXY(i,(uv.getX(i)+o.width/2)/o.width,uv.getY(i)/(o.top-o.bottom));
  const material=new THREE.MeshPhongMaterial({color:o.color,transparent:true,opacity:o.opacity,side:THREE.DoubleSide,depthWrite:false,shininess:110});
  if(o.glass==='image'&&typeof document!=='undefined'){
    const source=textures.find(t=>t.id===o.image);if(source){material.map=new THREE.TextureLoader().load(source.data,()=>globalThis.dispatchEvent?.(new Event('island-texture-ready')));material.map.colorSpace=THREE.SRGBColorSpace;}
  }
  if(o.glass==='stained'){
    // Opaque lead at cell boundaries; coloured translucent glass within each cell.
    material.onBeforeCompile=shader=>{shader.fragmentShader=shader.fragmentShader.replace('#include <common>','#include <common>\nvarying vec2 paneUv;');shader.vertexShader=shader.vertexShader.replace('#include <common>','#include <common>\nvarying vec2 paneUv;').replace('#include <uv_vertex>','#include <uv_vertex>\npaneUv=uv;');shader.fragmentShader=shader.fragmentShader.replace('#include <color_fragment>',`#include <color_fragment>
      vec2 cell=paneUv*vec2(4.,5.); vec2 edge=min(fract(cell),1.-fract(cell));
      float lead=1.-step(.045,min(edge.x,edge.y));
      float tone=fract(sin(dot(floor(cell),vec2(12.9898,78.233)))*43758.5453);
      diffuseColor.rgb=mix(diffuseColor.rgb*mix(vec3(.35,.7,1.),vec3(1.,.35,.18),tone),vec3(.055),lead);
      diffuseColor.a=mix(opacity,1.,lead);`);};
    material.customProgramCacheKey=()=> 'stained-glass-v1';
  }
  const mesh=new THREE.Mesh(geometry,material);mesh.userData.solid=true;return mesh;
}
