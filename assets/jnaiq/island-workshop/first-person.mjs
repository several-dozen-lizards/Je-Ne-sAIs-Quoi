import * as THREE from './vendor/three.module.js';
import {heightAt} from './terrain.mjs?caves=retired';

export const EYE_HEIGHT=1.7,WALK_SPEED=8,FAST_SPEED=20;
export function firstPersonPointerIntent({active,onCanvas,button,editorAction=false}){
  if(!active||!onCanvas)return 'pass';
  if(button===0&&editorAction)return 'edit';
  return 'look';
}
export function walkStep(position,yaw,keys,seconds,world){
  const forward=Number(keys.has('KeyW'))-Number(keys.has('KeyS'));
  const right=Number(keys.has('KeyD'))-Number(keys.has('KeyA'));
  const length=Math.hypot(forward,right);if(!length)return false;
  const distance=Math.min(Math.max(seconds,0),.05)*(keys.has('ShiftLeft')||keys.has('ShiftRight')?FAST_SPEED:WALK_SPEED)/length;
  const edge=world.size/2;
  position.x=THREE.MathUtils.clamp(position.x+(right*Math.cos(yaw)-forward*Math.sin(yaw))*distance,-edge,edge);
  position.z=THREE.MathUtils.clamp(position.z+(-forward*Math.cos(yaw)-right*Math.sin(yaw))*distance,-edge,edge);
  // Perspective inspection follows the terrain only. Scenery, walls and other
  // solid objects deliberately do not participate in movement.
  position.y=heightAt(world,position.x,position.z)+EYE_HEIGHT;
  return true;
}

export function installFirstPerson({camera,controls,canvas,world,button,help,invalidate,onEnter=()=>{},allowEditorEvent=()=>false}){
  const doc=canvas.ownerDocument,win=doc.defaultView,keys=new Set(),editorPointers=new Set(),direction=new THREE.Vector3();
  let active=false,saved=null,yaw=0,pitch=0,drag=null,hadLock=false;
  const movement=new Set(['KeyW','KeyA','KeyS','KeyD','ShiftLeft','ShiftRight']);
  const hint='WASD to walk · Shift to move faster · Right-drag to look · Left-click uses the active editor tool · Esc releases mouse look. Objects can be walked through.';
  function orient(){camera.rotation.set(pitch,yaw,0,'YXZ');camera.getWorldDirection(direction);controls.target.copy(camera.position).addScaledVector(direction,10);invalidate();}
  function clear(){keys.clear();editorPointers.clear();drag=null;}
  function exit(){
    if(!active)return;active=false;clear();
    if(doc.pointerLockElement===canvas)doc.exitPointerLock?.();
    camera.position.copy(saved.position);camera.quaternion.copy(saved.quaternion);camera.rotation.order=saved.order;camera.fov=saved.fov;camera.updateProjectionMatrix();
    controls.target.copy(saved.target);controls.enabled=saved.enabled;controls.update();
    help.textContent=saved.help;button.textContent='First person';button.setAttribute('aria-pressed','false');canvas.style.cursor=saved.cursor;hadLock=false;invalidate();
  }
  function enter(){
    if(active)return;onEnter();
    saved={position:camera.position.clone(),quaternion:camera.quaternion.clone(),order:camera.rotation.order,fov:camera.fov,target:controls.target.clone(),enabled:controls.enabled,help:help.textContent,cursor:canvas.style.cursor};
    const edge=world().size/2;
    camera.getWorldDirection(direction);yaw=Math.atan2(-direction.x,-direction.z);pitch=0;
    camera.position.set(THREE.MathUtils.clamp(controls.target.x,-edge,edge),0,THREE.MathUtils.clamp(controls.target.z,-edge,edge));
    camera.position.y=heightAt(world(),camera.position.x,camera.position.z)+EYE_HEIGHT;
    camera.fov=65;camera.updateProjectionMatrix();
    active=true;controls.enabled=false;button.textContent='Exit first person';button.setAttribute('aria-pressed','true');help.textContent=hint;canvas.style.cursor='crosshair';canvas.focus({preventScroll:true});orient();
  }
  button.setAttribute('aria-pressed','false');button.onclick=()=>active?exit():enter();
  canvas.tabIndex=0;
  const stop=e=>{e.preventDefault();e.stopImmediatePropagation();};
  const listen=(target,type,handler,options)=>{target.addEventListener(type,handler,options);removers.push(()=>target.removeEventListener(type,handler,options));};
  const removers=[];
  // Capture before every editor (including furniture and construction) so a
  // look gesture cannot paint, select, drag, delete or cache a changed draft.
  listen(doc,'pointerdown',e=>{
    if(!active)return;
    if(e.target!==canvas){clear();return;}
    const intent=firstPersonPointerIntent({active,onCanvas:true,button:e.button,editorAction:allowEditorEvent(e)});
    if(intent==='edit'){editorPointers.add(e.pointerId);drag=null;return;}
    stop(e);drag={id:e.pointerId,x:e.clientX,y:e.clientY};
    if(e.button===0&&doc.pointerLockElement!==canvas){
      try{const result=canvas.requestPointerLock?.();result?.catch?.(()=>{if(active)help.textContent=hint;});}catch{}
    }
  },true);
  listen(doc,'pointermove',e=>{
    if(editorPointers.has(e.pointerId))return;
    if(!active||!(e.target===canvas||doc.pointerLockElement===canvas||drag))return;
    stop(e);const locked=doc.pointerLockElement===canvas;
    if(!locked&&!drag)return;
    const dx=locked?e.movementX:e.clientX-drag.x,dy=locked?e.movementY:e.clientY-drag.y;
    if(drag){drag.x=e.clientX;drag.y=e.clientY;}
    yaw-=dx*.002;pitch=THREE.MathUtils.clamp(pitch-dy*.002,-Math.PI*.48,Math.PI*.48);orient();
  },true);
  for(const type of ['pointerup','pointercancel'])listen(doc,type,e=>{if(editorPointers.delete(e.pointerId))return;if(active&&(e.target===canvas||drag)){drag=null;stop(e);}},true);
  for(const type of ['click','dblclick','contextmenu','wheel'])listen(doc,type,e=>{if(active&&e.target===canvas&&!allowEditorEvent(e))stop(e);},{capture:true,passive:false});
  listen(doc,'keydown',e=>{
    if(!active)return;
    if(e.code==='Escape'||e.key==='Escape'){
      stop(e);clear();
      if(doc.pointerLockElement===canvas)doc.exitPointerLock?.();
      else exit();
      return;
    }
    if(e.target?.closest?.('input,textarea,select,[contenteditable="true"]'))return;
    if(e.ctrlKey||e.metaKey||e.altKey)return;
    if(movement.has(e.code)){stop(e);keys.add(e.code);}
  },true);
  listen(doc,'keyup',e=>{if(active&&movement.has(e.code)){keys.delete(e.code);stop(e);}},true);
  listen(doc,'pointerlockchange',()=>{if(doc.pointerLockElement===canvas){if(!active){doc.exitPointerLock?.();return;}hadLock=true;}else if(active&&hadLock){hadLock=false;clear();help.textContent=hint;invalidate();}});
  listen(win,'blur',clear);listen(doc,'visibilitychange',clear);
  return {get active(){return active;},enter,exit,update(seconds){if(active&&walkStep(camera.position,yaw,keys,seconds,world()))orient();},dispose(){exit();removers.forEach(remove=>remove());}};
}
