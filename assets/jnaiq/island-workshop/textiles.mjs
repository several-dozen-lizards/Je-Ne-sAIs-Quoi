import * as THREE from './vendor/three.module.js';

export const CURTAIN_STYLES={
  pair:'Pleated curtain pair',
  closed:'Closed full curtain',
  cafe:'Café curtains',
};
export const RUG_STYLES={
  rectangle:'Rectangular rug',
  round:'Round rug',
  runner:'Long runner',
};
export const isTextileKind=kind=>/^fabric_curtain_(pair|closed|cafe)$/.test(kind||'')||/^rug_(rectangle|round|runner)$/.test(kind||'');
export const isCurtainKind=kind=>/^fabric_curtain_/.test(kind||'');
export const isRugKind=kind=>/^rug_/.test(kind||'');

export function normalizeTextileSurface(value){
  if(/^#[0-9a-f]{6}$/i.test(value||''))return value;
  if(/^custom_[a-f0-9-]{36}$/.test(value||''))return value;
  return '#8f3f4b';
}

function surfaceMaterial(surface,textures=[]){
  const value=normalizeTextileSurface(surface),source=textures.find(t=>t.id===value);
  const material=new THREE.MeshStandardMaterial({color:source?0xffffff:value,roughness:.9,metalness:0,side:THREE.DoubleSide});
  if(source){material.map=new THREE.TextureLoader().load(source.data,()=>globalThis.dispatchEvent?.(new Event('island-texture-ready')));material.map.colorSpace=THREE.SRGBColorSpace;material.map.wrapS=material.map.wrapT=THREE.ClampToEdgeWrapping;}
  return material;
}
function panelGeometry(width,height,segments=20,pull=0){
  const geometry=new THREE.PlaneGeometry(width,height,segments,12),position=geometry.attributes.position,uv=geometry.attributes.uv;
  for(let i=0;i<position.count;i++){
    const u=uv.getX(i),v=uv.getY(i),edgePull=pull*Math.sin(v*Math.PI);
    position.setX(i,position.getX(i)+(u-.5)*edgePull);position.setZ(i,.045*Math.sin(u*Math.PI*segments*.72)*(0.45+.55*v));
  }
  position.needsUpdate=true;geometry.computeVertexNormals();geometry.translate(0,height/2,0);return geometry;
}
function rod(width,height,group){
  const metal=new THREE.MeshStandardMaterial({color:0x302d2a,roughness:.42,metalness:.72});
  const bar=new THREE.Mesh(new THREE.CylinderGeometry(.025,.025,width+.28,10),metal);bar.rotation.z=Math.PI/2;bar.position.y=height+.08;bar.castShadow=true;group.add(bar);
  for(const x of [-width/2-.14,width/2+.14]){const cap=new THREE.Mesh(new THREE.SphereGeometry(.055,10,7),metal);cap.position.set(x,height+.08,0);group.add(cap);}
}
export function createCurtain(style='pair',surface='#8f3f4b',textures=[]){
  const chosen=Object.hasOwn(CURTAIN_STYLES,style)?style:'pair',group=new THREE.Group(),material=surfaceMaterial(surface,textures),width=2.35;
  if(chosen==='pair'){
    for(const side of [-1,1]){const mesh=new THREE.Mesh(panelGeometry(1.03,2.28,18,-.22),material);mesh.position.x=side*.59;mesh.castShadow=true;mesh.receiveShadow=true;group.add(mesh);const tie=new THREE.Mesh(new THREE.BoxGeometry(.27,.08,.09),material);tie.position.set(side*.73,1.04,.03);group.add(tie);}
    rod(width,2.28,group);
  }else if(chosen==='cafe'){
    for(const side of [-1,1]){const mesh=new THREE.Mesh(panelGeometry(1.12,1.12,16,-.08),material);mesh.position.set(side*.57,.55,0);mesh.castShadow=true;mesh.receiveShadow=true;group.add(mesh);}rod(width,1.68,group);
  }else{const mesh=new THREE.Mesh(panelGeometry(width,2.28,28,0),material);mesh.castShadow=true;mesh.receiveShadow=true;group.add(mesh);rod(width,2.28,group);}
  const height=chosen==='cafe'?1.76:2.36,selectionProxy=new THREE.Mesh(new THREE.BoxGeometry(width,height,.16),new THREE.MeshBasicMaterial({transparent:true,opacity:0,depthWrite:false,colorWrite:false}));selectionProxy.position.y=height/2;selectionProxy.userData.selectionProxy=true;selectionProxy.castShadow=false;selectionProxy.receiveShadow=false;group.add(selectionProxy);group.userData.textile={selectionProxy};group.name=CURTAIN_STYLES[chosen];return group;
}
function rugTopGeometry(style){
  if(style==='round'){const g=new THREE.CircleGeometry(1,48);g.rotateX(-Math.PI/2);return g;}
  const [w,d]=style==='runner'?[3.2,1]:[2.4,1.7],g=new THREE.PlaneGeometry(w,d,1,1);g.rotateX(-Math.PI/2);return g;
}
export function createRug(style='rectangle',surface='#315f67',textures=[]){
  const chosen=Object.hasOwn(RUG_STYLES,style)?style:'rectangle',group=new THREE.Group(),top=new THREE.Mesh(rugTopGeometry(chosen),surfaceMaterial(surface,textures));top.position.y=.026;top.receiveShadow=true;group.add(top);
  const [w,d]=chosen==='round'?[2,2]:chosen==='runner'?[3.2,1]:[2.4,1.7],base=new THREE.Mesh(chosen==='round'?new THREE.CylinderGeometry(1,1,.025,48):new THREE.BoxGeometry(w,.025,d),new THREE.MeshStandardMaterial({color:0x3b3029,roughness:1}));base.position.y=.012;base.receiveShadow=true;group.add(base);
  if(chosen!=='round')for(const side of [-1,1])for(let i=0;i<14;i++){const fringe=new THREE.Mesh(new THREE.BoxGeometry(.008,.008,.12),top.material);fringe.position.set((i/13-.5)*w,.02,side*(d/2+.055));group.add(fringe);}
  group.name=RUG_STYLES[chosen];return group;
}
export function textileRecord(id,type='curtain',style,typeSurface,x=0,z=0){
  const curtain=type==='curtain',chosen=curtain?(Object.hasOwn(CURTAIN_STYLES,style)?style:'pair'):(Object.hasOwn(RUG_STYLES,style)?style:'rectangle'),name=(curtain?CURTAIN_STYLES:RUG_STYLES)[chosen];
  return {id,name,kind:(curtain?'fabric_curtain_':'rug_')+chosen,position_m:[x,-z],size_m:curtain?2.35:(chosen==='runner'?3.2:2.4),rot_deg:0,y_off_m:0,support_surface:'island_ground',support_oid:null,description:curtain?'Soft fabric curtains with editable colour or printed surface.':'A low-profile textile rug with editable colour or printed surface.',texture:normalizeTextileSurface(typeSurface||(curtain?'#8f3f4b':'#315f67')),mass_kg:curtain?5:7,affordances:{},capability:null,power:1,owner:null};
}
