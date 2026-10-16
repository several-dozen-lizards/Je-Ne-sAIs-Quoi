// GLTFLoader removes punctuation from node names. Resolve anatomical roles
// across the resident, MakeHuman studio, and humanoid import naming schemes.
export const boneKey=name=>String(name).toLowerCase().replace(/[^a-z0-9]/g,'');

const aliases={
  Hips:['Coccyx-pelvis','root','mixamorigHips'],
  Spine:['Lumbar','spine03','mixamorigSpine'],
  Chest:['spine02','mixamorigSpine1'],
  UpperChest:['Thoraic','spine01','mixamorigSpine2'],
  Neck:['CervicalV','neck01','mixamorigNeck'],
  Head:['Skull','mixamorigHead'],
};
for(const side of ['L','R']){
  const prefix=side==='L'?'Left':'Right';
  for(const [role,native,studio,mixamo] of [
    ['Shoulder','shoulder','clavicle','Shoulder'],
    ['UpperArm','Humerus','upperarm01','Arm'],
    ['LowerArm','Ulna-radius','lowerarm01','ForeArm'],
    ['Hand','carpals','wrist','Hand'],
    ['UpperLeg','Femur','upperleg01','UpLeg'],
    ['LowerLeg','Fibula-tibia','lowerleg01','Leg'],
    ['Foot','foot','foot','Foot'],
    ['Toes','2ndmetatarsal','toe1-1','ToeBase'],
  ])aliases[prefix+role]=[native+'.'+side,studio+'.'+side,'mixamorig'+prefix+mixamo];
  // Palm anchors inform arm roll; native finger articulation stays authored.
  for(const [digit,finger] of [[2,'Index'],[3,'Middle'],[5,'Little']])
    aliases[prefix+finger+'Proximal']=['metacarpal'+digit+'.'+side,'finger'+digit+'-1.'+side,'mixamorig'+prefix+'Hand'+(digit===5?'Pinky':finger)+'1'];
}
const roles=new Map(Object.entries(aliases).flatMap(([role,names])=>
  [role,...names].map(name=>[boneKey(name),role])));

export function avatarRig(model){
  const bones=[],slots=new Map();
  model.traverse(bone=>{if(bone.isBone){bones.push(bone);const role=roles.get(boneKey(bone.name));if(role&&!slots.has(role))slots.set(role,bone);}});
  return {bones,slots};
}
