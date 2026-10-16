import {wallSegments,wallSpec,resizeStoreys,defaultOpeningShape} from './building-components.mjs';
import {OPENING_SHAPES} from './opening-shapes.mjs';
import {DOOR_STYLES} from './door-leaves.mjs';

export function installComponentEditor({section,current,world,commit,status,showFloor,moveOpening}){
  const panel=document.createElement('details');panel.id='buildingComponents';panel.open=true;
  panel.innerHTML=`<summary>Walls, openings, doors & glass</summary>
    <button id="interiorWallControls" class="wide">Interior walls & doors</button>
    <p><a href="/assets/island-workshop/door-gallery.html" target="_blank" rel="noopener">Browse the four door styles ↗</a></p>
    <p>Select a storey and exterior wall. Openings are measured from that wall’s centre. Removing an opening fills it with wall; removing a frame keeps the opening. Individually edited walls retain their opening shapes when building defaults change.</p>
    <label for="componentFloor">Storey</label><select id="componentFloor"></select>
    <div class="row"><button id="addStorey">Add top storey</button><button id="removeStorey">Remove top storey</button></div>
    <label for="componentWall">Exterior wall</label><select id="componentWall"></select>
    <button id="toggleWall" class="wide">Remove wall</button>
    <label for="componentOpening">Opening</label><select id="componentOpening"></select>
    <div class="row"><button id="addWindow">Add window</button><button id="addDoorway">Add doorway</button></div>
    <button id="moveOpening" class="wide">Move selected opening on its wall</button>
    <button id="removeOpening" class="wide">Remove selected opening</button>
    <label for="componentShape">Opening shape</label><select id="componentShape"></select>
    <div class="row"><div><label for="openingOffset">Position (m)</label><input id="openingOffset" type="number" step=".1"></div><div><label for="openingWidth">Width (m)</label><input id="openingWidth" type="number" min=".2" step=".1"></div></div>
    <div class="row"><div><label for="openingBottom">Sill height (m)</label><input id="openingBottom" type="number" min="0" step=".1"></div><div><label for="openingTop">Top height (m)</label><input id="openingTop" type="number" max="3.05" step=".1"></div></div>
    <label><input id="componentFrames" type="checkbox"> Add frame</label>
    <label for="componentDoor">Door leaf</label><select id="componentDoor"><option value="none">Open doorway / no door</option><option value="solid">Solid door</option></select>
    <label for="doorStyle">Door style</label><select id="doorStyle"></select>
    <label for="doorColor">Door colour</label><input id="doorColor" type="color" value="#9a5d31">
    <label for="doorImage">Door image</label><select id="doorImage"><option value="">Use colour</option></select><button id="uploadDoorImage" type="button">Upload door image</button>
    <label for="doorAngle">Door opening angle (0 = closed)</label><input id="doorAngle" type="number" min="0" max="120" step="15">
    <label for="componentGlass">Window glazing</label><select id="componentGlass"><option value="none">No glass</option><option value="clear">Clear / tinted glass</option><option value="image">Translucent image</option><option value="stained">Stained glass with opaque lead</option></select>
    <label for="glassColor">Glass colour</label><input id="glassColor" type="color" value="#a4d8ef">
    <label for="glassOpacity">Glass opacity</label><input id="glassOpacity" type="number" min=".05" max="1" step=".05" value=".4">
    <label for="glassImage">Glass image (upload with Custom surface above)</label><select id="glassImage"></select>
    <button id="applyOpening" class="wide">Apply opening, frame & glazing</button>
    <p>Door angles are saved building settings. A closed door blocks passage. Image glass uses your uploaded picture with adjustable translucency.</p>
    <label>Roof sections (relative to the building)</label>
    <div id="roofSections"></div><button id="applyRoofSections" class="wide">Apply roof sections</button>`;
  section.append(panel);const $=id=>panel.querySelector('#'+id);
  $('interiorWallControls').onclick=()=>document.getElementById('partitionFloor').scrollIntoView({block:'start'});
  $('componentShape').replaceChildren(...OPENING_SHAPES.map(k=>new Option(k,k)));
  $('doorStyle').replaceChildren(...Object.entries(DOOR_STYLES).map(([id,name])=>new Option(name,id)));
  $('roofSections').innerHTML=['Front left','Front right','Back left','Back right'].map((name,i)=>`<label><input id="roofSection${i}" type="checkbox" checked> ${name}</label>`).join('');
  const chosen=()=>{const b=current();return b?wallSpec(b,Number($('componentFloor').value),Number($('componentWall').value)):null;};
  function saveWall(w,message){const b=current();commit({...b,wallEdits:[...(b.wallEdits||[]).filter(p=>p.floor!==w.floor||p.segment!==w.segment),w]},message);}
  function attempt(fn){try{fn();}catch(e){status(e.message,true);}}
  function openingFields(){
    const o=chosen()?.openings.find(o=>o.id===$('componentOpening').value);
    for(const id of ['componentShape','openingOffset','openingWidth','openingBottom','openingTop','componentFrames','componentDoor','doorStyle','doorColor','doorImage','uploadDoorImage','doorAngle','componentGlass','glassColor','glassOpacity','glassImage','applyOpening','moveOpening','removeOpening'])$(id).disabled=!o;
    if(!o)return;
    for(const [id,key] of Object.entries({componentShape:'shape',openingOffset:'offset',openingWidth:'width',openingBottom:'bottom',openingTop:'top',componentDoor:'door',doorAngle:'angle',componentGlass:'glass',glassColor:'color',glassOpacity:'opacity'}))$(id).value=o[key];
    $('componentFrames').checked=o.frames;$('glassImage').value=o.image||'';$('doorStyle').value=o.doorStyle||'flat';$('doorColor').value=o.doorColor||'#9a5d31';$('doorImage').value=o.doorImage||'';$('componentDoor').disabled=o.kind!=='door';for(const id of ['doorStyle','doorColor','doorImage','uploadDoorImage','doorAngle'])$(id).disabled=o.kind!=='door';$('openingBottom').disabled=o.kind==='door';$('componentGlass').disabled=o.kind==='door';
  }
  function openings(){const w=chosen(),old=$('componentOpening').value;$('componentOpening').replaceChildren(...(w?.openings||[]).map((o,i)=>new Option(`${i+1}. ${o.kind} · ${o.shape} · ${o.offset.toFixed(1)} m`,o.id)));if(w?.openings.some(o=>o.id===old))$('componentOpening').value=old;$('toggleWall').textContent=w?.removed?'Restore wall':'Remove wall';openingFields();}
  function refresh(){
    const b=current(),floor=$('componentFloor').value,wall=$('componentWall').value;
    for(const button of panel.querySelectorAll('button'))button.disabled=!b;
    $('componentFloor').replaceChildren(...Array.from({length:b?.floors||1},(_,i)=>new Option(i?'Storey '+(i+1):'Ground floor',i)));$('componentFloor').value=Number(floor)<(b?.floors||1)?floor||'0':'0';
    $('componentWall').replaceChildren(...(b?wallSegments(b):[]).map((s,i)=>new Option((b.shape==='round'?`Segment ${i+1}`:['Front','Right','Back','Left'][i])+` · ${s.length.toFixed(1)} m`,i)));$('componentWall').value=Number(wall)<(b?.shape==='round'?32:4)?wall||'0':'0';
    $('glassImage').replaceChildren(new Option('Choose an image',''),...(world().textures||[]).map(t=>new Option(t.name,t.id)));$('doorImage').replaceChildren(new Option('Use colour',''),...(world().textures||[]).map(t=>new Option(t.name,t.id)));
    for(let i=0;i<4;i++)$('roofSection'+i).checked=b?.roofSections?.[i]??true;
    $('addStorey').disabled=!b||b.floors===4;$('removeStorey').disabled=!b||b.floors===1;openings();
  }
  $('componentWall').onchange=openings;$('componentOpening').onchange=openingFields;
  $('componentFloor').onchange=()=>{openings();showFloor(Number($('componentFloor').value));};
  for(const [id,delta] of [['addStorey',1],['removeStorey',-1]])$(id).onclick=()=>attempt(()=>{const b=current();commit(resizeStoreys(b,b.floors+delta),delta>0?'Top storey added':'Top storey and its walls removed · Undo restores them');});
  $('toggleWall').onclick=()=>attempt(()=>{const w=chosen();w.removed=!w.removed;saveWall(w,w.removed?'Exterior wall removed':'Exterior wall restored');});
  for(const [id,kind] of [['addWindow','window'],['addDoorway','door']])$(id).onclick=()=>attempt(()=>{
    const b=current(),w=chosen(),length=wallSegments(b)[w.segment].length,width=Math.min(kind==='door'?1.1:1.4,length-.2),sorted=[...w.openings].sort((a,b)=>a.offset-b.offset);let start=-length/2+.1,offset;
    for(const o of [...sorted,{offset:length/2+.1,width:0}]){if(o.offset-o.width/2-start>=width+.1){offset=start+width/2;break;}start=o.offset+o.width/2+.15;}
    if(offset===undefined)throw Error('No free space on this wall. Move, resize or remove an opening first.');
    w.removed=false;const o={id:crypto.randomUUID(),kind,offset,width,bottom:kind==='door'?0:.95,top:2.3,shape:defaultOpeningShape(b,kind==='door'),frames:true,door:'none',angle:0,glass:'none',color:'#a4d8ef',opacity:.4,...(kind==='door'?{doorStyle:'flat',doorColor:'#9a5d31'}:{})};w.openings.push(o);saveWall(w,kind==='door'?'Doorway added':'Window added');$('componentOpening').value=o.id;openingFields();
  });
  $('removeOpening').onclick=()=>attempt(()=>{const w=chosen();w.openings=w.openings.filter(o=>o.id!==$('componentOpening').value);saveWall(w,'Opening filled with wall');});
  $('moveOpening').onclick=()=>{const w=chosen(),openingId=$('componentOpening').value;if(w&&openingId)moveOpening?.({floor:w.floor,segment:w.segment,openingId});};
  $('applyOpening').onclick=()=>attempt(()=>{const w=chosen(),o=w.openings.find(o=>o.id===$('componentOpening').value);Object.assign(o,{shape:$('componentShape').value,offset:Number($('openingOffset').value),width:Number($('openingWidth').value),bottom:o.kind==='door'?0:Number($('openingBottom').value),top:Number($('openingTop').value),frames:$('componentFrames').checked,door:o.kind==='door'?$('componentDoor').value:'none',angle:Number($('doorAngle').value),glass:o.kind==='door'?'none':$('componentGlass').value,color:$('glassColor').value,opacity:Number($('glassOpacity').value)});if(o.kind==='door'){o.doorStyle=$('doorStyle').value;o.doorColor=$('doorColor').value;if($('doorImage').value)o.doorImage=$('doorImage').value;else delete o.doorImage;}else{delete o.doorStyle;delete o.doorColor;delete o.doorImage;}delete o.image;if(o.glass==='image')o.image=$('glassImage').value;saveWall(w,'Opening, door surface, frame and glazing updated');});
  $('uploadDoorImage').onclick=()=>document.getElementById('customSurface')?.click();
  $('applyRoofSections').onclick=()=>attempt(()=>commit({...current(),roofSections:Array.from({length:4},(_,i)=>$('roofSection'+i).checked)},'Roof sections updated'));
  function selectOpening({floor,segment,openingId},scroll=true){
    panel.open=true;$('componentFloor').value=String(floor);$('componentWall').value=String(segment);openings();$('componentOpening').value=openingId;openingFields();
    if(scroll)panel.scrollIntoView({block:'nearest'});
  }
  return {refresh,selectOpening,panel};
}
