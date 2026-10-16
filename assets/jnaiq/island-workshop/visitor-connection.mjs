export async function roomJson(url,{signal,timeoutMs=15000,...options}={}){
  const controller=new AbortController();
  const abort=()=>controller.abort();
  if(signal?.aborted)abort();else signal?.addEventListener('abort',abort,{once:true});
  const timer=setTimeout(abort,timeoutMs);
  try{
    const response=await fetch(url,{...options,signal:controller.signal});
    const value=await response.json();
    if(!response.ok||value.error){const error=Error(value.error||'Room request failed');error.status=response.status;throw error;}
    return value;
  }finally{clearTimeout(timer);signal?.removeEventListener('abort',abort);}
}

export function recoveryPause(ms,signal){
  return new Promise(resolve=>{
    if(signal.aborted){resolve();return;}
    const finish=()=>{clearTimeout(timer);signal.removeEventListener('abort',finish);resolve();};
    const timer=setTimeout(finish,ms);signal.addEventListener('abort',finish,{once:true});
  });
}

// Only repeat observation requests. Movement and other actions are never replayed.
export async function watchRoomConnection({connect,wait,apply,signal,onConnect,onDisconnect,pause=recoveryPause}){
  let failures=0;
  while(!signal.aborted){
    try{
      let cursor=await connect();
      if(signal.aborted)return;
      onConnect();
      while(!signal.aborted){
        const packet=await wait(cursor);
        if(signal.aborted)return;
        cursor=await apply(packet,cursor);
        failures=0;
      }
    }catch(error){
      if(signal.aborted)return;
      if(error.status>=400&&error.status<500&&![408,429].includes(error.status))throw error;
      // Chromium variants use either AbortError or TimeoutError for expiry.
      // A disconnect must not permanently terminate the event stream.
      onDisconnect(error);
      await pause(Math.min(30000,1000*2**Math.min(failures++,5)),signal);
    }
  }
}
