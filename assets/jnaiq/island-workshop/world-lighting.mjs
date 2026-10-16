import * as THREE from './vendor/three.module.js';
import {createSunlight,solarProfile} from './sunlight.mjs?realism=1';
import {environmentLighting,hasOceanSurface,hasAtmosphericWeather} from './environment-lighting.mjs?terrain=4';
import {weatherProfile} from './weather.mjs?spacefx=1';
import {createContactOcclusion} from './contact-occlusion.mjs';

const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
export function airProfile(weather,space=false,enclosed=false){
  if(space)return {density:0,height:80};
  if(enclosed)return {density:.00065,height:300};
  return {density:.00055+weather.cover*.00035+weather.storm*.0007+weather.fog*.017,
    height:80*(1-weather.fog)+22*weather.fog};
}

// A stable light-space grid spends texels around the view, rather than around
// the origin of every island. Near objects get finer contact shadows.
export function fitSunShadow(sun,camera,target,worldSize,walking=false,resolution=2048){
  const radius=walking?48:clamp(camera.position.distanceTo(target)*.85,12,Math.max(160,worldSize*.8));
  const focus=walking?camera.position.clone().add(camera.getWorldDirection(new THREE.Vector3()).multiplyScalar(radius*.35)):target.clone();
  const direction=sun.position.clone().sub(sun.target.position).normalize();
  const right=new THREE.Vector3().crossVectors(new THREE.Vector3(0,1,0),direction);
  if(right.lengthSq()<.0001)right.set(1,0,0);else right.normalize();
  const up=new THREE.Vector3().crossVectors(direction,right).normalize();
  const texel=radius*2/resolution;
  // Hold the light volume on a perceptual grid. A shadow refresh now follows
  // accumulated image-space error instead of every centimetre of travel.
  const cell=texel*(walking?4:2),depthCell=Math.max(cell,radius/128);
  focus.addScaledVector(right,Math.round(focus.dot(right)/cell)*cell-focus.dot(right));
  focus.addScaledVector(up,Math.round(focus.dot(up)/cell)*cell-focus.dot(up));
  if(walking)focus.addScaledVector(direction,Math.round(focus.dot(direction)/depthCell)*depthCell-focus.dot(direction));
  const reach=Math.max(worldSize*1.5,200),position=focus.clone().addScaledVector(direction,reach);
  const c=sun.shadow.camera;
  const changed=position.distanceToSquared(sun.position)>texel*texel*.25||Math.abs(c.right-radius)>texel*.25;
  sun.position.copy(position);sun.target.position.copy(focus);sun.target.updateMatrixWorld();
  Object.assign(c,{left:-radius,right:radius,top:radius,bottom:-radius,near:.1,far:reach*2});c.updateProjectionMatrix();
  sun.shadow.normalBias=texel*.55;sun.shadow.bias=-.000015;
  return changed;
}

export function shadowCasterVisible(projectedRadiusPx,nearby,quality='balanced',wasVisible=true){
  if(nearby)return true;
  const edge=quality==='high'?.65:quality==='low'?1.6:1;
  return projectedRadiusPx>=edge*(wasVisible?.78:1.28);
}

