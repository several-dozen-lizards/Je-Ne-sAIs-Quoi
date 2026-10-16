// A single catalogue is also read by the save validator.
import catalogue from './architecture.json' with {type:'json'};
export const ARCHITECTURES=Object.freeze(catalogue);
export const architectureFor=b=>ARCHITECTURES[b.architecture||'plain']||ARCHITECTURES.plain;
export function styleDefaults(id){
  const a=ARCHITECTURES[id];if(!a)throw Error('Unknown architectural style.');
  return {architecture:id,roof:'auto',material:a.material,roofMaterial:a.roofMaterial,trimMaterial:a.trimMaterial,floorMaterial:a.floorMaterial,frames:true};
}
