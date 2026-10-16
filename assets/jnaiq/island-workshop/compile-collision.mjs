// Geometry comes from the same constructors as the editor. No renderer or DOM.
import * as THREE from './vendor/three.module.js';
import {makeStructure,disposeStructure} from './structures.mjs?caves=retired';
import {createFlora} from './flora-render.mjs?sumac=2';
import {objectHeight} from './geology.mjs?caves=retired';
import {heightAt} from './terrain.mjs?caves=retired';
import {specimenVariant} from './plants.mjs?sumac=2';
import {sculptGeometry} from './rock-sculpt.mjs';
import {columnGeometry,columnPositions} from './columns.mjs';
import {stepRouteGeometry} from './step-routes.mjs';
export function compileCollision(world){
  const triangles=[];
  const point=new THREE.Vector3(),local=new THREE.Matrix4(),matrix=new THREE.Matrix4();
  function add(root){
    root.updateMatrixWorld(true);
    root.traverse(mesh=>{
      if(!mesh.isMesh)return;
      // Pool water is a volume boundary, never a support surface.
      if(mesh.material.transparent&&!mesh.userData.solid)return;
      const p=mesh.geometry.attributes.position,index=mesh.geometry.index;
      for(let instance=0;instance<(mesh.isInstancedMesh?mesh.count:1);instance++){
        matrix.copy(mesh.matrixWorld);
        if(mesh.isInstancedMesh){mesh.getMatrixAt(instance,local);matrix.multiply(local);}
        for(let i=0;i<(index?index.count:p.count);i+=3){
          const tri=[];for(let k=0;k<3;k++){point.fromBufferAttribute(p,index?index.getX(i+k):i+k).applyMatrix4(matrix);tri.push(...point.toArray().map(v=>Math.round(v*1e5)/1e5));}triangles.push(tri);
        }
      }
    });
  }
  for(const b of world.structures||[]){const g=makeStructure(b);add(g);disposeStructure(g);}
  const base=new THREE.MeshStandardMaterial(),flora=createFlora({rock:base,bark:base});
  for(const r of world.stepRoutes||[]){const geometry=stepRouteGeometry(r);add(new THREE.Mesh(geometry,base));geometry.dispose();}
  for(const o of world.objects){
    if(heightAt(world,o.x,o.z)<=.1)continue;
    const g=new THREE.Group();g.position.set(o.x,objectHeight(world,o),o.z);g.rotation.y=o.rotation;g.scale.setScalar(o.scale);
    for(const p of flora.parts(o.kind,specimenVariant(o.id),'near')){
      // Collision follows plant identity and anatomy, never material sidedness.
      if(!p.solid)continue;
      g.add(new THREE.Mesh(p.geometry,p.material));
    }add(g);
  }
  if(world.rockSculpt?.length)add(new THREE.Mesh(sculptGeometry(world.rockSculpt),base));
  for(const c of world.columns||[])for(const p of columnPositions(c)){
    const m=new THREE.Mesh(columnGeometry(c.style,c.height,c.radius),base);m.position.set(p.x,heightAt(world,p.x,p.z),p.z);m.rotation.y=c.rotation;add(m);
  }
  return {schema:'jnsq-world-collision/2',triangles};
}
if(globalThis.process?.argv[1]?.endsWith('compile-collision.mjs')){
  let input='';for await(const chunk of process.stdin)input+=chunk;
  process.stdout.write(JSON.stringify(compileCollision(JSON.parse(input))));
}
