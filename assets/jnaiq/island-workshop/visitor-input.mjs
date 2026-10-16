export function walkingDirection(keys,yaw){
 const forward=Number(keys.has('KeyW'))-Number(keys.has('KeyS'));
 const right=Number(keys.has('KeyD'))-Number(keys.has('KeyA'));
 const length=Math.hypot(forward,right);
 if(!length)return null;
 return {x:(-Math.sin(yaw)*forward+Math.cos(yaw)*right)/length,z:(-Math.cos(yaw)*forward-Math.sin(yaw)*right)/length};
}
// Keep one request in flight. The next collision-checked stride must be sent
// early enough for its RESPONSE to reach the renderer as the current motion
// ends. Half an RTT only gets the request to the host and leaves a visible
// stop-then-jump gap on acknowledgement. RTT plus its observed change makes
// the handoff follow the actual transport rather than a polling timer.
export function createWalkInput({step,motionEnd,motionDuration=()=>0,now=()=>Date.now()/1000,onError=()=>{}}){
 const keys=new Set();let pending=false,blockedDirection=null,roundTrip=0,variation=0,generation=0,suspended=false;
 const clearBlock=()=>{blockedDirection=null;generation++;};
 return {keys,pause(){suspended=true;},resume(){suspended=false;},press(code){if(!keys.has(code)){keys.add(code);clearBlock();}},release(code){if(keys.delete(code))clearBlock();},clear(){keys.clear();clearBlock();},
 async tick(yaw){const direction=walkingDirection(keys,yaw),lead=Math.min(roundTrip+variation,Math.max(0,motionDuration()));
  // A collision blocks that direction, not a held key forever. Looking or
  // strafing away from the obstacle is a new request, even without key-up.
  const sameBlockedDirection=direction&&blockedDirection&&Math.hypot(direction.x-blockedDirection.x,direction.z-blockedDirection.z)<1e-6;
  if(!direction||pending||suspended||sameBlockedDirection||now()<motionEnd()-lead)return;pending=true;const sent=now(),attempt=generation;
  try{const blocked=!!(await step(direction,keys.has('ShiftLeft')||keys.has('ShiftRight')));if(attempt===generation)blockedDirection=blocked?direction:null;}
  catch(error){
   // An uncertain request is not a collision. Wait for a fresh host snapshot
   // before calculating another destination; never replay the failed request.
   suspended=true;onError(error);
  }finally{const sample=Math.max(0,now()-sent);variation=roundTrip?Math.abs(sample-roundTrip):0;roundTrip=sample;pending=false;}
 }};
}
