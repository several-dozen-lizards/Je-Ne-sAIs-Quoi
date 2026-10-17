import {proceduralScores} from './procedural-scores.mjs';
import * as THREE from './vendor/three.module.js';
import {avatarRig} from './avatar-rig.mjs';

const q=()=>new THREE.Quaternion(),v=()=>new THREE.Vector3(),up=new THREE.Vector3(0,1,0);
const arm=role=>/Shoulder|UpperArm|LowerArm|Hand/.test(role);
const support=role=>/Hips|Leg|Foot|Toes/.test(role);

function meanRotation(clip,index){
  const anchor=q().fromArray(clip.frames[0][index]),sum=new THREE.Vector4();
  for(const frame of clip.frames){const r=q().fromArray(frame[index]),sign=anchor.dot(r)<0?-1:1;sum.add(new THREE.Vector4(r.x,r.y,r.z,r.w).multiplyScalar(sign));}
  return new THREE.Quaternion(sum.x,sum.y,sum.z,sum.w).normalize();
}
function palm(points,prefix){
  const hand=points.get(prefix+'Hand'),middle=points.get(prefix+'MiddleProximal'),index=points.get(prefix+'IndexProximal'),little=points.get(prefix+'LittleProximal');
  if(!hand||!middle||!index||!little)return null;
  const y=middle.clone().sub(hand).normalize(),z=index.clone().sub(little).cross(y).normalize();
  if(z.lengthSq()<1e-8)return null;
  return q().setFromRotationMatrix(new THREE.Matrix4().makeBasis(y.clone().cross(z).normalize(),y,z));
}
function limb(direction,normal){
  const y=direction.clone().normalize(),z=normal.clone().addScaledVector(y,-normal.dot(y)).normalize();
  return q().setFromRotationMatrix(new THREE.Matrix4().makeBasis(y.clone().cross(z).normalize(),y,z));
}
function forward(points){
  const left=points.get('LeftUpperArm'),right=points.get('RightUpperArm');
  if(!left||!right)return new THREE.Vector3(0,0,1);
  const lateral=left.clone().sub(right);lateral.y=0;
  return lateral.normalize().cross(up).normalize();
}
function sample(clip,index,phase){
  if(clip.loop===false){
    const cursor=Math.max(0,Math.min(1,phase))*(clip.frames.length-1),first=Math.floor(cursor),second=Math.min(clip.frames.length-1,first+1);
    return q().fromArray(clip.frames[first][index]).slerp(q().fromArray(clip.frames[second][index]),cursor-first).normalize();
  }
  const cursor=((phase%1)+1)%1*clip.frames.length,first=Math.floor(cursor),second=(first+1)%clip.frames.length;
  return q().fromArray(clip.frames[first][index]).slerp(q().fromArray(clip.frames[second][index]),cursor-first).normalize();
}

