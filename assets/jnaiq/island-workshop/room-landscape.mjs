// Preview an existing workshop destination using its authored geometry.
import * as THREE from 'three';
import {makeStructure} from './structures.mjs';
import {createFlora} from './flora-render.mjs?surface=3';
import {heightAt} from './terrain.mjs';
import {objectHeight} from './geology.mjs';
import {specimenVariant} from './plants.mjs';
import {sculptGeometry} from './rock-sculpt.mjs';
import {stepRouteGeometry} from './step-routes.mjs';
import {columnGeometry,columnPositions} from './columns.mjs';
import {createVineObject} from './vines.mjs';
export function landscapePreview(world){
  const root=new THREE.Group(),mat=new THREE.MeshStandardMaterial({color:0x819574,roughness:.9});
  const geometry=new THREE.PlaneGeometry(world.size,world.size,128,128);geometry.rotateX(-Math.PI/2);
  const p=geometry.attributes.position;for(let i=0;i<p.count;i++)p.setY(i,world.heights[i]);geometry.computeVertexNormals();root.add(new THREE.Mesh(geometry,mat));
  for(const b of world.structures||[])root.add(makeStructure(b));
  const rock=new THREE.MeshStandardMaterial({color:0x858179}),bark=new THREE.MeshStandardMaterial({color:0x756047}),flora=createFlora({rock,bark});
  for(const o of world.objects||[]){const group=new THREE.Group();group.position.set(o.x,objectHeight(world,o),o.z);group.rotation.y=o.rotation;group.scale.setScalar(o.scale);for(const part of flora.parts(o.kind,specimenVariant(o.id),'near'))group.add(new THREE.Mesh(part.geometry,part.material));root.add(group);}
  if(world.rockSculpt?.length)root.add(new THREE.Mesh(sculptGeometry(world.rockSculpt),rock));
  for(const r of world.stepRoutes||[])root.add(new THREE.Mesh(stepRouteGeometry(r),rock));
  for(const c of world.columns||[])for(const p of columnPositions(c)){const mesh=new THREE.Mesh(columnGeometry(c.style,c.height,c.radius),rock);mesh.position.set(p.x,heightAt(world,p.x,p.z),p.z);mesh.rotation.y=c.rotation;root.add(mesh);}
  for(const vine of world.vines||[])root.add(createVineObject(vine));
  return root;
}
