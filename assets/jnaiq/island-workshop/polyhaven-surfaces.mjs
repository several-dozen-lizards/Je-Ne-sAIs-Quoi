import * as THREE from './vendor/three.module.js';
const cache=new Map();
export function polyhavenSurface(name,invalidate=()=>{},reportError=()=>{}){
  if(cache.has(name)){const pack=cache.get(name);pack.ready.then(invalidate).catch(()=>{});return pack;}
  const pack={},loader=new THREE.TextureLoader(),loads=[];
  for(const role of ['albedo','normal','rough','height']){
    if(role==='height'&&name==='coastal_cliff_02')continue;
    const file=`${name}_${role}.${role==='albedo'?'jpg':'png'}`;
    if(typeof document==='undefined'){
      pack[role]=new THREE.DataTexture(new Uint8Array(role==='normal'?[128,128,255,255]:[160,160,160,255]),1,1);continue;
    }
    loads.push(new Promise((resolve,reject)=>{
      const t=loader.load(new URL('./textures/polyhaven-v1/'+file,import.meta.url).href,()=>{invalidate();resolve();},undefined,e=>{reportError('Could not load Poly Haven material '+name);reject(e);});
      t.wrapS=t.wrapT=THREE.RepeatWrapping;t.anisotropy=4;if(role==='albedo')t.colorSpace=THREE.SRGBColorSpace;pack[role]=t;
    }));
  }
  pack.ready=Promise.all(loads);pack.ready.catch(()=>{});cache.set(name,pack);return pack;
}