// Match the room's native joint-frame transfer, using measured limb and palm
// directions. Body translation remains entirely owned by the room snapshot.
export function createGait(model,root,clip,ground,idleClip=null,{preserveShoulders=false,idleClips=[]}={}){
  const {bones,slots}=avatarRig(model),roles=new Map([...slots].map(([role,bone])=>[bone,role]));
  model.updateWorldMatrix(true,true);
  const inverse=model.getWorldQuaternion(q()).invert(),points=new Map(),rests=new Map();
  const origin=model.getWorldPosition(v());
  for(const [role,bone] of slots){
    points.set(role,bone.getWorldPosition(v()).sub(origin).applyQuaternion(inverse));
    rests.set(role,bone.getWorldQuaternion(q()).premultiply(inverse));
  }
  const hasLegs=slots.has('LeftUpperLeg')&&slots.has('RightUpperLeg');
  const shoulders=new Map(preserveShoulders?[...slots].filter(([role])=>/Shoulder$/.test(role)).map(([,bone])=>[bone,bone.quaternion.clone()]):[]);
  function bind(source){
    const sourcePoints=new Map(source.bones.map(b=>[b.name,v().fromArray(b.position)]));
    const frame=q().setFromUnitVectors(forward(sourcePoints),forward(points)),unframe=frame.clone().invert();
    const targetPoints=new Map([...points].map(([role,p])=>[role,p.clone().applyQuaternion(unframe)]));
    return new Map(bones.flatMap(bone=>{
      const role=roles.get(bone),index=source.bones.findIndex(b=>b.name===role);
      // Palm/finger anchors calibrate roll but retain their authored local pose.
      // A tail-bearing resident's pelvis/support chain also remains authored.
      if(index<0||shoulders.has(bone)||/Proximal$/.test(role)||(!hasLegs&&support(role)))return [];
      const rest=rests.get(role).clone().premultiply(unframe),record=source.bones[index];
      let alignment=q(),next='';
      for(const [start,end] of [['UpperArm','LowerArm'],['LowerArm','Hand'],['UpperLeg','LowerLeg'],['LowerLeg','Foot']])
        if(role.endsWith(start))next=role.replace(start,end);
      const direction=next&&targetPoints.has(next)?targetPoints.get(next).clone().sub(targetPoints.get(role)).normalize():null;
      if(direction)alignment.setFromUnitVectors(direction,v().fromArray(record.direction).normalize());
      if(/UpperArm|LowerArm|Hand/.test(role)){
        const prefix=role.startsWith('Left')?'Left':'Right',tp=palm(targetPoints,prefix),sp=palm(sourcePoints,prefix);
        if(tp&&sp){
          if(direction){
            const normal=new THREE.Vector3(0,0,1);
            alignment=limb(v().fromArray(record.direction),normal.clone().applyQuaternion(sp)).multiply(limb(direction,normal.applyQuaternion(tp)).invert());
          }else alignment=sp.multiply(tp.invert());
        }
      }
      return [[bone,{role,index,frame,rest,alignment,inverse:q().fromArray(record.rest).invert(),mean:meanRotation(source,index)}]];
    }));
  }
  const walkPairs=bind(clip),idlePairs=idleClip?bind(idleClip):walkPairs;
  const idles=(idleClips.length?idleClips:idleClip?[idleClip]:[]).map(source=>({source,pairs:source===idleClip?idlePairs:bind(source)}));
  const idleDuration=idles.reduce((total,idle)=>total+idle.source.duration,0);
  function idleAt(time){
    if(!idles.length)return null;
    let cursor=time%idleDuration,index=0;
    while(index<idles.length-1&&cursor>=idles[index].source.duration){cursor-=idles[index].source.duration;index++;}
    const phase=cursor/idles[index].source.duration;
    // Change at an authored clip boundary; blend into the next clip's first pose.
    return {current:idles[index],next:idles[(index+1)%idles.length],phase,blend:idles.length>1?THREE.MathUtils.smoothstep(phase,.85,1):0};
  }
  const legs=[];
  for(const side of ['Left','Right']){
    const hip=slots.get(side+'UpperLeg'),knee=slots.get(side+'LowerLeg'),foot=slots.get(side+'Foot');
    if(hip&&knee&&foot)legs.push({hip,knee,foot,ankle:foot.getWorldPosition(v()).y-root.getWorldPosition(v()).y});
  }
  const travel=clip.hips?v().fromArray(clip.hips.at(-1)).sub(v().fromArray(clip.hips[0])).length():0;
  let distance=0,time=0,weight=0,previous=root.position.clone(),motion=null,restPose=null,restWeight=0;
  const restCache=new Map();
  function restful(pair,source,phase){
    if(support(pair.role))return rests.get(pair.role).clone();
    // Remove the source pelvis orientation. Support belongs to this body's
    // seating/reclining layer, while torso and arms carry the performance.
    const hip=source.bones.findIndex(b=>b.name==='Hips');
    const rotation=sample(source,pair.index,phase);
    if(hip>=0)rotation.premultiply(q().fromArray(source.bones[hip].rest).multiply(sample(source,hip,phase).invert()));
    return pair.frame.clone().multiply(rotation).multiply(pair.inverse).multiply(pair.alignment).multiply(pair.rest).normalize();
  }
  function desired(pair,source,phase,standing){
    if(standing&&support(pair.role))return rests.get(pair.role).clone();
    const rotation=source?sample(source,pair.index,phase):pair.mean.clone();
    // Keep the authored upright torso baseline; transfer the clip's variation.
    // Arms carry the full lowered stance, independently of torso amplitude.
    const reference=!arm(pair.role)&&!support(pair.role)?pair.mean.clone().invert():pair.inverse;
    const alignment=!arm(pair.role)&&!support(pair.role)?q():pair.alignment;
    return pair.frame.clone().multiply(rotation).multiply(reference).multiply(alignment).multiply(pair.rest).normalize();
  }
  return {mappedBones:walkPairs.size,roles:[...walkPairs.values()].map(p=>p.role),
    setRestPose(source){
      if(!source){restPose=null;return;}
      if(!restCache.has(source))restCache.set(source,{source,pairs:bind(source)});
      restPose=restCache.get(source);
    },
    performMotion(source,elapsed=0){if(elapsed>=source.duration)return false;motion={source,pairs:bind(source),time:Math.max(0,elapsed)};return true;},
    update(moving,delta=0,{posture='standing'}={}){
    delta=Number.isFinite(delta)?Math.max(0,delta):0;time+=delta;
    // Custom clavicles retain their authored local attachment, matching
    // the room driver. Torso motion still carries them; arms keep full mocap.
    for(const [bone,rest] of shoulders)bone.quaternion.copy(rest);
    model.updateWorldMatrix(true,true);
    // Arrival/teleport displacement cannot advance an unrequested stride.
    if(moving)distance+=Math.hypot(root.position.x-previous.x,root.position.z-previous.z);
    previous.copy(root.position);
    weight+=(Number(!!moving)-weight)*(1-Math.exp(-delta/(clip.duration/4)));
    const walkPhase=travel>1e-6?distance/travel:time/clip.duration;
    restWeight+=((!moving&&posture!=='standing'&&restPose?1:0)-restWeight)*(1-Math.exp(-delta/.45));
    if(motion){motion.time+=delta;const compatible=motion.source.posture==='sitting'?posture.startsWith('sitting'):posture==='standing';if(moving||!compatible||motion.time>=motion.source.duration)motion=null;}
    model.userData.restActionActive=!!motion;
    const rootQ=model.getWorldQuaternion(q());
    const idleState=idleAt(time);
    for(const [bone,pair] of walkPairs){
      const idle=idleState?.current.pairs.get(bone)||idlePairs.get(bone),standing=idle?desired(idle,idleState?.current.source||idleClip,idleState?.phase||0,true):rests.get(pair.role).clone();
      const next=idleState?.next.pairs.get(bone);
      if(next&&idleState.blend)standing.slerp(desired(next,idleState.next.source,0,true),idleState.blend);
      const rotation=standing.slerp(desired(pair,clip,walkPhase,false),weight);
      if(restPose&&restWeight>1e-5&&restPose.pairs.has(bone))rotation.slerp(restful(restPose.pairs.get(bone),restPose.source,time/restPose.source.duration),restWeight);
      if(motion&&!support(pair.role)&&motion.pairs.has(bone)){
        const duration=motion.source.duration,fade=Math.min(.9,duration/3);
        const gain=Math.max(0,Math.min(1,motion.time/fade,(duration-motion.time)/fade));
        rotation.slerp(motion.source.posture==='sitting'?restful(motion.pairs.get(bone),motion.source,motion.time/duration):desired(motion.pairs.get(bone),motion.source,motion.time/duration,true),gain);
      }
      rotation.premultiply(rootQ);
      bone.quaternion.copy(bone.parent.getWorldQuaternion(q()).invert().multiply(rotation));bone.updateWorldMatrix(false,true);
    }
    for(const leg of legs){
      if(posture!=='standing')continue;
      const current=leg.foot.getWorldPosition(v()),height=ground?.(current.x,current.z,root.position.y);
      if(height==null)continue;
      const target=current.clone(),footRotation=leg.foot.getWorldQuaternion(q());
      target.y=Math.max(current.y,height+leg.ankle)*weight+(height+leg.ankle)*(1-weight);
      solveLeg(leg.hip,leg.knee,leg.foot,target,rootQ);
      leg.foot.quaternion.copy(leg.foot.parent.getWorldQuaternion(q()).invert().multiply(footRotation));
      leg.foot.updateWorldMatrix(false,true);
    }
    return walkPairs.size>0;
  }};
}

