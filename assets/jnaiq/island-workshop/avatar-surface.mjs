import * as THREE from './vendor/three.module.js';
import {avatarRig,boneKey} from './avatar-rig.mjs';
import {solveLeg} from './visitor-gait.mjs';
import {variantPose,restRoll,restVariant} from './rest-variants.mjs';

const bounded=(n,lo=0,hi=1)=>Number.isFinite(Number(n))?Math.max(lo,Math.min(hi,Number(n))):lo;
const quaternion=()=>new THREE.Quaternion();
const axes={x:new THREE.Vector3(-1,0,0),y:new THREE.Vector3(0,1,0),z:new THREE.Vector3(0,0,-1)};
const roles={head:'Head',neck:'Neck',chest:'UpperChest',lumbar:'Spine',armL:'LeftShoulder',armR:'RightShoulder',humL:'LeftUpperArm',humR:'RightUpperArm',elbowL:'LeftLowerArm',elbowR:'RightLowerArm',wristL:'LeftHand',wristR:'RightHand',hipL:'LeftUpperLeg',hipR:'RightUpperLeg',kneeL:'LeftLowerLeg',kneeR:'RightLowerLeg'};

export function visibleEmotions(face,data){
  const result={};
  for(const term of Array.isArray(face?.emotions)?face.emotions:[]){
    const text=String(term),colon=text.lastIndexOf(':'),raw=(colon<0?text:text.slice(0,colon)).trim().toLowerCase();
    const name=data.aliases?.[raw]||raw,weight=bounded(colon<0?.6:text.slice(colon+1));
    result[name]=(result[name]||0)+weight;
  }
  return result;
}

export function expressionTargets(face,data){
  const result={},emotions=visibleEmotions(face,data);
  for(const [name,weight] of Object.entries(emotions))
    for(const [shape,value] of Object.entries(data.emotions[name]||{}))result[shape]=(result[shape]||0)+value*weight;
  const threat=bounded(face?.threat),activation=bounded(.7+bounded(face?.tension)*.4+bounded(face?.emotional_arousal??.15)*.25,.7,1.3);
  for(const [shape,value] of Object.entries({eyeWideLeft:.6,eyeWideRight:.6,browInnerUp:.4,browOuterUpLeft:.4,browOuterUpRight:.4,mouthStretchLeft:.35,mouthStretchRight:.35}))result[shape]=(result[shape]||0)+threat*value;
  const hard=/^(browDown|mouthPress|eyeSquint|noseSneer|jawForward)/,relax=1-.5*bounded(face?.centering_softness??.4);
  for(const key of Object.keys(result))result[key]=bounded(result[key]*(key.startsWith('eyeBlink')?1:activation*(hard.test(key)?relax:1)));
  return result;
}

