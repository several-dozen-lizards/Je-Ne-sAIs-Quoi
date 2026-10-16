// The public traveller uses the host's ordinary travel route and membership.
export async function choosePublicDestination({member,json,status,onTravelState}){
  try{
    const world=await json('/api/world');
    const dialog=document.createElement('dialog'),title=document.createElement('h2');
    title.textContent='Travel to…';dialog.append(title);
    const current=world.where[member];
    for(const [id,room] of Object.entries(world.rooms)){
      if(id===current)continue;
      const button=document.createElement('button');button.textContent=room.name||id;
      button.onclick=async()=>{
        dialog.querySelectorAll('button').forEach(b=>b.disabled=true);
        onTravelState?.(true);
        try{
          await json('/api/public-worlds/travel',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({member,to:id,expected_room:current})});
          location.assign('/3d/?member='+encodeURIComponent(member));
        }catch(error){onTravelState?.(false);title.textContent=error.message;dialog.querySelectorAll('button').forEach(b=>b.disabled=false);}
      };dialog.append(button);
    }
    const close=document.createElement('button');close.textContent='Stay here';close.onclick=()=>dialog.close();dialog.append(close);
    dialog.addEventListener('close',()=>dialog.remove(),{once:true});document.body.append(dialog);dialog.showModal();
  }catch(error){status(error.message,true)}
}
