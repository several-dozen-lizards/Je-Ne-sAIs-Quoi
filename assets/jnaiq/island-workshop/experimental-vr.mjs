// Opt-in preference only: headset entry stays with the existing renderer.
let enabled=false;
const listeners=new Set();
const channel=typeof BroadcastChannel==='function'?new BroadcastChannel('jnaiq-vr-preference'):null;
if(channel)channel.onmessage=()=>refreshVr();
export function vrEnabled(){return enabled}
export function onVrChange(listener){listeners.add(listener)}
function update(value){const next=value===true;if(next===enabled)return;enabled=next;for(const listener of listeners)listener(enabled)}
async function request(options){
  const response=await fetch('/api/3d/experimental-vr',{cache:'no-store',...options});
  const value=await response.json();
  if(!response.ok)throw Error(value.error||'VR settings are unavailable.');
  return value;
}
export async function refreshVr(){try{update((await request()).enabled)}catch{update(false)}}
const container=document.getElementById('experimentalVr')||document.getElementById('page-appearance');
if(container){
  const card=document.createElement('section');card.className='card';
  card.style.marginTop='20px';
  card.innerHTML=`<h2>Experimental VR</h2><p class="note">Very much a work in progress. VR is untested across headsets and may be slow, clunky, or fail to connect. Tracking and controls may not work as expected. Leave the headset view if it feels uncomfortable.</p><label style="display:flex;align-items:center;gap:12px"><input type="checkbox" style="width:auto" disabled> Enable experimental VR in Worlds</label><p class="note">Off by default. This preference is saved for this JNAIQ installation. It does not install a renderer or start a headset session. With a compatible runtime, open a 3D view from Worlds and use its HEADSET control.</p><p class="note">Install the optional world assets with INSTALL_3D_RUNTIME.bat before importing a world. Headset support remains experimental and untested on physical hardware.</p><p role="status" aria-live="polite"></p>`;
  container.append(card);
  const toggle=card.querySelector('input'),status=card.querySelector('[role=status]');
  let token='';
  onVrChange(value=>{toggle.checked=value});
  try{const value=await request();token=value.token;update(value.enabled);toggle.disabled=false;status.textContent=enabled?'Experimental VR enabled. Runtime and headset still required.':'Experimental VR is off.'}
  catch(error){status.textContent=error.message}
  toggle.onchange=async()=>{
    const before=enabled;toggle.disabled=true;
    try{
      const value=await request({method:'POST',headers:{'Content-Type':'application/json','X-JNAIQ-3D-Token':token},body:JSON.stringify({enabled:toggle.checked})});
      update(value.enabled);
      channel?.postMessage('changed');
      status.textContent=enabled?'Experimental VR enabled. Runtime and headset still required.':'Experimental VR is off.';
      if(parent!==window)parent.postMessage({type:'jnaiq-vr-preference-changed'},location.origin);
    }catch(error){update(before);toggle.checked=before;status.textContent=error.message}
    finally{toggle.disabled=false}
  };
}
