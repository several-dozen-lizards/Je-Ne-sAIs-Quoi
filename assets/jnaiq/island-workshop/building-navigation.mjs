// Keep the original form nodes and editor listeners alive while changing layout.
export function buildingPickGesture(tool,event,furnitureOwnsPointer=false){
  if(tool!=='orbit'||event.button!==0||event.altKey||furnitureOwnsPointer)return null;
  return {x:event.clientX,y:event.clientY,id:event.pointerId};
}

export function installBuildingNavigation(aside,panel,activate){
  const $=id=>document.getElementById(id),building=$('build-home');
  const inspector=document.createElement('section');inspector.id='buildingInspector';inspector.hidden=true;
  const title=document.createElement('h2');title.textContent='Building editor';inspector.append(title);
  const selected=document.createElement('div');selected.className='building-selection';
  for(const id of ['buildingList','buildingCutaway'])selected.append(document.querySelector(`label[for="${id}"]`),$(id));
  inspector.append(selected,building);panel.append(inspector);
  $('drawPartition').after($('partitionFeedback'));
  const groups=new Map(),nav=document.createElement('nav');nav.className='building-navigation';nav.setAttribute('aria-label','Building tasks');
  const general=document.createElement('div');general.id='buildingGeneral';
  const candidates=[['general','Structure','Create, resize, rotate and move',general],['interiors','Interior walls','Divide rooms and add doors',$('partitionFloor').closest('.workshop-category')],['components','Walls & openings','Storeys, windows, doors and roof',$('buildingComponents')],['finishes','Materials','Surfaces and custom textures',$('floorMaterial').closest('.workshop-category')],['pool','Pool','Water and pool construction',$('poolEnabled').closest('.workshop-category')]];
  const special=new Set(candidates.slice(1).map(v=>v[3]));
  for(const child of [...building.children])if(!special.has(child))general.append(child);
  building.prepend(general);
  const footprintControls=document.createElement('div');
  for(const id of ['buildingShape','drawBuilding']){const label=document.querySelector(`label[for="${id}"]`);if(label)footprintControls.append(label);footprintControls.append($(id));}
  general.prepend(footprintControls);
  const pavilion=$('buildingEnclosure').parentElement,optional=document.createElement('details'),summary=document.createElement('summary');summary.textContent='Open pavilion / columns';pavilion.before(optional);optional.append(summary,pavilion);
  candidates.splice(1,0,['pavilion','Column buildings','Use columns instead of walls',general]);
  let active='general';
  function show(key){if(!groups.has(key))key='general';active=key;const selectedNode=groups.get(key).node;for(const [id,{node,button}] of groups){node.hidden=node!==selectedNode;if(node.tagName==='DETAILS')node.open=true;button.setAttribute('aria-pressed',String(id===key));}if(key==='pavilion')optional.open=true;title.textContent=groups.get(key).label;panel.scrollTop=0;}
  for(const [key,label,hint,node] of candidates){if(!node)continue;const button=document.createElement('button');button.type='button';button.innerHTML=`<strong>${label}</strong><span>${hint}</span>`;button.onclick=()=>{window.dispatchEvent(new Event('island-building-task'));show(key);};nav.append(button);groups.set(key,{node,button,label});}
  panel.append(nav);
  const hint=document.createElement('p');hint.textContent='Choose a task above, then edit the selected building below. Interior view hides upper floors and the roof.';panel.append(hint,inspector);
  function setActive(enabled){inspector.hidden=!enabled;aside.parentElement.classList.toggle('editing-buildings',enabled);}
  document.addEventListener('click',event=>{const id=event.target.closest('button')?.id;if(['interiorWallControls','drawPartition'].includes(id)){activate('buildings');show('interiors');}else if(['buildHouse','drawBuilding','houseSettings'].includes(id))show('general');},true);
  $('buildingCutaway').addEventListener('change',()=>{if($('buildingCutaway').value!=='all')show('interiors');});
  const style=document.createElement('style');style.textContent=`
    main.editing-buildings{grid-template-columns:300px minmax(0,1fr)}
    main.editing-buildings .ribbon-panels,main.editing-buildings #workshopRibbon .ribbon-panel{height:112px}
    #buildingInspector[hidden],#buildingInspector [hidden]{display:none!important}
    #buildingInspector{border:0;margin:0;padding:0}#buildingInspector section{border:0;padding:0}
    #buildingInspector h2{color:var(--gold);font-size:14px}#buildingInspector #build-home>div>h2{display:none}
    #buildingInspector input,#buildingInspector select{max-width:100%;box-sizing:border-box}
    #buildingInspector input[type=checkbox]{width:auto;display:inline-block;margin:0 7px 0 0}#buildingInspector label:has(input[type=checkbox]){display:flex;align-items:center;gap:5px}
    #buildingInspector .workshop-category{margin:10px 0}#buildingInspector .row{display:flex;gap:8px;flex-wrap:wrap}
    #buildingInspector .row>div{flex:1;min-width:95px}#buildingInspector .row button{flex:1}
    #buildingInspector p{font-size:12px;line-height:1.5}#partitionFeedback{color:var(--gold)}
    #workshopRibbon #ribbon-panel-buildings{overflow:auto}
    .building-navigation{display:flex;gap:10px;flex-wrap:wrap}.building-navigation button{width:180px;text-align:left;white-space:normal}
    .building-navigation strong,.building-navigation span{display:block}.building-navigation span{font-size:11px;margin-top:6px;color:var(--dim)}
    .building-navigation button[aria-pressed=true]{border-color:var(--gold);background:#334740;color:var(--ink)}
    .building-selection{border-bottom:1px solid var(--line);padding-bottom:12px}
    #buildingInspector #houseTools{display:none}
    @media(max-width:750px){main.editing-buildings{grid-template-columns:240px minmax(0,1fr)}}
  `;document.head.append(style);show(active);
  return {setActive,reveal(node){if(!inspector.contains(node))return false;activate('buildings');for(const [key,{node:group}] of groups)if(group===node||group.contains(node)){show(key);break;}return true;}};
}