export function solveLeg(hip,knee,foot,target,rootQ=new THREE.Quaternion(),bendDirection=null){
  const v=()=>new THREE.Vector3(),q=()=>new THREE.Quaternion();
  const a=hip.getWorldPosition(v()),b=knee.getWorldPosition(v()),c=foot.getWorldPosition(v());
  const upper=a.distanceTo(b),lower=b.distanceTo(c),delta=target.clone().sub(a),distance=Math.max(.001,Math.min(upper+lower-.0001,delta.length()));
  const along=delta.normalize(),forward=bendDirection?.clone()||new THREE.Vector3(0,0,1).applyQuaternion(rootQ);
  const bend=forward.addScaledVector(along,-forward.dot(along)).normalize();
  const projection=(upper*upper+distance*distance-lower*lower)/(2*distance),height=Math.sqrt(Math.max(0,upper*upper-projection*projection));
  const desiredKnee=a.clone().addScaledVector(along,projection).addScaledVector(bend,height);
  function aim(bone,child,target){const origin=bone.getWorldPosition(v()),from=child.getWorldPosition(v()).sub(origin).normalize(),to=target.clone().sub(origin).normalize();
    const desired=q().setFromUnitVectors(from,to).multiply(bone.getWorldQuaternion(q()));
    bone.quaternion.copy(bone.parent.getWorldQuaternion(q()).invert().multiply(desired));bone.updateWorldMatrix(false,true);
  }
  aim(hip,knee,desiredKnee);aim(knee,foot,target);
}


