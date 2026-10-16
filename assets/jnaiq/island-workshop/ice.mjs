import * as THREE from './vendor/three.module.js';
// Solid frozen rivers and ponds; pools remain liquid.
export function iceMaterial(pond=false){
  const m=new THREE.MeshStandardMaterial({color:0xb5d9e3,roughness:.28,metalness:.08,side:THREE.DoubleSide});
  m.onBeforeCompile=s=>{
    s.vertexShader=`varying vec3 icePosition;${pond?'attribute float pondDepth;varying float iceDepth;':''}\n`+s.vertexShader;
    s.vertexShader=s.vertexShader.replace('#include <begin_vertex>',`#include <begin_vertex>\nicePosition=position;${pond?'iceDepth=pondDepth;':''}`);
    s.fragmentShader=`varying vec3 icePosition;${pond?'varying float iceDepth;':''}\n`+s.fragmentShader;
    s.fragmentShader=s.fragmentShader.replace('#include <color_fragment>',`#include <color_fragment>
      ${pond?'if(iceDepth<=0.)discard;':''}
      float seams=abs(sin(icePosition.x*.73+sin(icePosition.z*.41)*2.)*sin(icePosition.z*.91+icePosition.x*.21));
      diffuseColor.rgb*=.70+(1.-smoothstep(.008,.034,seams))*.30;
    `);
  };m.customProgramCacheKey=()=>`ice-${pond}`;return m;
}
