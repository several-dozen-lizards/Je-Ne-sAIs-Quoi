import * as THREE from './vendor/three.module.js';
import {COLUMN_STYLES,columnGeometry,columnPositions,validateColumns} from './columns.mjs';
import {heightAt} from './terrain.mjs?caves=retired';
import {buildingMaterial} from './building-materials.mjs';

export function installPavilionControls(section){
  const panel=document.createElement('div');panel.innerHTML='<label for="buildingEnclosure">Walls or open columns</label><select id="buildingEnclosure"><option value="walls">Enclosed walls</option><option value="columns">Columns instead of walls / open pavilion</option></select><label for="pavilionColumnStyle">Pavilion column style</label><select id="pavilionColumnStyle"></select><label for="pavilionSpacing">Maximum column spacing (m)</label><input id="pavilionSpacing" type="number" min="2" max="8" step=".5" value="4"><p>Open pavilions retain their floor and chosen roof. Each storey has its own supports. Column finish follows its style; existing interior partitions remain editable.</p>';
  section.querySelector('label[for="buildingShape"]').before(panel);
  const $=id=>panel.querySelector('#'+id);$('pavilionColumnStyle').replaceChildren(...Object.entries(COLUMN_STYLES).map(([id,a])=>new Option(a.name,id)));
  const syncDisabled=()=>{for(const id of ['pavilionColumnStyle','pavilionSpacing'])$(id).disabled=$('buildingEnclosure').value!=='columns';};$('buildingEnclosure').onchange=syncDisabled;syncDisabled();
  return {read:()=>({enclosure:$('buildingEnclosure').value,columnStyle:$('pavilionColumnStyle').value,columnSpacing:Number($('pavilionSpacing').value)}),select:b=>{$('buildingEnclosure').value=b.enclosure||'walls';$('pavilionColumnStyle').value=b.columnStyle||'doric';$('pavilionSpacing').value=b.columnSpacing||4;syncDisabled();}};
}

