import * as THREE from './vendor/three.module.js';
import {makePlant,PLANTS} from './flora.mjs?smooth=3';
import {naturalScenerySurface} from './scenery-surface.mjs';
import {ROCK_IDS,SOLID_TREE_IDS,FANTASY_IDS,GARDEN_GROUPS,SMALL_MUSHROOM_IDS,DEADWOOD_IDS} from './plants.mjs?sumac=2';
import {makeRock} from './rocks.mjs?shape=4';
import {weatherStone} from './stone-surface.mjs?caves=retired';
import {GEOLOGY_IDS,CRYSTAL_IDS,CRYSTAL_STYLES,makeGeology} from './geology.mjs?crystals=2';

export function createFlora(natural){
  const cache=new Map(),leaf=new THREE.MeshStandardMaterial({vertexColors:true,side:THREE.DoubleSide,roughness:.92});
  const alienStem=new THREE.MeshStandardMaterial({vertexColors:true,roughness:.7});
  const alienCrown=new THREE.MeshStandardMaterial({vertexColors:true,side:THREE.DoubleSide,roughness:.48,emissive:0x16383d,emissiveIntensity:.4});
  const stoneMaterials=Object.fromEntries(ROCK_IDS.map((id,i)=>{const m=natural.rock.clone();m.color.setHex([0xb7b0a2,0x9eaaa9,0x737e8a,0x555c60,0xbbad91,0xa1947d][i]);m.roughness=id==='river_rock'?.65:.95;return [id,m];}));
  const bark=natural.bark.clone();bark.vertexColors=true;
  // Restrained front-face blending keeps clustered minerals solid-looking and
  // avoids an extra refraction pass. Depth writes retain their visible surface.
  const crystals=Object.fromEntries(CRYSTAL_IDS.map(id=>{const s=CRYSTAL_STYLES[id];return [id,new THREE.MeshStandardMaterial({color:s.color,roughness:.22,metalness:0,transparent:true,depthWrite:true,opacity:s.base==='quartz'?.78:.86,emissive:s.emissive,emissiveIntensity:s.glow})];}));
  // cliff_side is a warm sedimentary scan.  Preserve its real bedding and
  // normal detail, but neutralise the albedo before each rock family's tint.
  for(const material of [...Object.values(stoneMaterials)])weatherStone(material,{neutralColor:true});
  const pale=bark.clone();pale.map=null;pale.normalScale.set(.3,.3);
  const smooth=pale.clone();smooth.color.setHex(0x9b9280);smooth.normalScale.set(.12,.12);
  for(const m of [...Object.values(stoneMaterials),bark,pale,smooth,alienStem,...Object.values(crystals)])naturalScenerySurface(m);
  for(const m of [leaf,alienCrown])naturalScenerySurface(m,true);
  function parts(kind,variant=0,detail='near'){
    const key=`${kind}:${variant}:${detail}`;
    if(!cache.has(key))cache.set(key,GEOLOGY_IDS.includes(kind)?[{geometry:makeGeology(kind,variant),material:crystals[kind],solid:true}]:ROCK_IDS.includes(kind)?[{geometry:makeRock(kind,variant),material:stoneMaterials[kind],solid:true}]:makePlant(kind,variant,detail).map(p=>({geometry:p.geometry,solid:SOLID_TREE_IDS.includes(kind)&&p.material==='wood',material:SMALL_MUSHROOM_IDS.includes(kind)?(p.material==='leaves'?(kind==='glowcap_patch'?alienCrown:leaf):alienStem):FANTASY_IDS.includes(kind)?(p.material==='leaves'?alienCrown:alienStem):p.material==='leaves'?leaf:kind==='sycamore'?pale:kind==='baobab'?smooth:bark})));
    const result=cache.get(key);
    if(DEADWOOD_IDS.includes(kind))for(const part of result)part.solid=part.material===bark;
    return result;
  }
  function object(kind,variant=0){const group=new THREE.Group();for(const p of parts(kind,variant))group.add(new THREE.Mesh(p.geometry,p.material));return group;}
  return {parts,object};
}

