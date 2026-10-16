import {leafSurfaceTexture} from './leaf-surface.mjs';
// Shared material detail without changing collision geometry or specimen shape.
export function naturalScenerySurface(material,foliage=false){
  const previous=material.onBeforeCompile,key=material.customProgramCacheKey();
  material.onBeforeCompile=function(s,r){
    previous.call(this,s,r);
    if(foliage)s.uniforms.leafSurface={value:leafSurfaceTexture()};
    s.vertexShader=s.vertexShader.replace('#include <common>',`#include <common>
      varying vec3 natureLocal;varying vec3 natureAnchor;${foliage?'varying vec2 natureLeafUV;':''}`);
    s.vertexShader=s.vertexShader.replace('#include <begin_vertex>',`#include <begin_vertex>
      natureLocal=position;${foliage?'natureLeafUV=uv;':''}
      vec4 natureOrigin=vec4(0.,0.,0.,1.);
      #ifdef USE_INSTANCING
      natureOrigin=instanceMatrix*natureOrigin;
      #endif
      natureAnchor=(modelMatrix*natureOrigin).xyz;`);
    s.fragmentShader=s.fragmentShader.replace('#include <common>',`#include <common>
      varying vec3 natureLocal;varying vec3 natureAnchor;${foliage?'varying vec2 natureLeafUV;':''}
      ${foliage?'uniform sampler2D leafSurface;':''}
      float natureNoise(vec3 p){return sin(p.x*2.3+sin(p.z*1.7))*sin(p.y*3.1+p.z*.8);}`);
    s.fragmentShader=s.fragmentShader.replace('#include <metalnessmap_fragment>',`#include <metalnessmap_fragment>
      float grain=${foliage?'0.':'natureNoise(natureLocal*8.)'};
      float specimen=.94+.07*sin(dot(natureAnchor.xz,vec2(.73,1.31)));
      float basal=(1.-smoothstep(-.06,.65,natureLocal.y))*(.65+.35*natureNoise(natureLocal*2.));
      float luminance=dot(diffuseColor.rgb,vec3(.2126,.7152,.0722));
      diffuseColor.rgb=mix(diffuseColor.rgb,vec3(luminance),${foliage?'.13':'.04'})*specimen*(1.+grain*${foliage?'.055':'.09'});
      diffuseColor.rgb*=mix(vec3(1.),vec3(.48,.44,.34),basal*.48);
      roughnessFactor=clamp(roughnessFactor+grain*.035,.25,1.);`);
    if(foliage){
      s.fragmentShader=s.fragmentShader.replace('#include <normal_fragment_maps>',`#include <normal_fragment_maps>
        float leafMask=1.-step(-.5,natureLeafUV.y);
        vec2 leafUV=vec2(natureLeafUV.x,-natureLeafUV.y-1.);
        vec4 leafDetail=texture2D(leafSurface,leafUV);
        float leafResolution=1.-smoothstep(.025,.10,max(length(dFdx(leafUV)),length(dFdy(leafUV))));
        diffuseColor.rgb*=mix(vec3(1.),vec3(.84+leafDetail.r*.30),leafMask);
        diffuseColor.rgb*=mix(vec3(1.),vec3(1.13,1.06,.87),leafMask*leafDetail.g*.5);
        diffuseColor.rgb*=mix(vec3(1.),vec3(.94,.91,.76),leafMask*leafDetail.b*.22);
        roughnessFactor=clamp(roughnessFactor+leafMask*(-.10+leafDetail.a*.06),.25,1.);
        float leafRelief=leafMask*leafResolution*(leafDetail.g*.0003+leafDetail.r*.00012);
        vec3 leafX=dFdx(-vViewPosition),leafY=dFdy(-vViewPosition);
        vec3 leafRX=cross(leafY,normal),leafRY=cross(normal,leafX);
        float leafDet=dot(leafX,leafRX);
        normal=normalize(max(abs(leafDet),1e-8)*normal-sign(leafDet)*(dFdx(leafRelief)*leafRX+dFdy(leafRelief)*leafRY));
      `);
      s.fragmentShader=s.fragmentShader.replace('#include <lights_fragment_end>',`#include <lights_fragment_end>
      // Thin foliage transmits some directional light through its reverse side.
      #if NUM_DIR_LIGHTS > 0
      for(int leafLight=0;leafLight<NUM_DIR_LIGHTS;leafLight++){
        float transmission=pow(max(0.,dot(-normal,directionalLights[leafLight].direction)),2.);
        reflectedLight.directDiffuse+=diffuseColor.rgb*directionalLights[leafLight].color*transmission*.075;
      }
      #endif`);
    }
  };
  material.customProgramCacheKey=()=>key+'-natural-leaf-surface-v2-'+foliage;
}
