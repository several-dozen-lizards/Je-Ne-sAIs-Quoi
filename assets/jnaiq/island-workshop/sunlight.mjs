import * as THREE from './vendor/three.module.js';
export const cloudLightGLSL=`
uniform float solarTime,solarCover,solarStrength,solarRays,solarWeatherTransmission,solarSkyBrightness,solarSkyNeutral;
uniform vec3 solarDirection,solarColour;
float solarHash(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453);}
float solarNoise(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*(3.-2.*f);return mix(mix(solarHash(i),solarHash(i+vec2(1,0)),f.x),mix(solarHash(i+vec2(0,1)),solarHash(i+vec2(1)),f.x),f.y);}
float solarCloud(vec2 p){
  p=p*.018+vec2(solarTime*.003,solarTime*.0012);
  float n=solarNoise(p)*.65+solarNoise(p*2.03+13.)*.25+solarNoise(p*4.1-7.)*.1;
  return smoothstep(.70-solarCover*.60,.88-solarCover*.60,n)*smoothstep(0.,.15,solarCover);
}
float solarTransmission(vec3 p){
  vec2 projected=p.xz+solarDirection.xz*max(0.,180.-p.y)/max(.06,solarDirection.y);
  return exp(-solarCloud(projected)*mix(1.5,4.,solarCover));
}
vec3 solarScatter(vec3 origin,vec3 ray,float distance){
  if(solarRays<=.001)return vec3(0.);
  float scatter=0.;
  for(int i=0;i<8;i++){
    float t=(float(i)+.5)/8.;vec3 p=origin+ray*distance*t;
    float density=exp(-max(0.,p.y)*.009)*smoothstep(-12.,4.,p.y)*(1.-smoothstep(150.,190.,p.y));
    scatter+=solarTransmission(p)*density;
  }
  float facing=max(0.,dot(ray,solarDirection));
  float phase=.12+.88*pow(facing,6.);
  return solarColour*scatter/8.*(1.-exp(-distance*.003))*phase*solarRays*.7;
}
`;
import {solarProfile} from './atmosphere-profile.mjs';
export {solarProfile} from './atmosphere-profile.mjs';
export function createSunlight(scene){
  const uniforms={airDensity:{value:0},airHeight:{value:80},airSunAmount:{value:0},solarTime:{value:0},solarCover:{value:0},solarStrength:{value:0},solarRays:{value:0},solarWeatherTransmission:{value:1},solarSkyBrightness:{value:1},solarSkyNeutral:{value:0},solarDirection:{value:new THREE.Vector3()},solarColour:{value:new THREE.Color()}};
  const patched=new WeakSet();
  function install(m){
    if(!m?.isMeshStandardMaterial||patched.has(m))return;patched.add(m);
    const previous=m.onBeforeCompile,cache=m.customProgramCacheKey.bind(m),key=cache();
    m.onBeforeCompile=(s,r)=>{
      previous.call(m,s,r);Object.assign(s.uniforms,uniforms);
      s.vertexShader='varying vec3 solarPosition;\n'+s.vertexShader;
      s.vertexShader=s.vertexShader.replace('#include <project_vertex>',`#include <project_vertex>
        vec4 solarLocal=vec4(transformed,1.);
        #ifdef USE_INSTANCING
          solarLocal=instanceMatrix*solarLocal;
        #endif
        solarPosition=(modelMatrix*solarLocal).xyz;`);
      s.fragmentShader='varying vec3 solarPosition;\nuniform float airDensity,airHeight,airSunAmount;\n'+cloudLightGLSL+s.fragmentShader;
      const lights=THREE.ShaderChunk.lights_fragment_begin.replace('getDirectionalLightInfo( directionalLight, directLight );','getDirectionalLightInfo( directionalLight, directLight );\n if(solarStrength>.001)directLight.color *= mix(1.,solarTransmission(solarPosition),solarStrength);');
      s.fragmentShader=s.fragmentShader.replace('#include <lights_fragment_begin>',lights);
      s.fragmentShader=s.fragmentShader.replace('#include <fog_fragment>',`
        #ifdef USE_FOG
          vec3 airRay=solarPosition-cameraPosition;float airDistance=length(airRay);
          float startDensity=exp(-max(cameraPosition.y,-20.)/airHeight);
          float endDensity=exp(-max(solarPosition.y,-20.)/airHeight);
          float difference=log(max(startDensity,1e-6)/max(endDensity,1e-6));
          float meanDensity=abs(difference)<.001?startDensity:(startDensity-endDensity)/difference;
          float airFactor=1.-exp(-airDensity*airDistance*meanDensity);
          vec3 airColour=fogColor+solarColour*airSunAmount*pow(max(0.,dot(normalize(airRay),solarDirection)),6.);
          gl_FragColor.rgb=mix(gl_FragColor.rgb,airColour,clamp(airFactor,0.,1.));
        #endif
      `);
      s.fragmentShader=s.fragmentShader.replace('#include <opaque_fragment>',`vec3 solarView=solarPosition-cameraPosition;
        outgoingLight+=solarScatter(cameraPosition,normalize(solarView),min(length(solarView),500.));
        #include <opaque_fragment>`);
    };
    m.customProgramCacheKey=()=>key+'-cloud-light-height-air-v3';m.needsUpdate=true;
  }
  return {uniforms,update(seconds,light,weather,space,state){
    const profile=solarProfile(light,weather,space);
    uniforms.solarTime.value=seconds;uniforms.solarCover.value=space?0:weather.cover;
    uniforms.solarWeatherTransmission.value=profile.transmission;
    uniforms.solarSkyBrightness.value=profile.skyBrightness;uniforms.solarSkyNeutral.value=profile.skyNeutral;
    uniforms.solarStrength.value=state.cloudShadows===false?0:profile.shadows;
    uniforms.solarRays.value=state.sunRays===false?0:profile.rays;
    uniforms.solarDirection.value.fromArray(light.direction).normalize();uniforms.solarColour.value.setRGB(...profile.colour);
    scene.traverse(o=>{for(const m of Array.isArray(o.material)?o.material:[o.material])install(m);});
  }};
}