// Only visible surface packets enter this controller. The gait writes its
// baseline first; these bounded deposits compose over it without accumulating.
export function createAvatarSurface(model,root,data,{ground}={}){
  const {bones,slots}=avatarRig(model),targets=[],before=new Map(),poseCurrent=new Map(),current={},chosen={};
  model.updateWorldMatrix(true,true);
  const rootInverse=root.getWorldQuaternion(quaternion()).invert();
  const rests=new Map(bones.map(b=>[b,{local:b.quaternion.clone(),frame:b.getWorldQuaternion(quaternion()).premultiply(rootInverse)}]));
  const armHinges=new Map();
  for(const side of ['Left','Right']){
    const upper=slots.get(side+'UpperArm'),lower=slots.get(side+'LowerArm'),hand=slots.get(side+'Hand');
    if(!upper||!lower||!hand)continue;
    const a=upper.getWorldPosition(new THREE.Vector3()),b=lower.getWorldPosition(new THREE.Vector3()),c=hand.getWorldPosition(new THREE.Vector3());
    const normal=b.clone().sub(a).cross(c.sub(b));
    if(normal.lengthSq()>1e-10)armHinges.set(upper,normal.normalize().applyQuaternion(upper.getWorldQuaternion(quaternion()).invert()));
  }
  const basePosition=model.position.clone(),baseY=model.position.y,baseRotation=model.quaternion.clone(),box=new THREE.Box3().setFromObject(model),measuredHeight=box.max.y-box.min.y;
  const height=Number.isFinite(measuredHeight)&&measuredHeight>0?measuredHeight:1.75;
  const pelvis=slots.get('Hips'),contactSamples=[],pelvisSamples=[],sideHipSamples=[];
  const thighSamples={Left:[],Right:[]},handSamples={Left:[],Right:[]};
  const headSamples=[];
  const hipPoint=pelvis?.getWorldPosition(new THREE.Vector3());
  model.traverse(mesh=>{
    if(!mesh.isSkinnedMesh)return;
    // Resting poses move beyond the imported standing bounds. Do not cull
    // separate head/hair meshes against a stale bind-pose bounding sphere.
    mesh.frustumCulled=false;
    const count=mesh.geometry.attributes.position.count;mesh.skeleton.update();
    for(let i=0;i<count;i+=Math.max(1,Math.floor(count/320))){
      const p=mesh.localToWorld(mesh.getVertexPosition(i,new THREE.Vector3()));
      const ids=mesh.geometry.attributes.skinIndex,weights=mesh.geometry.attributes.skinWeight;
      let dominant=0;for(let j=1;j<4;j++)if(weights.getComponent(i,j)>weights.getComponent(i,dominant))dominant=j;
      const weightedBone=mesh.skeleton.bones[ids.getComponent(i,dominant)];
      if(weightedBone===pelvis&&hipPoint&&p.distanceTo(hipPoint)<height*.14)sideHipSamples.push([mesh,i]);
      for(let ancestor=weightedBone;ancestor;ancestor=ancestor.parent)if(ancestor===slots.get('Head')){headSamples.push([mesh,i]);break;}
      for(const side of ['Left','Right']){
        if(weightedBone===slots.get(side+'UpperLeg'))thighSamples[side].push([mesh,i]);
        for(let ancestor=weightedBone;ancestor;ancestor=ancestor.parent)if(ancestor===slots.get(side+'Hand')){handSamples[side].push([mesh,i]);break;}
      }
      let armBone=false;for(let parent=weightedBone;parent;parent=parent.parent)if([...slots].some(([role,bone])=>bone===parent&&/Arm|Hand|Shoulder/.test(role))){armBone=true;break;}
      if(!armBone)contactSamples.push([mesh,i]);
      if(hipPoint&&Math.abs(p.y-hipPoint.y)<height*.105&&Math.hypot(p.x-hipPoint.x,p.z-hipPoint.z)<height*.17)pelvisSamples.push([mesh,i]);
    }
  });
  function contactLow(seated){
    // A dangling coat hem or foot must not suspend a side-resting pelvis.
    const samples=restVariant(rec).startsWith('elbow')&&sideHipSamples.length?sideHipSamples:seated?pelvisSamples:contactSamples;let low=Infinity;
    root.updateMatrixWorld(true);
    const skeletons=new Set(samples.map(([m])=>m.skeleton));for(const skel of skeletons)skel.update();
    for(const [mesh,i] of samples)low=Math.min(low,mesh.localToWorld(mesh.getVertexPosition(i,new THREE.Vector3())).y);
    return Number.isFinite(low)?low:(pelvis?.getWorldPosition(new THREE.Vector3()).y??root.position.y)-height*.065;
  }
  function attachContact(seated){
    const support=rec.support_pose;if(!Number.isFinite(support?.surface_y_m)||!pelvis)return;
    const point=pelvis.getWorldPosition(new THREE.Vector3()),local=root.worldToLocal(point.clone());
    model.position.x-=local.x;model.position.z-=local.z;model.updateWorldMatrix(false,true);
    const lift=support.surface_y_m-contactLow(seated);
    // The parent is a yaw-only, metre-scaled room anchor.
    model.position.y+=lift;model.updateWorldMatrix(false,true);
  }
  function skinPoints(samples){
    root.updateMatrixWorld(true);for(const skeleton of new Set(samples.map(([m])=>m.skeleton)))skeleton.update();
    return samples.map(([mesh,i])=>mesh.localToWorld(mesh.getVertexPosition(i,new THREE.Vector3())));
  }
  function thighTop(side,point){
    const nearby=skinPoints(thighSamples[side]).filter(p=>Math.hypot(p.x-point.x,p.z-point.z)<height*.07);
    return nearby.length?Math.max(...nearby.map(p=>p.y)):null;
  }
  const legs=['Left','Right'].flatMap(side=>{
    const hip=slots.get(side+'UpperLeg'),knee=slots.get(side+'LowerLeg'),foot=slots.get(side+'Foot');
    if(!hip||!knee||!foot)return [];
    const point=root.worldToLocal(foot.getWorldPosition(new THREE.Vector3()));
    return [{hip,knee,foot,point,side:Math.sign(root.worldToLocal(hip.getWorldPosition(new THREE.Vector3())).x)||1}];
  });
  const tail=bones.filter(b=>/^tail_?\d+$/i.test(b.name)).sort((a,b)=>a.name.localeCompare(b.name,undefined,{numeric:true}));
  const jaw=bones.find(b=>boneKey(b.name)==='jaw');
  model.traverse(mesh=>{if(mesh.morphTargetDictionary&&mesh.morphTargetInfluences)
    for(const [name,index] of Object.entries(mesh.morphTargetDictionary)){
      const channels=data.channels[name]||[name];
      if(data.channels[name]||Object.values(data.emotions).some(g=>name in g))targets.push({mesh,index,channels});
    }});
  let rec={},time=0,hold=0,speech=0,drop=0,recline=0,transient=null,look=null;
  const transientCurrent={},gazeCurrent={yaw:0,pitch:0};
  let blinkPhase=0;
  // Per-body phase separates ordinary eyelid movement without a polling timer.
  const signature=[...model.name].reduce((sum,c)=>sum+c.charCodeAt(0),0);
  blinkPhase=(signature%97)/97;
  const resolve=role=>slots.get(roles[role])||(role==='chest'?slots.get('Chest'):null);
  function save(bone){if(!before.has(bone))before.set(bone,bone.quaternion.clone());}
  function aimRest(bone,child,direction){
    if(!bone||!child)return;save(bone);
    const from=child.getWorldPosition(new THREE.Vector3()).sub(bone.getWorldPosition(new THREE.Vector3())).normalize();
    const desired=quaternion().setFromUnitVectors(from,direction.clone().normalize()).multiply(bone.getWorldQuaternion(quaternion()));
    bone.quaternion.copy(bone.parent.getWorldQuaternion(quaternion()).invert().multiply(desired));bone.updateWorldMatrix(false,true);
  }
  function deposit(bone,rotation,absolute=false){
    if(!bone)return;save(bone);
    if(absolute)bone.quaternion.copy(rests.get(bone).local);
    const frame=rests.get(bone).frame;
    bone.quaternion.multiply(frame.clone().invert().multiply(rotation).multiply(frame)).normalize();
    bone.updateWorldMatrix(false,true);
  }
  function poseRotation(steps){const result=quaternion();for(const [axis,degrees] of steps||[])result.multiply(quaternion().setFromAxisAngle(axes[axis]||axes.x,THREE.MathUtils.degToRad(degrees)));return result;}
  function blendedPose(){
    const posture=rec.posture||'standing';
    if(posture==='lying'||restVariant(rec)==='sit_up')return variantPose(rec);
    if(data.sits[posture])return data.sits[posture];
    if(data.poses[rec.gesture])return data.poses[rec.gesture];
    let selected='',weight=0;
    for(const [emotion,value] of Object.entries(visibleEmotions(rec.face,data)))if(data.mood_poses[emotion]&&value>weight){selected=data.mood_poses[emotion];weight=value;}
    return Object.fromEntries(Object.entries(data.poses[selected]||{}).map(([role,steps])=>[role,steps.map(([axis,degrees])=>[axis,degrees*bounded(weight)])]));
  }
  return {
    mappedShapes:targets.length,
    sync(record){rec=record||{};if(rec.gesture||rec.posture&&rec.posture!=='standing')transient=null;},
    event(event){const d=event.data||{};
      if(event.kind==='arm_action')rec={...rec,support_pose:{...rec.support_pose,arm_action:d.arm_action}};
      if(event.kind==='expression')rec={...rec,face:d.face||{}};
      if(event.kind==='transient_pose')transient=d.active?d.pose:null;
      if(event.kind==='say')speech=Math.max(speech,Math.min(12,String(d.text||'').length/15));
      if(event.kind==='gaze')rec={...rec,gaze_yaw_deg:d.gaze_yaw_deg,gaze_pitch_deg:d.gaze_pitch_deg};
    },
    glance(yaw,hold){look={yaw:bounded(yaw,-.62,.62),left:bounded(hold,0,7)};},
    faceAction(action){
      const name=data.aliases?.[action.express]||action.express;
      const shapes=action.shapes||data.emotions[name]||{};
      for(const key of Object.keys(chosen))delete chosen[key];
      for(const [key,value] of Object.entries(shapes))chosen[key]=bounded(value*(action.shapes?1:bounded(action.intensity??.8)));
      hold=bounded(action.hold??1.5,.1,30);
    },
    beginFrame(){for(const [bone,rotation] of before)bone.quaternion.copy(rotation);before.clear();model.position.copy(basePosition);model.quaternion.copy(baseRotation);model.updateWorldMatrix(false,true);},
    update(delta,{moving=false}={}){
      delta=bounded(delta,0,.1);time+=delta;
      const target=expressionTargets(rec.face,data),response=1-Math.exp(-9*delta);
      hold=Math.max(0,hold-delta);
      for(const shape of Object.keys(chosen)){if(hold<=0)chosen[shape]=Math.max(0,chosen[shape]-2.5*delta);target[shape]=Math.max(target[shape]||0,chosen[shape]);}
      if(speech>0){speech-=delta;target.jawOpen=Math.max(target.jawOpen||0,.2+.16*(.5+.5*Math.sin(time*12)));}
      for(const shape of new Set([...Object.keys(target),...Object.keys(current)]))current[shape]=(current[shape]||0)+((target[shape]||0)-(current[shape]||0))*response;
      blinkPhase=(blinkPhase+delta/(5.2-1.8*bounded(rec.face?.emotional_arousal??.15)))%1;
      const blink=blinkPhase<.045?Math.sin(blinkPhase/.045*Math.PI):0;
      for(const {mesh,index,channels} of targets)mesh.morphTargetInfluences[index]=Math.max(...channels.map(c=>Math.max(current[c]||0,c.startsWith('eyeBlink')?blink:0)));
      const pose=blendedPose(),poseResponse=1-Math.exp(-delta/1.2),posture=rec.posture||'standing';
      for(const role of new Set([...Object.keys(pose),...poseCurrent.keys()])){
        const rotation=poseCurrent.get(role)||quaternion();rotation.slerp(poseRotation(pose[role]),poseResponse);poseCurrent.set(role,rotation);
        if(role==='tail_curl'){
          // Coiling stays in the ground plane; a human knee bend must never
          // tip a tail downward through the floor.
          const coil=quaternion().setFromAxisAngle(axes.y,rotation.angleTo(quaternion()));
          for(const bone of tail)deposit(bone,quaternion().slerp(coil,1/tail.length));
        }
        else deposit(resolve(role),rotation,posture!=='standing'&&/^(hip|knee)/.test(role));
      }
      if(moving||rec.gesture||posture!=='standing')transient=null;
      for(const [channel,limit] of Object.entries({head_yaw_deg:6,head_pitch_deg:3.5,torso_yaw_deg:7,torso_pitch_deg:2.5,weight_shift:.24})){
        const target=bounded(transient?.[channel]??0,-limit,limit),value=transientCurrent[channel]||0;
        transientCurrent[channel]=value+(target-value)*(1-Math.exp(-3*delta/.42));
      }
      if(!moving&&!rec.gesture&&posture==='standing'){
        const turn=(role,axis,value,limit)=>deposit(resolve(role),quaternion().setFromAxisAngle(axes[axis],THREE.MathUtils.degToRad(bounded(value,-limit,limit))));
        turn('head','y',transientCurrent.head_yaw_deg,6);turn('head','x',transientCurrent.head_pitch_deg,3.5);
        turn('chest','y',transientCurrent.torso_yaw_deg,7);turn('chest','x',transientCurrent.torso_pitch_deg,2.5);turn('lumbar','z',Number(transientCurrent.weight_shift||0)*10,2.4);
      }
      if(look){look.left-=delta;if(look.left<=0)look=null;}
      const gaze={yaw:look?.yaw??bounded(THREE.MathUtils.degToRad(rec.gaze_yaw_deg||0),-.62,.62),pitch:bounded(THREE.MathUtils.degToRad(rec.gaze_pitch_deg||0),-.78,.78)};
      for(const key of ['yaw','pitch'])gazeCurrent[key]+=(gaze[key]-gazeCurrent[key])*(1-Math.exp(-4*delta));
      deposit(resolve('head'),quaternion().setFromAxisAngle(axes.y,gazeCurrent.yaw).multiply(quaternion().setFromAxisAngle(axes.x,-gazeCurrent.pitch)));
      const arousal=bounded(rec.face?.emotional_arousal??.15),breath=Math.sin(time*Math.PI*2/(4.5-2.1*arousal))*THREE.MathUtils.degToRad(2)*(1+.5*arousal);
      deposit(resolve('chest'),quaternion().setFromAxisAngle(axes.x,breath));
      deposit(resolve('head'),quaternion().setFromAxisAngle(axes.x,-breath));
      if(jaw){save(jaw);jaw.quaternion.copy(rests.get(jaw).local).multiply(quaternion().setFromAxisAngle(new THREE.Vector3(1,0,0),(current.jawOpen||0)*.45));}
      const desiredDrop=legs.length?(posture==='sitting'?.38:posture==='sitting_floor'?.72:0)*height/1.75:0;
      drop+=(desiredDrop-drop)*(1-Math.exp(-2.5*delta));model.position.y=baseY-drop;
      model.updateWorldMatrix(false,true);
      if(posture==='sitting'&&rec.support_pose?.object&&!model.userData.restActionActive){
        const front=new THREE.Vector3(0,0,-1).applyQuaternion(root.getWorldQuaternion(quaternion()));
        aimRest(resolve('lumbar'),resolve('neck')||resolve('head'),new THREE.Vector3(0,1,0).addScaledVector(front,.035));
      }
      if(posture.startsWith('sitting'))attachContact(true);
      // A seated body still has feet. Resolve support from measured limb
      // lengths and the local floor; never push the calves through it.
      if(posture.startsWith('sitting')&&legs.length){
        const rootRotation=root.getWorldQuaternion(quaternion());
        for(const leg of legs){
          const targetLocal=leg.point.clone();
          if(posture==='sitting_floor'){targetLocal.x=-leg.side*.075*height/1.75;targetLocal.z-=.24*height/1.75;}
          else targetLocal.z-=.34*height/1.75;
          const target=root.localToWorld(targetLocal),floor=ground?.(target.x,target.z,root.position.y);
          target.y=(floor??root.getWorldPosition(new THREE.Vector3()).y)+bounded(leg.point.y,.015,height*.12);
          if(Number.isFinite(rec.support_pose?.surface_y_m)){
            const hip=leg.hip.getWorldPosition(new THREE.Vector3()),knee=leg.knee.getWorldPosition(new THREE.Vector3()),foot=leg.foot.getWorldPosition(new THREE.Vector3());
            const thigh=hip.distanceTo(knee),shin=knee.distanceTo(foot),front=new THREE.Vector3(0,0,-1).applyQuaternion(rootRotation);
            target.x=hip.x+front.x*thigh;target.z=hip.z+front.z*thigh;
            target.y=Math.max(target.y,hip.y-shin);
            if(restVariant(rec)==='sit_up'){
              const folded=leg.hip===slots.get('RightUpperLeg'),out=new THREE.Vector3(folded?-.17:.025,0,0).applyQuaternion(rootRotation);
              target.copy(hip).addScaledVector(front,(thigh+shin)*(folded?.37:.91)).addScaledVector(out,height);target.y=rec.support_pose.surface_y_m+height*.065;
            }
          }
          const bend=new THREE.Vector3(posture==='sitting_floor'||restVariant(rec)==='sit_up'?leg.side:0,0,-1).applyQuaternion(rootRotation);
          for(const bone of [leg.hip,leg.knee,leg.foot])save(bone);
          solveLeg(leg.hip,leg.knee,leg.foot,target,rootRotation,bend);
          leg.foot.quaternion.copy(leg.foot.parent.getWorldQuaternion(quaternion()).invert().multiply(rootRotation).multiply(rests.get(leg.foot).frame));
          leg.foot.updateWorldMatrix(false,true);
        }
      }
      recline+=((posture==='lying'?1:0)-recline)*(1-Math.exp(-delta/.45));
      if(recline>1e-5){
        // Rotate the intact body as a unit; keep the ground underneath its
        // lowest skeletal landmark plus a body-scaled soft-tissue clearance.
        if(legs.length)model.quaternion.copy(baseRotation).premultiply(quaternion().setFromAxisAngle(new THREE.Vector3(0,1,0),restRoll(rec)*recline)).premultiply(quaternion().setFromAxisAngle(new THREE.Vector3(1,0,0),recline*Math.PI/2));
        else if(Number.isFinite(rec.support_pose?.surface_y_m)){
          const spine=resolve('lumbar'),head=slots.get('Head');
          if(spine&&head){
            save(spine);const origin=spine.getWorldPosition(new THREE.Vector3()),from=head.getWorldPosition(new THREE.Vector3()).sub(origin).normalize(),to=new THREE.Vector3(0,0,1).applyQuaternion(root.getWorldQuaternion(quaternion()));
            const desired=quaternion().setFromAxisAngle(to,restRoll(rec)).multiply(quaternion().setFromUnitVectors(from,to)).multiply(spine.getWorldQuaternion(quaternion()));
            spine.quaternion.copy(spine.parent.getWorldQuaternion(quaternion()).invert().multiply(desired));
          }
        }else deposit(resolve('lumbar'),quaternion().setFromAxisAngle(new THREE.Vector3(1,0,0),recline*Math.PI/3));
        model.updateWorldMatrix(false,true);
        const landmarks=[...slots.values(),...tail],point=new THREE.Vector3();
        const groundProbes=new Set(['Head','LeftHand','RightHand','LeftFoot','RightFoot'].map(role=>slots.get(role)));
        const rootFloor=root.getWorldPosition(new THREE.Vector3()).y;
        let lift=-Infinity;
        for(const bone of landmarks){bone.getWorldPosition(point);const floor=(groundProbes.has(bone)?ground?.(point.x,point.z,rootFloor):null)??rootFloor;lift=Math.max(lift,floor+height*.05-point.y);}
        if(Number.isFinite(lift)&&legs.length)model.position.y+=lift*recline;
        model.updateWorldMatrix(false,true);
      }
      if(posture==='lying')attachContact(false);
      if(posture==='lying'&&Number.isFinite(rec.support_pose?.surface_y_m)&&legs.length){
        const yaw=root.getWorldQuaternion(quaternion()),variant=restVariant(rec),sideways=['left','right','elbow_left','elbow_right'].includes(variant);
        const front=new THREE.Vector3(0,0,-1).applyQuaternion(yaw),bend=new THREE.Vector3(sideways?(variant.endsWith('left')||variant==='left'?1:-1):0,sideways?0:1,0).applyQuaternion(yaw);
        for(const leg of legs){
          const hip=leg.hip.getWorldPosition(new THREE.Vector3()),knee=leg.knee.getWorldPosition(new THREE.Vector3()),foot=leg.foot.getWorldPosition(new THREE.Vector3()),length=hip.distanceTo(knee)+knee.distanceTo(foot);
          const upperSide=variant.endsWith('left')||variant==='left'?leg.hip===slots.get('RightUpperLeg'):leg.hip===slots.get('LeftUpperLeg');
          const target=hip.clone().addScaledVector(front,length*(sideways?(upperSide?.67:.76):.96));target.y=rec.support_pose.surface_y_m+height*(sideways?.025:.055)+(sideways&&upperSide?height*.065:0);
          for(const bone of [leg.hip,leg.knee,leg.foot])save(bone);
          solveLeg(leg.hip,leg.knee,leg.foot,target,yaw,bend);
          const side=leg.hip===slots.get('LeftUpperLeg')?'Left':'Right',toe=slots.get(side+'Toes');
          if(toe){const toeDirection=toe.getWorldPosition(new THREE.Vector3()).sub(leg.foot.getWorldPosition(new THREE.Vector3())).normalize().lerp(front,variant==='front'?.65:.3);aimRest(leg.foot,toe,toeDirection);}
        }
        attachContact(false);
      }
      if(posture==='lying'&&restVariant(rec).startsWith('elbow')){
        const spine=resolve('lumbar'),crown=slots.get('Head');
        if(spine&&crown){
          save(spine);const origin=spine.getWorldPosition(new THREE.Vector3()),headPoint=crown.getWorldPosition(new THREE.Vector3());
          const from=headPoint.clone().sub(origin).normalize(),to=headPoint.add(new THREE.Vector3(0,height*.08,0)).sub(origin).normalize();
          const desired=new THREE.Quaternion().setFromUnitVectors(from,to).multiply(spine.getWorldQuaternion(quaternion()));
          spine.quaternion.copy(spine.parent.getWorldQuaternion(quaternion()).invert().multiply(desired));spine.updateWorldMatrix(false,true);
        }
        attachContact(false);
        if(spine&&crown&&Number.isFinite(rec.support_pose?.surface_y_m)){
          // Fit torso pitch and roll to the measured arm: wrist over elbow,
          // elbow on mattress, unchanged bone lengths and anchored pelvis.
          const supportSide=['Left','Right'].filter(s=>slots.get(s+'UpperArm')).sort((a,b)=>slots.get(a+'UpperArm').getWorldPosition(new THREE.Vector3()).y-slots.get(b+'UpperArm').getWorldPosition(new THREE.Vector3()).y)[0];
          const supportUpper=slots.get(supportSide+'UpperArm'),supportLower=slots.get(supportSide+'LowerArm'),supportHand=slots.get(supportSide+'Hand');
          if(supportUpper&&supportLower&&supportHand){
            const origin=spine.getWorldPosition(new THREE.Vector3()),long=crown.getWorldPosition(new THREE.Vector3()).sub(origin).normalize(),across=long.clone().cross(new THREE.Vector3(0,1,0)).normalize();
            const headLocal=skinPoints(headSamples).map(p=>spine.worldToLocal(p));
            const u=supportUpper.getWorldPosition(new THREE.Vector3()).distanceTo(supportLower.getWorldPosition(new THREE.Vector3())),l=supportLower.getWorldPosition(new THREE.Vector3()).distanceTo(supportHand.getWorldPosition(new THREE.Vector3()));
            const rotate=(axis,angle)=>{const desired=quaternion().setFromAxisAngle(axis,angle).multiply(spine.getWorldQuaternion(quaternion()));spine.quaternion.copy(spine.parent.getWorldQuaternion(quaternion()).invert().multiply(desired));spine.updateWorldMatrix(false,true);};
            const error=()=>{const box=new THREE.Box3().setFromPoints(headLocal.map(p=>spine.localToWorld(p.clone()))),front=new THREE.Vector3(0,0,-1).applyQuaternion(rests.get(spine).frame.clone().invert()).applyQuaternion(spine.getWorldQuaternion(quaternion()));const wrist=box.getCenter(new THREE.Vector3()).addScaledVector(front,height*.025);wrist.y=box.min.y-height*.018;const elbow=wrist.clone().add(new THREE.Vector3(0,-l,0));return [elbow.y-rec.support_pose.surface_y_m-height*.025,elbow.distanceTo(supportUpper.getWorldPosition(new THREE.Vector3()))-u];};
            if(headLocal.length)for(let pass=0;pass<8;pass++){
              const e=error();if(Math.hypot(...e)<height*.0005)break;
              const base=spine.quaternion.clone(),columns=[];
              for(const axis of [across,long]){rotate(axis,.001);const shifted=error();columns.push(shifted.map((x,i)=>(x-e[i])/.001));spine.quaternion.copy(base);spine.updateWorldMatrix(false,true);}
              const [[a,c],[b,d]]=columns,det=a*d-b*c;if(Math.abs(det)<1e-8)break;
              rotate(across,THREE.MathUtils.clamp((-d*e[0]+b*e[1])/det,-.2,.2));rotate(long,THREE.MathUtils.clamp((c*e[0]-a*e[1])/det,-.2,.2));
            }
          }
          const bodyFront=new THREE.Vector3(0,0,-1).applyQuaternion(rests.get(spine).frame.clone().invert()).applyQuaternion(spine.getWorldQuaternion(quaternion())).normalize();
          const shoulders=['Left','Right'].map(side=>({side,bone:slots.get(side+'UpperArm')})).filter(s=>s.bone);
          shoulders.sort((a,b)=>a.bone.getWorldPosition(new THREE.Vector3()).y-b.bone.getWorldPosition(new THREE.Vector3()).y);
          const supporting=shoulders[0]?.side,headPoints=skinPoints(headSamples),headBox=new THREE.Box3().setFromPoints(headPoints);
          const center=headPoints.length?headBox.getCenter(new THREE.Vector3()):crown.getWorldPosition(new THREE.Vector3());
          const cheek=center.clone().addScaledVector(bodyFront,height*.025);cheek.y=(headPoints.length?headBox.min.y:center.y-height*.06)-height*.018;
          const headUp=crown.getWorldPosition(new THREE.Vector3()).sub(spine.getWorldPosition(new THREE.Vector3())).normalize();
          for(const {side,bone:upper} of shoulders){
            const lower=slots.get(side+'LowerArm'),hand=slots.get(side+'Hand');if(!lower||!hand)continue;
            for(const bone of [upper,lower,hand])save(bone);
            // IK owns the resting chain. Carrying the clip's axial arm twist
            // into a new elbow plane corkscrews the shoulder and sleeve.
            if(side!==supporting)for(const bone of [upper,lower,hand])bone.quaternion.copy(rests.get(bone).local);
            upper.updateWorldMatrix(false,true);
            const support=side===supporting,target=support?cheek.clone():spine.getWorldPosition(new THREE.Vector3()).addScaledVector(bodyFront,height*.12).addScaledVector(headUp,height*.18);
            if(!support)target.y=rec.support_pose.surface_y_m+height*.018;
            if(!support){
              const intent=rec.support_pose.arm_action,offset=intent?.target_offset_m;
              if(Array.isArray(offset)&&offset.length===3&&offset.every(Number.isFinite)){
                const elapsed=Number.isFinite(intent.elapsed_s)?intent.elapsed_s:Date.now()/1000-intent.started_at,phase=elapsed/intent.duration_s;
                if(phase>=0&&phase<1){
                  const gain=Math.sin(Math.PI*phase)**2,goal=root.localToWorld(new THREE.Vector3(offset[0],0,offset[2]));goal.y=rec.support_pose.surface_y_m+offset[1];target.lerp(goal,gain);
                }
              }
              // Keep reach inside a bent-elbow workspace and outside the torso.
              const shoulder=upper.getWorldPosition(new THREE.Vector3()),elbow=lower.getWorldPosition(new THREE.Vector3()),wrist=hand.getWorldPosition(new THREE.Vector3());
              const u=shoulder.distanceTo(elbow),l=elbow.distanceTo(wrist),maximum=Math.sqrt(u*u+l*l+2*u*l*Math.cos(40*Math.PI/180));
              const chest=spine.getWorldPosition(new THREE.Vector3()),frontDistance=target.clone().sub(chest).dot(bodyFront);
              if(frontDistance<height*.1)target.addScaledVector(bodyFront,height*.1-frontDistance);
              const delta=target.clone().sub(shoulder);if(delta.length()>maximum)target.copy(shoulder).add(delta.setLength(maximum));
              target.y=Math.max(target.y,rec.support_pose.surface_y_m+height*.018);
            }
            const elbowTarget=support?target.clone().add(new THREE.Vector3(0,-height,0)):upper.getWorldPosition(new THREE.Vector3()).addScaledVector(bodyFront,height*.12);if(!support)elbowTarget.y=rec.support_pose.surface_y_m+height*.025;
            if(!support)elbowTarget.addScaledVector(headUp,-height*.25).addScaledVector(bodyFront,height*.12);
            const pole=elbowTarget.sub(upper.getWorldPosition(new THREE.Vector3())).normalize();
            solveLeg(upper,lower,hand,target,root.getWorldQuaternion(quaternion()),pole);
            const hinge=armHinges.get(upper);
            if(hinge&&!support){
              const a=upper.getWorldPosition(new THREE.Vector3()),b=lower.getWorldPosition(new THREE.Vector3()),c=hand.getWorldPosition(new THREE.Vector3()),axis=b.clone().sub(a).normalize();
              const desiredNormal=axis.clone().cross(c.clone().sub(b)).normalize(),currentNormal=hinge.clone().applyQuaternion(upper.getWorldQuaternion(quaternion())).normalize();
              const angle=Math.atan2(axis.dot(currentNormal.clone().cross(desiredNormal)),currentNormal.dot(desiredNormal));
              const desired=quaternion().setFromAxisAngle(axis,angle).multiply(upper.getWorldQuaternion(quaternion()));
              upper.quaternion.copy(upper.parent.getWorldQuaternion(quaternion()).invert().multiply(desired));upper.updateWorldMatrix(false,true);
              aimRest(lower,hand,c.sub(b));
            }
            hand.quaternion.copy(rests.get(hand).local);hand.updateWorldMatrix(false,true);
            const middle=slots.get(side+'MiddleProximal');
            if(support){
              if(middle)aimRest(hand,middle,headUp);
              const face=skinPoints(headSamples.filter(([mesh])=>!/hair/i.test(mesh.name)));
              for(let pass=0;pass<2;pass++){
                const wrist=hand.getWorldPosition(new THREE.Vector3());let gap=Infinity,offset=null;
                for(const palm of skinPoints(handSamples[side])){
                  if(palm.distanceTo(wrist)>height*.075)continue;
                  for(const point of face){const distance=point.distanceTo(palm);if(distance<gap){gap=distance;offset=point.clone().sub(palm);}}
                }
                if(!offset||gap<=height*.002)break;
                const orientation=hand.getWorldQuaternion(quaternion());wrist.addScaledVector(offset,1-height*.0015/gap);
                solveLeg(upper,lower,hand,wrist,root.getWorldQuaternion(quaternion()),new THREE.Vector3(0,-1,0));
                hand.quaternion.copy(hand.parent.getWorldQuaternion(quaternion()).invert().multiply(orientation));hand.updateWorldMatrix(false,true);
              }
            }
            else{
              const suffix=side==='Left'?'l':'r',tip=bones.find(b=>boneKey(b.name)==='middle3'+suffix),index=bones.find(b=>boneKey(b.name)==='middle2'+suffix),little=bones.find(b=>boneKey(b.name)==='middle5'+suffix);
              const reach=hand.getWorldPosition(new THREE.Vector3()).sub(lower.getWorldPosition(new THREE.Vector3()));
              if(hand.getWorldPosition(new THREE.Vector3()).y-rec.support_pose.surface_y_m<height*.05)reach.y=0;
              if(reach.lengthSq()<1e-6)reach.copy(headUp).setY(0);
              if(tip&&index&&little){
                aimRest(hand,tip,reach.normalize());
                const origin=hand.getWorldPosition(new THREE.Vector3()),normal=index.getWorldPosition(new THREE.Vector3()).sub(origin).cross(little.getWorldPosition(new THREE.Vector3()).sub(origin)).normalize().multiplyScalar(side==='Left'?1:-1);
                const palmUp=new THREE.Vector3(0,1,0).addScaledVector(reach,-reach.y).normalize();
                const desired=quaternion().setFromUnitVectors(normal,palmUp).multiply(hand.getWorldQuaternion(quaternion()));
                hand.quaternion.copy(hand.parent.getWorldQuaternion(quaternion()).invert().multiply(desired));hand.updateWorldMatrix(false,true);
              }else if(middle)aimRest(hand,middle,reach.normalize());
            }
          }
        }
      }
      if(posture==='lying'&&restVariant(rec)==='front'){
        const head=slots.get('Head');
        for(const side of ['Left','Right']){
          const upper=slots.get(side+'UpperArm'),lower=slots.get(side+'LowerArm'),hand=slots.get(side+'Hand');
          if(!head||!upper||!lower||!hand)continue;
          for(const bone of [upper,lower,hand])save(bone);
          const yaw=root.getWorldQuaternion(quaternion()),out=new THREE.Vector3(side==='Left'?1:-1,0,0).applyQuaternion(yaw),target=head.getWorldPosition(new THREE.Vector3()).addScaledVector(out,height*.12);
          target.y=(rec.support_pose?.surface_y_m??root.position.y)+height*.025;
          solveLeg(upper,lower,hand,target,yaw,out);
        }
      }
      else if(posture.startsWith('sitting'))attachContact(true);
      if(rec.support_pose?.object&&!model.userData.restActionActive&&!rec.gesture){
        const yaw=root.getWorldQuaternion(quaternion()),front=new THREE.Vector3(0,0,-1).applyQuaternion(yaw),hip=pelvis?.getWorldPosition(new THREE.Vector3()),head=slots.get('Head')?.getWorldPosition(new THREE.Vector3()),v=restVariant(rec),surface=rec.support_pose.surface_y_m;
        if(hip&&head)for(const side of ['Left','Right']){
          if(v==='front'||v.startsWith('elbow'))continue;
          const upper=slots.get(side+'UpperArm'),lower=slots.get(side+'LowerArm'),hand=slots.get(side+'Hand');if(!upper||!lower||!hand)continue;
          const lateral=new THREE.Vector3(1,0,0).applyQuaternion(yaw),shoulder=upper.getWorldPosition(new THREE.Vector3());
          const sideSign=posture==='sitting'?Math.sign(shoulder.clone().sub(hip).dot(lateral)):(side==='Left'?1:-1);
          const out=lateral.multiplyScalar(sideSign||1),target=hip.clone();
          let pole=out.clone().addScaledVector(front,.2);
          if(posture==='sitting'){
            const thigh=slots.get(side+'UpperLeg'),knee=slots.get(side+'LowerLeg');
            if(!v.startsWith('sit_edge')&&thigh&&knee)target.copy(thigh.getWorldPosition(new THREE.Vector3())).lerp(knee.getWorldPosition(new THREE.Vector3()),.55);
            else target.addScaledVector(out,height*.16).addScaledVector(front,-height*.025);
            target.y=v.startsWith('sit_edge')?surface+height*.025:Math.max(target.y+height*.025,surface+height*.085);
            if(!v.startsWith('sit_edge')){const top=thighTop(side,target);if(top!==null)target.y=Math.max(target.y,top+height*.018);}
            if(!v.startsWith('sit_edge')){
              const elbow=lower.getWorldPosition(new THREE.Vector3()),wrist=hand.getWorldPosition(new THREE.Vector3()),u=shoulder.distanceTo(elbow),l=elbow.distanceTo(wrist);
              const comfortableReach=Math.sqrt(u*u+l*l+2*u*l*Math.cos(55*Math.PI/180));
              const reach=target.clone().sub(shoulder);if(reach.length()>comfortableReach)target.copy(shoulder).add(reach.setLength(comfortableReach));
            }
          }else if(v==='left'||v==='right'){
            target.copy(head).addScaledVector(front,height*.065);target.y=surface+height*(side===(v==='left'?'Left':'Right')?.055:.1);pole=front.clone();
          }else{
            target.addScaledVector(out,height*(v.startsWith('elbow')?.18:.15)).addScaledVector(front,height*(v.startsWith('elbow')?-.12:.08));target.y=surface+height*.035;
          }
          for(const bone of [upper,lower,hand])save(bone);
          solveLeg(upper,lower,hand,target,yaw,pole);
          hand.quaternion.copy(rests.get(hand).local);hand.updateWorldMatrix(false,true);
          if(posture==='sitting'){
            const suffix=side==='Left'?'l':'r',middle=bones.find(b=>boneKey(b.name)==='middle3'+suffix),index=bones.find(b=>boneKey(b.name)==='middle2'+suffix),little=bones.find(b=>boneKey(b.name)==='middle5'+suffix);
            if(middle&&index&&little){
              aimRest(hand,middle,front);
              const origin=hand.getWorldPosition(new THREE.Vector3()),normal=index.getWorldPosition(new THREE.Vector3()).sub(origin).cross(little.getWorldPosition(new THREE.Vector3()).sub(origin)).normalize().multiplyScalar(side==='Left'?1:-1);
              const desired=quaternion().setFromUnitVectors(normal,new THREE.Vector3(0,1,0)).multiply(hand.getWorldQuaternion(quaternion()));
              hand.quaternion.copy(hand.parent.getWorldQuaternion(quaternion()).invert().multiply(desired));hand.updateWorldMatrix(false,true);
            }
            if(!v.startsWith('sit_edge')&&thighSamples[side].length&&handSamples[side].length){
              const leg=skinPoints(thighSamples[side]);
              for(let pass=0;pass<2;pass++){
                let lift=0;
                for(const palm of skinPoints(handSamples[side]))for(const point of leg)if(Math.hypot(point.x-palm.x,point.z-palm.z)<height*.025)lift=Math.max(lift,point.y+height*.003-palm.y);
                if(lift<=height*.0005)break;
                const orientation=hand.getWorldQuaternion(quaternion()),contact=hand.getWorldPosition(new THREE.Vector3());contact.y+=lift;
                solveLeg(upper,lower,hand,contact,yaw,pole);
                hand.quaternion.copy(hand.parent.getWorldQuaternion(quaternion()).invert().multiply(orientation));hand.updateWorldMatrix(false,true);
              }
            }
          }
        }
      }
      return targets.length>0||poseCurrent.size>0||drop>1e-5||recline>1e-5;
    },
    inspect(){return {face:{...current},posture:rec.posture||'standing',gesture:rec.gesture||'',mappedShapes:targets.length};}
  };
}
