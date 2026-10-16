/* Optional presentation of the editor's existing scene. No household actions. */
import * as THREE from './vendor/three.module.js';

export function installBuilderVR({renderer,scene,camera,controls,ground,status,invalidate,beforeEnter=()=>{}}){
  const panel=document.createElement('details');panel.className='builder-vr';
  panel.innerHTML='<summary>Experimental VR</summary><p>Very early and still being worked on. Expect clunky behavior, incomplete controls, and headset compatibility problems. This previews your world; editing stays on the desktop. Headset testing is still needed.</p><label><input type="checkbox"> Enable experimental VR on this browser</label><button type="button" disabled>Enter VR</button><p class="vr-state" role="status"></p>';
  document.querySelector('header .actions').append(panel);
  const style=document.createElement('style');style.textContent='.builder-vr{position:relative}.builder-vr[open]{position:absolute;right:18px;top:60px;z-index:10005;width:min(360px,85vw);padding:16px;background:#142e32;color:#e6ecdf;border:1px solid #9d895d;border-radius:12px;box-shadow:0 12px 35px #0008}.builder-vr summary{cursor:pointer}.builder-vr p{font-size:13px;line-height:1.5}.builder-vr label{display:block}.builder-vr input{width:auto}';document.head.append(style);
  const enabled=panel.querySelector('input'),button=panel.querySelector('button'),message=panel.querySelector('.vr-state');
  const key='jnaiq.builders.experimental-vr';let session=null,busy=false,supported=false,snapshot=null,failure='';
  const rig=new THREE.Group();rig.name='Builder headset view';scene.add(rig);
  try{enabled.checked=localStorage.getItem(key)==='true';}catch{}
  function refresh(){button.disabled=busy||!enabled.checked||!supported;button.textContent=session?'Leave VR':'Enter VR';renderer.xr.enabled=enabled.checked||!!session;message.textContent=failure||(!enabled.checked?'Off. Ordinary editing works without a headset.':session?'VR is active. Use Leave VR or your headset menu to return.':supported?'Use Enter VR when your headset is ready.':'No compatible immersive headset was detected. Use a WebXR-capable browser with the headset connected.');}
  function restore(){
    if(snapshot){scene.attach(camera);camera.position.copy(snapshot.position);camera.quaternion.copy(snapshot.quaternion);controls.enabled=snapshot.controls;snapshot=null;controls.update();}
    session=null;busy=false;refresh();invalidate();
  }
  enabled.onchange=async()=>{failure='';try{localStorage.setItem(key,String(enabled.checked));}catch{}if(!enabled.checked&&session){try{await session.end();}catch(error){failure=error.message;}}refresh();};
  button.onclick=async()=>{
    if(busy||!enabled.checked)return;
    if(session){try{await session.end();}catch(error){message.textContent=error.message;}return;}
    busy=true;failure='';refresh();
    try{
      const next=await navigator.xr.requestSession('immersive-vr',{optionalFeatures:['local-floor','bounded-floor']});
      session=next;next.addEventListener('end',restore,{once:true});
      if(!enabled.checked){await next.end();return;}
      beforeEnter();
      snapshot={position:camera.position.clone(),quaternion:camera.quaternion.clone(),controls:controls.enabled};
      rig.position.set(controls.target.x,ground(controls.target.x,controls.target.z),controls.target.z);
      rig.add(camera);camera.position.set(0,0,0);camera.quaternion.identity();controls.enabled=false;
      renderer.xr.setReferenceSpaceType('local-floor');await renderer.xr.setSession(next);
      status('Experimental VR · headset view only; edit on the desktop.');
    }catch(error){const failed=session;if(failed)try{await failed.end();}catch{}restore();failure='VR could not start: '+error.message;}
    finally{busy=false;refresh();invalidate();}
  };
  refresh();
  if(navigator.xr?.isSessionSupported)navigator.xr.isSessionSupported('immersive-vr').then(value=>{supported=value;refresh();}).catch(()=>refresh());
  return {get active(){return !!session;}};
}
