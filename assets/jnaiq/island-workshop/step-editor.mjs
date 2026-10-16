import * as THREE from './vendor/three.module.js';
import {planStepRoute,applyStepRoute,stepRouteGeometry} from './step-routes.mjs';
export function installStepEditor({scene,canvas,controls,pick,world,getTool,chooseTool,commit,status,invalidate}){
  const button=document.createElement('button');button.dataset.tool='steps';button.textContent='Steps & slopes';button.setAttribute('aria-pressed','false');document.getElementById('tools').append(button);
  const panel=document.createElement('div');panel.hidden=true;
  panel.innerHTML='<h3>Steps & slopes</h3><label for="stepFinish">Surface</label><select id="stepFinish"><option value="built">Built stone stairs</option><option value="rock">Natural rock steps</option><option value="slope">Smooth landscape slope</option></select><label for="stepWidth">Run width (metres)</label><input id="stepWidth" type="number" min="1.5" max="12" step=".5" value="3"><p>Drag between two heights on dry land. Release to build; Escape cancels. The preview shows the whole run. Each run is one Undo. Natural scenery in its way is cleared; hand-placed objects stay protected.</p>';
  document.getElementById('toolHint').after(panel);
  const finish=panel.querySelector('select'),width=panel.querySelector('input');
  const material=new THREE.MeshBasicMaterial({color:0xabe4be,transparent:true,opacity:.65,depthTest:true});
  let start=null,pointerId=null,preview=null,planned=null;
  function clearPreview(){if(preview){scene.remove(preview);preview.geometry.dispose();preview=null;}planned=null;invalidate();}
  function cancel(){start=null;const id=pointerId;pointerId=null;clearPreview();controls.enabled=true;if(id!==null&&canvas.hasPointerCapture(id))canvas.releasePointerCapture(id);}
  button.onclick=()=>{cancel();chooseTool('steps','Drag between two terrain heights to preview steps or a slope. Release to build; Escape cancels.');panel.scrollIntoView({block:'nearest'});};
  function update(event){
    clearPreview();const end=pick(event);if(!end)return;
    try{if(!width.checkValidity())throw Error('Choose a width from 1.5 to 12 metres.');planned=planStepRoute(world(),start,end,finish.value,Number(width.value));preview=new THREE.Mesh(stepRouteGeometry(planned),material);preview.position.y=.025;scene.add(preview);status('Release to build this '+(planned.kind==='slope'?'slope':'stair run')+' · Escape cancels');}
    catch(e){status(e.message,true);}invalidate();
  }
  canvas.addEventListener('pointerdown',e=>{
    if(getTool()!=='steps'||e.button!==0||e.altKey)return;
    e.stopImmediatePropagation();e.preventDefault();cancel();start=pick(e)?.clone();if(!start)return;
    pointerId=e.pointerId;controls.enabled=false;canvas.setPointerCapture(pointerId);status('Drag to the other end of the run.');
  },true);
  canvas.addEventListener('pointermove',e=>{if(start&&e.pointerId===pointerId){e.stopImmediatePropagation();update(e);}},true);
  canvas.addEventListener('pointerup',e=>{if(!start||e.pointerId!==pointerId)return;e.stopImmediatePropagation();update(e);const r=planned;cancel();if(r){const next=structuredClone(world());applyStepRoute(next,r);commit(next,'Steps / slope added · Undo restores the terrain and scenery');}},true);
  for(const event of ['pointercancel','lostpointercapture'])canvas.addEventListener(event,e=>{if(e.pointerId===pointerId)cancel();},true);
  window.addEventListener('keydown',e=>{if(e.key==='Escape'&&start){cancel();status('Stair stroke cancelled');}});
  return {cancel,select(tool){panel.hidden=tool!=='steps'&&!panel.dataset.sidebarManaged;if(tool!=='steps')cancel();}};
}
