import * as THREE from './vendor/three.module.js';
import {isSpaceEnvironment,hasAtmosphericWeather,hasOceanSurface} from './environment-lighting.mjs?lava=1';
import {fantasySkyGLSL} from './fantasy-sky.mjs?moonhaze=1';
import {createSpace} from './space.mjs?fantasy=1';
import {createWeather,weatherProfile} from './weather.mjs?spacefx=1';
import {cloudVolumeGLSL} from './cloud-volume.mjs?billows=5';
import {cloudLightGLSL} from './sunlight.mjs?space=1';

import {oceanSurfaceGLSL} from './ocean-surface.mjs?lava=1';
import {normalizedSkyColors} from './sky-colors.mjs';
import {normalizedWater} from './sky-water-options.mjs';

const skyCode=`
uniform float nebulaClouds,meteorAmount;
uniform float environmentCapture;
uniform sampler2D customSky;
uniform float customSkyAmount,customSkyRotation,customSkyBrightness,generatedSkyBrightness;
uniform float skyColorsEnabled;
uniform vec3 skyHorizon,skyZenith,skyNightHorizon,skyNightZenith;
uniform float frozenWater;
uniform float lavaOcean;
${cloudLightGLSL}
uniform vec3 sunDirection,fogColour;uniform float dayAmount,twilight,cloudWorld,spaceMode,cloudCover,stormAmount,fogAmount;
${cloudVolumeGLSL}
float hash21(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453);}
float noise21(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*(3.-2.*f);return mix(mix(hash21(i),hash21(i+vec2(1,0)),f.x),mix(hash21(i+vec2(0,1)),hash21(i+vec2(1)),f.x),f.y);}
float cloudNoise(vec2 p){return noise21(p)*.5+noise21(p*2.03)*.26+noise21(p*4.07)*.14+noise21(p*8.13)*.07+noise21(p*16.3)*.03;}
float directionNoise(vec3 p){return (cloudNoise(p.xy)+cloudNoise(p.yz+17.)+cloudNoise(p.zx-11.))/3.;}
vec3 starHash(vec3 p){return fract(sin(vec3(dot(p,vec3(127.1,311.7,74.7)),dot(p,vec3(269.5,183.3,246.1)),dot(p,vec3(113.5,271.9,124.6))))*43758.5453);}
vec3 starField(vec3 ray,float band,float dust){
  // Jitter in three dimensions, with all eight neighbouring vertices sampled.
  // No longitude seam, cell-centre rows, or clipped stars at cell boundaries.
  vec3 p=ray*220.,base=floor(p),light=vec3(0.);
  float pixel=max(length(dFdx(p)),length(dFdy(p)));
  for(int x=0;x<2;x++)for(int y=0;y<2;y++)for(int z=0;z<2;z++){
    vec3 cell=base+vec3(float(x),float(y),float(z));
    vec3 seed=starHash(cell),extra=starHash(cell+19.43);
    vec3 centre=cell+(seed-.5)*.70;
    float rarity=extra.x;
    float radius=mix(.045,.14,pow(rarity,8.));
    float width=radius*radius+pixel*pixel*.22;
    float distance2=dot(p-centre,p-centre);
    float glow=exp(-distance2/width)*radius*radius/width;
    float density=.30+band*(.20+.35*dust);
    float brightness=.28+pow(rarity,10.)*3.8;
    vec3 tint=mix(vec3(1.,.77,.53),vec3(.66,.80,1.),extra.y);
    light+=tint*glow*brightness*step(extra.z,density);
  }
  return light;
}
${fantasySkyGLSL}
vec3 shootingStars(vec3 ray,float visibility){
  if(meteorAmount<=0.||visibility<=0.)return vec3(0.);
  vec3 result=vec3(0.);
  // Seeded events are independent of frame rate. Intensity controls arrivals;
  // each event has its own location, direction, speed and short-lived trail.
  float phase=solarTime*mix(.025,.16,meteorAmount),event=floor(phase);
  vec3 seed=starHash(vec3(event,18.,71.));
  float elapsed=fract(phase)/mix(.025,.16,meteorAmount)-seed.z*2.;
  if(elapsed<0.||elapsed>1.4)return result;
  vec3 start=normalize(vec3(seed.x*2.-1.,.25+seed.y*.7,seed.z*2.-1.));
  vec3 tangent=normalize(cross(start,vec3(.3,1.,.2)));
  float progress=elapsed*(.13+seed.y*.12);
  vec3 head=normalize(start+tangent*progress);
  float along=dot(ray-head,tangent),across=length((ray-head)-tangent*along);
  float width=max(.00045,fwidth(across));
  float trail=exp(-across*across/(width*width))*exp(min(along,0.)*65.)*step(along,0.)*step(-.09,along);
  float point=exp(-pow(length(ray-head)/max(.001,fwidth(across)),2.));
  float life=smoothstep(0.,.12,elapsed)*(1.-smoothstep(.65,1.4,elapsed));
  return vec3(.62,.78,1.)*(trail*.7+point*2.)*life*visibility;
}
vec3 unscaledSkyColour(vec3 ray){
  if(customSkyAmount>.5){float longitude=atan(ray.z,ray.x)+customSkyRotation;vec2 skyUv=vec2(fract(.5+longitude/6.2831853),clamp(.5-asin(clamp(ray.y,-1.,1.))/3.14159265,0.,1.));return texture2D(customSky,skyUv).rgb*customSkyBrightness;}
  #if JNAIQ_CAVERN
  return cavernSurroundings(cameraPosition,ray);
  #else
  float up=max(ray.y,0.);vec3 sunDir=normalize(sunDirection);
  vec3 daylight=mix(vec3(.27,.42,.61),vec3(.027,.10,.32),pow(up,.45));
  vec3 nightlight=mix(vec3(.026,.012,.065),vec3(.002,.003,.015),pow(up,.5));
  if(skyColorsEnabled>.5){daylight=mix(skyHorizon,skyZenith,pow(up,.45));nightlight=mix(skyNightHorizon,skyNightZenith,pow(up,.5));}
  vec3 colour=mix(nightlight,daylight,dayAmount);
  float toward=pow(max(dot(normalize(vec3(ray.x,.01,ray.z)),normalize(vec3(sunDir.x,.01,sunDir.z))),0.),3.);
  float band=exp(-pow((up-.035)/.105,2.));
  colour=mix(colour,vec3(.45,.015,.065),twilight*band*.72);
  colour+=vec3(1.1,.19,.012)*twilight*band*(.2+toward*.8);
  float luminance=dot(colour,vec3(.2126,.7152,.0722));
  colour=mix(colour,vec3(luminance),solarSkyNeutral)*solarSkyBrightness;
  float sun=max(dot(ray,sunDir),0.);
  float disc=smoothstep(.999989-max(fwidth(sun),.000003),.999989+max(fwidth(sun),.000003),sun);
  colour+=solarColour*(pow(sun,32.)*.09+pow(sun,350.)*.22+disc*12.*(1.-environmentCapture))*dayAmount*solarWeatherTransmission;
  vec3 airColour=colour;
  // Sample the continuous unit direction, never wrapped longitude coordinates.
  float nebulaBand=exp(-pow(dot(ray,normalize(vec3(.3,.8,.5)))/.3,2.));
  float nebula=directionNoise(ray*7.+4.);float starsVisibility=spaceMode>0.?1.:1.-smoothstep(.15,.75,dayAmount);
  vec3 nebulaColour=mix(vec3(.11,.035,.35),vec3(.015,.27,.36),directionNoise(ray*12.));
  nebulaColour=mix(nebulaColour,vec3(.55,.10,.07),smoothstep(.5,.7,directionNoise(ray*8.+30.)));
  if(spaceMode>0.)colour=vec3(.001,.001,.005);
  colour+=nebulaColour*nebulaBand*pow(nebula,2.)*starsVisibility*3.*(spaceMode>0.?nebulaClouds:1.);
  colour+=starField(ray,nebulaBand,nebula)*starsVisibility*(spaceMode>0.?1.:smoothstep(0.,.16,up));
  if(spaceMode>0.){
    colour+=shootingStars(ray,1.);
    colour+=solarColour*disc*12.*(1.-environmentCapture);
    if(spaceMode<1.5){
      vec3 planetDir=normalize(vec3(-.65,-.45,-.75));float facing=dot(ray,planetDir);float disk=smoothstep(.755,.761,facing);
      vec3 axis=normalize(cross(planetDir,vec3(0,1,0))),vertical=cross(axis,planetDir);vec2 q=vec2(dot(ray,axis),dot(ray,vertical))/.65;
      vec3 n=normalize(axis*q.x+vertical*q.y-planetDir*sqrt(max(0.,1.-dot(q,q))));
      float land=directionNoise(n*5.);vec3 planet=mix(vec3(.014,.055,.16),vec3(.10,.24,.11),smoothstep(.48,.54,land));
      float clouds=smoothstep(.53,.65,directionNoise(n*14.));planet=mix(planet,vec3(.72,.79,.84),clouds);
      planet*=.10+.9*max(dot(n,sunDir),0.);
      colour=mix(colour,planet,disk);colour+=vec3(.015,.16,.4)*exp(-abs(facing-.759)*140.);
    }
    return colour;
  }
  vec3 moonDir=-sunDir;float moon=max(dot(ray,moonDir),0.);colour+=vec3(.32,.43,.8)*pow(moon,4000.)*(1.-dayAmount);
  colour=fantasyAtmosphere(ray,colour,airColour);
  colour+=shootingStars(ray,1.-dayAmount);
  vec4 bank=billowClouds(cameraPosition,ray,180.,mix(125.,230.,stormAmount),0.);
  colour=colour*(1.-bank.a)+bank.rgb;
  colour+=solarScatter(cameraPosition,ray,500.)*(1.-bank.a*.75);
  #if JNAIQ_CLOUD_BANK
  if(cloudWorld>.5&&ray.y<0.){
    // Render the bank in the sky's ray direction rather than on an opaque
    // horizontal sheet: gaps reveal blue atmosphere, with no flat white rim.
    vec4 lower=billowClouds(cameraPosition,ray,-130.,100.,1.);
    float aerial=1.-exp(-max(0.,(-30.-cameraPosition.y)/min(ray.y,-.001))*.00045);
    lower.rgb=mix(lower.rgb,colour*lower.a,aerial);
    colour=colour*(1.-lower.a)+lower.rgb;
  }
  #endif
  colour*=.78+.22*dayAmount;
  colour=mix(colour,fogColour,fogAmount*.92);
  return colour;
  #endif
}
vec3 skyColour(vec3 ray){return unscaledSkyColour(ray)*(customSkyAmount>.5?1.:generatedSkyBrightness);}
`;

