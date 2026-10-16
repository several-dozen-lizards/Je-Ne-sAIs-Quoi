import * as THREE from './vendor/three.module.js';

const MAX_CONTACTS=1000;
const clamp=(value,min,max)=>Math.max(min,Math.min(max,value));

export function contactOcclusionStrength(quality='balanced',gap=0,span=1){
  const base=quality==='high'?.18:quality==='low'?.08:.13;
  const scale=Math.max(.08,Math.abs(span)*.35);
  return base*Math.exp(-Math.max(0,gap)/scale);
}

function radialTexture(size=32){
  const data=new Uint8Array(size*size*4);
  for(let y=0;y<size;y++)for(let x=0;x<size;x++){
    const dx=(x+.5)/size*2-1,dy=(y+.5)/size*2-1,r=Math.sqrt(dx*dx+dy*dy);
    const alpha=Math.round(255*Math.pow(clamp(1-r,0,1),1.7)),i=(y*size+x)*4;
    data[i]=data[i+1]=data[i+2]=255;data[i+3]=alpha;
  }
  const texture=new THREE.DataTexture(data,size,size,THREE.RGBAFormat);
  texture.needsUpdate=true;texture.colorSpace=THREE.SRGBColorSpace;
  return texture;
}

// One instanced draw gives tagged residents and furniture a restrained contact
// term. It is ambient occlusion, not a second directional shadow.
export function createContactOcclusion(scene){
  const geometry=new THREE.PlaneGeometry(2,2),texture=radialTexture();
  const material=new THREE.MeshBasicMaterial({map:texture,color:0x17201a,transparent:true,opacity:.13,
    depthWrite:false,polygonOffset:true,polygonOffsetFactor:-1,polygonOffsetUnits:-1,toneMapped:false});
  const mesh=new THREE.InstancedMesh(geometry,material,MAX_CONTACTS);
  mesh.name='JNAIQ contact occlusion';mesh.userData.lightingHelper=true;mesh.castShadow=false;mesh.receiveShadow=false;
  mesh.frustumCulled=false;mesh.renderOrder=2;mesh.count=0;scene.add(mesh);
  const local=new THREE.Matrix4(),world=new THREE.Matrix4(),rotation=new THREE.Matrix4().makeRotationX(-Math.PI/2),contactScale=new THREE.Matrix4();
  function update(quality='balanced'){
    let count=0,totalStrength=0;
    scene.updateMatrixWorld();
    scene.traverse(root=>{
      const contact=root.userData?.contactOcclusion;
      if(!contact||!root.visible||count>=MAX_CONTACTS)return;
      const radius=clamp(Number(contact.radius)||0,.04,3),gap=Math.max(0,Number(contact.gap)||0);
      const strength=contactOcclusionStrength(quality,gap,radius*2);
      if(strength<.006)return;
      local.identity().makeTranslation(0,(Number(contact.offsetY)||0)+.012,0).multiply(rotation)
        .multiply(contactScale.makeScale(radius,radius,1));
      world.multiplyMatrices(root.matrixWorld,local);mesh.setMatrixAt(count++,world);totalStrength+=strength;
    });
    mesh.count=count;mesh.instanceMatrix.needsUpdate=true;
    material.opacity=count?totalStrength/count:0;
  }
  function dispose(){scene.remove(mesh);geometry.dispose();material.dispose();texture.dispose();}
  return {mesh,update,dispose};
}