export function installColumnEditor({scene,canvas,pick,world,remember,rebuild,changed,status,chooseTool,invalidate,frame}){
  const $=id=>document.getElementById(id),section=document.createElement('section');section.id='column-workshop';
  section.innerHTML=`<h2>Columns & colonnades</h2><p>Place a single column or mark the ends of a row. Rows follow the ground. For a roofed, open space, choose Columns instead of walls in House settings.</p>
  <label for="columnStyle">Column style</label><select id="columnStyle"></select>
  <div class="row"><div><label for="columnHeight">Height (m)</label><input id="columnHeight" type="number" min="1" max="16" step=".1" value="4"></div><div><label for="columnRadius">Shaft radius (m)</label><input id="columnRadius" type="number" min=".1" max="1.5" step=".05" value=".3"></div></div>
  <label for="columnSpacing">Maximum spacing (m)</label><input id="columnSpacing" type="number" min="1" max="12" step=".25" value="3">
  <label for="columnMaterial">Column finish</label><select id="columnMaterial"><option value="stone">Stone</option><option value="marble">Marble</option><option value="timber">Timber</option><option value="plaster">Plaster</option><option value="concrete">Concrete</option><option value="copper">Copper</option><option value="brick">Brick</option></select>
  <div class="row"><button id="singleColumn">Place one column</button><button id="columnRow">Draw column row</button></div>
  <label for="columnList">Selected column / row</label><select id="columnList"></select>
  <div class="row"><div><label for="columnLength">Row length (m)</label><input id="columnLength" type="number" min="0" max="80" step=".25" value="0"></div><div><label for="columnRotation">Rotation (degrees)</label><input id="columnRotation" type="number" min="-360" max="360" step="15" value="0"></div></div>
  <button id="applyColumns" class="wide">Apply to selected columns</button><div class="row"><button id="moveColumns">Move</button><button id="frameColumns">Frame</button><button id="removeColumns">Remove</button></div><p>Spacing is the maximum distance between centres; the row includes both endpoints. Capitals need at least four shaft radii between centres. Escape cancels. Undo restores edits and removals.</p>`;
  document.getElementById('build-home').after(section);
  $('columnStyle').replaceChildren(...Object.entries(COLUMN_STYLES).map(([id,a])=>new Option(a.name,id)));
  $('columnStyle').onchange=()=>{$('columnMaterial').value=COLUMN_STYLES[$('columnStyle').value].material;};
  const shortcut=document.createElement('button');shortcut.textContent='Columns';shortcut.id='openColumns';$('houseTools').append(shortcut);shortcut.onclick=()=>{cancel();chooseTool('orbit');section.scrollIntoView({block:'start'});$('columnStyle').focus({preventScroll:true});};
  const group=new THREE.Group();scene.add(group);
  const preview=new THREE.Line(new THREE.BufferGeometry(),new THREE.LineBasicMaterial({color:0xffd77b,depthTest:false}));preview.renderOrder=12;preview.visible=false;scene.add(preview);
  let selected='',signature='',mode=null,anchor=null;
  const current=()=>world().columns?.find(c=>c.id===selected);
  const options=()=>({style:$('columnStyle').value,height:Number($('columnHeight').value),radius:Number($('columnRadius').value),spacing:Number($('columnSpacing').value),material:$('columnMaterial').value});
  function sync(){const c=current();if(!c)return;$('columnStyle').value=c.style;$('columnHeight').value=c.height;$('columnRadius').value=c.radius;$('columnSpacing').value=c.spacing;$('columnMaterial').value=c.material;$('columnLength').value=c.length.toFixed(2);$('columnRotation').value=(c.rotation*180/Math.PI).toFixed(1);}
  function refresh(){
    while(group.children.length){const m=group.children[0];group.remove(m);m.geometry.dispose();m.material.dispose();}
    for(const c of world().columns||[]){const points=columnPositions(c),mesh=new THREE.InstancedMesh(columnGeometry(c.style,c.height,c.radius),buildingMaterial(c.material),points.length);mesh.castShadow=true;mesh.receiveShadow=true;points.forEach((p,i)=>mesh.setMatrixAt(i,new THREE.Matrix4().makeRotationY(c.rotation).setPosition(p.x,heightAt(world(),p.x,p.z),p.z)));mesh.userData.columnId=c.id;group.add(mesh);}
    if(!current())selected=world().columns?.[0]?.id||'';
    $('columnList').replaceChildren(...(world().columns?.length?world().columns.map((c,i)=>new Option(`${i+1}. ${COLUMN_STYLES[c.style].name} · ${columnPositions(c).length} column${c.length?'s':''}`,c.id)):[new Option('No columns yet','')]));$('columnList').value=selected;
    for(const id of ['applyColumns','moveColumns','frameColumns','removeColumns'])$(id).disabled=!current();
    const next=JSON.stringify(current());if(next!==signature){sync();signature=next;}invalidate();
  }
  function cancel(){mode=null;anchor=null;preview.visible=false;invalidate();}
  function begin(next){cancel();chooseTool('orbit');mode=next;status(next==='single'?'Click dry ground for one column.':next==='move'?'Click the new centre for these columns.':'Click the first end of the column row, then the other end.');}
  function check(c,replacing=false){const all=(world().columns||[]).filter(o=>!replacing||o.id!==c.id);validateColumns([...all,c],world().size);for(const p of columnPositions(c))for(const [dx,dz] of [[0,0],[1,0],[-1,0],[0,1],[0,-1]])if(heightAt(world(),p.x+dx*c.radius*1.8,p.z+dz*c.radius*1.8)<.1)throw Error('Keep each column base on dry land.');}
  function commit(c,replacing=false){check(c,replacing);remember();if(replacing)world().columns=world().columns.map(o=>o.id===c.id?c:o);else(world().columns??=[]).push(c);const points=columnPositions(c);world().objects=world().objects.filter(o=>o.source!=='scatter'||!points.some(p=>Math.hypot(o.x-p.x,o.z-p.z)<c.radius*1.8+2*o.scale));selected=c.id;cancel();rebuild();changed('Columns placed / updated · Undo restores the previous arrangement');}
  $('singleColumn').onclick=()=>begin('single');$('columnRow').onclick=()=>begin('row');$('moveColumns').onclick=()=>begin('move');
  $('columnList').onchange=()=>{cancel();selected=$('columnList').value;sync();};
  $('applyColumns').onclick=()=>{try{if(current())commit({...current(),...options(),length:Number($('columnLength').value),rotation:Number($('columnRotation').value)*Math.PI/180},true);}catch(e){status(e.message,true);}};
  $('removeColumns').onclick=()=>{if(!current())return;remember();world().columns=world().columns.filter(c=>c.id!==selected);cancel();refresh();changed('Columns removed · Undo restores them');};
  $('frameColumns').onclick=()=>{const c=current();if(c)frame({x:c.x,z:c.z,y:heightAt(world(),c.x,c.z),width:Math.max(c.length,6),depth:6,floors:c.height/3.2});};
  canvas.addEventListener('pointerdown',event=>{
    if(!mode||event.button!==0||event.altKey)return;event.preventDefault();event.stopImmediatePropagation();const p=pick(event);if(!p)return;
    try{
      if(mode==='move'){if(current())commit({...current(),x:p.x,z:p.z},true);return;}
      if(mode==='row'&&!anchor){anchor=p.clone();status('Click the other end of the row.');return;}
      const a=mode==='single'?p:anchor,c={id:crypto.randomUUID(),...options(),x:(a.x+p.x)/2,z:(a.z+p.z)/2,length:Math.hypot(p.x-a.x,p.z-a.z),rotation:mode==='single'?0:-Math.atan2(p.z-a.z,p.x-a.x)};
      if(mode==='row'&&c.length<1)throw Error('Mark a row at least one metre long.');commit(c);
    }catch(e){status(e.message,true);}
  },true);
  canvas.addEventListener('pointermove',event=>{if(!mode||!anchor)return;const p=pick(event);if(!p)return;preview.geometry.dispose();preview.geometry=new THREE.BufferGeometry().setFromPoints([anchor.clone().add(new THREE.Vector3(0,.3,0)),p.clone().add(new THREE.Vector3(0,.3,0))]);preview.visible=true;invalidate();});
  document.addEventListener('keydown',event=>{if(event.key==='Escape')cancel();});
  document.addEventListener('click',event=>{if(!section.contains(event.target)&&event.target!==canvas&&event.target.closest('button,select'))cancel();});
  refresh();return {refresh,cancel};
}
