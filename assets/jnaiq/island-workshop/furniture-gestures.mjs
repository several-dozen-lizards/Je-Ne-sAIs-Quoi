export function wheelTransform(object,event,viewportHeight){
  const delta=-event.deltaY*(event.deltaMode===1?16:event.deltaMode===2?viewportHeight:1)/100;
  if(!Number.isFinite(delta)||!delta)return false;
  if(event.ctrlKey||event.metaKey)object.size_m=Math.max(.02,Math.min(6,object.size_m*Math.exp(delta*.1)));
  else if(event.shiftKey)object.y_off_m+=delta*.05;
  else object.rot_deg=(object.rot_deg+delta*5)%360;
  return true;
}
