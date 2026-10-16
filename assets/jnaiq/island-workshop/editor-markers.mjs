import * as THREE from 'three';

// Editor handles stay readable when the camera frames an entire island.
// Their size never changes the authored object's dimensions or behavior.
export function editorMarkerTexture(kind){
  const canvas=document.createElement('canvas');canvas.width=canvas.height=96;
  const ctx=canvas.getContext('2d');
  ctx.fillStyle='#142127';ctx.strokeStyle='#ffffff';ctx.lineWidth=5;
  ctx.beginPath();ctx.arc(48,48,35,0,Math.PI*2);ctx.fill();ctx.stroke();
  ctx.lineWidth=4;ctx.lineCap='round';
  if(kind==='portal'){
    ctx.beginPath();ctx.ellipse(43,48,14,23,0,0,Math.PI*2);ctx.stroke();
    ctx.beginPath();ctx.moveTo(42,48);ctx.lineTo(70,48);
    ctx.moveTo(61,39);ctx.lineTo(70,48);ctx.lineTo(61,57);ctx.stroke();
  }else{
    ctx.beginPath();ctx.arc(48,48,12,0,Math.PI*2);ctx.fillStyle='#ffffff';ctx.fill();
    for(let i=0;i<8;i++){
      const angle=i*Math.PI/4;
      ctx.beginPath();ctx.moveTo(48+20*Math.cos(angle),48+20*Math.sin(angle));
      ctx.lineTo(48+26*Math.cos(angle),48+26*Math.sin(angle));ctx.stroke();
    }
  }
  const texture=new THREE.CanvasTexture(canvas);texture.colorSpace=THREE.SRGBColorSpace;
  return texture;
}

export function createEditorMarker(texture,kind){
  const marker=new THREE.Sprite(new THREE.SpriteMaterial({map:texture,sizeAttenuation:false,depthWrite:false,toneMapped:false}));
  marker.name=kind==='portal'?'Teleporter handle':'Local light handle';marker.frustumCulled=false;
  const viewport=new THREE.Vector2();
  marker.onBeforeRender=(renderer,scene,camera)=>{
    const height=renderer.getSize(viewport).y;
    // SpriteMaterial removes perspective distance; account for FOV and canvas
    // height as well so the click target remains 28 CSS pixels across.
    marker.scale.setScalar(56/(Math.max(1,height)*camera.projectionMatrix.elements[5]));
    marker.updateMatrixWorld();
  };
  return marker;
}
