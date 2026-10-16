import * as THREE from './vendor/three.module.js';

export function teleporterModel(){
  const group=new THREE.Group();
  const material=new THREE.MeshStandardMaterial({color:0x65ffd4,emissive:0x167b64,emissiveIntensity:1.5});
  const ring=new THREE.Mesh(new THREE.TorusGeometry(.45,.05,12,48),material);
  ring.position.y=.5;group.add(ring);
  return group;
}

export function teleporterRecord(id, x, z){
  return {id,name:'Teleporter',kind:'teleporter',position_m:[x,-z],size_m:1.6,
    rot_deg:0,y_off_m:0,support_surface:'island_ground',support_oid:null,
    description:'Open the destination list here to travel to another teleporter.',
    texture:'neutral',mass_kg:100,affordances:{},capability:'portal',owner:null};
}

export function nearbyTeleporters(snapshot, position){
  return Object.entries(snapshot?.objects||{}).filter(([,o])=>o.capability==='portal'
    && Math.hypot(position.x-o.position_m[0],position.z+o.position_m[1]) <= o.interaction_radius_m
    && (o.interaction_height_m==null || Math.abs(position.y-o.interaction_y_m)<=o.interaction_height_m))
    .map(([id])=>id);
}
