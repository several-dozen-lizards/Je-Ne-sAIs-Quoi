import * as THREE from 'three';
import {OrbitControls} from './vendor/OrbitControls.js';
import {GLTFLoader} from './vendor/GLTFLoader.js';
import {installFurnitureEditor,request,validateFurniture} from './furniture.mjs';
import {heightAt} from './terrain.mjs';
import {normalizeImportedLights} from './imported-lighting.mjs';
let landscapeWorld=null;
const $=id=>document.getElementById(id),status=(text,error=false)=>{$('status').textContent=text;$('status').classList.toggle('error',error);};
document.title='JNAIQ · World workshop';document.querySelector('h1').textContent='World workshop';
document.querySelector('header small').textContent='EXISTING WORLDS · ROOMS & LANDSCAPES';
const landscapeLink=document.querySelector('header nav a');landscapeLink.textContent='Build & furnish worlds';landscapeLink.href='./index.html?furniture=1';
const worldLabel=$('rooms').parentElement;worldLabel.firstChild.textContent='JNAIQ world';
const worldHint=document.createElement('p');worldHint.textContent='Rooms are worlds too. Open a room or published landscape here to edit its objects. To furnish an unpublished landscape, use Build & furnish worlds.';worldLabel.before(worldHint);
const renderer=new THREE.WebGLRenderer({canvas:$('viewport'),antialias:true});renderer.setPixelRatio(Math.min(devicePixelRatio,1.5));renderer.setClearColor(0x253d42);renderer.toneMapping=THREE.ACESFilmicToneMapping;
const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera(45,1,.02,3000),controls=new OrbitControls(camera,$('viewport'));controls.mouseButtons={LEFT:THREE.MOUSE.ROTATE,MIDDLE:THREE.MOUSE.ROTATE,RIGHT:THREE.MOUSE.PAN};
scene.add(new THREE.HemisphereLight(0xeaf7ff,0x7a694d,.82));const sun=new THREE.DirectionalLight(0xffead1,1);sun.position.set(12,30,15);scene.add(sun);
const grid=new THREE.GridHelper(100,100,0x688e89,0x3b5558);grid.position.y=-.015;scene.add(grid);
const base=new THREE.Group();scene.add(base);let world=null,original=null,draftId=null,revision=null,dirty=false,busy=false,past=[],future=[],loadToken=0;
const recoveryKey='jnsq-room-workshop-recovery-v1';let recovery=localStorage.getItem(recoveryKey);
try{const value=JSON.parse(recovery);if(value?.original&&JSON.stringify(value.world)===JSON.stringify(value.original))recovery=null;}catch{recovery=null;}
$('recover').hidden=!recovery;
function render(){controls.update();renderer.render(scene,camera);}
controls.addEventListener('change',()=>{editor?.updateBox();renderer.render(scene,camera);});
const groundRay=new THREE.Raycaster();function ground(x,z,surface){if(landscapeWorld)return heightAt(landscapeWorld,x,z);if(surface==='yurt_floor'||surface==='yurt_wall')return 0;groundRay.set(new THREE.Vector3(x,100,z),new THREE.Vector3(0,-1,0));return groundRay.intersectObject(base,true).find(h=>h.object.isMesh&&!h.object.material?.transparent)?.point.y||0;}
const editor=installFurnitureEditor({scene,camera,canvas:$('viewport'),controls,panel:$('furniture'),objects:()=>world?.objects||{},ground,status,invalidate:()=>renderer.render(scene,camera),commit:(objects,message)=>{if(!world)return;past.push(structuredClone(world));future=[];world.objects=objects;changed(message);}});
$('hint').textContent='Drag objects to move · wheel rotates · Shift-wheel height · Ctrl-wheel size. Escape deselects for zoom · middle-drag orbits · right-drag pans.';
new ResizeObserver(()=>{const rect=$('stage').getBoundingClientRect();renderer.setSize(rect.width,rect.height,false);camera.aspect=rect.width/rect.height;camera.updateProjectionMatrix();render();}).observe($('stage'));
function history(){ $('undo').disabled=!past.length;$('redo').disabled=!future.length;}
function changed(message){dirty=JSON.stringify(world)!==JSON.stringify(original);history();try{localStorage.setItem(recoveryKey,JSON.stringify({world,original,draftId,revision}));}catch{status('Browser recovery storage is full. Save or export this draft.',true);return;}status(message+(dirty?' · draft only':' · original draft restored'));}
async function run(fn){if(busy)return;busy=true;document.querySelector('main').inert=true;document.querySelector('header').inert=true;try{await fn();}catch(e){status(e.message,true);}finally{busy=false;document.querySelector('main').inert=false;document.querySelector('header').inert=false;}}
function frame(top=false){const box=new THREE.Box3().setFromObject(base);if(box.isEmpty())box.setFromCenterAndSize(new THREE.Vector3(),new THREE.Vector3((world?.radius_m||5)*2,2,(world?.radius_m||5)*2));const center=box.getCenter(new THREE.Vector3()),span=Math.max(8,Math.min(150,box.getSize(new THREE.Vector3()).length()));controls.target.copy(center);camera.position.copy(center).add(new THREE.Vector3(top?0:span*.55,span*.7,top?.001:span*.7));render();}
function clearBase(){for(const child of [...base.children]){base.remove(child);child.traverse(n=>{n.geometry?.dispose();const mats=Array.isArray(n.material)?n.material:[n.material];for(const mat of mats){if(!mat)continue;for(const v of Object.values(mat))if(v?.isTexture)v.dispose();mat.dispose();}});}}
async function loadBase(){const token=++loadToken;clearBase();const loader=new GLTFLoader();
  landscapeWorld=null;
  if(world.destination){const published=await request('/api/world-destinations/'+encodeURIComponent(world.destination.id));const {landscapePreview}=await import('./room-landscape.mjs');if(token!==loadToken)return;landscapeWorld=published.world;base.add(landscapePreview(published.world));}
  // Editable furniture uses the room snapshot. Authored room geometry stays intact.
  for(const url of world.base_models||[]){try{if(!/^\/api\/room-workshop\/assets\/world\/[a-zA-Z0-9_-]+\.glb$/.test(url))throw Error('Unsupported room model');const gltf=await loader.loadAsync(url);if(token!==loadToken)return;if(url.endsWith('/yurt_den.glb'))gltf.scene.scale.setScalar(world.radius_m/2.5);base.add(normalizeImportedLights(gltf.scene));editor.refresh();frame();}catch{status('A room model is unavailable; the object layout remains editable.',true);}}
  if(!base.children.length){const size=(world.radius_m||5)*2;const floor=new THREE.Mesh(new THREE.PlaneGeometry(size,size),new THREE.MeshStandardMaterial({color:0x596d60,side:THREE.DoubleSide}));floor.rotation.x=-Math.PI/2;floor.position.y=-.02;base.add(floor);}
  editor.refresh();frame();
}
function validate(value){if(value?.schema!=='jnsq-room-layout/1'||!value.room_id||!value.base_revision)throw Error('Choose a JNAIQ room layout file. Landscape files open in Landscapes.');validateFurniture(value.objects);return value;}
async function open(value,id=null,rev=null){world=structuredClone(validate(value));original=structuredClone(value);draftId=id;revision=rev;past=[];future=[];dirty=false;history();$('source').textContent=world.name+' · saved layout copy. Editing does not change the household.';editor.refresh();frame();await loadBase();status('Opened '+world.name+' as a draft');}
async function shelf(){const [rooms,drafts]=await Promise.all([request('/api/room-workshop/rooms'),request('/api/room-workshop/drafts')]);$('rooms').replaceChildren(...rooms.rooms.map(r=>new Option(r.name,r.id)));$('drafts').replaceChildren(new Option('Choose a saved draft',''),...drafts.drafts.map(d=>new Option(d.name,d.id)));return rooms;}
async function save(copy=false){if(!world)throw Error('Open a world first');const result=await request('/api/room-workshop/drafts',{draft:world,draft_id:copy?null:draftId,revision:copy?null:revision});draftId=result.id;revision=result.revision;original=structuredClone(world);dirty=false;await shelf();status('Draft saved · household unchanged');return result;}
function protectDraft(){if(!dirty)return true;status('Save this draft or export it before opening another world.',true);return false;}
$('open').onclick=()=>run(async()=>{if(protectDraft())await open(await request('/api/room-workshop/rooms/'+encodeURIComponent($('rooms').value)));});
$('load').onclick=()=>run(async()=>{if(!protectDraft()||!$('drafts').value)return;const v=await request('/api/room-workshop/drafts/'+$('drafts').value);await open(v.world,v.id,v.revision);});
$('save').onclick=()=>run(()=>save());$('copy').onclick=()=>run(()=>save(true));
$('undo').onclick=()=>{if(!past.length)return;future.push(structuredClone(world));world=past.pop();editor.refresh();changed('Undid layout edit');};$('redo').onclick=()=>{if(!future.length)return;past.push(structuredClone(world));world=future.pop();editor.refresh();changed('Redid layout edit');};
$('frame').onclick=()=>frame();$('top').onclick=()=>frame(true);$('baseVisible').onchange=()=>{base.visible=$('baseVisible').checked;render();};
$('export').onclick=()=>{if(!world)return;const a=document.createElement('a'),url=URL.createObjectURL(new Blob([JSON.stringify(world)],{type:'application/json'}));a.href=url;a.download=world.room_id+'-layout.json';a.click();URL.revokeObjectURL(url);status('Layout exported');};
$('import').onclick=()=>{if(protectDraft())$('file').click();};$('file').onchange=()=>run(async()=>{const file=$('file').files[0];if(!file)return;if(file.size>4_000_000)throw Error('Choose a layout smaller than 4 MB');await open(JSON.parse(await file.text()));$('file').value='';});
$('recover').onclick=()=>run(async()=>{if(!protectDraft())return;const saved=JSON.parse(recovery);await open(saved.world,saved.draftId,saved.revision);original=saved.original;dirty=true;$('recover').hidden=true;status('Recovered unsaved draft');});
$('apply').onclick=()=>run(async()=>{
  if(!world)throw Error('Open a world first');await save();
  const live=await request('/api/room-workshop/rooms/'+world.room_id),lines=[];
  if(live.base_revision!==world.base_revision)throw Error('The household layout has changed. Your draft is saved; open the room again before applying changes.');
  for(const [id,o] of Object.entries(world.objects)){const before=live.objects[id];if(!before)lines.push('Add '+o.name);else if(JSON.stringify(['position_m','rot_deg','size_m','y_off_m','support_surface','support_oid'].map(k=>before[k]))!==JSON.stringify(['position_m','rot_deg','size_m','y_off_m','support_surface','support_oid'].map(k=>o[k])))lines.push(`Move ${o.name}: X ${o.position_m[0].toFixed(2)}, Z ${(-o.position_m[1]).toFixed(2)}, height ${o.y_off_m.toFixed(2)} m; ${o.rot_deg}°, size ${o.size_m} m`);}
  for(const [id,o] of Object.entries(live.objects))if(!world.objects[id])lines.push('Remove '+o.name);
  if(!lines.length)throw Error('This layout already matches JNAIQ.');$('reviewText').textContent=world.name+'\n\n'+lines.join('\n');$('review').showModal();
});
$('cancelApply').onclick=()=>$('review').close();$('confirmApply').onclick=()=>run(async()=>{const result=await request('/api/room-workshop/apply',world);$('review').close();if(result.queued){status(result.message);return;}world.base_revision=result.base_revision;original=structuredClone(world);await save();status('Layout applied · resident objects and their histories preserved');});
window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
run(async()=>{await shelf();const room=new URLSearchParams(location.search).get('room');if(room)$('rooms').value=room;if($('rooms').value)await open(await request('/api/room-workshop/rooms/'+encodeURIComponent($('rooms').value)));});
