export function renderRecovery(canvas,{onLost,onRestored,onFailure}){
  let lost=false,failed=false,restoring=false;
  const lose=event=>{event.preventDefault();lost=true;onLost();};
  const restore=()=>{lost=false;failed=false;restoring=true;};
  canvas.addEventListener('webglcontextlost',lose);
  canvas.addEventListener('webglcontextrestored',restore);
  return {
    frame(draw){
      if(lost||failed)return false;
      try{draw();if(restoring){restoring=false;onRestored();}return true;}
      catch(error){failed=true;onFailure(error);return false;}
    },
    dispose(){canvas.removeEventListener('webglcontextlost',lose);canvas.removeEventListener('webglcontextrestored',restore);},
  };
}

export function graphicsRecoveryPanel(stage){
  let panel;
  return {
    show(message){
      if(!panel){
        panel=document.createElement('div');panel.setAttribute('role','alert');
        panel.style.cssText='position:absolute;inset:0;z-index:20;display:grid;place-content:center;gap:16px;padding:24px;text-align:center;background:#14231f;color:#e7eee7';
        const text=document.createElement('p'),retry=document.createElement('button'),hint=document.createElement('p');
        retry.textContent='Reload 3D view';retry.onclick=()=>location.reload();
        hint.textContent='If graphics remain unavailable, press Ctrl+R to refresh the browser.';
        panel.append(text,retry,hint);stage.append(panel);
      }
      panel.firstElementChild.textContent=message;
    },
    hide(){panel?.remove();panel=null;},
  };
}
