import * as THREE from './vendor/three.module.js';
import {paintPond} from './pond-brush.mjs';
import {N} from './terrain.mjs?caves=retired';
export function installPondBrush({canvas,scene,controls,active,hit,world,commit,status,invalidate,radius,depth}){
  let stroke=null,pointer=null,previousControls=true;
  const line=new THREE.Line(new THREE.BufferGeometry(),new THREE.LineBasicMaterial({color:0x60d9ed,depthTest:false}));line.renderOrder=100;line.visible=false;scene.add(line);
  const ring=new THREE.Mesh(new THREE.RingGeometry(.97,1,48),new THREE.MeshBasicMaterial({color:0x60d9ed,depthTest:false,side:THREE.DoubleSide}));ring.rotation.x=-Math.PI/2;ring.renderOrder=101;ring.visible=false;scene.add(ring);
  function showRing(p){ring.position.copy(p);ring.position.y+=.2;ring.scale.setScalar(radius());ring.visible=true;invalidate();}
  function preview(){line.geometry.dispose();line.geometry=new THREE.BufferGeometry().setFromPoints(stroke.map(p=>new THREE.Vector3(p.x,p.y+.25,p.z)));line.visible=true;invalidate();}
  function cancel(){const id=pointer;pointer=null;stroke=null;line.visible=false;ring.visible=false;if(id!==null){controls.enabled=previousControls;if(canvas.hasPointerCapture(id))canvas.releasePointerCapture(id);}invalidate();}
  canvas.addEventListener('pointerdown',e=>{
    if(!active()||e.button!==0||e.altKey)return;e.preventDefault();e.stopImmediatePropagation();const p=hit(e);if(!p)return;
    const minimum=world().size/N*3;if(radius()<minimum){status(`Use a pond radius of at least ${minimum.toFixed(1)} metres for this island.`,true);return;}
    stroke=[p];pointer=e.pointerId;previousControls=controls.enabled;controls.enabled=false;canvas.setPointerCapture(pointer);preview();status('Drag to paint the pond. Release to carve and fill; Escape cancels.');
  },true);
  canvas.addEventListener('pointermove',e=>{if(!active()||e.altKey)return;e.stopImmediatePropagation();const p=hit(e);if(p)showRing(p);if(!stroke||e.pointerId!==pointer)return;if(p&&p.distanceTo(stroke.at(-1))>=world().size/N){if(stroke.length<256)stroke.push(p);else status('Stroke limit reached. Release, then paint another stroke to extend the pond.');preview();}},true);
  canvas.addEventListener('pointerleave',()=>{ring.visible=false;invalidate();});
  canvas.addEventListener('pointerup',e=>{if(!stroke||e.pointerId!==pointer)return;e.stopImmediatePropagation();try{const next=paintPond(world(),stroke,radius(),depth());cancel();commit(next);}catch(error){cancel();status(error.message,true);}},true);
  for(const name of ['pointercancel','lostpointercapture'])canvas.addEventListener(name,()=>{if(stroke)cancel();});
  window.addEventListener('blur',cancel);
  return {cancel};
}