export function createShadowCasterBudget(scene,camera,renderer){
  const authored=new WeakMap(),visible=new WeakMap(),center=new THREE.Vector3(),scale=new THREE.Vector3();
  const cameraWorld=new THREE.Vector3(),worldPosition=new THREE.Vector3(),worldRotation=new THREE.Quaternion();
  function update(quality='balanced'){
    const height=Math.max(240,renderer.domElement?.height||renderer.domElement?.clientHeight||720);
    const focal=height/(2*Math.tan(THREE.MathUtils.degToRad(camera.fov||50)/2));let changed=false,kept=0,culled=0;
    scene.updateMatrixWorld();camera.getWorldPosition(cameraWorld);
    scene.traverse(object=>{
      if(!object.isMesh||object.userData?.lightingHelper)return;
      if(!authored.has(object))authored.set(object,!!object.castShadow);
      if(!authored.get(object)){object.castShadow=false;return;}
      let forced=!!object.isSkinnedMesh;
      for(let p=object.parent;p&&!forced;p=p.parent)forced=!!p.userData?.visitorBody;
      if(!forced){
        if(object.geometry&&!object.geometry.boundingSphere)object.geometry.computeBoundingSphere?.();const sphere=object.geometry?.boundingSphere;
        if(!sphere){forced=true;}else{
          center.copy(sphere.center).applyMatrix4(object.matrixWorld);object.matrixWorld.decompose(worldPosition,worldRotation,scale);
          const radius=sphere.radius*Math.max(Math.abs(scale.x),Math.abs(scale.y),Math.abs(scale.z));
          const distance=Math.max(.001,center.distanceTo(cameraWorld)),projected=radius/distance*focal;
          forced=shadowCasterVisible(projected,distance<Math.max(5,radius*10),quality,visible.get(object)!==false);
        }
      }
      if(object.castShadow!==forced){object.castShadow=forced;changed=true;}
      visible.set(object,forced);if(forced)kept++;else culled++;
    });
    renderer.domElement?.dataset&&(renderer.domElement.dataset.shadowCasters=`${kept}/${kept+culled}`);
    return {changed,kept,culled};
  }
  return {update};
}

