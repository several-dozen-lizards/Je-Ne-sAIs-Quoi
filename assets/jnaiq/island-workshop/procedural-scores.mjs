// SPDX-License-Identifier: Apache-2.0
// Original JNAIQ public motion scores, 2026-10-16. No captured or third-party
// motion data. Angles are authored choreography; stride follows measured limbs
// and canonical room displacement. Names are action choices, never diagnoses.
export const proceduralScores={
 acknowledge:[1.4,{Head:[['x',12,1]]}],
 yes_nod:[1.8,{Head:[['x',16,2]]}],hard_nod:[1.3,{Head:[['x',24,1]],UpperChest:[['x',4,1]]}],
 long_nod:[2.5,{Head:[['x',18,1]]}],sarcastic_nod:[2.2,{Head:[['x',10,1],['z',7,0]]}],
 no_head_shake:[2,{Head:[['y',22,2]]}],annoyed_head_shake:[1.6,{Head:[['y',18,2]],UpperChest:[['z',3,1]]}],
 thoughtful_head_shake:[2.8,{Head:[['y',12,1],['z',6,0]]}],
 neck_stretch:[3.2,{Head:[['z',18,1]],Neck:[['z',6,1]]}],
 look_around:[3.4,{Head:[['y',35,1]],UpperChest:[['y',8,1]]}],
 look_away:[2.6,{Head:[['y',32,0]],UpperChest:[['y',9,0]]}],
 relieved_sigh:[2.8,{UpperChest:[['x',6,1]],Head:[['x',9,1]]}],
 cocky:[2.4,{Head:[['z',10,0]],UpperChest:[['z',5,0]],RightUpperArm:[['z',-15,0]],RightLowerArm:[['x',-40,0]]}],
 dismiss:[2,{RightUpperArm:[['x',-30,0]],RightLowerArm:[['x',-55,0]],RightHand:[['y',28,1]]}],
 happy_gesture:[2.5,{LeftUpperArm:[['z',-50,0]],RightUpperArm:[['z',50,0]],Head:[['x',-8,1]]}],
 angry_gesture:[2.2,{LeftUpperArm:[['x',-22,1]],RightUpperArm:[['x',-22,1]],LeftLowerArm:[['x',-50,0]],RightLowerArm:[['x',-50,0]],UpperChest:[['x',7,0]]}],
 talk_gesture:[3,{RightUpperArm:[['x',-35,0],['z',15,1]],RightLowerArm:[['x',-55,0]],Head:[['x',5,2]]}],
 talk_gesture_alt:[3,{LeftUpperArm:[['x',-35,0],['z',-15,1]],LeftLowerArm:[['x',-55,0]],UpperChest:[['y',5,1]]}],
 seated_point:[2.4,{RightUpperArm:[['x',-75,0]],RightLowerArm:[['x',-10,0]],Head:[['y',-10,0]]}],
 seated_talk:[3,{RightUpperArm:[['x',-30,0]],RightLowerArm:[['x',-65,0]],Head:[['x',6,2]]}],
 seated_laugh:[2.8,{UpperChest:[['x',7,3]],Head:[['x',-10,0]],LeftLowerArm:[['x',-30,0]],RightLowerArm:[['x',-30,0]]}],
 seated_clap:[2.7,{LeftUpperArm:[['x',-45,0],['z',16,3]],RightUpperArm:[['x',-45,0],['z',-16,3]],LeftLowerArm:[['x',-80,0]],RightLowerArm:[['x',-80,0]]}],
};
export const proceduralMotionNames=Object.keys(proceduralScores);
export function proceduralMotion(name){
 const score=proceduralScores[name];if(!score)throw Error('Unknown procedural motion: '+name);
 return {name,duration:score[0],posture:name.startsWith('seated_')?'sitting':'standing',procedural:true};
}
