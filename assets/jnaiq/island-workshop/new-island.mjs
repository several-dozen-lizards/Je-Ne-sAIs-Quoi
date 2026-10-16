// Keep the decision modal open while saving; a failed save must not discard
// the current island or allow edits to race the saved snapshot.
export function promptNewIsland({name,save,create,errorMessage=()=>''}){
  const dialog=document.createElement('dialog');dialog.id='newIslandDialog';
  const title=document.createElement('h2');title.textContent='Start a new island?';
  const text=document.createElement('p');text.textContent=`Save “${name||'Untitled island'}” before opening a fresh island?`;
  const detail=document.createElement('p');detail.textContent='Starting fresh clears this editing session. Any version already saved in My islands will remain there.';
  const error=document.createElement('p');error.setAttribute('role','alert');error.style.color='#ffb4a0';
  const cancel=document.createElement('button');cancel.textContent='Cancel';
  const discard=document.createElement('button');discard.textContent='Discard changes & new';
  const keep=document.createElement('button');keep.textContent='Save & new';keep.className='primary';
  let working=false;
  let resolveClosed;
  const closed=new Promise(resolve=>{resolveClosed=resolve;});
  function cleanup(){dialog.remove();resolveClosed();}
  function close(){dialog.close();cleanup();}
  const buttons=[cancel,discard,keep];
  function lock(value){working=value;for(const b of buttons)b.disabled=value;}
  async function proceed(withSave){
    if(working)return;lock(true);error.textContent='';
    try{
      if(withSave&&await save()!==true){error.textContent=errorMessage()||'The save did not complete. Your current island is still open.';return;}
      await create();close();
    }catch(e){error.textContent=e.message||'Could not start a new island.';}
    finally{lock(false);}
  }
  cancel.onclick=close;discard.onclick=()=>proceed(false);keep.onclick=()=>proceed(true);
  dialog.addEventListener('cancel',e=>{if(working)e.preventDefault();});
  dialog.append(title,text,detail,error,...buttons);document.body.append(dialog);
  dialog.addEventListener('close',cleanup,{once:true});
  dialog.showModal();cancel.focus();return closed;
}
