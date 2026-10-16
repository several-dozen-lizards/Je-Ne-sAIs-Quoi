import * as THREE from './vendor/three.module.js';
import {heightAt} from './terrain.mjs?caves=retired';
import {inPond,pondEdge} from './pond-shape.mjs';
export function pondMaterial(time){
  const m=new THREE.MeshStandardMaterial({color:0x39685c,roughness:.34,metalness:0,transparent:true,depthWrite:false,side:THREE.DoubleSide});
  m.onBeforeCompile=s=>{
    s.uniforms.pondTime=time;s.vertexShader='attribute float pondDepth;varying float basinDepth;varying vec2 pondUV;\n'+s.vertexShader;
    s.vertexShader=s.vertexShader.replace('#include <begin_vertex>','#include <begin_vertex>\nbasinDepth=pondDepth;pondUV=position.xz;');
    s.fragmentShader='uniform float pondTime;varying float basinDepth;varying vec2 pondUV;\n'+s.fragmentShader;
    s.fragmentShader=s.fragmentShader.replace('#include <color_fragment>',`#include <color_fragment>
      diffuseColor.a*=smoothstep(0.,.35,basinDepth)*.88;
      if(diffuseColor.a<.01)discard;
      float wave=sin(pondUV.x*2.1+pondUV.y*1.4+pondTime*.7+sin(pondUV.y*.8))*.004+sin(pondUV.x*-.8+pondUV.y*3.3-pondTime*.52+sin(pondUV.x*.6))*.003;
      diffuseColor.rgb=mix(vec3(.17,.25,.15),vec3(.025,.095,.085),1.-exp(-basinDepth*.65))*(1.+wave*2.);`);
    s.fragmentShader=s.fragmentShader.replace('#include <normal_fragment_maps>',`#include <normal_fragment_maps>
      vec3 dx=dFdx(vViewPosition),dy=dFdy(vViewPosition),rx=cross(dy,normal),ry=cross(normal,dx);
      float det=dot(dx,rx);normal=normalize(abs(det)*normal-sign(det)*(dFdx(wave)*rx+dFdy(wave)*ry));`);
  };m.customProgramCacheKey=()=> 'pond-v1';return m;
}
export function pondMesh(w,f,material){
  const minX=Math.min(...f.points.map(p=>p.x)),maxX=Math.max(...f.points.map(p=>p.x)),minZ=Math.min(...f.points.map(p=>p.z)),maxZ=Math.max(...f.points.map(p=>p.z));
  const nx=Math.ceil((maxX-minX)/.75),nz=Math.ceil((maxZ-minZ)/.75),p=[],d=[],indices=[],level=f.points[0].y;
  for(let j=0;j<=nz;j++)for(let i=0;i<=nx;i++){
    const x=minX+(maxX-minX)*i/nx,z=minZ+(maxZ-minZ)*j/nz;
    p.push(x,level+.045,z);
    d.push(inPond(f.points,x,z)?Math.min(Math.max(0,level-heightAt(w,x,z)),pondEdge(f.points,x,z)):0);
    if(i&&j){const k=j*(nx+1)+i;indices.push(k,k-1,k-nx-1,k-1,k-nx-2,k-nx-1);}
  }
  const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(p,3));g.setAttribute('pondDepth',new THREE.Float32BufferAttribute(d,1));g.setIndex(indices);g.computeVertexNormals();
  const mesh=new THREE.Mesh(g,material);mesh.receiveShadow=true;mesh.renderOrder=3;return mesh;
}
