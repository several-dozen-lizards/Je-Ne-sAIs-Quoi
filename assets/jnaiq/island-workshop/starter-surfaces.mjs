import * as THREE from './vendor/three.module.js';

export const STARTER_SIZE=512;
// Approximate relief derived from generated colour, not measured PBR scans.
// Edge blending and wrapped derivatives keep every channel periodic.
export function prepareStarterSurface(source,size,kind){
  const colour=new Uint8Array(size*size*4),normal=new Uint8Array(colour.length),rough=new Uint8Array(colour.length),height=new Float32Array(size*size);
  const edge=v=>{const t=Math.min(1,Math.min(v,size-1-v)/(size*.12));return t*t*(3-2*t);};
  const sample=(x,y,c)=>source[((y%size)*size+x%size)*4+c];
  for(let y=0;y<size;y++)for(let x=0;x<size;x++){
    const wx=edge(x),wy=edge(y),i=(y*size+x)*4;
    for(let c=0;c<3;c++){
      const a=sample(x,y,c)*wx+sample((x+size/2)%size,y,c)*(1-wx);
      const b=sample(x,(y+size/2)%size,c)*wx+sample((x+size/2)%size,(y+size/2)%size,c)*(1-wx);
      colour[i+c]=a*wy+b*(1-wy);
    }
    height[y*size+x]=(colour[i]*.2126+colour[i+1]*.7152+colour[i+2]*.0722)/255;
  }
  // Share identical boundary texels after the broad blend, including corners.
  for(let y=0;y<size;y++)for(let c=0;c<3;c++){const a=y*size*4+c,b=(y*size+size-1)*4+c;colour[a]=colour[b]=Math.round((colour[a]+colour[b])/2);}
  for(let x=0;x<size;x++)for(let c=0;c<3;c++){const a=x*4+c,b=((size-1)*size+x)*4+c;colour[a]=colour[b]=Math.round((colour[a]+colour[b])/2);}
  for(let i=0;i<height.length;i++)height[i]=(colour[i*4]*.2126+colour[i*4+1]*.7152+colour[i*4+2]*.0722)/255;
  const h=(x,y)=>height[((y+size)%size)*size+(x+size)%size];
  const strength=kind==='stone'?size*.018/2:kind==='meadow'?size*.012/1.6:size*.002;
  for(let y=0;y<size;y++)for(let x=0;x<size;x++){
    const i=(y*size+x)*4,value=h(x,y),dx=(h(x+1,y)-h(x-1,y))*strength,dy=(h(x,y+1)-h(x,y-1))*strength,length=Math.hypot(dx,dy,1);
    normal.set([Math.round(127.5-dx/length*127.5),Math.round(127.5+dy/length*127.5),Math.round(127.5+127.5/length),255],i);
    const r=Math.round(255*(kind==='timber'?.78+value*.12:.87+value*.1));rough.set([r,r,r,255],i);
    colour[i+3]=Math.round(value*255);
  }
  return {albedo:colour,normal,rough};
}

const cache=new Map();
export function starterSurface(kind,invalidate=()=>{},reportError=()=>{}){
  if(cache.has(kind)){const pack=cache.get(kind);pack.ready.then(invalidate).catch(()=>{});return pack;}
  const make=(pixel,srgb=false)=>{const t=new THREE.DataTexture(new Uint8Array(pixel),1,1);t.colorSpace=srgb?THREE.SRGBColorSpace:THREE.NoColorSpace;t.wrapS=t.wrapT=THREE.RepeatWrapping;t.minFilter=THREE.LinearMipmapLinearFilter;t.magFilter=THREE.LinearFilter;t.generateMipmaps=true;t.flipY=true;t.needsUpdate=true;return t;};
  const pack={albedo:make(kind==='meadow'?[70,86,43,128]:kind==='stone'?[135,134,128,128]:[136,105,73,128],true),normal:make([128,128,255,255]),rough:make([235,235,235,255])};
  cache.set(kind,pack);
  // Collision compilation and geometry tests construct materials without a DOM.
  // They need the same geometry, but never upload or sample the visual textures.
  if(typeof document==='undefined'){pack.ready=Promise.resolve(pack);return pack;}
  pack.ready=new Promise((resolve,reject)=>{
    new THREE.ImageLoader().load(new URL(`./textures/starter-v1/${kind}-source.png`,import.meta.url).href,image=>{
      try{
        const canvas=document.createElement('canvas');canvas.width=canvas.height=STARTER_SIZE;
        const ctx=canvas.getContext('2d',{willReadFrequently:true});ctx.drawImage(image,0,0,STARTER_SIZE,STARTER_SIZE);
        const pixels=prepareStarterSurface(ctx.getImageData(0,0,STARTER_SIZE,STARTER_SIZE).data,STARTER_SIZE,kind);
        for(const channel of ['albedo','normal','rough']){pack[channel].image={data:pixels[channel],width:STARTER_SIZE,height:STARTER_SIZE};pack[channel].needsUpdate=true;}
        invalidate();resolve(pack);
      }catch(error){reportError(error);reject(error);}
    },undefined,error=>{reportError(error);reject(error);});
  });
  pack.ready.catch(()=>{});return pack;
}
