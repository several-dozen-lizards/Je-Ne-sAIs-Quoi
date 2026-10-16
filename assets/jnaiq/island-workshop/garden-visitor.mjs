import {createGardenLayer} from './garden-render.mjs';
import {heightAt} from './terrain.mjs';

export function installGardenVisitor({scene,world,member,bar,canvas,walk,use,place,invalidate,status}){
  const layer=createGardenLayer(scene,invalidate);layer.sync(world);
  const button=document.createElement('button');button.textContent='Garden';bar.append(button);
  let snapshot=null,dialog=null,selected=null,pending=false,feedback='';
  const style=document.createElement('style');style.textContent='.shared-garden{color:#e7efdf;background:#142c29;border:1px solid #658d70;border-radius:16px;padding:24px;width:min(500px,calc(100vw - 70px));max-height:80vh;overflow:auto}.shared-garden::backdrop{background:#07161188}.shared-garden h2{margin:0 0 6px}.shared-garden p{line-height:1.5}.shared-garden button{margin:4px 5px 4px 0;padding:8px 12px}.shared-garden select{width:100%;margin:10px 0}.garden-progress{height:8px;background:#071611;border-radius:5px;overflow:hidden}.garden-progress span{display:block;height:100%;background:#9dbd76}.shared-garden small{display:block;color:#bdd0b7;line-height:1.5}.garden-receipt{border-top:1px solid #36594b;padding-top:10px}';document.head.append(style);
  const controlsStyle=document.createElement('style');controlsStyle.textContent='.shared-garden select{background:#223e36;color:#e7efdf;border:1px solid #658d70;border-radius:6px;padding:8px;font:inherit}.shared-garden button:disabled{opacity:.45;cursor:default}.shared-garden [role=status]{color:#d4dc9a;border-left:2px solid #86a572;padding-left:10px}';document.head.append(controlsStyle);
  function draw(restoreAction){
    if(!dialog||pending)return;
    const focusKey=restoreAction||document.activeElement?.dataset.gardenAction,focusSelect=document.activeElement?.id==='sharedGardenBeds';
    dialog.replaceChildren();const title=document.createElement('h2');title.textContent='The shared garden';dialog.append(title);
    if(feedback){const message=document.createElement('p');message.setAttribute('role','status');message.textContent=feedback;dialog.append(message);}
    if(place){const add=document.createElement('button');add.textContent='+ Place garden bed';add.disabled=!snapshot?.members?.[member];add.onclick=()=>{dialog.close();place();};dialog.append(add);}
    const garden=snapshot?.garden;
    if(!garden||!garden.beds.length){const p=document.createElement('p');p.textContent='Place a bed here to start a shared garden. You and the residents can plant, water, harvest and compost.';dialog.append(p);}
    else{
      const summary=document.createElement('p');summary.textContent='Basket · '+Object.entries(garden.basket).map(([k,n])=>`${n} ${garden.crops[k].name.toLowerCase()}`).join(' · ')+`  |  Compost ${garden.compost}`;dialog.append(summary);
      const list=document.createElement('select');list.id='sharedGardenBeds';list.setAttribute('aria-label','Garden bed');
      for(const b of garden.beds)list.append(new Option(b.name,b.id));
      if(!garden.beds.some(b=>b.id===selected))selected=garden.beds[0]?.id;list.value=selected;list.onchange=()=>{selected=list.value;draw();};dialog.append(list);
      const bed=garden.beds.find(b=>b.id===selected),me=snapshot.members?.[member];
      if(bed){
        const info=document.createElement('p');info.textContent=bed.description;dialog.append(info);
        const meter=document.createElement('div');meter.className='garden-progress';meter.setAttribute('role','meter');meter.setAttribute('aria-label','Crop development');meter.setAttribute('aria-valuemin','0');meter.setAttribute('aria-valuemax','100');meter.setAttribute('aria-valuenow',String(Math.round(bed.progress*100)));const fill=document.createElement('span');fill.style.width=`${bed.progress*100}%`;meter.append(fill);dialog.append(meter);
        const object=snapshot.objects?.[bed.id];
        const near=!!me&&Math.hypot(me.position_m[0]-bed.x,-me.position_m[1]-bed.z)<=(object?.interaction_radius_m||2.2)&&Math.abs((me.height_m||0)-(object?.interaction_y_m??heightAt(world,bed.x,bed.z)))<=1.5;
        const hint=document.createElement('p');hint.textContent=near?'At the bed · seeds and water are ready to use.':'Walk to this bed to tend it.';dialog.append(hint);
        const go=document.createElement('button');go.textContent='Walk to bed';go.disabled=!me;go.onclick=async()=>{const c=Math.cos(bed.rotation),s=Math.sin(bed.rotation);dialog.close();await walk(bed.x+s*1.45,bed.z+c*1.45);};dialog.append(go);
        for(const mode of bed.modes){
          const action=document.createElement('button');action.dataset.gardenAction=mode;action.textContent=mode.startsWith('plant_')?'Plant '+garden.crops[mode.slice(6)].name.toLowerCase():mode==='water'?'Water':mode==='compost'?'Add compost':'Harvest';action.disabled=!near;
          action.onclick=async()=>{pending=true;dialog.querySelectorAll('button,select').forEach(b=>b.disabled=true);try{const result=await use(bed.id,mode);if(result.garden){snapshot={...snapshot,garden:result.garden};layer.sync(world,result.garden.beds);}feedback=result.description;status(result.description);}catch(e){feedback=e.message;status(e.message,true);}finally{pending=false;draw(mode);}};dialog.append(action);
        }
        const note=document.createElement('small');note.textContent=`${garden.pace} garden hours per real hour. Growth follows moisture, fertility and daily light exposure. The last observed weather carries forward between visits. Ripe crops wait for you.`;dialog.append(note);
      }
      const history=document.createElement('div');history.className='garden-receipt';for(const e of (garden.history||[]).slice(-4).reverse()){const p=document.createElement('small');p.textContent=e.description;history.append(p);}dialog.append(history);
    }
    const close=document.createElement('button');close.textContent='Close';close.onclick=()=>dialog.close();dialog.append(close);
    if(focusKey)(dialog.querySelector(`[data-garden-action="${focusKey}"]`)||dialog.querySelector('select'))?.focus();else if(focusSelect)dialog.querySelector('select')?.focus();
  }
  button.onclick=()=>{if(dialog){dialog.focus();return;}if(document.pointerLockElement===canvas)document.exitPointerLock();dialog=document.createElement('dialog');dialog.className='shared-garden';dialog.setAttribute('aria-label','Shared garden');dialog.addEventListener('close',()=>{dialog.remove();dialog=null;});document.body.append(dialog);draw();dialog.showModal();};
  window.addEventListener('pagehide',()=>layer.dispose(),{once:true});
  return {sync(value){snapshot=value;layer.sync(world,value.garden?.beds||[]);draw();}};
}
