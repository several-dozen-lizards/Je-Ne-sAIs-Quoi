// Public room speech follows the same canonical member location as the body.
export function installRoomChat(member){
  if(document.getElementById('traveller-chat'))return;
  const panel=document.createElement('details');panel.id='traveller-chat';
  panel.style.cssText='position:fixed;right:12px;bottom:12px;z-index:1000;width:min(340px,90vw);background:#142522;color:#edf5ed;padding:10px;border:1px solid #789b8c;border-radius:8px;font:14px sans-serif';
  const title=document.createElement('summary');title.textContent='Room chat';panel.append(title);
  const log=document.createElement('div');log.style.cssText='max-height:220px;overflow:auto;white-space:pre-wrap;margin:8px 0';panel.append(log);
  const input=document.createElement('textarea');input.placeholder='Say something in this room';input.style.cssText='width:100%;box-sizing:border-box';panel.append(input);
  const send=document.createElement('button');send.textContent='Send';panel.append(send);
  const note=document.createElement('div');panel.append(note);document.body.append(panel);
  for(const kind of ['keydown','keyup','pointerdown','pointerup','click'])panel.addEventListener(kind,e=>e.stopPropagation());
  let room='',seq=0,generation=0,abort=null;
  const speechFlights=new Set(),pendingSpeechIds=new Map();
  async function json(path,options={}){const r=await fetch(path,options),v=await r.json();if(!r.ok||v.error)throw Error(v.error||'Room unavailable');return v;}
  function show(events){for(const e of events){seq=Math.max(seq,Number(e.seq)||0);if(e.kind!=='say')continue;const eventSeq=Number(e.seq)||0;if(eventSeq&&log.querySelector(`[data-event-seq="${eventSeq}"]`))continue;const row=document.createElement('div');if(eventSeq)row.dataset.eventSeq=String(eventSeq);row.textContent=e.member+': '+(e.data?.text||'');log.append(row);}log.scrollTop=log.scrollHeight;}
  async function follow(){const run=++generation;abort?.abort();abort=new AbortController();
    try{const world=await json('/api/world');if(run!==generation)return;room=world.where[member]||'';log.replaceChildren();
      if(!room){title.textContent='Room chat · no current room';return;}
      const snapshot=await json('/api/rooms/'+encodeURIComponent(room));if(run!==generation)return;
      title.textContent='Room chat · '+snapshot.name;seq=Number(snapshot.last_seq)||0;
      const history=await json(`/api/rooms/${encodeURIComponent(room)}/events?since=${Math.max(0,seq-100)}`);if(run!==generation)return;show((history.events||[]).filter(e=>e.seq<=seq));
      while(panel.open&&run===generation){const data=await json(`/api/rooms/${encodeURIComponent(room)}/events/wait?since=${seq}&member=${encodeURIComponent(member)}`,{signal:abort.signal});if(run!==generation)return;
        if((data.events||[]).some(e=>e.kind==='depart'&&e.member===member)){follow();return;}
        show(data.events||[]);}
    }catch(e){if(e.name!=='AbortError')note.textContent=e.message+' · Close and reopen room chat to reconnect.';}
  }
  panel.addEventListener('toggle',()=>{if(panel.open)follow();else{generation++;abort?.abort();}});
  async function speak(){const text=input.value.trim();if(!text||!room)return;const roomAtSend=room,key=`${member}\u0000${roomAtSend}\u0000${text}`;
    if(speechFlights.has(key))return;
    if(!pendingSpeechIds.has(key))pendingSpeechIds.set(key,(crypto.randomUUID?crypto.randomUUID():`room-${Date.now()}-${Math.random()}`));
    speechFlights.add(key);const conversation_id=pendingSpeechIds.get(key);send.textContent='sending…';note.textContent='Sending…';
    try{const result=await json('/api/act',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({member,action:'say',text,conversation_id,payload:{expected_room:roomAtSend}})});
      if(input.value.trim()===text)input.value='';pendingSpeechIds.delete(key);const eventSeq=Number(result.seq)||0;if(eventSeq&&room===roomAtSend)show([{seq:eventSeq,member,kind:'say',data:{text,conversation_id}}]);note.textContent='Sent.';
    }catch(e){note.textContent='Not sent · '+e.message;}finally{speechFlights.delete(key);send.textContent=speechFlights.size?'sending…':'Send';}
  }
  send.onclick=speak;
  input.addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();speak();}});
}
