// Choices act on the visiting member; residents use the same room actions.
import {bedPoses} from './rest-variants.mjs';
export function installPoseControls({bar,canvas,member,snapshot,data,act,refresh,status}){
  const open=document.createElement('button');open.textContent='Poses';bar.append(open);
  open.openFor=async(selected='')=>{
    if(document.pointerLockElement===canvas)document.exitPointerLock();
    try{
      const library=await data,record=snapshot()?.members?.[member];if(!record)return;
      document.getElementById('visitor-poses')?.remove();
      const dialog=document.createElement('dialog');dialog.id='visitor-poses';dialog.style.cssText='max-width:560px;max-height:75vh;overflow:auto';
      const title=document.createElement('h2');title.textContent='Pose · '+(snapshot()?.objects?.[selected||record.support_pose?.object]?.name||member);dialog.append(title);
      const note=document.createElement('p');note.textContent='Procedural poses need a compatible humanoid skeleton. Unrigged/custom models may show only part of a pose.';dialog.append(note);
      const choices=document.createElement('div');choices.style.cssText='display:flex;gap:8px;flex-wrap:wrap';dialog.append(choices);
      function choice(label,action,object='',payload={}){
        const button=document.createElement('button');button.textContent=label;choices.append(button);
        button.onclick=async()=>{button.disabled=true;try{const result=await act(action,object,payload);if(result.error)throw Error(result.error);await refresh();dialog.close();status(result.rest_pending?'Approaching '+(snapshot()?.objects?.[object]?.name||object)+'…':label);}catch(e){status(e.message,true);button.disabled=false;}};
      }
      if(!selected||record.support_pose?.object===selected)choice('Stand','stand');
      if(!selected){choice('Sit on ground','sit');if(record.posture!=='sitting')choice('Lie on ground','lie_down');}
      for(const [id,obj] of Object.entries(snapshot()?.objects||{})){
        if(selected?id!==selected:id!==record.support_pose?.object&&Math.hypot(obj.position_m[0]-record.position_m[0],obj.position_m[1]-record.position_m[1])>3)continue;
        if(obj.rest_support?.kind==='bed')for(const [variant,label] of Object.entries(bedPoses))choice(label+' · '+obj.name,'rest',id,{variant});
        else if(obj.capability==='sitting')choice('Sit · '+obj.name,'rest',id);
      }
      if(record.gesture)choice('Release pose','release_gesture');
      if(record.support_pose?.variant?.startsWith('elbow')){
        choice('Lift free hand','reach');choice('Poke','poke');choice('Rest free hand','release_reach');
        for(const [id,obj] of Object.entries(snapshot()?.objects||{}))if(id!==record.support_pose.object&&Math.hypot(obj.position_m[0]-record.position_m[0],obj.position_m[1]-record.position_m[1])<1){choice('Reach toward '+obj.name,'reach',id);choice('Poke toward '+obj.name,'poke',id);}
      }
      if(!selected&&(record.posture||'standing')==='standing')for(const name of ['attentive','weary','guarded','open','curious_tilt'])choice(name.replaceAll('_',' '),'gesture',name);
      for(const name of library.motions||[]){
        if(selected&&record.support_pose?.object!==selected)continue;
        const required=library.motion_postures?.[name]||'standing',posture=record.posture||'standing';
        if(required==='sitting'?posture.startsWith('sitting'):posture==='standing')choice(name.replaceAll('_',' '),'body_motion',name);
      }
      const close=document.createElement('button');close.textContent='Close';close.onclick=()=>dialog.close();dialog.append(close);
      dialog.addEventListener('close',()=>dialog.remove(),{once:true});document.body.append(dialog);dialog.showModal();
    }catch(e){status(e.message,true);}
  };
  open.onclick=()=>open.openFor();
  return open;
}