export function createWorldLighting({scene,renderer,camera,controls,naturalMaterials,invalidate=()=>{}}){
  scene.fog=new THREE.FogExp2(0xb9d5df,.0008);
  const ambient=new THREE.HemisphereLight(0xe2f6ff,0x495d3a,1);
  const sun=new THREE.DirectionalLight(0xffe4b4,3),moon=new THREE.DirectionalLight(0x6d87ef,.48);
  sun.position.set(-70,140,60);sun.castShadow=true;
  scene.add(ambient,sun,sun.target,moon,moon.target);
  renderer.shadowMap.enabled=true;renderer.shadowMap.type=THREE.PCFSoftShadowMap;
  renderer.shadowMap.autoUpdate=false;renderer.shadowMap.needsUpdate=true;
  renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.05;
  const sunlight=createSunlight(scene),contactOcclusion=createContactOcclusion(scene),shadowBudget=createShadowCasterBudget(scene,camera,renderer),tint=new THREE.Color();
  let quality='balanced',disposed=false;
  try{const saved=localStorage.getItem('jnsq.graphics.lighting.v1');if(['low','balanced','high'].includes(saved))quality=saved;}catch{}
  function setQuality(value){
    quality=['low','balanced','high'].includes(value)?value:'balanced';
    const size=quality==='high'?4096:quality==='low'?1024:2048;
    sun.shadow.mapSize.set(size,size);sun.shadow.map?.dispose();sun.shadow.map=null;
    renderer.shadowMap.needsUpdate=true;invalidate();
  }
  setQuality(quality);
  function mountQuality(parent){
    const label=document.createElement('label');label.style.cssText='display:inline-flex;align-items:center;gap:6px;margin:0 10px;font:12px system-ui';
    label.append('Lighting ');const select=document.createElement('select');select.setAttribute('aria-label','Lighting quality');
    for(const [value,text] of [['low','Lightweight'],['balanced','Balanced'],['high','High detail']])select.add(new Option(text,value));
    select.value=quality;select.title='This device only. Balanced adds sky reflections; High detail sharpens shadows. Lightweight uses less graphics power.';select.style.cssText='background:#213d34;color:#e7eee7;border:1px solid #78958a;border-radius:5px;padding:4px';
    select.onchange=()=>{setQuality(select.value);try{localStorage.setItem('jnsq.graphics.lighting.v1',quality);}catch{}};
    label.append(select);parent.append(label);return label;
  }
  function update(light,state,seconds,worldSize=160){
    if(disposed)return;
    const weather=weatherProfile(hasAtmosphericWeather(state.environment)?state.weather:'clear',state.strength);
    const surroundings=environmentLighting(state.environment,state.cavernLighting),space=surroundings.space,enclosed=!!surroundings.enclosed;
    const solar=solarProfile(light,weather,space),brightness=Number.isFinite(state.landBrightness)?clamp(state.landBrightness,0,2):1;
    sunlight.update(seconds,light,weather,space||enclosed,state);
    naturalMaterials.setSpace(!hasOceanSurface(state.environment));
    const direction=enclosed?new THREE.Vector3(-80,140,60).normalize():new THREE.Vector3().fromArray(light.direction);
    // Remember the prior pose before fitting, so sun motion also invalidates shadows.
    const oldPosition=sun.position.clone(),oldTarget=sun.target.position.clone(),oldRadius=sun.shadow.camera.right;
    sun.position.copy(sun.target.position).addScaledVector(direction,180);
    fitSunShadow(sun,camera,controls.target,worldSize,!controls.enabled,sun.shadow.mapSize.x);
    const texel=sun.shadow.camera.right*2/sun.shadow.mapSize.x;
    if(Math.abs(oldRadius-sun.shadow.camera.right)>texel*.25||oldPosition.distanceToSquared(sun.position)>texel*texel*.25||oldTarget.distanceToSquared(sun.target.position)>texel*texel*.25)renderer.shadowMap.needsUpdate=true;
    moon.target.position.copy(sun.target.position);moon.position.copy(moon.target.position).addScaledVector(direction,-180);
    sun.color.setRGB(...(enclosed?surroundings.sky:solar.colour));
    sun.intensity=(enclosed?surroundings.direct:solar.direct*3.6*(surroundings.directScale||1))*brightness;
    moon.intensity=space||enclosed?0:(1-light.day)*.48*brightness;
    renderer.toneMappingExposure=surroundings.exposure;
    ambient.intensity=space||enclosed?surroundings.ambient:(.28+light.day*.90)*solar.ambientScale*surroundings.ambient;
    if(space||enclosed)ambient.color.setRGB(...surroundings.sky);
    else ambient.color.setRGB(.20,.26,.64).lerp(new THREE.Color(...(surroundings.sky||solar.ambientColour)),light.day).lerp(new THREE.Color(.45,.21,.60),light.twilight*.5*solar.sunsetVisibility);
    ambient.groundColor.setRGB(...surroundings.ground);if(!space&&!enclosed)ambient.groundColor.lerp(new THREE.Color(.06,.045,.1),1-light.day);
    tint.set(/^#[0-9a-f]{6}$/i.test(state.lightingColor)?state.lightingColor:'#ffffff');
    ambient.intensity=ambient.intensity*brightness+Math.max(0,brightness-1)*3;
    sun.color.multiply(tint);moon.color.set(0x6d87ef).multiply(tint);
    ambient.color.lerp(new THREE.Color(1,1,1),Math.max(0,brightness-1)).multiply(tint);ambient.groundColor.multiply(tint);
    // PMREM supplies material reflections, not diffuse irradiance for matte
    // surfaces. Keep the hemisphere fill continuous when the asynchronous sky
    // probe arrives so terrain and structures do not visibly switch darker.
    const fill=ambient.intensity;
    const applySky=()=>{ambient.intensity=fill;};
    applySky();
    scene.environmentIntensity=brightness*(surroundings.reflectionScale||1);
    scene.fog.color.setRGB(.025,.018,.065).lerp(new THREE.Color(.30,.43,.61).lerp(new THREE.Color(.40,.44,.49),solar.skyNeutral).multiplyScalar(solar.skyBrightness),light.day).lerp(new THREE.Color(.46,.14,.19),light.twilight*.7*solar.sunsetVisibility);
    if(enclosed)scene.fog.color.setRGB(.022,.055,.065);
    const air=airProfile(weather,space,enclosed);scene.fog.density=air.density;
    sunlight.uniforms.airDensity.value=air.density;sunlight.uniforms.airHeight.value=air.height;
    sunlight.uniforms.airSunAmount.value=space||enclosed?0:solar.direct*.18;
    contactOcclusion.update(quality);
    if(renderer.shadowMap.needsUpdate)shadowBudget.update(quality);
    return {quality,enclosed,ground:ambient.groundColor,tint,brightness,applySky};
  }
  function dispose(){if(disposed)return;disposed=true;contactOcclusion.dispose();sun.shadow.dispose();scene.remove(ambient,sun,sun.target,moon,moon.target);}
  return {sunlight,sun,ambient,contactOcclusion,shadowBudget,update,setQuality,mountQuality,dispose,get quality(){return quality;}};
}
