import * as THREE from './vendor/three.module.js';

// One small, shared linear-data texture: mottling, veins, edge wear, roughness.
// Bake once on the CPU. Mipmaps filter away fine veins on distant specimens.
export function leafSurfacePixels(size=256){
  const data=new Uint8Array(size*size*4);
  const clamp=v=>Math.max(0,Math.min(1,v));
  for(let y=0;y<size;y++)for(let x=0;x<size;x++){
    const u=(x+.5)/size,v=(y+.5)/size,d=Math.abs(u-.5);
    const mottle=.5+.16*Math.sin(u*23+Math.sin(v*17))+.10*Math.sin(v*43+u*31);
    const midrib=Math.exp(-(((u-.5)/.009)**2));
    const branch=Math.abs(Math.sin((v*8-d*2.6+.025*Math.sin(v*19))*Math.PI));
    const veins=Math.max(midrib,Math.exp(-((branch/.07)**2))*(.7-d));
    const edge=clamp((d-.38)/.12)*(.35+.3*Math.sin(v*37+u*11)**2);
    const grain=((Math.imul(x+1,73856093)^Math.imul(y+3,19349663))>>>0)%997/997;
    const i=(y*size+x)*4;
    for(const [channel,value] of [mottle,veins,edge,.5+(grain-.5)*.2].entries())data[i+channel]=Math.round(clamp(value)*255);
  }
  return data;
}
let shared;
export function leafSurfaceTexture(){
  if(!shared){
    shared=new THREE.DataTexture(leafSurfacePixels(),256,256,THREE.RGBAFormat);
    shared.name='Shared leaf surface detail';shared.generateMipmaps=true;
    shared.minFilter=THREE.LinearMipmapLinearFilter;shared.magFilter=THREE.LinearFilter;
    shared.wrapS=shared.wrapT=THREE.ClampToEdgeWrapping;shared.needsUpdate=true;
  }
  return shared;
}
