import {choosePublicDestination} from './public-travel.mjs?public=4b';
import * as THREE from 'three';
import {GLTFLoader} from './vendor/GLTFLoader.js';
import {createGait} from './visitor-gait.mjs';
import {installPoseControls} from './visitor-poses.mjs';
import {createAvatarSurface} from './avatar-surface.mjs';
import {alignAvatarFacing} from './avatar-facing.mjs';
import {furnitureLayer} from './furniture.mjs';
import {heightAt} from './terrain.mjs';
import {nearbyTeleporters} from './teleporter-model.mjs';
import {installRoomChat} from './room-chat.mjs';
import {createWalkInput} from './visitor-input.mjs?held=3';
import {eyeAnchor} from './avatar-eye.mjs?perf=1';
import {createEyeFollower,localAvatarVisible} from './visitor-camera.mjs';
import {roomJson,watchRoomConnection} from './visitor-connection.mjs';
import {walkingSurfaces} from './visitor-surfaces.mjs';
import {avatarHeightSetting,fitAvatarHeight} from './avatar-height.mjs';
import {installGardenVisitor} from './garden-visitor.mjs';
import {installLiveGardenPlacement} from './live-garden-placement.mjs';

export async function installVisitor({scene,camera,controls,canvas,world,restore,invalidate,status,arrival,id,applyEnvironment,onFurnitureLayer,onReady,onError,xr=null}){
  const member=new URLSearchParams(location.search).get('member')||'user',rid='workshop_'+id;
  installRoomChat(member);
  async function refreshEnvironment(){
    const data=await json('/tuning'),patch=data.rooms?.[rid]||{};
    const atmosphere={...world.atmosphere};
    for(const key of ['environment','landBrightness','lightingColor','skyBrightness','skyColors','cavernLighting','cloudShadows','sunRays','nebulaClouds','strength','followLocalWeather','water','customSky'])if(key in patch)atmosphere[key]=patch[key];
    if('weather' in patch)atmosphere.weather=patch.weather==='cloudy'?'overcast':patch.weather;
    if('hour_override' in patch){atmosphere.followLocalTime=patch.hour_override<0;if(patch.hour_override>=0)atmosphere.hour=patch.hour_override;}
    weatherLabel.textContent='Weather · '+(atmosphere.weather||'scattered');
    applyEnvironment?.(atmosphere);invalidate();
  }
  document.body.classList.add('visiting');
  document.title=world.name+' · JNAIQ';
  document.querySelector('header h1').textContent=world.name;
  document.querySelector('header small').textContent='JNAIQ / VISITING';
  document.querySelector('header .actions').replaceChildren();
  const bar=document.querySelector('header .actions');
  const weatherLabel=document.createElement('span');weatherLabel.style.cssText='font-size:12px;color:#b9d5cb';bar.append(weatherLabel);
  const grassControl=document.getElementById('groundCover');if(grassControl)bar.append(grassControl.parentElement);
  function button(label,run){const b=document.createElement('button');b.textContent=label;b.onclick=run;bar.append(b);return b;}
  const style=document.createElement('style');style.textContent='.visiting aside,.visiting #workspace>*:not(#stage),.visiting #viewbar,.visiting footer>span:not(#status){display:none!important}.visiting main{display:block}.visiting #workspace{height:100%}.visiting header .actions{flex-wrap:wrap}.visiting #help{pointer-events:none}';document.head.append(style);
  const label=document.createElement('span');label.style.cssText='color:#b9d5cb;font-size:12px';bar.append(label);
  let snapshot=null,first=true,firstPerson=true,stopped=false,connected=false,started=false;
  const lifetime=new AbortController();
  // Register before awaiting the long-lived subscription, not after it exits.
  window.addEventListener('pagehide',()=>{stopped=true;lifetime.abort();},{once:true});
  const furniture=furnitureLayer({scene,invalidate:()=>invalidate(true),status,ground:(x,z)=>heightAt(world,x,z),textures:()=>world.textures||[]});
  onFurnitureLayer?.(furniture);
  controls.enabled=false;
  const bodies=new Map(),loader=new GLTFLoader();
  const avatarSettings=json('/tuning');
  const clipPromise=Promise.resolve(null);
  const idlePromise=Promise.resolve(null);
  const idleLibraryPromise=Promise.resolve(null);
  const surfacePromise=json(new URL('./avatar-surface.json',import.meta.url).href);
  const poseControls=installPoseControls({bar,canvas,member,snapshot:()=>snapshot,data:surfacePromise,refresh,status,
    act:(action,object,payload)=>json('/api/act',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({member,action,object,payload})})});
  const motionClips=new Map();
  function motionClip(name){if(!motionClips.has(name))motionClips.set(name,json(new URL('./visitor-motions/'+encodeURIComponent(name)+'.json',import.meta.url).href).catch(error=>{motionClips.delete(name);throw error;}));return motionClips.get(name);}
  async function syncRest(entry){
    if(!entry.gait)return;
    const posture=entry.rec.posture||'standing',key=posture==='lying'?'rest_lying':posture.startsWith('sitting')?'rest_seated':'';
    if(entry.restKey===key)return;entry.restKey=key;
    if(!key)return; // retain the source while its contribution fades out
    try{const clip=await motionClip(key);if(entry.restKey===key)entry.gait.setRestPose(clip);}catch(e){entry.restKey=null;status('Rest animation: '+e.message,true);}
  }
  async function surfaceEvent(entry,event){
    if(event.kind==='rest_failed'&&event.member===member)status(event.data?.error||'Could not settle on that surface.',true);
    event={...event,receivedAt:event.receivedAt??performance.now()};
    if(!entry.surface){(entry.pendingSurface??=[]).push(event);entry.pendingSurface=entry.pendingSurface.slice(-64);return;}
    entry.surface.event(event);
    if(event.kind==='say'){
      const source=pose(entry.rec),hold=Math.max(2.5,Math.min(7,String(event.data?.text||'').length*.06));
      for(const other of bodies.values())if(other!==entry){const delta=source.clone().sub(pose(other.rec));if(delta.length()<.05)continue;const yaw=Math.atan2(-delta.x,-delta.z)-(other.rec.heading_deg||0)*Math.PI/180;other.surface?.glance(Math.atan2(Math.sin(yaw),Math.cos(yaw)),hold);}
    }
    if(event.kind==='motion'){
      const name=event.data?.motion,requested=event.receivedAt;
      if(!entry.motionNames.includes(name)||!entry.gait)return;
      const token={};entry.motionRequest=token;
      try{const clip=await motionClip(name);if(bodies.get(event.member)===entry&&entry.motionRequest===token)entry.gait.performMotion(clip,(performance.now()-requested)/1000);}
      catch(error){status('Unable to load '+name.replaceAll('_',' ')+': '+error.message,true);}
    }
  }
  const footRay=new THREE.Raycaster(),down=new THREE.Vector3(0,-1,0);
  const ground=(x,z,y)=>{footRay.set(new THREE.Vector3(x,y+.45,z),down);footRay.far=.9;
    const hit=footRay.intersectObjects(walkingSurfaces(scene.children),false).find(h=>h.face?.normal.y>.5);return hit?hit.point.y:null;};
  async function json(url,options={}){return roomJson(url,{...options,signal:lifetime.signal,timeoutMs:url.includes('/events/wait')?35000:15000});}
  async function act(action,payload={}){return json('/api/act',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({member,action,object:payload.object||'',payload:{expected_room:rid,...payload},...(action==='walk'?{to:payload.to,heading_deg:((yaw*180/Math.PI)%360+360)%360}:{})})});}
  const gardenPlacement=installLiveGardenPlacement({scene,camera,canvas,world,member,room:rid,json,refresh,invalidate,status,
    view(){const previous=firstPerson;walkInput.clear();firstPerson=false;controls.enabled=true;focus();viewButton.textContent='Orbit · return to first person';return ()=>{firstPerson=previous;controls.enabled=!previous;viewButton.textContent=previous?'First person · switch to orbit':'Orbit · return to first person';focus();};}});
  const garden=installGardenVisitor({scene,world,member,bar,canvas,walk,invalidate,status,
    place:async()=>{try{await json('/api/rooms/'+rid+'/garden');gardenPlacement.start();}catch(error){status('Garden placement needs the updated room host. '+error.message,true);}},
    use:async(object,mode)=>{const result=await json('/api/act',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({member,action:'use',object,payload:{mode,expected_room:rid}})});await refresh();return {description:result.description};}});
  let publicTravelling=false;
  async function chooseDestination(){if(document.pointerLockElement===canvas)document.exitPointerLock();await choosePublicDestination({member,json,status,onTravelState:value=>publicTravelling=value});}
  button('Travel',chooseDestination);
  for(const control of bar.querySelectorAll('button'))if(['Garden','Poses'].includes(control.textContent))control.remove();
  const returnButton=document.createElement('span');bar.append(returnButton);
  const viewButton=button('First person · switch to orbit',()=>{walkInput.clear();firstPerson=!firstPerson;viewButton.textContent=firstPerson?'First person · switch to orbit':'Orbit · return to first person';controls.enabled=!firstPerson;focus();});
  button('Find me',focus);
  // Headset (20260914): WebXR immersive-vr through the browser's OpenXR runtime
  // (Meta Quest Link on this machine). Wearer-local presentation only: the head
  // pose moves nothing in the room; W/A/S/D still walks through /api/act like
  // the mouse-look path does, with the head's yaw as "forward".
  const onHeadset=()=>!!xr?.renderer.xr.isPresenting;
  const headsetButton=button('Headset',async()=>{
    if(!xr)return;if(new URLSearchParams(location.search).get('experimental_vr')!=='1'){status('Enable experimental VR in JNAIQ Worlds first.',true);return;}
    if(onHeadset()){await xr.renderer.xr.getSession()?.end();return;}
    if(!navigator.xr){status('This browser has no WebXR. Open the room in Edge or Chrome with Meta Quest Link running.',true);return;}
    try{
      if(!await navigator.xr.isSessionSupported('immersive-vr'))throw Error('no headset runtime answered. Is the Quest in Link?');
      const session=await navigator.xr.requestSession('immersive-vr',{optionalFeatures:['local-floor','bounded-floor']});
      if(stopped){await session.end();return;}
      session.addEventListener('end',leaveHeadset,{once:true});
      const me=snapshot?.members[member];
      if(me)xr.rig.position.copy(pose(me));
      xr.rig.rotation.set(0,yaw,0);
      await xr.renderer.xr.setSession(session);
      if(!firstPerson){firstPerson=true;controls.enabled=false;viewButton.textContent='First person · switch to orbit';}
      if(document.pointerLockElement===canvas)document.exitPointerLock();
      walkInput.clear();
      headsetButton.textContent='Leave headset';status('On the headset. Turn your head to look · W / A / S / D to walk · Shift to run.');
    }catch(e){
      const detail=String(e?.message||e||'unknown WebXR error');
      const policyBlocked=e?.name==='SecurityError'||/feature ["']?xr|xr-spatial-tracking|permissions policy/i.test(detail);
      status(policyBlocked
        ? 'Headset access was blocked by the page frame. Reload JNAIQ, then try Headset again.'
        : 'Headset: '+detail,true);
    }
  });
  headsetButton.disabled=new URLSearchParams(location.search).get('experimental_vr')!=='1';
  window.addEventListener('pagehide',()=>xr?.renderer.xr.getSession()?.end(),{once:true});
  function leaveHeadset(){walkInput.clear();xr.rig.position.set(0,0,0);xr.rig.rotation.set(0,0,0);camera.scale.set(1,1,1);headsetButton.textContent='Headset';focus();status('Back on the desktop.');}
  const headQuaternion=new THREE.Quaternion(),headEuler=new THREE.Euler(0,0,0,'YXZ');
  document.querySelector('#help').textContent='Hold W / S to walk forward or back · A / D to strafe · Shift to run. Click the view and move the mouse to look. Double-click ground to walk there. Press E for destinations. Use Travel or press E to choose a destination.';
  function pose(rec,now=Date.now()/1000){
    const p=new THREE.Vector3(rec.position_m[0],rec.height_m||0,-rec.position_m[1]),motion=rec.movement;
    if(!motion?.path_xyz)return p;
    let t=Math.max(0,Math.min(1,(now-motion.started_at-motion.turn_duration_s)/motion.move_duration_s));
    if(motion.interpolation!=='linear')t=t<.5?2*t*t:1-(-2*t+2)**2/2;
    const path=motion.path_xyz,k=t*(path.length-1),i=Math.min(path.length-2,Math.floor(k));
    return p.fromArray(path[i]).lerp(new THREE.Vector3().fromArray(path[i+1]),k-i);
  }
  let yaw=0,pitch=0;
  const eyeFollower=createEyeFollower();
  function eyePosition(p){return p.clone().add((bodies.get(member)?.eye||new THREE.Vector3(0,1.55,0)).clone().applyAxisAngle(new THREE.Vector3(0,1,0),yaw));}
  function focus(){const rec=snapshot?.members[member];if(!rec)return;const p=pose(rec);
    if(firstPerson){camera.position.copy(eyeFollower.reset(eyePosition(p)));camera.rotation.order='YXZ';camera.rotation.set(pitch,yaw,0);}
    else{controls.target.copy(p).add(new THREE.Vector3(0,1,0));camera.position.copy(p).add(new THREE.Vector3(2,1.8,3));controls.update();}invalidate();}
  async function body(name,rec){
    const root=new THREE.Group();root.userData.visitorBody=true;root.userData.contactOcclusion={radius:.28};scene.add(root);const marker=new THREE.Mesh(new THREE.CapsuleGeometry(.22,1.15,6,10),new THREE.MeshStandardMaterial({color:name===member?0xffce80:0x80d6b6}));marker.position.y=.8;root.add(marker);
    const entry={root,rec,marker};bodies.set(name,entry);
    try{
      let url='/avatars/'+encodeURIComponent(name.toLowerCase())+'.glb';
      if(rec.avatar_package)url='/api/avatar-library/packages/'+encodeURIComponent(rec.avatar_package)+'/model';
      const [gltf,settings]=await Promise.all([loader.loadAsync(url),avatarSettings]);if(bodies.get(name)!==entry)return;
      // Normalize in model space before attaching to an elevated room body.
      // Skinned bounds after parenting can count the room elevation twice.
      alignAvatarFacing(gltf.scene);
      fitAvatarHeight(gltf.scene,avatarHeightSetting(settings,rid,name));
      root.remove(marker);root.add(gltf.scene);entry.model=gltf.scene;
      entry.eye=eyeAnchor(gltf.scene,root);
      gltf.scene.traverse(o=>{if(o.isMesh){o.castShadow=true;o.receiveShadow=true;}});
      if(gltf.animations.length){entry.mixer=new THREE.AnimationMixer(gltf.scene);const walk=gltf.animations.find(a=>/walk/i.test(a.name));if(walk)entry.walk=entry.mixer.clipAction(walk).play();}
      const [clip,idle,surface,idleLibrary]=await Promise.all([clipPromise,idlePromise,surfacePromise,idleLibraryPromise]);
      if(bodies.get(name)!==entry)return;
      if(clip)entry.gait=createGait(gltf.scene,root,clip,ground,idle,{preserveShoulders:false,idleClips:[]});
      entry.surface=createAvatarSurface(gltf.scene,root,surface,{ground});entry.surface.sync(entry.rec);entry.motionNames=surface.motions;
      syncRest(entry);
      for(const event of entry.pendingSurface||[])surfaceEvent(entry,event);entry.pendingSurface=[];
      invalidate(true);
    }catch(error){console.error(name+': avatar load failed',error);status(name+': avatar unavailable; showing a body marker.',true);}
  }
  let furnitureState='';
  function apply(s){snapshot=s;garden.sync(s);
    const objects=Object.fromEntries(Object.entries(s.objects||{}).filter(([,o])=>o.capability!=='garden'));
    const nextFurnitureState=JSON.stringify(objects);
    if(nextFurnitureState!==furnitureState){furnitureState=nextFurnitureState;furniture.sync(objects);}
    for(const [name,rec] of Object.entries(s.members)){if(!bodies.has(name))body(name,rec);else {let entry=bodies.get(name);if(entry.rec.avatar_package!==rec.avatar_package){scene.remove(entry.root);bodies.delete(name);body(name,rec);continue;}entry.rec=rec;entry.surface?.sync(rec);syncRest(entry);}}
    for(const [name,entry] of bodies)if(!s.members[name]){scene.remove(entry.root);bodies.delete(name);}
    const me=s.members[member];if(!me){status('You are not in this world. Enter through the Nexus teleporter.',true);returnButton.disabled=true;return;}
    if(first){yaw=(me.heading_deg||0)*Math.PI/180;first=false;focus();}
    if(connected)walkInput.resume();
    invalidate();
  }
  async function refresh(){apply(await json('/api/rooms/'+rid+'?member='+encodeURIComponent(member)));}
  async function walk(x,z,control){try{if(!connected)throw Error('Room connection interrupted');const r=await act('walk',{to:[x,-z],control,expected_room:rid});status(r.blocked_by?'Stopped at '+r.blocked_by.replaceAll('_',' '):control==='run'?'Running':'Walking');const rec=snapshot?.members[member];if(rec&&r.motion){rec.movement=r.motion;rec.position_m=r.current_position_m||rec.position_m;}else await refresh();return !!r.blocked_by;}catch(e){status(e.message,true);if(control)throw e;return true;}}
  canvas.addEventListener('dblclick',e=>{e.preventDefault();e.stopImmediatePropagation();const rect=canvas.getBoundingClientRect(),ray=new THREE.Raycaster();ray.setFromCamera(new THREE.Vector2((e.clientX-rect.left)/rect.width*2-1,-(e.clientY-rect.top)/rect.height*2+1),camera);const hits=ray.intersectObjects(walkingSurfaces(scene.children),false);const p=hits[0]?.point;if(p)walk(p.x,p.z);},true);
  let dragging=null,hoverSeat='',restFlight=false;
  const seatPointer=new THREE.Vector2(),seatRay=new THREE.Raycaster();let pointerOnCanvas=false,seatPickKey='',seatPickValue='';
  const seatHint=document.createElement('button');seatHint.hidden=true;bar.append(seatHint);seatHint.onclick=()=>{if(hoverSeat)useSeat(hoverSeat);};
  canvas.addEventListener('contextmenu',e=>{const id=seatUnderPointer();if(id){e.preventDefault();e.stopImmediatePropagation();poseControls.openFor(id);}},true);
  function seatUnderPointer(){
    if(!pointerOnCanvas&&document.pointerLockElement!==canvas)return '';
    camera.updateWorldMatrix(true,false);
    const key=[...camera.matrixWorld.elements,...camera.projectionMatrix.elements,seatPointer.x,seatPointer.y,document.pointerLockElement===canvas,snapshot?.last_seq].join(',');
    if(key===seatPickKey)return seatPickValue;
    seatPickKey=key;seatPickValue='';
    seatRay.setFromCamera(document.pointerLockElement===canvas?new THREE.Vector2():seatPointer,camera);
    for(const hit of seatRay.intersectObjects(scene.children,true)){
      if(!hit.object.isMesh)continue;
      let id='',visible=true;
      for(let n=hit.object;n;n=n.parent){if(!n.visible)visible=false;if(n.userData.furnitureId)id=n.userData.furnitureId;}
      if(!visible)continue;
      const object=snapshot?.objects?.[id];
      seatPickValue=object&&(object.capability==='sitting'||object.rest_support?.kind==='bed')?id:'';
      return seatPickValue;
    }
    return '';
  }
  canvas.addEventListener('pointermove',e=>{const r=canvas.getBoundingClientRect();seatPointer.set((e.clientX-r.left)/r.width*2-1,-(e.clientY-r.top)/r.height*2+1);pointerOnCanvas=true;hoverSeat=seatUnderPointer();},true);
  canvas.addEventListener('pointerleave',()=>{pointerOnCanvas=false;hoverSeat='';});
  async function useSeat(id){
    if(restFlight)return;
    if(snapshot?.members?.[member]?.support_pose?.object===id){poseControls.openFor(id);return;}
    restFlight=true;
    try{const r=await act('rest',{object:id});if(r.error)throw Error(r.error);await refresh();status(r.rest_pending?'Approaching '+snapshot.objects[id].name+'…':'Settled · choose Poses or press E again');if(!r.rest_pending)poseControls.openFor(id);}catch(e){status(e.message,true);}finally{restFlight=false;}
  }
  canvas.addEventListener('pointerdown',e=>{canvas.focus();if(firstPerson){dragging=[e.clientX,e.clientY];canvas.setPointerCapture(e.pointerId);if(document.pointerLockElement!==canvas)canvas.requestPointerLock?.()?.catch?.(()=>{});e.stopImmediatePropagation();}},true);
  canvas.addEventListener('pointermove',e=>{if(firstPerson){if(dragging&&document.pointerLockElement!==canvas){yaw-=(e.clientX-dragging[0])*.004;pitch=Math.max(-1.35,Math.min(1.35,pitch-(e.clientY-dragging[1])*.004));dragging=[e.clientX,e.clientY];camera.rotation.set(pitch,yaw,0);invalidate();}e.stopImmediatePropagation();}},true);
  document.addEventListener('mousemove',e=>{if(firstPerson&&document.pointerLockElement===canvas){yaw-=e.movementX*.004;pitch=Math.max(-1.35,Math.min(1.35,pitch-e.movementY*.004));camera.rotation.set(pitch,yaw,0);invalidate();}});
  canvas.addEventListener('pointerup',e=>{dragging=null;if(firstPerson)e.stopImmediatePropagation();},true);
  const walkInput=createWalkInput({onError:error=>{
    status('Movement paused · '+error.message,true);
    if(error.status>=400&&error.status<500&&![408,429].includes(error.status)){walkInput.clear();return;}
    // Reconcile uncertain movement before continuing the still-held intent.
    // A failed reconciliation stays paused until the event stream reconnects.
    connected=false;
    refresh().then(()=>{connected=true;walkInput.resume();}).catch(()=>{});
  },motionEnd:()=>{const m=snapshot?.members[member]?.movement;return m?m.started_at+m.total_duration_s:0;},motionDuration:()=>snapshot?.members[member]?.movement?.total_duration_s||0,step:async (direction,running)=>{const rec=snapshot?.members[member];if(!rec)return true;const p=pose(rec);return walk(p.x+direction.x*.9,p.z+direction.z*.9,running?'run':'walk');}});
  canvas.tabIndex=0;
  const movementKeys=new Set(['KeyW','KeyA','KeyS','KeyD','ShiftLeft','ShiftRight']);
  document.addEventListener('keydown',e=>{
    if(gardenPlacement.active){walkInput.clear();return;}
    if(e.target.closest('#traveller-chat,input,textarea,select,[contenteditable]')||document.querySelector('dialog[open]')){walkInput.clear();return;}
    if(e.code==='KeyE'&&!e.repeat){walkInput.clear();e.preventDefault();e.stopImmediatePropagation();const id=seatUnderPointer();if(id)useSeat(id);else if(snapshot?.members?.[member]?.support_pose?.object)poseControls.openFor(snapshot.members[member].support_pose.object);else chooseDestination();return;}
    if(!movementKeys.has(e.code))return;
    e.preventDefault();e.stopImmediatePropagation();
    // Key repeats also establish a currently held key after a focus or
    // connection interruption. press is idempotent, so a solid wall still
    // cannot generate a request for every OS repeat.
    walkInput.press(e.code);
    walkInput.tick(yaw);
  },true);
  document.addEventListener('keyup',e=>walkInput.release(e.code),true);
  window.addEventListener('blur',()=>walkInput.clear());
  document.addEventListener('visibilitychange',()=>{if(document.hidden)walkInput.clear();});
  document.addEventListener('focusin',e=>{if(e.target.closest('#traveller-chat,input,textarea,select,[contenteditable]'))walkInput.clear();});
  let previous=performance.now();
  function updateFrame(now){walkInput.tick(yaw);const delta=Math.min((now-previous)/1000,.1);previous=now;let moving=false;
    hoverSeat=seatUnderPointer();seatHint.hidden=!hoverSeat;seatHint.textContent=hoverSeat?'E · '+snapshot.objects[hoverSeat].name+(snapshot.members[member]?.support_pose?.object===hoverSeat?' · poses':' · sit'):'';
    for(const [name,entry] of bodies){const p=pose(entry.rec),motion=entry.rec.movement,isMoving=!!(motion&&Date.now()/1000<motion.started_at+motion.total_duration_s);entry.root.position.copy(p);entry.root.rotation.y=(entry.rec.heading_deg||0)*Math.PI/180;entry.root.visible=localAvatarVisible(firstPerson,name,member);
      let bodyChanged=isMoving;
      entry.surface?.beginFrame();
      if(entry.walk){entry.walk.paused=!isMoving;entry.mixer.update(delta);}
      if((!entry.walk||!isMoving)&&entry.gait?.update(isMoving,delta,{posture:entry.rec.posture}))bodyChanged=true;
      if(entry.surface?.update(delta,{moving:isMoving}))bodyChanged=true;
      if(name===member&&entry.model)entry.eye=eyeAnchor(entry.model,entry.root);
      // Invisible first-person anatomy still drives the camera, but casts no shadows.
      moving||=entry.root.visible&&bodyChanged;}
    const me=snapshot?.members[member];if(me){const p=pose(me);label.textContent=`${member} · elevation ${p.y.toFixed(2)} m`;const near=nearbyTeleporters(snapshot,p);returnButton.textContent=near.length?'E · '+snapshot.objects[near[0]].name+' — destinations':'';if(firstPerson){if(onHeadset()){xr.rig.position.copy(p);yaw=headEuler.setFromQuaternion(camera.getWorldQuaternion(headQuaternion)).y;}else{camera.position.copy(eyeFollower.update(eyePosition(p),delta));camera.rotation.set(pitch,yaw,0);}}if(moving||firstPerson)invalidate(moving);}
  }
  function render(now){if(stopped)return;requestAnimationFrame(render);if(!onHeadset())updateFrame(now);}
  xr?.setFrameHandler?.(now=>{if(!stopped&&onHeadset())updateFrame(now);});
  try{await watchRoomConnection({signal:lifetime.signal,
    connect:async()=>{await refresh();await refreshEnvironment();return snapshot.last_seq||0;},
    wait:seq=>json(`/api/rooms/${rid}/events/wait?since=${seq}&surface=1&member=${encodeURIComponent(member)}`),
    apply:async(data,seq)=>{let changed=false;for(const e of data.events||[]){seq=Math.max(seq,e.seq);const entry=bodies.get(e.member);if(entry)surfaceEvent(entry,e);if(!['expression','transient_pose'].includes(e.kind))changed=true;if(['environment_settings','weather_revision'].includes(e.kind))await refreshEnvironment();if(e.kind==='depart'&&e.member===member&&!publicTravelling){lifetime.abort();location.replace('/3d/?member='+encodeURIComponent(member));return seq;}}if(changed||snapshot?.garden?.beds?.length)await refresh();return seq;},
    onConnect:()=>{connected=true;walkInput.resume();status('Visiting '+world.name);if(!started){started=true;onReady?.();requestAnimationFrame(render);}},
    onDisconnect:()=>{connected=false;walkInput.pause();status('Connection interrupted · reconnecting to the room…',true);},
  });}catch(e){connected=false;walkInput.clear();status(e.message+' · Reload the room view to reconnect.',true);onError?.(e);}
}

