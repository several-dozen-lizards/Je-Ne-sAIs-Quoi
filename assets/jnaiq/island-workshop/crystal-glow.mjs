import * as THREE from './vendor/three.module.js';
import {CRYSTAL_STYLES,objectHeight} from './geology.mjs?caves=retired';
import {heightAt} from './terrain.mjs?caves=retired';
import {specimenVariant} from './plants.mjs?sumac=2';

// One camera-facing quad per luminous cluster, all in one draw call. No lights,
// render targets, textures, or per-frame CPU updates are needed for the halo.
export function createCrystalGlow(scene,flora){
  const material=new THREE.ShaderMaterial({
    transparent:true,depthWrite:false,depthTest:true,blending:THREE.AdditiveBlending,
    fog:true,toneMapped:false,uniforms:THREE.UniformsUtils.clone(THREE.UniformsLib.fog),
    vertexShader:`
      attribute vec4 glowPosition;
      attribute vec4 glowColor;
      attribute float glowGround;
      varying vec2 haloUv;
      varying vec4 haloColor;
      varying float haloHeight;
      #include <fog_pars_vertex>
      void main(){
        haloUv=position.xy;haloColor=glowColor;
        haloHeight=(glowPosition.y-glowGround)/glowPosition.w+position.x*viewMatrix[1][0]+position.y*viewMatrix[1][1];
        vec4 mvPosition=modelViewMatrix*vec4(glowPosition.xyz,1.);
        mvPosition.xy+=position.xy*glowPosition.w;
        gl_Position=projectionMatrix*mvPosition;
        #include <fog_vertex>
      }`,
    fragmentShader:`
      varying vec2 haloUv;
      varying vec4 haloColor;
      varying float haloHeight;
      #include <fog_pars_fragment>
      void main(){
        float radius=length(haloUv);
        float alpha=exp(-radius*radius*4.5)*(1.-smoothstep(.65,1.,radius))*haloColor.a;
        alpha*=smoothstep(0.,.35,haloHeight);
        #ifdef USE_FOG
          #ifdef FOG_EXP2
            alpha*=exp(-fogDensity*fogDensity*vFogDepth*vFogDepth);
          #else
            alpha*=1.-smoothstep(fogNear,fogFar,vFogDepth);
          #endif
        #endif
        gl_FragColor=vec4(haloColor.rgb,alpha);
        #include <colorspace_fragment>
      }`
  });
  const mesh=new THREE.Mesh(new THREE.InstancedBufferGeometry(),material);
  mesh.name='Crystal glow halos';mesh.renderOrder=1;mesh.visible=false;mesh.raycast=()=>{};scene.add(mesh);
  function rebuild(world){
    const objects=world.objects.filter(o=>o.kind.startsWith('glow_crystal_')&&CRYSTAL_STYLES[o.kind]&&heightAt(world,o.x,o.z)>.1);
    mesh.visible=objects.length>0;
    const geometry=new THREE.InstancedBufferGeometry(),centres=new Float32Array(objects.length*4),colors=new Float32Array(objects.length*4),ground=new Float32Array(objects.length),bounds=new THREE.Box3();
    geometry.setAttribute('position',new THREE.Float32BufferAttribute([-1,-1,0,1,-1,0,1,1,0,-1,1,0],3));geometry.setIndex([0,1,2,0,2,3]);
    objects.forEach((o,i)=>{
      const part=flora.parts(o.kind,specimenVariant(o.id))[0],sphere=part.geometry.boundingSphere;
      const centre=sphere.center.clone().multiplyScalar(o.scale).applyAxisAngle(new THREE.Vector3(0,1,0),o.rotation).add(new THREE.Vector3(o.x,objectHeight(world,o),o.z));
      const radius=sphere.radius*o.scale*1.85,style=CRYSTAL_STYLES[o.kind],color=new THREE.Color(style.emissive);
      centres.set([centre.x,centre.y,centre.z,radius],i*4);colors.set([color.r,color.g,color.b,style.glow*.55],i*4);
      ground[i]=objectHeight(world,o);
      bounds.expandByPoint(centre.clone().addScalar(radius));bounds.expandByPoint(centre.clone().addScalar(-radius));
    });
    geometry.setAttribute('glowPosition',new THREE.InstancedBufferAttribute(centres,4));geometry.setAttribute('glowColor',new THREE.InstancedBufferAttribute(colors,4));geometry.instanceCount=objects.length;
    geometry.setAttribute('glowGround',new THREE.InstancedBufferAttribute(ground,1));
    geometry.boundingBox=bounds;geometry.boundingSphere=objects.length?bounds.getBoundingSphere(new THREE.Sphere()):new THREE.Sphere(new THREE.Vector3(),0);
    mesh.geometry.dispose();mesh.geometry=geometry;
  }
  return {mesh,rebuild,dispose(){scene.remove(mesh);mesh.geometry.dispose();material.dispose();}};
}
