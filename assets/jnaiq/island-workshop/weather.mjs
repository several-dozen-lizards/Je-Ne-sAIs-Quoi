import * as THREE from './vendor/three.module.js';
import {random,heightAt,insideStructure} from './terrain.mjs?caves=retired';
import {weatherProfile} from './atmosphere-profile.mjs';
export {weatherProfile} from './atmosphere-profile.mjs';
export function createWeather(scene){
  const count=6500,rng=random(86531),positions=new Float32Array(count*3),floor=new Float32Array(count);
  for(let i=0;i<count;i++){positions[i*3]=rng()-.5;positions[i*3+1]=rng();positions[i*3+2]=rng()-.5;}
  const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.BufferAttribute(positions,3));geometry.setAttribute('floorHeight',new THREE.BufferAttribute(floor,1));
  const uniforms={time:{value:0},span:{value:160},snow:{value:0},amount:{value:.65},day:{value:1}};
  const material=new THREE.ShaderMaterial({uniforms,transparent:true,depthWrite:false,
    vertexShader:`attribute float floorHeight;uniform float time,span,snow,amount;varying float visibleDrop;void main(){vec3 p=position;p.xz*=span;float speed=mix(26.,3.5,snow);p.y=80.-mod(position.y*100.+time*speed,100.);p.x+=sin(time*.7+position.z*43.)*snow*1.5;visibleDrop=step(floorHeight+.1,p.y)*step(position.y,amount);vec4 mv=modelViewMatrix*vec4(p,1.);gl_Position=projectionMatrix*mv;gl_PointSize=clamp(mix(10.,7.,snow)*170./max(10.,-mv.z),2.,20.);}`,
    fragmentShader:`uniform float snow,day;varying float visibleDrop;void main(){vec2 p=gl_PointCoord-.5;float flake=1.-smoothstep(.12,.5,length(p));float rain=(1.-smoothstep(.035,.11,abs(p.x)))*(1.-smoothstep(.2,.5,abs(p.y)));float alpha=mix(rain,flake,snow)*visibleDrop*mix(.22,.65,snow);if(alpha<.01)discard;gl_FragColor=vec4(mix(vec3(.40,.58,.8),vec3(.9,.95,1.),day),alpha);#include <tonemapping_fragment>\n#include <colorspace_fragment>}`.replace(';#include',';\n#include')
  });
  const points=new THREE.Points(geometry,material);points.frustumCulled=false;points.renderOrder=3;scene.add(points);
  return {updateTerrain(w){uniforms.span.value=w.size*1.2;for(let i=0;i<count;i++){const x=positions[i*3]*uniforms.span.value,z=positions[i*3+2]*uniforms.span.value;let h=heightAt(w,x,z);for(const b of w.structures||[])if(insideStructure(b,x,z))h=Math.max(h,b.y+b.floors*3.2+(b.roof==='auto'?Math.min(b.width,b.depth)*.28:0));floor[i]=h;}geometry.attributes.floorHeight.needsUpdate=true;},update(seconds,profile,light){points.visible=profile.precipitation>0;uniforms.time.value=seconds;uniforms.amount.value=profile.precipitation;uniforms.snow.value=profile.snow?1:0;uniforms.day.value=light.day;}};
}