export function createAtmosphere(scene,rockMaterial,solarUniforms){
  const defines={JNAIQ_CAVERN:0,JNAIQ_CLOUD_BANK:1},materials=[];
  function specialize(environment){
    const cavern=environment.startsWith('cavern')?1:0,bank=environment==='clouds'?1:0;
    if(defines.JNAIQ_CAVERN===cavern&&defines.JNAIQ_CLOUD_BANK===bank)return;
    defines.JNAIQ_CAVERN=cavern;defines.JNAIQ_CLOUD_BANK=bank;
    for(const material of materials)material.needsUpdate=true;
  }
  const space=createSpace(scene,rockMaterial),weather=createWeather(scene);
  const lighting={skyColorsEnabled:{value:0},skyHorizon:{value:new THREE.Color()},skyZenith:{value:new THREE.Color()},skyNightHorizon:{value:new THREE.Color()},skyNightZenith:{value:new THREE.Color()},fantasyMode:{value:0},sunDirection:{value:new THREE.Vector3(-.8,.1,-.6)},fogColour:{value:scene.fog.color},fogAmount:{value:0},dayAmount:{value:1},twilight:{value:0},cloudWorld:{value:1},spaceMode:{value:0},cloudCover:{value:.5},stormAmount:{value:0}};
  Object.assign(lighting,solarUniforms);
  lighting.cloudMarchSteps={value:32};
  lighting.cavernRock={value:rockMaterial.map};
  lighting.cavernLightMode={value:0};
  lighting.environmentCapture={value:0};lighting.nebulaClouds={value:0};lighting.meteorAmount={value:0};
  lighting.frozenWater={value:0};
  lighting.lavaOcean={value:0};
  const emptySky=new THREE.DataTexture(new Uint8Array([0,0,0,255]),1,1);emptySky.needsUpdate=true;
  lighting.reflectedSky={value:emptySky};lighting.reflectedSkyReady={value:0};
  lighting.generatedSkyBrightness={value:1};lighting.customSky={value:emptySky};lighting.customSkyAmount={value:0};lighting.customSkyRotation={value:0};lighting.customSkyBrightness={value:1};
  lighting.waterTint={value:new THREE.Color('#087f91')};lighting.waterGlow={value:.35};lighting.waterRipples={value:1};
  let customSkyData=null,loadedSky=null,skyLoad=0;
  function applyCustomSky(value){const data=value?.data||null;if(data!==customSkyData){customSkyData=data;const token=++skyLoad;lighting.customSkyAmount.value=0;if(loadedSky){loadedSky.dispose();loadedSky=null;lighting.customSky.value=emptySky;}if(data)new THREE.TextureLoader().load(data,texture=>{if(token!==skyLoad){texture.dispose();return;}texture.colorSpace=THREE.SRGBColorSpace;texture.wrapS=THREE.RepeatWrapping;texture.minFilter=THREE.LinearFilter;loadedSky=texture;lighting.customSky.value=texture;lighting.customSkyAmount.value=1;window.dispatchEvent(new Event('island-texture-ready'));},undefined,()=>{if(token===skyLoad)lighting.customSkyAmount.value=0;});}lighting.customSkyRotation.value=(Number(value?.rotation)||0)*Math.PI/180;lighting.customSkyBrightness.value=Number.isFinite(value?.brightness)?value.brightness:1;}
  const sky=new THREE.Mesh(new THREE.SphereGeometry(5000,32,16),new THREE.ShaderMaterial({side:THREE.BackSide,depthWrite:false,
    uniforms:lighting,
    vertexShader:`varying vec3 direction;void main(){direction=position;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}`,
    fragmentShader:`varying vec3 direction;${skyCode}void main(){gl_FragColor=vec4(skyColour(normalize(direction)),1.);#include <tonemapping_fragment>\n#include <colorspace_fragment>}`.replace(';#include',';\n#include')
  }));sky.renderOrder=-10;scene.add(sky);
  const heightTexture=new THREE.DataTexture(new Uint8Array(129*129*4),129,129);heightTexture.minFilter=heightTexture.magFilter=THREE.LinearFilter;heightTexture.needsUpdate=true;
  const uniforms={...lighting,time:{value:0},terrainHeight:{value:heightTexture},islandSize:{value:160}};
  const water=new THREE.Mesh(new THREE.PlaneGeometry(16000,16000),new THREE.ShaderMaterial({uniforms,transparent:true,depthWrite:false,
    vertexShader:`varying vec3 waterPosition;void main(){waterPosition=(modelMatrix*vec4(position,1.)).xyz;gl_Position=projectionMatrix*viewMatrix*vec4(waterPosition,1.);}`,
    fragmentShader:`uniform float time,islandSize;uniform sampler2D terrainHeight;varying vec3 waterPosition;${skyCode}\n${oceanSurfaceGLSL}`
  }));water.rotation.x=-Math.PI/2;water.position.y=-.04;scene.add(water);
  materials.push(sky.material,water.material);for(const material of materials)material.defines=defines;
  return {
    get needsReflectionSky(){return water.visible;},
    setReflectionSky(texture){lighting.reflectedSky.value=texture||emptySky;lighting.reflectedSkyReady.value=texture?1:0;},
    createEnvironmentMaterial(){
      // Water uses this same capture, including authored cavern surroundings.
      const illuminationCode=skyCode;
      const material=new THREE.ShaderMaterial({defines,depthTest:false,depthWrite:false,toneMapped:false,
      uniforms:{...lighting,environmentCapture:{value:1},environmentGround:{value:new THREE.Color()},environmentTint:{value:new THREE.Color(1,1,1)}},
      vertexShader:'varying vec2 probeUv;void main(){probeUv=uv;gl_Position=vec4(position.xy,0.,1.);}',
      fragmentShader:`varying vec2 probeUv;uniform vec3 environmentGround,environmentTint;${illuminationCode}
        void main(){float lon=(probeUv.x-.5)*6.2831853,lat=(probeUv.y-.5)*3.14159265;
          vec3 ray=vec3(cos(lat)*cos(lon),sin(lat),cos(lat)*sin(lon));
          vec3 radiance=skyColour(ray)*environmentTint;
          if(spaceMode<.5&&fantasyMode<2.5)radiance=mix(environmentGround,radiance,smoothstep(-.18,.08,ray.y));
          gl_FragColor=vec4(radiance,1.);}`});materials.push(material);return material;},
    updateTerrain(world){lighting.frozenWater.value=world.frozenWater?1:0;water.material.depthWrite=!!world.frozenWater;const data=heightTexture.image.data;for(let i=0;i<world.heights.length;i++){const h=Math.round((world.heights[i]+12)/77*65535);data[i*4]=h>>8;data[i*4+1]=h&255;data[i*4+3]=255;}heightTexture.needsUpdate=true;uniforms.islandSize.value=world.size;space.updateTerrain(world);weather.updateTerrain(world);},
    update(camera,seconds,light,state){specialize(state.environment);lighting.generatedSkyBrightness.value=Number.isFinite(state.skyBrightness)?Math.max(.1,Math.min(2,state.skyBrightness)):1;applyCustomSky(state.customSky);const skyColors=normalizedSkyColors(state.skyColors);lighting.skyColorsEnabled.value=skyColors.enabled?1:0;for(const [key,uniform] of [["horizon","skyHorizon"],["zenith","skyZenith"],["nightHorizon","skyNightHorizon"],["nightZenith","skyNightZenith"]])lighting[uniform].value.set(skyColors[key]);const waterState=normalizedWater(state.water);lighting.waterTint.value.set(waterState.color);lighting.waterGlow.value=waterState.glow;lighting.waterRipples.value=waterState.ripples;lighting.lavaOcean.value=['lava','cavern-lava'].includes(state.environment)?1:0;lighting.nebulaClouds.value=state.nebulaClouds?1:0;lighting.meteorAmount.value=state.weather==='meteors'?state.strength:0;lighting.cavernLightMode.value=Math.max(0,['natural','bio','amber','cool'].indexOf(state.cavernLighting));const airless=isSpaceEnvironment(state.environment),profile=weatherProfile(hasAtmosphericWeather(state.environment)?state.weather:'clear',state.strength);sky.position.copy(camera.position);uniforms.time.value=seconds;lighting.sunDirection.value.fromArray(light.direction);lighting.dayAmount.value=light.day;lighting.twilight.value=light.twilight;lighting.fantasyMode.value=state.environment==='aurora'?1:state.environment==='alien'?2:state.environment==='cavern-glow'?4:state.environment.startsWith('cavern')?3:0;lighting.spaceMode.value=state.environment==='planet'?1:state.environment==='asteroids'?2:state.environment==='space'?3:0;lighting.cloudCover.value=profile.cover;lighting.stormAmount.value=profile.storm;lighting.fogAmount.value=profile.fog;water.visible=hasOceanSurface(state.environment)&&waterState.surface!=='none';lighting.cloudWorld.value=state.environment==='clouds'?1:0;space.update(state.environment);weather.update(seconds,profile,light);}
  };
}
