import * as THREE from 'three';
// The same wall record used by Godot, including immutable host image URLs.
export async function studioFrame(data){
  const root=new THREE.Group();
  root.add(new THREE.Mesh(new THREE.BoxGeometry(1.067,1.067,.038),new THREE.MeshStandardMaterial({color:0x644738})));
  let texture,ratio=1;
  if(data.image_url){texture=await new THREE.TextureLoader().loadAsync(data.image_url);ratio=texture.image.width/texture.image.height;}
  else{
    const canvas=document.createElement('canvas');canvas.width=1200;canvas.height=1200;
    const ctx=canvas.getContext('2d'),text=String(data.text||''),lines=text.split('\n');
    ctx.fillStyle='#fffaf0';ctx.fillRect(0,0,1200,1200);ctx.fillStyle='#292333';
    const longest=Math.max(1,...lines.map(l=>l.length));
    let size=Math.max(8,Math.min(38,Math.floor(Math.sqrt(800000/Math.max(1,text.length))),Math.floor(950/Math.max(1,lines.length)/1.4)));
    if(data.medium==='ascii')size=Math.max(8,Math.min(size,Math.floor(1080/(longest*.65))));
    ctx.font=`${size}px ${data.medium==='ascii'?'monospace':'serif'}`;
    const wrapped=[];
    for(const line of lines){let current='';for(const char of line){if(ctx.measureText(current+char).width>1080){wrapped.push(current);current='';}current+=char;}wrapped.push(current);}
    const fit=Math.min(1,1100/Math.max(1,wrapped.length*size*1.3));ctx.translate(600*(1-fit),600*(1-fit));ctx.scale(fit,fit);
    ctx.textBaseline='top';wrapped.forEach((line,i)=>ctx.fillText(line,60,Math.max(50,(1200-wrapped.length*size*1.3)/2)+i*size*1.3));
    texture=new THREE.CanvasTexture(canvas);
  }
  texture.colorSpace=THREE.SRGBColorSpace;
  const paper=new THREE.Mesh(new THREE.PlaneGeometry(ratio>1?1:ratio,ratio>1?1/ratio:1),new THREE.MeshBasicMaterial({map:texture,side:THREE.DoubleSide}));paper.position.z=.023;root.add(paper);
  root.userData.studio=data;
  return root;
}
