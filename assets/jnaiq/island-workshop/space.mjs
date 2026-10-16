import * as THREE from './vendor/three.module.js';
import {hasOceanSurface} from './environment-lighting.mjs?fantasy=1';
import {random,N} from './terrain.mjs?caves=retired';
import {makeRock} from './rocks.mjs?shape=4';
import {undersidePoints} from './underside.mjs';
export function createSpace(scene,rockMaterial){
  const belt=new THREE.Group();scene.add(belt);const rng=random(359719),matrix=new THREE.Object3D();
  for(let variant=0;variant<3;variant++){
    const material=rockMaterial.clone();material.color.setHex([0x99938a,0x686b73,0xa0836b][variant]);material.fog=false;
    const mesh=new THREE.InstancedMesh(makeRock('rock',variant),material,120);
    for(let i=0;i<120;i++){const a=rng()*Math.PI*2,r=240+rng()*1400,s=3+rng()*14;matrix.position.set(Math.cos(a)*r,-150+rng()*420,Math.sin(a)*r);matrix.rotation.set(rng()*6,rng()*6,rng()*6);matrix.scale.setScalar(s);matrix.updateMatrix();mesh.setMatrixAt(i,matrix.matrix);}mesh.computeBoundingSphere();belt.add(mesh);
  }
  const material=rockMaterial.clone();material.side=THREE.DoubleSide;material.color.setHex(0x727781);
  const underside=new THREE.Mesh(new THREE.BufferGeometry(),material);scene.add(underside);
  return {updateTerrain(w){
    const bottoms=undersidePoints(w);
    const p=[],uv=[],edges=new Map(),point=k=>[(k%(N+1)/N-.5)*w.size,w.heights[k],(Math.floor(k/(N+1))/N-.5)*w.size],bottom=k=>bottoms[k];
    function tri(a,b,c){for(const v of [a,b,c]){p.push(...v);uv.push(v[0]*.12,(v[1]+v[2])*.12);}}
    function face(a,b,c){if([a,b,c].some(k=>w.heights[k]<=0))return;tri(bottom(a),bottom(c),bottom(b));for(const [i,j] of [[a,b],[b,c],[c,a]]){const key=Math.min(i,j)+':'+Math.max(i,j);if(edges.has(key))edges.delete(key);else edges.set(key,[i,j]);}}
    for(let j=0;j<N;j++)for(let i=0;i<N;i++){const a=j*(N+1)+i;face(a,a+N+1,a+1);face(a+1,a+N+1,a+N+2);}
    for(const [a,b] of edges.values()){tri(point(a),point(b),bottom(a));tri(point(b),bottom(b),bottom(a));}
    const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.Float32BufferAttribute(p,3));geometry.setAttribute('uv',new THREE.Float32BufferAttribute(uv,2));geometry.computeVertexNormals();underside.geometry.dispose();underside.geometry=geometry;
  },update(environment){belt.visible=environment==='asteroids';underside.visible=!hasOceanSurface(environment);}};
}
