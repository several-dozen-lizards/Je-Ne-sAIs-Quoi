// Seeded, bounded terrain geometry. Metres; Y is up. No model calls.
import {PLANT_MIXES,SOLID_TREE_IDS} from './plants.mjs?sumac=2';
import {LANDSCAPES} from './landscape-profiles.mjs';
import {GENERATION_OPTIONS,validateGeneration,landformHeight} from './generation.mjs';
import {generatedTreeScale} from './tree-heights.mjs';
import {layerSampler} from './plant-layers.mjs';
import {generateFeatures,featureDistance} from './landscape-features.mjs?caves=retired';
export const N = 128;
export const STYLES = Object.keys(LANDSCAPES);
export const clamp = (v,a,b) => Math.max(a,Math.min(b,v));
export function random(seed) {
  let a = seed >>> 0;
  return () => { a += 0x6D2B79F5; let t = a; t = Math.imul(t ^ t >>> 15,t | 1); t ^= t + Math.imul(t ^ t >>> 7,t | 61); return ((t ^ t >>> 14) >>> 0) / 4294967296; };
}
const smooth = t => {t=clamp(t,0,1);return t*t*(3-2*t);};
export function generate(style='meadow', seed=1, size=160,features={}) {
  if(!STYLES.includes(style)) throw Error('Unknown island style');
  validateGeneration(features.generation);
  const rng=random(seed), phases=Array.from({length:12},()=>rng()*Math.PI*2);
  const hills=Array.from({length:8},()=>({x:(rng()-.5)*size*.7,z:(rng()-.5)*size*.7,r:size*(.08+rng()*.17),h:2+rng()*14}));
  const heights=[];
  for(let j=0;j<=N;j++) for(let i=0;i<=N;i++) {
    const x=(i/N-.5)*size,z=(j/N-.5)*size, angle=Math.atan2(z,x);
    const coast=size*(.36+.037*Math.sin(angle*3+phases[0])+.025*Math.sin(angle*5+phases[1]));
    const d=Math.hypot(x,z)/coast, edge=smooth((1-d)/.17);
    let h=1.7;
    for(const hill of hills) h+=hill.h*Math.exp(-((x-hill.x)**2+(z-hill.z)**2)/(2*hill.r**2));
    const noise=(Math.sin(x*.13+phases[2])*Math.cos(z*.11+phases[3])+Math.sin(x*.31+z*.19+phases[4])*.3);
    if(features.generation){h=clamp(features.generation.landforms.reduce((sum,kind)=>sum+landformHeight(kind,{x,z,size,h,noise,phases}),0)/features.generation.landforms.length,-12,65);}
    else {
    if(style==='meadow') h=h*.30+noise*.4;
    if(style==='highland') h=h*.92+noise*1.2;
    if(style==='craggy') h=Math.floor(h*.75/3)*3+noise*1.1;
    if(style==='tropical') h=h*.22+noise*.35+Math.exp(-((x-size*.12)**2+(z+size*.10)**2)/(size*size*.008))*13;
    if(!['meadow','highland','craggy','tropical'].includes(style))h=h*LANDSCAPES[style].height+noise*.65;
    if(style==='desert'||features.cliffs)h=Math.floor(h/5)*5+smooth((h%5)/.65)*1.2+noise*.18;
    }
    heights.push(-3+(h+3)*edge);
  }
  const world={schema:'jnsq-island/1',name:'Untitled island',style,seed:seed>>>0,size,resolution:N,heights,objects:[]};
  generateFeatures(world,features);
  if(features.generation){world.generation=structuredClone(features.generation);scatter(world,world.generation.density,world.generation.communities,world.seed,world.generation.rocks,world.generation.clustering||0);}
  else scatter(world,.55);
  return world;
}
export function heightAt(w,x,z) {
  const u=clamp((x/w.size+.5)*N,0,N),v=clamp((z/w.size+.5)*N,0,N);
  const i=Math.min(N-1,Math.floor(u)),j=Math.min(N-1,Math.floor(v)),a=u-i,b=v-j;
  const k=j*(N+1)+i,h=w.heights;
  // Same diagonal as the preview's indexed triangles, not a bilinear surrogate.
  return a+b<=1 ? h[k]+a*(h[k+1]-h[k])+b*(h[k+N+1]-h[k]) : h[k+N+2]+(1-a)*(h[k+N+1]-h[k+N+2])+(1-b)*(h[k+1]-h[k+N+2]);
}
export function slopeAt(w,x,z) {
  const step=w.size/N;
  return Math.hypot(heightAt(w,x+step,z)-heightAt(w,x-step,z),heightAt(w,x,z+step)-heightAt(w,x,z-step))/(2*step);
}
export function localPoint(b,x,z){const c=Math.cos(b.rotation),s=Math.sin(b.rotation),dx=x-b.x,dz=z-b.z;return {x:c*dx-s*dz,z:s*dx+c*dz};}
export function insideStructure(b,x,z,margin=0){const p=localPoint(b,x,z),w=b.width/2+margin,d=b.depth/2+margin;return b.shape==='round'?(p.x/w)**2+(p.z/d)**2<=1:Math.abs(p.x)<=w&&Math.abs(p.z)<=d;}
export function scatter(w,density=.55,mix='auto',arrangementSeed=w.seed,selectedRocks=null,clustering=0) {
  if(!Number.isFinite(clustering)||clustering<0||clustering>1)throw Error('Invalid scenery clustering');
  const independent=Array.isArray(selectedRocks);
  const communities=[...new Set(Array.isArray(mix)?mix:[mix])];
  const chooseLayerPlant=independent?layerSampler(w.generation?.plantLayers,communities):null;
  const palettes=independent?communities.map(id=>{if(!GENERATION_OPTIONS.communities[id])throw Error('Unknown plant community');return GENERATION_OPTIONS.communities[id].plants;}):(communities.length?communities:['auto']).map(id=>PLANT_MIXES[id]||LANDSCAPES[w.style].plants);
  if(independent&&selectedRocks.some(id=>!Object.hasOwn(GENERATION_OPTIONS.rocks,id)))throw Error('Unknown rock type');
  const columnSites=(w.columns||[]).flatMap(c=>{const n=c.length?Math.ceil(c.length/c.spacing):0;return Array.from({length:n+1},(_,i)=>({x:c.x+Math.cos(c.rotation)*c.length*(n?i/n-.5:0),z:c.z-Math.sin(c.rotation)*c.length*(n?i/n-.5:0),radius:c.radius*1.8}));});
  const rng=random(arrangementSeed^0x7a519), kept=w.objects.filter(o=>o.source!=='scatter');
  const manualCount=kept.length;
  const count=Math.min(2500-manualCount,Math.round(w.size*w.size/22*density*(independent?1:(LANDSCAPES[w.style]?.coverage||1)))), cells=new Map(), spacing=3*(1-.45*clustering);
  if(independent&&!palettes.length&&!selectedRocks.length){w.objects=kept;return;}
  const patchRandom=random(arrangementSeed^0x3957a),patches=[];
  const patchCount=Math.max(3,Math.round(w.size*w.size/1600)),patchRadius=w.size*(.075-.045*clustering);
  if(clustering)for(let attempt=0;attempt<patchCount*32&&patches.length<patchCount;attempt++){
    const x=(patchRandom()-.5)*w.size,z=(patchRandom()-.5)*w.size;
    if(heightAt(w,x,z)>=.65&&slopeAt(w,x,z)<=1.3)patches.push({x,z});
  }
  for(const o of kept) cells.set(`${Math.floor(o.x/spacing)},${Math.floor(o.z/spacing)}`,true);
  for(let k=0;k<count*8 && kept.length<count+manualCount;k++) {
    let x=(rng()-.5)*w.size,z=(rng()-.5)*w.size;
    if(patches.length&&patchRandom()<clustering){
      const patch=patches[Math.floor(patchRandom()*patches.length)],angle=patchRandom()*Math.PI*2;
      const radius=patchRadius*Math.sqrt(-2*Math.log(Math.max(Number.EPSILON,patchRandom())));
      x=patch.x+Math.cos(angle)*radius;z=patch.z+Math.sin(angle)*radius;
    }
    if(Math.abs(x)>w.size/2||Math.abs(z)>w.size/2)continue;
    const y=heightAt(w,x,z),slope=slopeAt(w,x,z);
    const roll=rng(),sizeRoll=rng(),rotation=rng()*Math.PI*2;
    // Equal community shares, independent of how many species each contains.
    const rockShare=independent?(selectedRocks.length?(palettes.length?.25:1):0):.36;
    const choice=clamp((roll-rockShare)/(1-rockShare||1),0,1-Number.EPSILON)*palettes.length;
    const palette=palettes[Math.floor(choice)]||[],speciesRoll=choice-Math.floor(choice);
    const stones=slope>.55?['rock','slate_rock','basalt_rock','standing_rock']:['rock','river_rock','rock_cluster'];
    const kind=independent?(selectedRocks.length&&(slope>.55||roll<rockShare)?selectedRocks[k%selectedRocks.length]:chooseLayerPlant?chooseLayerPlant(clamp((roll-rockShare)/(1-rockShare||1),0,1-Number.EPSILON)):palette[Math.min(palette.length-1,Math.floor(speciesRoll*palette.length))]):slope>.55||roll<.21?stones[k%stones.length]:roll<.36?'shrub':palette[Math.min(palette.length-1,Math.floor(speciesRoll*palette.length))];
    if(!kind)continue;
    // A continuous upper tail gives forests mature canopy trees among smaller growth.
    // Reuse the seeded size draw; shrubs and rocks retain their original range.
    const scale=generatedTreeScale(kind,`s${k}`,sizeRoll,w.generation)??(.7+sizeRoll*.9+(SOLID_TREE_IDS.includes(kind)?1.35*sizeRoll**3:0));
    if(y<.65||slope>1.3||(w.structures||[]).some(b=>insideStructure(b,x,z,4*scale)))continue;
    if(independent&&slope>.55&&!selectedRocks.length)continue;
    if(columnSites.some(p=>Math.hypot(x-p.x,z-p.z)<p.radius+2*scale))continue;
    if((w.features||[]).some(f=>featureDistance(f,x,z)<f.width/2+1.5*scale))continue;
    if((w.stepRoutes||[]).some(r=>featureDistance({points:[r.a,r.b]},x,z)<r.width/2+2*scale))continue;
    const cx=Math.floor(x/spacing),cz=Math.floor(z/spacing),key=`${cx},${cz}`;
    if(cells.has(key))continue;
    cells.set(key,true);
    kept.push({id:`s${k}`,kind,x,z,scale,rotation,source:'scatter'});
  }
  w.objects=kept;
}
export function sculpt(w,x,z,radius,strength,mode,target=0) {
  const old=w.heights.slice(),step=w.size/N;
  const imin=clamp(Math.floor((x-radius+w.size/2)/step),1,N-1),imax=clamp(Math.ceil((x+radius+w.size/2)/step),1,N-1);
  const jmin=clamp(Math.floor((z-radius+w.size/2)/step),1,N-1),jmax=clamp(Math.ceil((z+radius+w.size/2)/step),1,N-1);
  for(let j=jmin;j<=jmax;j++)for(let i=imin;i<=imax;i++){
    const d=Math.hypot(i*step-w.size/2-x,j*step-w.size/2-z)/radius;if(d>=1)continue;
    const k=j*(N+1)+i,weight=mode==='cliff'?smooth((1-d)*8):smooth(1-d);
    let h=old[k];
    if(mode==='raise'||mode==='cliff')h+=strength*weight;
    if(mode==='lower')h-=strength*weight;
    if(mode==='flatten')h+=(target-h)*clamp(strength*.3*weight,0,1);
    if(mode==='smooth')h+=((old[k-1]+old[k+1]+old[k-N-1]+old[k+N+1])/4-h)*clamp(strength*weight,0,1);
    w.heights[k]=clamp(h,-12,65);
  }
}
