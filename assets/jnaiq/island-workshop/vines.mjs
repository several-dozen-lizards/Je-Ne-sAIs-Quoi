import * as THREE from './vendor/three.module.js';
import {mergeGeometries} from './vendor/BufferGeometryUtils.js';

export const VINE_STYLES={
  ivy:{name:'Ivy',stem:0x496334,leaf:0x668d43,accent:null,climb:1},
  wisteria:{name:'Wisteria',stem:0x5a5730,leaf:0x688946,accent:0x9c77c4,climb:.82},
  rose:{name:'Climbing rose',stem:0x50602f,leaf:0x477c3d,accent:0xd96b80,climb:.9},
  bramble:{name:'Thorny bramble',stem:0x6c5434,leaf:0x496d35,accent:0xb9a4d5,climb:.55},
  dead:{name:'Bare woody creeper',stem:0x70583b,leaf:null,accent:null,climb:.72},
};
export const VINE_LIMIT=80,PATH_LIMIT=32,POINT_LIMIT=128;
const finite=v=>Number.isFinite(v);
const hash=(seed,n)=>{let x=(seed^(n*0x9e3779b9))>>>0;x=Math.imul(x^(x>>>16),0x21f0aaad);x=Math.imul(x^(x>>>15),0x735a2d97);return ((x^(x>>>15))>>>0)/4294967296;};
const vector=p=>new THREE.Vector3(p[0],p[1],p[2]);
const normal=p=>new THREE.Vector3(p[3],p[4],p[5]).normalize();
const rounded=v=>Math.round(v*10000)/10000;
export const vinePoint=(point,surfaceNormal)=>[...point.toArray(),...surfaceNormal.clone().normalize().toArray()].map(rounded);

export function validateVines(items=[],size=160){
  if(!Array.isArray(items)||items.length>VINE_LIMIT)throw Error(`An island supports up to ${VINE_LIMIT} vine tangles.`);
  const ids=new Set();
  for(const vine of items){
    if(!vine||typeof vine.id!=='string'||!vine.id||vine.id.length>80||ids.has(vine.id)||!VINE_STYLES[vine.style]
      ||!Number.isInteger(vine.seed)||vine.seed<0||vine.seed>4294967295
      ||!finite(vine.stemWidth)||vine.stemWidth<.012||vine.stemWidth>.12
      ||!finite(vine.leafiness)||vine.leafiness<0||vine.leafiness>1
      ||!finite(vine.branching)||vine.branching<0||vine.branching>1
      ||!Array.isArray(vine.paths)||!vine.paths.length||vine.paths.length>PATH_LIMIT)throw Error('Invalid vine identity or growth settings.');
    ids.add(vine.id);
    for(const path of vine.paths){
      if(!Array.isArray(path)||path.length<2||path.length>POINT_LIMIT)throw Error('Invalid vine path.');
      for(const p of path){
        if(!Array.isArray(p)||p.length!==6||!p.every(finite)||Math.abs(p[0])>size/2+2||Math.abs(p[2])>size/2+2||p[1]<-12||p[1]>78
          ||Math.hypot(p[3],p[4],p[5])<.8||Math.hypot(p[3],p[4],p[5])>1.2)throw Error('Invalid vine surface point.');
      }
    }
  }
  return items;
}

function pathLength(points){let length=0;for(let i=1;i<points.length;i++)length+=vector(points[i]).distanceTo(vector(points[i-1]));return length;}
function cleanGuide(points){
  const out=[];for(const p of points){if(!out.length||vector(p).distanceTo(vector(out.at(-1)))>.12)out.push(p);}
  return out;
}

