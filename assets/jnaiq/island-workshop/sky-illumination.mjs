import * as THREE from './vendor/three.module.js';

// Refresh on a visible change in radiance, not on a timer. Cloud drift itself
// stays in the sky and direct-light shader; tiny changes do not rebake the probe.
export function radianceChanged(previous,next){
  if(!previous||previous.length!==next.length)return true;
  return next.some((v,i)=>typeof v==='number'?Math.abs(v-previous[i])>.025:v!==previous[i]);
}

export function createSkyIllumination(renderer,scene,atmosphere,invalidate=()=>{}){
  const probeScene=new THREE.Scene(),camera=new THREE.OrthographicCamera(-1,1,1,-1,0,1);
  const material=atmosphere.createEnvironmentMaterial();
  const quad=new THREE.Mesh(new THREE.PlaneGeometry(2,2),material);quad.frustumCulled=false;probeScene.add(quad);
  let pmrem=null;
  let source=null,filtered=null,signature=null,disposed=false,ready=false;
  // KHR_parallel_shader_compile lets the ordinary scene appear while the
  // reflection variant compiles. Do not stall its first frame on this extra shader.
  let preparation=null;
  const prepare=()=>preparation||(preparation=renderer.compileAsync(probeScene,camera).then(()=>{ready=true;if(!disposed)invalidate();}));
  function reset(){signature=null;ready=false;preparation=null;atmosphere.setReflectionSky?.(null);}
  renderer.domElement.addEventListener('webglcontextrestored',reset);
  return {
    get preparation(){return prepare();},
    update(light,state,rig){
      if(disposed)return;
      if((rig.quality==='low'||rig.enclosed)&&!atmosphere.needsReflectionSky){scene.environment=null;signature=null;renderer.domElement.dataset.skyIllumination='fill';return;}
      if(!ready){prepare();return;}
      const u=material.uniforms;
      const next=[rig.quality,state.environment,state.weather,state.strength,...light.direction,
        light.day,light.twilight,u.customSky.value?.uuid,u.customSkyAmount.value,
        u.customSkyRotation.value,u.customSkyBrightness.value,u.generatedSkyBrightness.value,state.nebulaClouds,
        u.skyColorsEnabled.value,...u.skyHorizon.value.toArray(),...u.skyZenith.value.toArray(),...u.skyNightHorizon.value.toArray(),...u.skyNightZenith.value.toArray(),
        rig.tint.r,rig.tint.g,rig.tint.b,rig.ground.r,rig.ground.g,rig.ground.b];
      if(!radianceChanged(signature,next)){scene.environment=rig.quality==='low'||rig.enclosed?null:filtered?.texture||null;return;}
      const width=rig.quality==='high'?1024:rig.quality==='low'?256:512;
      if(!source||source.width!==width){source?.dispose();source=new THREE.WebGLRenderTarget(width,width/2,{type:THREE.HalfFloatType,depthBuffer:false});source.texture.mapping=THREE.EquirectangularReflectionMapping;}
      u.environmentGround.value.copy(rig.ground).multiplyScalar(.3+light.day*.4);
      u.environmentTint.value.copy(rig.tint);
      const target=renderer.getRenderTarget(),tone=renderer.toneMapping,xr=renderer.xr.enabled;
      const autoShadow=renderer.shadowMap.autoUpdate,dirtyShadow=renderer.shadowMap.needsUpdate;
      try{
        renderer.xr.enabled=false;renderer.toneMapping=THREE.NoToneMapping;
        renderer.shadowMap.autoUpdate=false;renderer.shadowMap.needsUpdate=false;
        renderer.setRenderTarget(source);renderer.render(probeScene,camera);
        atmosphere.setReflectionSky(source.texture);
        if(rig.quality==='low'||rig.enclosed){scene.environment=null;signature=next;renderer.domElement.dataset.skyIllumination='fill';return;}
        // Same-sized targets are reused; a quality change gets a matching allocation.
        if(filtered&&signature?.[0]!==rig.quality){filtered.dispose();filtered=null;}
        pmrem ||= new THREE.PMREMGenerator(renderer);
        filtered=pmrem.fromEquirectangular(source.texture,filtered);
        scene.environment=filtered.texture;signature=next;renderer.domElement.dataset.skyIllumination='ready';
      }finally{
        renderer.setRenderTarget(target);renderer.toneMapping=tone;renderer.xr.enabled=xr;
        renderer.shadowMap.autoUpdate=autoShadow;renderer.shadowMap.needsUpdate=dirtyShadow;
      }
    },
    dispose(){if(disposed)return;disposed=true;renderer.domElement.removeEventListener('webglcontextrestored',reset);scene.environment=null;source?.dispose();filtered?.dispose();pmrem?.dispose();quad.geometry.dispose();material.dispose();}
  };
}