export function installPlantLibrary(flora,select,choose){
  select.replaceChildren(...PLANTS.map(([id,name])=>new Option(name,id)));
  const dialog=document.createElement('div');dialog.id='sceneryLibrary';select.after(dialog);
  const heading=document.createElement('h2');heading.textContent='Plants, fungi & stone';
  const hint=document.createElement('p');hint.textContent='Choose a specimen, then click dry land to plant it. Each variety has three repeatable growth forms. Previews fit each plant independently; sizes differ in the world.';
  const grid=document.createElement('div');grid.className='scenery-preview-strip';grid.tabIndex=0;grid.setAttribute('role','group');grid.setAttribute('aria-label','Scenery specimens');
  const filters=document.createElement('div');filters.className='scenery-filters';
  const category=id=>SMALL_MUSHROOM_IDS.includes(id)?'low':GARDEN_GROUPS[id]||(GEOLOGY_IDS.includes(id)?'geology':ROCK_IDS.includes(id)?'rocks':FANTASY_IDS.includes(id)?'fantasy':'earth');
  function filter(value){for(const card of grid.children)card.style.display=value==='all'||category(card.dataset.kind)===value?'flex':'none';for(const b of filters.children)b.setAttribute('aria-pressed',String(b.dataset.filter===value));grid.scrollLeft=0;}
  filters.style.flexWrap='wrap';
  for(const [id,label] of [['low','Low meadow'],['medium','Bushes & flowers'],['large','Large plants'],['earth','Trees & plants'],['fantasy','Fantasy & fungi'],['rocks','Rocks'],['geology','Crystals'],['all','All']]){const b=document.createElement('button');b.textContent=label;b.dataset.filter=id;b.onclick=()=>filter(id);filters.append(b);}
  dialog.append(filters,grid);hint.className='scenery-preview-hint';hint.textContent='Choose a specimen, then click or drag on land. Previews fit each specimen; world sizes differ.';dialog.append(hint);
  grid.addEventListener('wheel',e=>{if(e.ctrlKey||Math.abs(e.deltaX)>Math.abs(e.deltaY))return;const before=grid.scrollLeft;grid.scrollLeft+=e.deltaY*(e.deltaMode===1?16:e.deltaMode===2?grid.clientWidth:1);if(grid.scrollLeft!==before)e.preventDefault();},{passive:false});
  const syncSelection=()=>{for(const card of grid.children)card.setAttribute('aria-pressed',String(card.dataset.kind===select.value));};
  select.addEventListener('change',()=>{syncSelection();filter(category(select.value));});
  let rendered=false;
  function render(){
    const r=new THREE.WebGLRenderer({antialias:true,alpha:true,preserveDrawingBuffer:true});r.setSize(210,190);r.setPixelRatio(1);r.outputColorSpace=THREE.SRGBColorSpace;r.toneMapping=THREE.ACESFilmicToneMapping;
    const scene=new THREE.Scene();scene.background=new THREE.Color(0x23383a);scene.add(new THREE.HemisphereLight(0xf1f7ee,0x596649,2.2));const sun=new THREE.DirectionalLight(0xffedcc,2.7);sun.position.set(-4,8,6);scene.add(sun);
    const camera=new THREE.PerspectiveCamera(36,210/190,.05,150);
    for(const [id,name] of PLANTS){
      const specimen=flora.object(id),box=new THREE.Box3().setFromObject(specimen),size=box.getSize(new THREE.Vector3()),center=box.getCenter(new THREE.Vector3()),span=Math.max(size.x,size.y,size.z);
      scene.add(specimen);camera.position.copy(center).add(new THREE.Vector3(.7,.36,1).normalize().multiplyScalar(span*2.1));camera.lookAt(center);r.render(scene,camera);
      const button=document.createElement('button');button.dataset.kind=id;button.style.cssText='padding:5px;display:flex;flex-direction:column;align-items:center;gap:7px';button.setAttribute('aria-label','Place '+name);
      const image=document.createElement('img');image.src=r.domElement.toDataURL('image/png');image.alt=name+' specimen';image.style.cssText='width:100%;aspect-ratio:210/190;object-fit:contain;border-radius:5px';
      const label=document.createElement('span');label.textContent=name+(GARDEN_GROUPS[id]?' · '+({low:'0.2–0.5 m',medium:'1–2 m',large:'3–4 m'}[GARDEN_GROUPS[id]]):'');button.append(image,label);button.onclick=()=>{select.value=id;syncSelection();choose(id);};grid.append(button);scene.remove(specimen);
    }
    r.dispose();r.forceContextLoss();rendered=true;
  }
  // Generate the thumbnails only when the ribbon is first visible.
  const observer=new IntersectionObserver(entries=>{if(!entries.some(e=>e.isIntersecting)||rendered)return;try{grid.replaceChildren();render();filter(category(select.value));syncSelection();observer.disconnect();}catch(error){hint.textContent='Preview could not load. Use the scenery menu or switch tabs to retry.';}});observer.observe(dialog);
  return dialog;
}
