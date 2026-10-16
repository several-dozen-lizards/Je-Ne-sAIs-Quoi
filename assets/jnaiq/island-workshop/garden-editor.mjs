import * as THREE from './vendor/three.module.js';
import {heightAt} from './terrain.mjs';
import {placeBed,CROPS,bedPoint,BED_WIDTH,BED_DEPTH} from './garden.mjs';
export function installGardenEditor({panel,scene,world,commit,chooseTool,frame,status,invalidate=()=>{}}){
  panel.innerHTML=`<div class="garden-layout"><h2>Shared garden</h2><p>Place beds here. Publish and visit to plant, water and harvest together with residents.</p>
    <label for="gardenName">Bed name</label><input id="gardenName" maxlength="60" value="Kitchen garden">
    <label for="gardenRotation">Rotation</label><input id="gardenRotation" type="range" min="0" max="360" step="5" value="0">
    <button id="gardenPlace">Place a bed</button><p>2.4 × 1.6 metres. Click gentle, dry ground. Scenery within the bed is cleared; Undo restores the whole edit.</p></div>
    <div class="garden-layout"><h3>Your beds</h3><label for="gardenBeds">Select a bed</label><select id="gardenBeds"></select>
    <button id="gardenFind">Find bed</button><button id="gardenRename">Rename</button><button id="gardenRemove">Remove bed</button>
    <label for="gardenPace">Garden hours per real hour</label><input id="gardenPace" type="number" min="1" max="24" step="1" value="12">
    <p>Growth uses moisture, daily light exposure and soil fertility. Dry, flooded or frozen beds wait; ripe crops keep until harvested.</p>
    <p>Seeds and water are supplied at each bed. Harvests fill the shared basket and provide compost for the next crop.</p><p id="gardenCrops"></p></div>`;
  const style=document.createElement('style');style.textContent='#ribbon-panel-garden{display:block;overflow:auto}#ribbon-panel-garden .garden-layout{max-width:100%;margin-bottom:20px}#ribbon-panel-garden button{margin:4px 5px 4px 0}';document.head.append(style);
  const $=id=>panel.querySelector('#'+id);
  const outline=new THREE.LineLoop(new THREE.BufferGeometry(),new THREE.LineBasicMaterial({color:0xd9da99,depthTest:false}));outline.visible=false;outline.frustumCulled=false;outline.renderOrder=10;scene?.add(outline);
  window.addEventListener('pagehide',()=>{outline.geometry.dispose();outline.material.dispose();scene?.remove(outline);},{once:true});
  function hover(point){outline.visible=!!point;if(point){const b={x:point.x,z:point.z,rotation:Number($('gardenRotation').value)*Math.PI/180};outline.geometry.setFromPoints([[-1,-1],[1,-1],[1,1],[-1,1]].map(([x,z])=>{const p=bedPoint(b,x*BED_WIDTH/2,z*BED_DEPTH/2);return new THREE.Vector3(p.x,heightAt(world(),p.x,p.z)+.18,p.z);}));}invalidate();}
  $('gardenCrops').textContent='First crops: '+Object.values(CROPS).map(c=>c.name.toLowerCase()).join(', ')+'.';
  const mutate=(f,message)=>{const next=structuredClone(world());next.garden??={beds:[],pace:12};f(next.garden);commit(next,message);};
  const selected=()=>world().garden?.beds.find(b=>b.id===$('gardenBeds').value);
  $('gardenPlace').onclick=()=>chooseTool('garden','Click dry, gentle ground to place this garden bed. Escape cancels.');
  $('gardenFind').onclick=()=>{const b=selected();if(b)frame(b);};
  $('gardenRename').onclick=()=>{const b=selected(),name=$('gardenName').value.trim();if(b&&name)mutate(g=>g.beds.find(v=>v.id===b.id).name=name,'Garden bed renamed');};
  $('gardenRemove').onclick=()=>{const b=selected();if(b)mutate(g=>g.beds=g.beds.filter(v=>v.id!==b.id),'Bed removed from layout · Undo restores it');};
  $('gardenPace').onchange=()=>{const pace=Number($('gardenPace').value);if(!Number.isFinite(pace)||pace<1||pace>24){status('Use a pace between 1 and 24.',true);refresh();return;}mutate(g=>g.pace=pace,'Garden pace changed · applies when published');};
  $('gardenBeds').onchange=()=>{const b=selected();if(b)$('gardenName').value=b.name;};
  function refresh(){const id=$('gardenBeds').value;$('gardenBeds').replaceChildren(...(world().garden?.beds||[]).map(b=>new Option(b.name,b.id)));if([...$('gardenBeds').options].some(o=>o.value===id))$('gardenBeds').value=id;const empty=!selected();for(const k of ['gardenFind','gardenRename','gardenRemove'])$(k).disabled=empty;$('gardenPace').value=world().garden?.pace||12;}
  refresh();
  return {refresh,hover,click(point){try{
    const b={id:'garden_'+crypto.randomUUID(),name:$('gardenName').value.trim()||'Garden bed',x:point.x,z:point.z,rotation:Number($('gardenRotation').value)*Math.PI/180};
    commit(placeBed(world(),b),'Garden bed placed · Save and publish to garden together');$('gardenBeds').value=b.id;
  }catch(e){status(e.message,true);}}};
}
