import * as THREE from './vendor/three.module.js';

// Solid leaf silhouettes, no transparent cards or per-leaf objects.
// Rounded, cupped leaves share the existing 28-triangle patch ceiling.
export function leafCarpetGeometry(flowers=false){
  const p=[],c=[],uv=[];
  function tri(vertices,colour,coords=null){for(const [i,v] of vertices.entries()){p.push(...v);c.push(...colour);uv.push(...(coords?coords[i]:[i===1?1:0,i===2?1:0]));}}
  const count=flowers?3:4;
  for(let i=0;i<count;i++){
    const angle=i*2.399,r=.08+Math.sqrt(i/count)*.32,x=Math.cos(angle)*r,z=Math.sin(angle)*r;
    const length=.32+(i%3)*.035,width=length*.40,y=.12+(i%4)*.09;
    const along=[Math.cos(angle+.6),Math.sin(angle+.6)],across=[-along[1],along[0]];
    const outline=[[.5,0],[.08,.26],[.12,.69],[.5,1],[.88,.69],[.92,.26]],center=[.5,.48];
    const point=([u,v])=>[x+along[0]*(v-.45)*length+across[0]*(u-.5)*width*2,y+v*.10+Math.sin(v*Math.PI)*.055-Math.abs(u-.5)*.11,z+along[1]*(v-.45)*length+across[1]*(u-.5)*width*2];
    const tex=([u,v])=>[u,-1-v];
    const colour=[.19+(i%3)*.025,.35+(i%4)*.018,.11+(i%2)*.025];
    for(let j=0;j<outline.length;j++){
      const a=outline[j],b=outline[(j+1)%outline.length];
      tri([point(center),point(a),point(b)],colour,[tex(center),tex(a),tex(b)]);
    }
  }
  if(flowers)for(let i=0;i<2;i++){
    const x=i?.21:-.24,z=i?-.15:.12,y=.39+i*.08;
    for(let j=0;j<5;j++){
      const angle=j*Math.PI*2/5,a=angle-.42,b=angle+.42,r=.07;
      tri([[x,y-.015,z],[x+Math.cos(a)*r,y,z+Math.sin(a)*r],[x+Math.cos(b)*r,y,z+Math.sin(b)*r]],[.64,.39,.84]);
    }
  }
  const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(p,3));g.setAttribute('color',new THREE.Float32BufferAttribute(c,3));g.setAttribute('uv',new THREE.Float32BufferAttribute(uv,2));g.computeVertexNormals();
  // Upward-facing leaf lighting on both faces, matching the grass material.
  const n=g.attributes.normal,groups=new Map();
  for(let i=0;i<n.count;i++){const key=p.slice(i*3,i*3+3).map(v=>v.toFixed(5)).join(',');if(!groups.has(key))groups.set(key,[]);groups.get(key).push(i);}
  for(const indices of groups.values()){const v=new THREE.Vector3();for(const i of indices)v.add(new THREE.Vector3(n.getX(i),Math.abs(n.getY(i))+.5,n.getZ(i)));v.normalize();for(const i of indices)n.setXYZ(i,v.x,v.y,v.z);}
  g.computeBoundingSphere();return g;
}
export function coverKind(site,world){
  if(['desert','craggy','savanna'].includes(world.style))return 'grass';
  const phase=(world.seed%997)*.017;
  const patch=Math.sin(site.x*.17+phase)*Math.cos(site.z*.13-phase)+.38*Math.sin(site.x*.43+site.z*.27+phase);
  if(patch<-.18)return 'grass';
  return patch>.65&&site.tint>.75?'flowers':'leaves';
}
