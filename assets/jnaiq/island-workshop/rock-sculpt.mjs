import * as THREE from './vendor/three.module.js';
export const ROCK_LIMIT=16000;
export const ROCK_TYPES=['Weathered stone','Granite','Sandstone','Limestone','Basalt','Mossy rock'];
const rockColors=[0xa49c8e,0xada3a0,0xc19763,0xd1c7aa,0x55565c,0x788360].map(c=>new THREE.Color(c));
function rockColor(p,type){
  const color=rockColors[type].clone(),grain=Math.sin(p.x*37.1+p.z*61.7+p.y*43.3)*Math.sin(p.z*29.3-p.y*51.1);
  const layers=Math.sin(p.y*(type===2?3.8:7)+Math.sin(p.x*.7+p.z*.4)*.8);
  color.multiplyScalar(1+grain*(type===1?.19:.06)+layers*(type===2?.13:.035));
  if(type===5)color.lerp(new THREE.Color(0x475a28),Math.max(0,Math.sin(p.x*.8+p.z*.6)*Math.sin(p.y*.9))*.65);
  return color;
}
export function validateSculpt(points=[],size=160){
  if(!Array.isArray(points)||points.length>ROCK_LIMIT)throw Error('Sculpted rock has reached its 16,000-point detail budget.');
  const seen=new Set();for(const p of points){if(!Array.isArray(p)||![4,5].includes(p.length)||!p.every(Number.isFinite)||(p.length===5&&(!Number.isInteger(p[4])||p[4]<0||p[4]>=ROCK_TYPES.length))||!p.slice(0,3).every(Number.isInteger)||Math.abs(p[0])>size/2||Math.abs(p[2])>size/2||p[1]<-8||p[1]>72||p[3]<=-1||p[3]>1||seen.has(p.slice(0,3).join(',')))throw Error('Invalid sculpted rock.');seen.add(p.slice(0,3).join(','));}return points;
}
export function sculptStroke(points,center,radius,carve,size,type=0){
  if(!Number.isInteger(type)||type<0||type>=ROCK_TYPES.length)throw Error('Choose a valid rock type.');
  const map=new Map(points.map(p=>[p.slice(0,3).join(','),p]));let changed=false;
  for(let x=Math.max(-size/2,Math.floor(center.x-radius-1));x<=Math.min(size/2,Math.ceil(center.x+radius+1));x++)for(let y=Math.max(-8,Math.floor(center.y-radius-1));y<=Math.min(72,Math.ceil(center.y+radius+1));y++)for(let z=Math.max(-size/2,Math.floor(center.z-radius-1));z<=Math.min(size/2,Math.ceil(center.z+radius+1));z++){
    const key=`${x},${y},${z}`,old=map.get(key)?.[3]??-1,d=radius-Math.hypot(x-center.x,y-center.y,z-center.z),value=Math.round(Math.max(-1,Math.min(1,carve?Math.min(old,-d):Math.max(old,d)))*1000)/1000;
    const previous=map.get(key),kind=carve?(previous?.[4]??0):type;
    if(value===old&&(carve||d<=0||(previous?.[4]??0)===kind))continue;changed=true;if(value<=-1)map.delete(key);else map.set(key,kind?[x,y,z,value,kind]:[x,y,z,value]);
  }
  if(map.size>ROCK_LIMIT)throw Error('Rock detail budget reached. Carve some rock away or Undo before adding more.');
  return changed?[...map.values()]:points;
}
const corners=[[0,0,0],[1,0,0],[1,1,0],[0,1,0],[0,0,1],[1,0,1],[1,1,1],[0,1,1]],tetra=[[0,5,1,6],[0,1,2,6],[0,2,3,6],[0,3,7,6],[0,7,4,6],[0,4,5,6]];
// Extract a closed surface from the density field. Shared lattice samples let
// brush strokes merge, while subtraction opens real passages through the mass.
export function sculptGeometry(points){
  const map=new Map(points.map(p=>[p.slice(0,3).join(','),p[3]])),types=new Map(points.map(p=>[p.slice(0,3).join(','),p[4]??0])),cells=new Set(),positions=[],colors=[];
  for(const [x,y,z,d] of points)if(d>0)for(let i=-1;i<=0;i++)for(let j=-1;j<=0;j++)for(let k=-1;k<=0;k++)cells.add(`${x+i},${y+j},${z+k}`);
  for(const key of cells){const base=key.split(',').map(Number),v=corners.map(c=>new THREE.Vector3(...c.map((n,i)=>n+base[i]))),d=v.map(p=>map.get(`${p.x},${p.y},${p.z}`)??-1);
    for(const t of tetra){const inside=t.filter(i=>d[i]>0),outside=t.filter(i=>d[i]<=0);if(!inside.length||!outside.length)continue;
      const polygon=[];for(const i of inside)for(const o of outside)polygon.push(v[i].clone().lerp(v[o],d[i]/(d[i]-d[o])));
      const middle=polygon.reduce((s,p)=>s.add(p),new THREE.Vector3()).multiplyScalar(1/polygon.length),normal=outside.reduce((s,i)=>s.add(v[i]),new THREE.Vector3()).multiplyScalar(1/outside.length).sub(inside.reduce((s,i)=>s.add(v[i]),new THREE.Vector3()).multiplyScalar(1/inside.length)).normalize();
      const u=polygon[0].clone().sub(middle).normalize(),w=new THREE.Vector3().crossVectors(normal,u);
      polygon.sort((a,b)=>Math.atan2(a.clone().sub(middle).dot(w),a.clone().sub(middle).dot(u))-Math.atan2(b.clone().sub(middle).dot(w),b.clone().sub(middle).dot(u)));
      for(let i=1;i<polygon.length-1;i++)for(const p of [polygon[0],polygon[i],polygon[i+1]]){
        const rough=.09*Math.sin(p.x*2.3+p.y*.8)*Math.sin(p.z*2.1-p.y*1.7);positions.push(p.x+rough,p.y+rough*.7,p.z+rough*.8);
        const nearest=inside.reduce((best,i)=>p.distanceToSquared(v[i])<p.distanceToSquared(v[best])?i:best,inside[0]),sample=v[nearest];
        const color=rockColor(p,types.get(`${sample.x},${sample.y},${sample.z}`)??0);colors.push(color.r,color.g,color.b);
      }
    }
  }
  const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));g.setAttribute('color',new THREE.Float32BufferAttribute(colors,3));g.setAttribute('uv',new THREE.Float32BufferAttribute(positions.flatMap((v,i)=>i%3===1?[]:[v*.1]),2));g.computeVertexNormals();g.computeBoundingSphere();return g;
}
