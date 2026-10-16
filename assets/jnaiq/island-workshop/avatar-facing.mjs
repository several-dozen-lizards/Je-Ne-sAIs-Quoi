import * as THREE from './vendor/three.module.js';
import {avatarRig} from './avatar-rig.mjs';

// Resolve authored anatomical forward, then mount it on the room's -Z heading.
export function alignAvatarFacing(model){
  model.updateWorldMatrix(true,true);
  const bones=[];model.traverse(o=>{if(o.isBone)bones.push(o);});
  const name=b=>b.name.toLowerCase().replace(/_([lr])$/,'.$1');
  const head=avatarRig(model).slots.get('Head');
  const eyes=bones.filter(b=>['eyel','eyer','eye.l','eye.r','left_eye','right_eye'].includes(name(b)));
  const feet=bones.filter(b=>['leftfoot','rightfoot','foot.l','foot.r'].includes(name(b)));
  const toes=bones.filter(b=>['lefttoes','righttoes'].includes(name(b)));
  const average=list=>list.reduce((v,b)=>v.add(b.getWorldPosition(new THREE.Vector3())),new THREE.Vector3()).divideScalar(list.length);
  let direction;
  if(head&&eyes.length)direction=average(eyes).sub(head.getWorldPosition(new THREE.Vector3()));
  else if(feet.length&&toes.length)direction=average(toes).sub(average(feet));
  else return false;
  if(model.parent)direction.applyQuaternion(model.parent.getWorldQuaternion(new THREE.Quaternion()).invert());
  direction.y=0;if(direction.lengthSq()<1e-12)return false;
  model.quaternion.premultiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0,1,0),Math.atan2(direction.x,-direction.z)));
  model.updateWorldMatrix(false,true);
  return true;
}
