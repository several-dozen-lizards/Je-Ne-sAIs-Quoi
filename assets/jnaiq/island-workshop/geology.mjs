import * as THREE from './vendor/three.module.js';
import {random,heightAt} from './terrain.mjs?caves=retired';
export const CRYSTAL_STYLES={
  amethyst:{base:'amethyst',scale:[1,1,1],color:0x9966d8,emissive:0x170525,glow:.35},
  quartz:{base:'quartz',scale:[1,1,1],color:0xd6e4e8,emissive:0x050808,glow:.35},
  azure_crystal:{base:'azure_crystal',scale:[1,1,1],color:0x419dc4,emissive:0x031723,glow:.35},
  rose_quartz:{base:'amethyst',scale:[.25,.16,.25],color:0xe6a1bb,emissive:0x000000,glow:0},
  citrine_points:{base:'quartz',scale:[.30,.12,.30],color:0xe5ac48,emissive:0x000000,glow:0},
  emerald_shards:{base:'azure_crystal',scale:[.22,.19,.22],color:0x319977,emissive:0x000000,glow:0},
  glow_crystal_cyan:{base:'quartz',scale:[.32,.24,.32],color:0x62ced9,emissive:0x29c9e0,glow:1.2},
  glow_crystal_violet:{base:'amethyst',scale:[.32,.25,.32],color:0xb98de5,emissive:0x9a49ed,glow:1.1},
  glow_crystal_amber:{base:'azure_crystal',scale:[.25,.18,.25],color:0xe9af58,emissive:0xe89527,glow:1.0}
};
export const CRYSTAL_IDS=Object.keys(CRYSTAL_STYLES);
export const GEOLOGY_IDS=CRYSTAL_IDS;
export const objectHeight=(w,o)=>heightAt(w,o.x,o.z);
export function makeGeology(kind,variant=0){
  if(!CRYSTAL_IDS.includes(kind))throw Error('Unknown crystal');
  const style=CRYSTAL_STYLES[kind];kind=style.base;
  const rng=random(58431+variant*7919),pieces=[];
  function add(g){pieces.push(g.index?g.toNonIndexed():g);if(g.index)g.dispose();}
    const crystal=true,hanging=false,count=crystal?(kind==='amethyst'?16+variant*4:kind==='quartz'?5+variant*3:10+variant*3):7;
    for(let i=0;i<count;i++){
      const a=i*2.399+rng()*.6,r=i?Math.sqrt(i)*(kind==='amethyst'?.48:.36):0;
      const h=crystal?(kind==='amethyst'?(.55+rng()*2.1)*(1+variant*.2):kind==='quartz'?(i?1.5+rng()*3:5+variant*.7):1.2+rng()*3.8):(i?1.1+rng()*2.4:4.5+rng());
      const radius=crystal?(kind==='quartz'?.19+rng()*.24:kind==='azure_crystal'?.16+rng()*.24:.22+rng()*.36):.28+rng()*.3;
      const g=new THREE.CylinderGeometry(crystal?radius*.72:.035,radius,h*.78,crystal?6:9,crystal?1:7),tip=new THREE.ConeGeometry(crystal?radius*.72:.035,h*.22,crystal?6:9);
      g.translate(0,h*.39,0);tip.translate(0,h*.89,0);
      const lean=(rng()-.5)*(crystal?(kind==='azure_crystal'?1.5:.85):.35);for(const mesh of [g,tip]){mesh.rotateZ(lean);mesh.rotateY(a);mesh.translate(Math.cos(a)*r,0,Math.sin(a)*r);if(hanging)mesh.rotateX(Math.PI);add(mesh);}
    }
  const g=new THREE.BufferGeometry();for(const name of ['position','normal','uv']){const arrays=pieces.map(p=>p.attributes[name].array),out=new Float32Array(arrays.reduce((n,a)=>n+a.length,0));let offset=0;for(const a of arrays){out.set(a,offset);offset+=a.length;}g.setAttribute(name,new THREE.BufferAttribute(out,name==='uv'?2:3));}
  pieces.forEach(g=>g.dispose());g.scale(...style.scale);g.computeBoundingBox();g.computeBoundingSphere();return g;
}
