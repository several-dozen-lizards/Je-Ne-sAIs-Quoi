import * as THREE from './vendor/three.module.js';
export const OPENING_SHAPES=['rectangle','arched','circle','oval','rounded','diamond','triangle','rhomboid'];
export function openingOutline(kind,width,height){
  if(!OPENING_SHAPES.includes(kind)||!(width>0&&height>0))throw Error('Invalid opening shape');
  let points=[];
  if(kind==='triangle')points=[[-1,-1],[1,-1],[0,1]];
  else if(kind==='diamond')points=[[0,-1],[1,0],[0,1],[-1,0]];
  else if(kind==='rhomboid')points=[[-1,-1],[.5,-1],[1,1],[-.5,1]];
  else if(kind==='arched'){
    const radius=Math.min(width/2,height*.45),p=[new THREE.Vector2(-width/2,0),new THREE.Vector2(width/2,0),new THREE.Vector2(width/2,height-radius)];
    for(let i=1;i<=24;i++){const a=i/24*Math.PI;p.push(new THREE.Vector2(Math.cos(a)*width/2,height-radius+Math.sin(a)*radius));}return p;
  }else if(['circle','oval','rounded'].includes(kind)){
    const w=kind==='circle'?Math.min(width,height):width,h=kind==='circle'?w:height;
    for(let i=0;i<48;i++){const a=i/48*Math.PI*2,c=Math.cos(a),s=Math.sin(a),power=kind==='rounded'?.5:1;points.push([Math.sign(c)*Math.abs(c)**power*w/width,Math.sign(s)*Math.abs(s)**power*h/height]);}
  }else points=[[-1,-1],[1,-1],[1,1],[-1,1]];
  return points.map(([x,y])=>new THREE.Vector2(x*width/2,(y+1)*height/2));
}
export function shapedOpening(kind,width,height){
  const outline=openingOutline(kind,width,height),hole=new THREE.Path(outline);hole.closePath();
  // The surrounding infill must end exactly at the rectangular wall cutout.
  // Extending it into the neighbouring wall spans makes two textured faces
  // occupy the same plane, so the depth buffer flickers between their UVs.
  const surround=new THREE.Shape([new THREE.Vector2(-width/2,0),new THREE.Vector2(width/2,0),new THREE.Vector2(width/2,height),new THREE.Vector2(-width/2,height)]);surround.closePath();surround.holes.push(hole);
  const trim=new THREE.Shape(outline.map(p=>new THREE.Vector2(p.x*(1+.24/width),(p.y-height/2)*(1+.24/height)+height/2)));trim.closePath();trim.holes.push(hole);
  const build=(shape,depth)=>{const g=new THREE.ExtrudeGeometry(shape,{depth,bevelEnabled:false,curveSegments:32});g.translate(0,0,-depth/2);return g;};
  return {wall:build(surround,.22),trim:build(trim,.34)};
}