// Surface projection is supplied by the editor. The generator itself stays
// deterministic and DOM-free, so saved growth can be checked independently.
export function growVineNetwork({id,style='ivy',seed=1,guide,reach=7,branching=.58,leafiness=.72,stemWidth=.045,project}){
  if(!VINE_STYLES[style])throw Error('Choose a vine character.');
  let main=cleanGuide(guide||[]);if(!main.length)throw Error('Choose a surface for the vine.');
  const walk=(start,tangent,length,salt)=>{
    const points=[start],step=Math.max(.22,Math.min(.52,length/18));let travelled=0,current=start,heading=tangent.clone().normalize();
    for(let i=0;i<POINT_LIMIT-1&&travelled+step<=length;i++){
      const n=normal(current),up=new THREE.Vector3(0,1,0).addScaledVector(n,-n.y);if(up.lengthSq()>.001)up.normalize();
      const curl=(hash(seed,salt+i*3)-.5)*.48,side=new THREE.Vector3().crossVectors(n,heading).normalize();
      heading.addScaledVector(up,VINE_STYLES[style].climb*.2).addScaledVector(side,curl).addScaledVector(n,-heading.dot(n)).normalize();
      const next=project?.(current,heading,step);if(!next)break;
      const distance=vector(next).distanceTo(vector(current));if(distance<step*.25||distance>step*2.4)break;
      points.push(next);travelled+=distance;heading=vector(next).sub(vector(current)).normalize();current=next;
    }return points;
  };
  if(main.length===1){
    const n=normal(main[0]),up=new THREE.Vector3(0,1,0).addScaledVector(n,-n.y);
    if(up.lengthSq()<.01)up.set(1,0,0).addScaledVector(n,-n.x);main=walk(main[0],up.normalize(),reach,7);
  }
  if(main.length<2)throw Error('This surface does not have enough connected room for a vine.');
  const paths=[main],length=pathLength(main),wanted=Math.min(PATH_LIMIT-1,Math.max(0,Math.round(length*(.18+branching*.55))));
  for(let branch=0;branch<wanted;branch++){
    const t=(branch+1)/(wanted+1),index=Math.max(1,Math.min(main.length-2,Math.round(t*(main.length-1))));
    if(hash(seed,200+branch)>branching*.82+.16)continue;
    const base=main[index],n=normal(base),along=vector(main[index+1]).sub(vector(main[index-1])).normalize(),side=new THREE.Vector3().crossVectors(n,along).normalize();
    const sign=hash(seed,400+branch)>.5?1:-1,up=new THREE.Vector3(0,1,0).addScaledVector(n,-n.y).normalize();
    side.multiplyScalar(sign).addScaledVector(up,(hash(seed,500+branch)-.3)*.75).normalize();
    const branchLength=Math.min(reach*.46,length*(.16+hash(seed,600+branch)*.24));
    const grown=walk(base,side,branchLength,1000+branch*97);if(grown.length>1)paths.push(grown);
  }
  const vine={id:id||crypto.randomUUID(),style,seed:seed>>>0,stemWidth,leafiness,branching,paths};validateVines([vine],Math.max(160,...main.map(p=>Math.max(Math.abs(p[0]),Math.abs(p[2]))*2+4)));return vine;
}

function disposeTree(root){root.traverse(o=>{o.geometry?.dispose();if(Array.isArray(o.material))o.material.forEach(m=>m.dispose());else o.material?.dispose();});}
function orientation(point,tangent,scale,matrix){
  const n=normal(point),x=tangent.clone().addScaledVector(n,-tangent.dot(n)).normalize();if(x.lengthSq()<.01)x.set(1,0,0);
  const y=new THREE.Vector3().crossVectors(n,x).normalize();matrix.makeBasis(x,y,n);matrix.scale(new THREE.Vector3(scale,scale,scale));matrix.setPosition(vector(point).addScaledVector(n,.012));return matrix;
}

