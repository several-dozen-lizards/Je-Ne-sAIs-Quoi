import * as THREE from './vendor/three.module.js';

// The visitor camera follows authored anatomy in body-local coordinates. Keep
// this separate from the World Builder's free-roaming first-person controls.
const anatomy=new WeakMap();
export function eyeAnchor(model,root){
  let anchors=anatomy.get(model);
  if(!anchors){
    const eyes=[];
    let head=null;
    model.traverse(node=>{
    if(!node.isBone)return;
    const name=node.name.toLowerCase().replace(/_([lr])$/,'.$1');
    if(['eyel','eyer','eye.l','eye.r','left_eye','right_eye','lefteye','righteye'].includes(name))eyes.push(node);
    if(name==='head')head=node;
    });
    anchors=eyes.length?eyes:head?[head]:[];
    // Empty/unrigged models may still be loading; keep their fallback live.
    if(anchors.length)anatomy.set(model,anchors);
  }
  const point=new THREE.Vector3();
  if(anchors.length){
    // getWorldPosition updates the bone's ancestry, not every mesh and bone.
    const position=new THREE.Vector3();
    for(const anchor of anchors)point.add(anchor.getWorldPosition(position));
    point.divideScalar(anchors.length);
  }else{
    model.updateWorldMatrix(true,true);
    const bounds=new THREE.Box3().setFromObject(model);
    if(bounds.isEmpty())return new THREE.Vector3(0,1.55,0);
    bounds.getCenter(point);
    point.y=bounds.min.y+(bounds.max.y-bounds.min.y)*.93;
  }
  return root.worldToLocal(point);
}
