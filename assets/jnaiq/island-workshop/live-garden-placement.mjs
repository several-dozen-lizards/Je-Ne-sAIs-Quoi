import * as THREE from './vendor/three.module.js';
import {walkingSurfaces} from './visitor-surfaces.mjs';
import {createGardenLayer} from './garden-render.mjs';
import {heightAt} from './terrain.mjs';

// The camera supplies a preview; only a confirmed click creates a host object.
export function installLiveGardenPlacement({scene,camera,canvas,world,member,room,json,refresh,view,invalidate,status}){
  const preview=createGardenLayer(scene,invalidate),ray=new THREE.Raycaster();
  let active=false,pending=false,point=null,rotation=0,down=null,toolbar=null,restoreView=null,name=null;
  function clear(){active=false;point=null;down=null;preview.sync(world,[]);toolbar?.remove();toolbar=null;restoreView?.();restoreView=null;}
  function paint(){preview.sync(world,point?[{id:'preview',x:point.x,z:point.z,y_m:point.y,rotation,scale:1}]:[]);}
  function hit(e){const rect=canvas.getBoundingClientRect();ray.setFromCamera(new THREE.Vector2((e.clientX-rect.left)/rect.width*2-1,1-(e.clientY-rect.top)/rect.height*2),camera);
    const h=ray.intersectObjects(walkingSurfaces(scene.children),false).find(h=>h.face?.normal.clone().transformDirection(h.object.matrixWorld).y>.5);point=h?.point||null;
    if(point&&Math.abs(point.y-heightAt(world,point.x,point.z))>.2){point=null;status('Choose ground level for this bed.');}paint();}
  async function commit(){if(pending||!point)return;pending=true;toolbar.querySelectorAll('button,input').forEach(b=>b.disabled=true);
    try{await json('/api/rooms/'+encodeURIComponent(room)+'/objects',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:name.value.trim()||'Shared garden bed',kind:'garden_bed',capability:'garden',size_m:2.4,position_m:[point.x,-point.z],rot_deg:rotation*180/Math.PI,y_off_m:0,support_surface:'island_ground',description:'Shared garden bed. Seeds and water are available here.',by:member})});clear();await refresh();status('Garden bed placed. Open Garden to plant together.');}
    catch(e){status(e.message,true);if(toolbar)toolbar.querySelectorAll('button,input').forEach(b=>b.disabled=false);}finally{pending=false;}}
  function start(){if(active||pending)return;active=true;rotation=0;if(document.pointerLockElement===canvas)document.exitPointerLock();restoreView=view();
    toolbar=document.createElement('div');toolbar.setAttribute('role','region');toolbar.setAttribute('aria-label','Place garden bed');toolbar.style.cssText='position:fixed;z-index:20;top:80px;left:50%;transform:translateX(-50%);background:#142c29;color:#e7efdf;border:1px solid #658d70;border-radius:12px;padding:14px;display:flex;align-items:center;gap:10px;flex-wrap:wrap;max-width:90vw';
    const hint=document.createElement('span');hint.textContent='Click dry ground to place · right-drag to orbit';toolbar.append(hint);
    name=document.createElement('input');name.value='Shared garden bed';name.maxLength=60;name.setAttribute('aria-label','Bed name');toolbar.append(name);
    const rotate=document.createElement('button');rotate.textContent='Rotate 15°';rotate.onclick=()=>{rotation=(rotation+Math.PI/12)%(Math.PI*2);paint();};toolbar.append(rotate);
    const cancel=document.createElement('button');cancel.textContent='Cancel · Esc';cancel.onclick=clear;toolbar.append(cancel);document.body.append(toolbar);status('Choose a spot in this world for your shared bed.');}
  canvas.addEventListener('pointerdown',e=>{if(!active||e.button!==0)return;e.stopImmediatePropagation();e.preventDefault();down=[e.clientX,e.clientY];hit(e);},true);
  canvas.addEventListener('pointermove',e=>{if(active&&!pending)hit(e);},true);
  canvas.addEventListener('pointerup',e=>{if(!active||e.button!==0)return;e.stopImmediatePropagation();e.preventDefault();if(down&&Math.hypot(e.clientX-down[0],e.clientY-down[1])<5)commit();down=null;},true);
  canvas.addEventListener('dblclick',e=>{if(active){e.stopImmediatePropagation();e.preventDefault();}},true);
  window.addEventListener('keydown',e=>{if(active&&e.key==='Escape'&&!pending){e.stopImmediatePropagation();e.preventDefault();clear();}},true);
  window.addEventListener('pagehide',()=>{clear();preview.dispose();},{once:true});
  return {start,get active(){return active;}};
}
