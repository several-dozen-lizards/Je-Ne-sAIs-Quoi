import * as THREE from './vendor/three.module.js';

export function avatarHeightSetting(settings,room,name){
  const key=name.toLowerCase();
  return settings.rooms?.[room]?.avatar_overrides?.[key]?.size_m
    ?? settings.avatar_overrides?.[key]?.size_m;
}

// Fit the detached, complete avatar uniformly. Its optical anchor is measured
// after mounting, so the first-person view follows the same body proportions.
export function fitAvatarHeight(model,height){
  model.updateMatrixWorld(true);
  const bounds=new THREE.Box3().setFromObject(model),nativeHeight=bounds.max.y-bounds.min.y;
  if(!Number.isFinite(nativeHeight)||nativeHeight<=0)return null;
  if(Number.isFinite(height)&&height>=.3&&height<=3){
    model.scale.multiplyScalar(height/nativeHeight);
    model.updateMatrixWorld(true);
    bounds.setFromObject(model);
  }
  model.position.y-=bounds.min.y;
  model.updateMatrixWorld(true);
  return {nativeHeight,height:bounds.max.y-bounds.min.y};
}
