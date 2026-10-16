export const DEFAULT_WATER={surface:'visible',color:'#087f91',glow:.35,ripples:1};

export function normalizedWater(value={}){
  return {
    surface:value?.surface==='none'?'none':'visible',
    color:/^#[0-9a-f]{6}$/i.test(value?.color)?value.color:'#087f91',
    glow:Number.isFinite(value?.glow)?Math.max(0,Math.min(2,value.glow)):.35,
    ripples:Number.isFinite(value?.ripples)?Math.max(0,Math.min(2,value.ripples)):1,
  };
}

export function validateCustomSky(value){
  if(value==null)return null;
  if(!value||typeof value.name!=='string'||value.name.length<1||value.name.length>80||
      typeof value.data!=='string'||value.data.length>1200000||
      !/^data:image\/jpeg;base64,[A-Za-z0-9+/]+={0,2}$/.test(value.data)||
      !Number.isInteger(value.width)||value.width<512||value.width>4096||
      !Number.isInteger(value.height)||value.height*2!==value.width||
      !Number.isFinite(value.rotation)||value.rotation< -180||value.rotation>180||
      !Number.isFinite(value.brightness)||value.brightness<.1||value.brightness>2){
    throw Error('Invalid custom sky panorama.');
  }
  return value;
}

function imageFromFile(file){
  return new Promise((resolve,reject)=>{
    const image=new Image(),url=URL.createObjectURL(file);
    image.onload=()=>{URL.revokeObjectURL(url);resolve(image);};
    image.onerror=()=>{URL.revokeObjectURL(url);reject(Error('That sky image could not be read.'));};
    image.src=url;
  });
}

export async function prepareSkyPanorama(file){
  if(!file||file.size>12000000)throw Error('Choose a sky image smaller than 12 MB.');
  const image=await imageFromFile(file),ratio=image.naturalWidth/image.naturalHeight;
  if(image.naturalWidth<512||image.naturalHeight<256||Math.abs(ratio-2)>.04){
    throw Error('Choose a 2:1 equirectangular panorama, such as 2048 x 1024.');
  }
  const width=Math.min(4096,image.naturalWidth-image.naturalWidth%2),height=width/2;
  const canvas=document.createElement('canvas');canvas.width=width;canvas.height=height;
  canvas.getContext('2d',{alpha:false}).drawImage(image,0,0,width,height);
  let quality=.9,data=canvas.toDataURL('image/jpeg',quality);
  while(data.length>1200000&&quality>.46){quality-=.06;data=canvas.toDataURL('image/jpeg',quality);}
  if(data.length>1200000)throw Error('This panorama is too detailed to fit safely in an island. Try a smaller image.');
  return {name:(file.name||'Custom sky').slice(0,80),data,width,height,rotation:0,brightness:1};
}