export function createVineObject(vine,{preview=false}={}){
  const spec=VINE_STYLES[vine.style]||VINE_STYLES.ivy,root=new THREE.Group();root.userData={vineVisual:true,walkThrough:true,vineId:vine.id};
  const stemMaterial=new THREE.MeshStandardMaterial({color:spec.stem,roughness:.9,metalness:0});
  const stems=[];
  for(const path of vine.paths){const points=path.map(vector);if(points.length<2)continue;const curve=new THREE.CatmullRomCurve3(points,false,'centripetal',.25),radius=vine.stemWidth*(path===vine.paths[0]?.5:.32);stems.push(new THREE.TubeGeometry(curve,Math.max(3,(points.length-1)*3),radius,preview?4:6,false));}
  if(stems.length){const geometry=stems.length===1?stems[0]:mergeGeometries(stems);if(stems.length>1)stems.forEach(g=>g.dispose());const mesh=new THREE.Mesh(geometry,stemMaterial);mesh.castShadow=!preview;mesh.receiveShadow=true;mesh.userData.walkThrough=true;root.add(mesh);}else stemMaterial.dispose();
  if(preview||!spec.leaf||vine.leafiness<=0)return root;
  const leaves=[];let ordinal=0;
  for(const path of vine.paths){let total=0,target=.14+(1-vine.leafiness)*.38;for(let i=1;i<path.length;i++){
    const a=vector(path[i-1]),b=vector(path[i]),segment=b.distanceTo(a),before=total;total+=segment;if(segment<1e-5)continue;
    const tangent=b.clone().sub(a).normalize();
    while(target<=total){const t=(target-before)/segment,pa=path[i-1],pb=path[i],n=new THREE.Vector3(pa[3],pa[4],pa[5]).lerp(new THREE.Vector3(pb[3],pb[4],pb[5]),t).normalize(),point=vinePoint(a.clone().lerp(b,t),n);ordinal++;const leafTangent=tangent.clone().applyAxisAngle(n,(ordinal%2?1:-1)*(.42+hash(vine.seed,1500+ordinal)*.8));leaves.push({point,tangent:leafTangent,scale:(.66+vine.stemWidth*4)*(vine.style==='bramble'?.82:vine.style==='wisteria'?.94:1)*(.8+hash(vine.seed,2000+ordinal)*.44)});target+=.14+(1-vine.leafiness)*.38+hash(vine.seed,ordinal)*.09;}
  }}
  if(leaves.length){
    const shape=new THREE.Shape();shape.moveTo(0,-.1);shape.bezierCurveTo(.12,-.04,.12,.12,0,.22);shape.bezierCurveTo(-.12,.12,-.12,-.04,0,-.1);const geometry=new THREE.ShapeGeometry(shape,3);geometry.translate(0,-.04,0);
    const material=new THREE.MeshStandardMaterial({color:spec.leaf,side:THREE.DoubleSide,roughness:.88,alphaTest:.15});const mesh=new THREE.InstancedMesh(geometry,material,leaves.length),matrix=new THREE.Matrix4();
    leaves.forEach((leaf,i)=>mesh.setMatrixAt(i,orientation(leaf.point,leaf.tangent,leaf.scale,matrix)));mesh.instanceMatrix.needsUpdate=true;mesh.computeBoundingSphere();mesh.castShadow=true;mesh.userData.walkThrough=true;root.add(mesh);
  }
  if(spec.accent){
    const count=Math.min(180,Math.floor(leaves.length*(vine.style==='wisteria'?.28:vine.style==='bramble'?.1:.18))),geometry=vine.style==='wisteria'?new THREE.ConeGeometry(.095,.34,7):vine.style==='rose'?new THREE.DodecahedronGeometry(.105,0):new THREE.SphereGeometry(.055,7,5),material=new THREE.MeshStandardMaterial({color:spec.accent,roughness:.75}),mesh=new THREE.InstancedMesh(geometry,material,count),matrix=new THREE.Matrix4();
    for(let i=0;i<count;i++){const leaf=leaves[Math.floor(hash(vine.seed,3000+i)*leaves.length)]||leaves[0];if(!leaf)break;const q=vine.style==='wisteria'?new THREE.Quaternion():new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0,1,0),normal(leaf.point));matrix.compose(vector(leaf.point).addScaledVector(normal(leaf.point),.055).add(vine.style==='wisteria'?new THREE.Vector3(0,-.12,0):new THREE.Vector3()),q,new THREE.Vector3(1,1,1).multiplyScalar(.82+hash(vine.seed,4000+i)*.42));mesh.setMatrixAt(i,matrix);}mesh.instanceMatrix.needsUpdate=true;mesh.computeBoundingSphere();mesh.castShadow=true;mesh.userData.walkThrough=true;root.add(mesh);
  }
  if(vine.style==='bramble'&&leaves.length){
    const count=Math.min(220,Math.floor(pathLength(vine.paths[0])/Math.max(.18,vine.stemWidth*5))),geometry=new THREE.ConeGeometry(vine.stemWidth*.34,vine.stemWidth*2.4,4),material=new THREE.MeshStandardMaterial({color:0x8e7651,roughness:1}),mesh=new THREE.InstancedMesh(geometry,material,count),matrix=new THREE.Matrix4();
    for(let i=0;i<count;i++){const path=vine.paths[i%vine.paths.length],point=path[1+Math.floor(hash(vine.seed,5000+i)*(path.length-1))],n=normal(point);matrix.makeRotationFromQuaternion(new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0,1,0),n)).setPosition(vector(point).addScaledVector(n,vine.stemWidth));mesh.setMatrixAt(i,matrix);}mesh.instanceMatrix.needsUpdate=true;mesh.computeBoundingSphere();mesh.castShadow=true;mesh.userData.walkThrough=true;root.add(mesh);
  }
  return root;
}

export function createVineLayer(scene){
  const root=new THREE.Group();root.name='clinging-growth';root.userData={vineVisual:true,walkThrough:true};scene.add(root);
  function rebuild(world){while(root.children.length){const child=root.children[0];root.remove(child);disposeTree(child);}for(const vine of world.vines||[])root.add(createVineObject(vine));}
  return {root,rebuild,dispose(){scene.remove(root);disposeTree(root);}};
}