// Original analytic motion driver for the public build. Uses the same room
// event/gait interface; changes joints only, never canonical location or mood.
export function createProceduralGait(model,root,ground){
  const {bones,slots}=avatarRig(model),q=()=>new THREE.Quaternion(),v=()=>new THREE.Vector3();
  const axes={x:new THREE.Vector3(-1,0,0),y:new THREE.Vector3(0,1,0),z:new THREE.Vector3(0,0,-1)};
  model.updateWorldMatrix(true,true);
  const rootFrame=root.getWorldQuaternion(q()),rootInverse=rootFrame.clone().invert();
  // Calibrate the authored starter's raised bind arms from measured joint
  // directions. Unknown/nonhumanoid bodies keep their imported geometry.
  for(const side of ['Left','Right']){
    const upper=slots.get(side+'UpperArm'),lower=slots.get(side+'LowerArm');if(!upper||!lower)continue;
    const a=upper.getWorldPosition(v()),b=lower.getWorldPosition(v()),center=model.getWorldPosition(v());
    const sign=Math.sign(a.clone().sub(center).applyQuaternion(rootInverse).x)|| (side==='Left'?1:-1);
    const down=new THREE.Vector3(sign*.13,-.99,-.025).normalize().applyQuaternion(rootFrame);
    const desired=q().setFromUnitVectors(b.sub(a).normalize(),down).multiply(upper.getWorldQuaternion(q()));
    upper.quaternion.copy(upper.parent.getWorldQuaternion(q()).invert().multiply(desired));model.updateWorldMatrix(true,true);
  }
  const sideSigns=new Map(['Left','Right'].flatMap(side=>{const b=slots.get(side+'UpperArm');return b?[[side,Math.sign(b.getWorldPosition(v()).sub(model.getWorldPosition(v())).applyQuaternion(rootInverse).x)||(side==='Left'?1:-1)]]:[];}));
  const arms=['Left','Right'].flatMap(side=>{const upper=slots.get(side+'UpperArm'),lower=slots.get(side+'LowerArm'),hand=slots.get(side+'Hand');return upper&&lower&&hand?[{side,upper,lower,hand}]:[];});
  const base=new Map(bones.map(b=>[b,b.quaternion.clone()]));
  const frames=new Map([...slots].map(([role,b])=>[role,b.getWorldQuaternion(q()).premultiply(rootInverse)]));
  const measured=new THREE.Box3().setFromObject(model).getSize(v()).y;
  const height=Number.isFinite(measured)&&measured>0?measured:1.7;
  const legs=[];
  for(const side of ['Left','Right']){
    const hip=slots.get(side+'UpperLeg'),knee=slots.get(side+'LowerLeg'),foot=slots.get(side+'Foot');
    if(hip&&knee&&foot)legs.push({hip,knee,foot,side,length:hip.getWorldPosition(v()).distanceTo(knee.getWorldPosition(v()))+knee.getWorldPosition(v()).distanceTo(foot.getWorldPosition(v())),ankle:foot.getWorldPosition(v()).y-root.getWorldPosition(v()).y});
  }
  const legLength=legs.length?legs.reduce((s,l)=>s+l.length,0)/legs.length:height*.5;
  const stride=Math.max(.1,legLength*1.35),swing=Math.asin(Math.min(.65,stride/(2*Math.max(.1,legLength))));
  let phase=0,weight=0,previous=root.position.clone(),motion=null;
  function rotate(role,axis,radians){const bone=slots.get(role),frame=frames.get(role);if(!bone||!frame)return;
    if(axis==='z'&&/^(Left|Right)(UpperArm|LowerArm|Hand)$/.test(role)){const side=role.startsWith('Left')?'Left':'Right';radians*= (sideSigns.get(side)||1)/(side==='Left'?1:-1);}
    bone.quaternion.multiply(frame.clone().invert().multiply(q().setFromAxisAngle(axes[axis],radians)).multiply(frame)).normalize();
  }
  return {mappedBones:slots.size,roles:[...slots.keys()],procedural:true,
    setRestPose(){},
    performMotion(source,elapsed=0){
      if(!source?.procedural||elapsed>=source.duration)return false;
      const score=proceduralScores[source.name];
      if(!score||!Object.keys(score[1]).some(role=>slots.has(role)))return false;
      motion={source,time:Math.max(0,elapsed)};return true;
    },
    update(moving,delta=0,{posture='standing'}={}){
      delta=Math.max(0,Math.min(.1,Number(delta)||0));
      const distance=Math.hypot(root.position.x-previous.x,root.position.z-previous.z);previous.copy(root.position);
      if(moving)phase+=distance/stride*Math.PI*2;
      const response=1-Math.exp(-delta/(stride/1.4*.22));weight+=((moving&&posture==='standing'?1:0)-weight)*response;
      for(const [bone,rest] of base)bone.quaternion.copy(rest);
      if(posture==='standing')for(const [side,sign] of [['Left',1],['Right',-1]]){
        const wave=Math.sin(phase)*sign;
        rotate(side+'UpperLeg','x',wave*swing*weight);
        rotate(side+'LowerLeg','x',-Math.max(0,-wave)*swing*.85*weight);
        rotate(side+'UpperArm','x',-wave*swing*.55*weight);
      }
      if(motion){
        motion.time+=delta;const source=motion.source;
        const compatible=source.posture==='sitting'?posture.startsWith('sitting'):posture==='standing';
        if(moving||!compatible||motion.time>=source.duration)motion=null;
        else{
          const p=motion.time/source.duration,envelope=Math.sin(Math.PI*p)**2;
          for(const [role,steps] of Object.entries(proceduralScores[source.name][1]))for(const [axis,degrees,cycles] of steps)
            rotate(role,axis,THREE.MathUtils.degToRad(degrees)*envelope*(cycles?Math.sin(Math.PI*2*cycles*p):1));
        }
      }
      // The original clap score includes a measured two-arm contact solve.
      // Hand separation oscillates with the authored clap phase, scaled to body.
      if(motion?.source.name==='seated_clap'&&arms.length===2){
        model.updateWorldMatrix(true,true);
        const p=motion.time/motion.source.duration,envelope=Math.sin(Math.PI*p)**2,scale=height/1.7;
        const center=arms.reduce((sum,a)=>sum.add(a.upper.getWorldPosition(v())),v()).multiplyScalar(.5);
        const frame=root.getWorldQuaternion(q()),spread=(.025+.10*(.5+.5*Math.cos(p*Math.PI*6)))*scale;
        for(const a of arms){const sign=sideSigns.get(a.side)||1,current=a.hand.getWorldPosition(v()),handRotation=a.hand.getWorldQuaternion(q());
          const target=center.clone().add(new THREE.Vector3(sign*spread,-.20*scale,-.32*scale).applyQuaternion(frame));
          target.lerp(current,1-envelope);
          solveLeg(a.upper,a.lower,a.hand,target,frame,new THREE.Vector3(sign*.6,-1,0).applyQuaternion(frame));
          a.hand.quaternion.copy(a.hand.parent.getWorldQuaternion(q()).invert().multiply(handRotation));model.updateWorldMatrix(true,true);
        }
      }
      model.userData.restActionActive=!!motion;model.userData.publicMotion=motion?.source.name||'';model.userData.publicMotionProgress=motion?motion.time/motion.source.duration:0;
      model.userData.publicRigRoles=[...slots.keys()];model.updateWorldMatrix(true,true);
      if(posture==='standing'&&weight>1e-5)for(const leg of legs){
        const current=leg.foot.getWorldPosition(v()),floor=ground?.(current.x,current.z,root.position.y);
        if(floor==null||current.y>=floor+leg.ankle)continue;
        const target=current.clone();target.y=floor+leg.ankle;
        solveLeg(leg.hip,leg.knee,leg.foot,target,root.getWorldQuaternion(q()));
      }
      return weight>1e-4||!!motion;
    }
  };
}
