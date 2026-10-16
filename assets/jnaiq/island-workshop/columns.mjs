import * as THREE from './vendor/three.module.js';
import catalogue from './column-styles.json' with {type:'json'};
export const COLUMN_STYLES=Object.freeze(catalogue);
export function columnPositions(c){
  const n=c.length===0?0:Math.max(1,Math.ceil(c.length/c.spacing));
  return Array.from({length:n+1},(_,i)=>{const t=n?i/n-.5:0;return {x:c.x+Math.cos(c.rotation)*c.length*t,z:c.z-Math.sin(c.rotation)*c.length*t};});
}
export function validateColumns(items=[],size=160){
  if(!Array.isArray(items)||items.length>160)throw Error('Use up to 160 column placements.');
  const ids=new Set();let count=0;
  for(const c of items){
    if(!c||typeof c.id!=='string'||!c.id.length||c.id.length>80||ids.has(c.id)||!Object.hasOwn(COLUMN_STYLES,c.style)||!['stone','marble','timber','plaster','concrete','copper','brick'].includes(c.material)||![c.x,c.z,c.rotation,c.length,c.height,c.radius,c.spacing].every(Number.isFinite)||c.length<0||c.length>80||c.height<1||c.height>16||c.radius<.1||c.radius>1.5||c.spacing<1||c.spacing>12||c.spacing<c.radius*4||Math.abs(c.rotation)>Math.PI*2)throw Error('Invalid column dimensions or style. Keep spacing at least four times the shaft radius.');
    ids.add(c.id);const points=columnPositions(c);count+=points.length;
    if(c.length&&c.length/(points.length-1)<c.radius*4)throw Error('Column capitals overlap; lengthen the row or reduce the radius.');
    for(const p of points)if(Math.abs(p.x)+c.radius*1.8>size/2||Math.abs(p.z)+c.radius*1.8>size/2)throw Error('Keep columns and capitals inside the island.');
  }
  if(count>1000)throw Error('Use up to 1,000 freestanding columns per island.');return items;
}
export function validateColumnBuilding(b){
  if(b.enclosure!==undefined&&!['walls','columns'].includes(b.enclosure))throw Error('Invalid enclosure.');
  if(b.columnStyle!==undefined&&!Object.hasOwn(COLUMN_STYLES,b.columnStyle))throw Error('Invalid column style.');
  if(b.columnSpacing!==undefined&&(!Number.isFinite(b.columnSpacing)||b.columnSpacing<2||b.columnSpacing>8))throw Error('Pavilion spacing must be 2–8 metres.');
}
export function pavilionPositions(b){
  const spacing=b.columnSpacing||4,w=b.width,d=b.depth;
  if(b.shape==='round'){
    const count=Math.max(8,Math.ceil(Math.PI*(3*(w+d)/2-Math.sqrt((3*w+d)*(w+3*d))/2)/spacing));
    return Array.from({length:count},(_,i)=>({x:Math.cos(i/count*Math.PI*2)*w/2,z:Math.sin(i/count*Math.PI*2)*d/2}));
  }
  const nx=Math.ceil(w/spacing),nz=Math.ceil(d/spacing),points=[];
  for(let i=0;i<nx;i++){points.push({x:-w/2+i*w/nx,z:-d/2},{x:w/2-i*w/nx,z:d/2});}
  for(let i=0;i<nz;i++){points.push({x:w/2,z:-d/2+i*d/nz},{x:-w/2,z:d/2-i*d/nz});}return points;
}
// Each style becomes one geometry so a row can instance it in one draw call.
export function columnGeometry(style,height=3.2,radius=.25){
  const a=COLUMN_STYLES[style];if(!a)throw Error('Unknown column style.');const parts=[];
  function part(g,x=0,y=0,z=0,rx=0,ry=0,rz=0){const m=new THREE.Matrix4().compose(new THREE.Vector3(x,y,z),new THREE.Quaternion().setFromEuler(new THREE.Euler(rx,ry,rz)),new THREE.Vector3(1,1,1));parts.push(g.applyMatrix4(m));}
  function ring(r,h,y,segments=24){part(new THREE.CylinderGeometry(r,r,h,segments),0,y);}
  function block(r,h,y){part(new THREE.BoxGeometry(r*2,h,r*2),0,y);}
  function stem(p,q,r){const v=new THREE.Vector3(...q).sub(new THREE.Vector3(...p)),g=new THREE.CylinderGeometry(r*.7,r,v.length(),6),m=new THREE.Matrix4().compose(new THREE.Vector3(...p).add(new THREE.Vector3(...q)).multiplyScalar(.5),new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0,1,0),v.normalize()),new THREE.Vector3(1,1,1));parts.push(g.applyMatrix4(m));}
  const cap=height*.19,base=style==='doric'?0:height*.07,shaft=height-cap-base,r=radius;
  if(base){block(r*1.35,base*.5,base*.25);ring(r*1.16,base*.5,base*.75);}
  if(a.form==='square')block(r,shaft,base+shaft/2);
  else{
    const segments=a.form==='octagon'?8:a.form==='crystal'?6:96,rings=12,points=[],indices=[],uv=[];
    for(let j=0;j<=rings;j++)for(let i=0;i<=segments;i++){
      const t=j/rings,theta=i/segments*Math.PI*2,twist=a.form==='twisted'?t*Math.PI*1.5:0;
      let rr=r*(1-.16*t+.055*Math.sin(t*Math.PI));
      if(a.form==='fluted')rr*=1-.075*(1+Math.cos(theta*24));
      if(a.form==='bundle')rr*=1+.12*Math.cos(theta*8);
      if(a.form==='rough')rr*=1+.1*Math.sin(theta*7+t*5)+.05*Math.sin(theta*11-t*8);
      if(a.form==='twisted')rr*=1+.15*Math.cos(theta*5);
      points.push(Math.cos(theta+twist)*rr,base+t*shaft,Math.sin(theta+twist)*rr);uv.push(i/segments,t);
      if(j<rings&&i<segments){const k=j*(segments+1)+i;indices.push(k,k+segments+1,k+1,k+1,k+segments+1,k+segments+2);}
    }
    const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(points,3));g.setAttribute('uv',new THREE.Float32BufferAttribute(uv,2));g.setIndex(indices);g.computeVertexNormals();part(g);
  }
  const y=height-cap;
  ring(r*.92,cap*.12,y+cap*.06);
  if(['cushion','rings','scrolls','leaves','composite','carved','lotus'].includes(a.capital)){
    part(new THREE.CylinderGeometry(r*1.4,r*.82,cap*.65,24),0,y+cap*.44);
    block(r*1.5,cap*.2,height-cap*.1);
  }else if(a.capital==='stepped'){for(let i=0;i<3;i++)block(r*(1+i*.25),cap/3,y+cap*(i+.5)/3);}
  else {block(r*1.2,cap*.18,height-cap*.09);ring(r*.88,cap*.82,y+cap*.41);}
  if(['scrolls','composite'].includes(a.capital))for(const sign of [-1,1])for(const z of [-r,r]){
    const points=Array.from({length:25},(_,i)=>{const t=i/24,angle=t*Math.PI*3,rr=r*.48*(1-t*.85);return new THREE.Vector3(sign*r+Math.cos(angle)*rr,y+cap*.6+Math.sin(angle)*rr,z);});
    part(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(points),24,r*.12,5,false));
  }
  if(['leaves','composite','lotus','carved'].includes(a.capital))for(let i=0;i<8;i++){
    const theta=i/8*Math.PI*2,leaf=new THREE.SphereGeometry(1,6,6);leaf.scale(r*.22,cap*.38,r*.25);
    part(leaf,Math.cos(theta)*r*1.14,y+cap*.48,Math.sin(theta)*r*1.14,Math.sin(theta)*.35,0,-Math.cos(theta)*.35);
    if(a.capital==='carved')part(new THREE.OctahedronGeometry(r*.22),Math.cos(theta)*r*1.35,y+cap*.68,Math.sin(theta)*r*1.35);
  }
  if(['brace','branches','fins','crystals'].includes(a.capital))for(let i=0;i<4;i++){
    const t=i/4*Math.PI*2,p=[Math.cos(t)*r*.65,height*.72,Math.sin(t)*r*.65],q=[Math.cos(t)*r*1.65,height-cap*.1,Math.sin(t)*r*1.65];stem(p,q,a.capital==='fins'?r*.22:r*.17);
    if(a.capital==='crystals'){const g=new THREE.ConeGeometry(r*.22,cap*.85,5);part(g,q[0]*.8,height-cap*.5,q[2]*.8);}
  }
  const geometries=parts.map(g=>g.index?g.toNonIndexed():g),out=new THREE.BufferGeometry();
  for(const key of ['position','normal','uv']){const data=new Float32Array(geometries.reduce((n,g)=>n+g.attributes[key].array.length,0));let offset=0;for(const g of geometries){data.set(g.attributes[key].array,offset);offset+=g.attributes[key].array.length;}out.setAttribute(key,new THREE.BufferAttribute(data,key==='uv'?2:3));}
  for(const g of new Set([...parts,...geometries]))g.dispose();out.computeBoundingBox();out.computeBoundingSphere();return out;
}
