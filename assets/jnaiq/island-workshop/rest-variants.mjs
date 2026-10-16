export const bedPoses={back:'On back',left:'On left side',right:'On right side',front:'Face down',elbow_left:'Propped on left elbow',elbow_right:'Propped on right elbow',sit_up:'Sit up in bed',sit_edge_left:'Sit on left edge',sit_edge_right:'Sit on right edge'};
export const restVariant=record=>record.support_pose?.variant||'back';
export function variantPose(record){
 const v=restVariant(record),left=v.endsWith('left')||v==='left',s=left?1:-1;
 if(v==='sit_up')return {hipL:[['x',-85]],hipR:[['x',-85]],kneeL:[['x',8]],kneeR:[['x',8]],lumbar:[['x',-12]]};
 if(v.startsWith('elbow'))return {lumbar:[['z',s*-4]],head:[['z',s*12]],hipL:[['x',-12]],hipR:[['x',-12]],kneeL:[['x',22]],kneeR:[['x',22]]};
 if(v==='left'||v==='right')return {hipL:[['x',-18]],hipR:[['x',-18]],kneeL:[['x',30]],kneeR:[['x',30]],elbowL:[['x',65]],elbowR:[['x',65]]};
 if(v==='front')return {head:[['y',45]],humL:[['z',-40]],humR:[['z',40]],elbowL:[['x',90]],elbowR:[['x',90]]};
 return {};
}
export function restRoll(record){const v=restVariant(record);return v==='front'?Math.PI:v==='left'||v==='elbow_left'?-Math.PI/2:v==='right'||v==='elbow_right'?Math.PI/2:0;}
