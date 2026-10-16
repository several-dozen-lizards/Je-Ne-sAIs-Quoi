import * as THREE from './vendor/three.module.js';
import {N,localPoint} from './terrain.mjs?caves=retired';
export const POOL_FINISHES=['marble','tiles','concrete','stone'];
export function intersectsPool(p,ax,az,bx,bz){
  let lo=0,hi=1;
  for(const [a,d,min,max] of [[ax,bx-ax,p.x-p.width/2-.3,p.x+p.width/2+.3],[az,bz-az,p.z-p.length/2-.3,p.z+p.length/2+.3]]){
    if(Math.abs(d)<1e-9){if(a<min||a>max)return false;}
    else{const t1=(min-a)/d,t2=(max-a)/d;lo=Math.max(lo,Math.min(t1,t2));hi=Math.min(hi,Math.max(t1,t2));}
  }return lo<=hi;
}
export function validatePool(b,size=160){
  const p=b.pool;if(p===undefined||p===null)return;
  if(typeof p!=='object'||![p.x,p.z,p.width,p.length,p.depth].every(Number.isFinite)||p.width<3||p.width>24||p.length<3||p.length>24||p.depth<.6||p.depth>2.4||!POOL_FINISHES.includes(p.finish)||!['none','north','south','east','west'].includes(p.steps))throw Error('Pool: use 3–24 m sides and 0.6–2.4 m depth.');
  const clearance=Math.max(1,size/N*1.5+.25);
  for(const x of [p.x-p.width/2,p.x+p.width/2])for(const z of [p.z-p.length/2,p.z+p.length/2])if(b.shape==='round'?(x/(b.width/2-clearance))**2+(z/(b.depth/2-clearance))**2>1:Math.abs(x)>b.width/2-clearance||Math.abs(z)>b.depth/2-clearance)throw Error(`Leave ${clearance.toFixed(1)} m of surrounding floor to cover the pool excavation.`);
  if(p.steps!=='none'&&Math.ceil(p.depth/.22)*.32>(['north','south'].includes(p.steps)?p.width:p.length)-.8)throw Error('Lengthen the wall for these steps, or reduce pool depth.');
  if(b.stairs&&b.floors>1&&p.x+p.width/2+.3>=.65&&p.x-p.width/2-.3<=2.95&&p.z+p.length/2+.3>=-3.3&&p.z-p.length/2-.3<=3.3)throw Error('Move the pool clear of the staircase and its landings.');
  for(const wall of b.partitions||[])if(wall.floor===0&&intersectsPool(p,wall.ax,wall.az,wall.bx,wall.bz))throw Error('Move the pool or ground-floor partition so they do not cross.');
}
export function excavatePool(w,b){
  const p=b.pool;if(!p)return;
  // Lower every vertex touching a pool cell; the surrounding floor hides the excavation margin.
  const margin=w.size/N*1.5;
  for(let j=0;j<=N;j++)for(let i=0;i<=N;i++){
    const q=localPoint(b,(i/N-.5)*w.size,(j/N-.5)*w.size);
    if(Math.abs(q.x-p.x)<=p.width/2+margin&&Math.abs(q.z-p.z)<=p.length/2+margin)w.heights[j*(N+1)+i]=Math.min(w.heights[j*(N+1)+i],b.y-p.depth-.25);
  }
}
export function poolHole(shape,p){
  if(!p)return;const h=new THREE.Path(),x=p.x,z=-p.z,w=p.width/2,d=p.length/2;
  h.moveTo(x-w,z-d);h.lineTo(x-w,z+d);h.lineTo(x+w,z+d);h.lineTo(x+w,z-d);h.closePath();shape.holes.push(h);
}
export function renderPool(p,{box,add}){
  if(!p)return;
  const {width:w,length:d,depth:h,x,z}=p;
  box(w+.4,.2,d+.4,x,-h-.1,z,'pool');
  for(const sign of [-1,1]){
    box(w+.4,h,.2,x,-h/2,z+sign*(d/2+.1),'pool');
    box(.2,h,d,x+sign*(w/2+.1),-h/2,z,'pool');
    box(w+.6,.1,.3,x,.025,z+sign*(d/2+.15),'pool');
    box(.3,.1,d,x+sign*(w/2+.15),.025,z,'pool');
  }
  if(p.steps!=='none'){
    const n=Math.ceil(h/.22),run=.32,alongX=['north','south'].includes(p.steps),sign=['north','west'].includes(p.steps)?-1:1;
    for(let i=0;i<n;i++){
      const top=-(i+1)*h/n,thickness=h+top+.12,along=-(alongX?w:d)/2+(i+.5)*run;
      box(alongX?run:1.1,thickness,alongX?1.1:run,x+(alongX?along:sign*(w/2-.55)),top-thickness/2,z+(alongX?sign*(d/2-.55):along),'pool');
    }
  }
  const water=add(new THREE.PlaneGeometry(w,d),'poolWater');water.rotation.x=-Math.PI/2;water.position.set(x,-.18,z);water.castShadow=false;
}
export function installPoolControls(section){
  const node=document.createElement('div');node.innerHTML=`<h3>Swimming pool</h3><label><input id="poolEnabled" type="checkbox"> Inset ground-floor pool</label><div id="poolFields"><div class="row"><div><label for="poolWidth">Pool width (m)</label><input id="poolWidth" type="number" min="3" max="24" step=".5" value="6"></div><div><label for="poolLength">Pool length (m)</label><input id="poolLength" type="number" min="3" max="24" step=".5" value="8"></div></div><label for="poolDepth">Water basin depth (m)</label><input id="poolDepth" type="number" min=".6" max="2.4" step=".1" value="1.4"><div class="row"><div><label for="poolX">Pool across room (m)</label><input id="poolX" type="number" step=".5" value="0"></div><div><label for="poolZ">Pool along room (m)</label><input id="poolZ" type="number" step=".5" value="0"></div></div><label for="poolSteps">Steps along inside wall</label><select id="poolSteps"><option value="north">Back wall</option><option value="south">Front wall</option><option value="west">Left wall</option><option value="east">Right wall</option><option value="none">No steps</option></select><label for="poolFinish">Basin & step finish</label><select id="poolFinish"><option value="marble">White marble</option><option value="tiles">Terracotta tiles</option><option value="concrete">Pale concrete</option><option value="stone">Stone masonry</option></select></div><p>Set size and position, then Apply to selected structure. Use Ground floor in Interior view to see inside. Steps descend beside the chosen basin wall. Ground buildings only; leave surrounding floor to cover the excavation (the required margin follows terrain resolution). Removing or moving a pool leaves its dug ground; Undo restores the excavation.</p>`;
  section.querySelector('#applyBuilding').before(node);
  const $=id=>node.querySelector('#'+id),fields={width:'poolWidth',length:'poolLength',depth:'poolDepth',x:'poolX',z:'poolZ'};
  const enabled=()=>{for(const el of $('poolFields').querySelectorAll('input,select'))el.disabled=!$('poolEnabled').checked;};$('poolEnabled').onchange=enabled;enabled();
  return {read:()=>({pool:$('poolEnabled').checked?{...Object.fromEntries(Object.entries(fields).map(([k,id])=>[k,Number($(id).value)])),steps:$('poolSteps').value,finish:$('poolFinish').value}:null}),select(b){$('poolEnabled').checked=!!b.pool;if(b.pool){for(const [k,id]of Object.entries(fields))$(id).value=b.pool[k];$('poolSteps').value=b.pool.steps;$('poolFinish').value=b.pool.finish;}enabled();}};
}
