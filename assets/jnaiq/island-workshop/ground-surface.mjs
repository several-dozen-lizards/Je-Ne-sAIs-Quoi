import * as THREE from './vendor/three.module.js';

// One small, repeatable data map shared by soil detail and instanced grass.
// R: mineral grit, G: rounded pebble relief, B: blade fibres, A: broad variation.
export function groundSurfacePixels(size=256){
  const data=new Uint8Array(size*size*4),tau=Math.PI*2;
  const hash=(x,y)=>{const n=Math.sin(x*127.1+y*311.7)*43758.5453;return n-Math.floor(n);};
  const noise=(u,v,n)=>{const x=u*n,y=v*n,ix=Math.floor(x),iy=Math.floor(y),a=x-ix,b=y-iy,fx=a*a*(3-2*a),fy=b*b*(3-2*b),h=(dx,dy)=>hash((ix+dx)%n,(iy+dy)%n);return (h(0,0)*(1-fx)+h(1,0)*fx)*(1-fy)+(h(0,1)*(1-fx)+h(1,1)*fx)*fy;};
  for(let y=0;y<size;y++)for(let x=0;x<size;x++){
    const u=x/size,v=y/size,px=u*16,py=v*16,ix=Math.floor(px),iy=Math.floor(py);
    let nearest=10;
    for(let dy=-1;dy<=1;dy++)for(let dx=-1;dx<=1;dx++){
      const cx=ix+dx,cy=iy+dy,hx=(cx+16)%16,hy=(cy+16)%16;
      nearest=Math.min(nearest,Math.hypot(px-cx-.18-hash(hx,hy)*.64,py-cy-.18-hash(hx+31,hy+17)*.64));
    }
    const i=(y*size+x)*4;
    data[i]=Math.round(255*(.22+.56*hash(x,y)));
    data[i+1]=Math.round(255*Math.max(0,1-nearest*1.65)**.65);
    data[i+2]=Math.round(255*(.5+.23*Math.cos(u*tau*13+.2*Math.sin(v*tau))+.12*Math.cos(u*tau*29)));
    data[i+3]=Math.round(255*(noise(u,v,8)*.6+noise(u,v,23)*.28+noise(u,v,57)*.12));
  }
  return data;
}
let shared;
export function groundSurfaceTexture(){
  if(!shared){
    shared=new THREE.DataTexture(groundSurfacePixels(),256,256,THREE.RGBAFormat);
    shared.wrapS=shared.wrapT=THREE.RepeatWrapping;shared.generateMipmaps=true;
    shared.minFilter=THREE.LinearMipmapLinearFilter;shared.magFilter=THREE.LinearFilter;
    shared.name='Shared soil and grass detail';shared.needsUpdate=true;
  }
  return shared;
}
