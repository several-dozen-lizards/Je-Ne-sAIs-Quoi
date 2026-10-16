// The existing Godot room window hands workshop destinations to their own
// renderer. Membership remains in the same host throughout the handoff.
const member=new URLSearchParams(location.search).get('member')||'Re';
import {installRoomChat} from './room-chat.mjs';
installRoomChat(member);
const environmentButton=document.createElement('button');
environmentButton.textContent='Room settings';
environmentButton.style.cssText='position:fixed;left:12px;bottom:12px;z-index:1000;padding:10px;background:#142522;color:#edf5ed;border:1px solid #789b8c;border-radius:8px;cursor:pointer';
environmentButton.onclick=async()=>{
  try{
    const response=await fetch('/api/world');
    if(!response.ok)throw Error('Room unavailable');
    const world=await response.json();
    const url='/?room='+encodeURIComponent(world.where[member]||'nexus')+'&member='+encodeURIComponent(member);
    location.assign(url);
  }catch(error){environmentButton.textContent='Settings unavailable · try again';}
};
document.body.append(environmentButton);
const littleWorldButton=document.createElement('button');littleWorldButton.textContent='Little world · 2D';littleWorldButton.style.cssText=environmentButton.style.cssText+';left:145px';littleWorldButton.onclick=()=>location.assign('/assets/topdown/index.html?member='+encodeURIComponent(member));document.body.append(littleWorldButton);
const studioButton=document.createElement('button');studioButton.textContent='On the walls';studioButton.style.cssText=environmentButton.style.cssText+';left:300px';studioButton.onclick=async()=>{try{const w=await (await fetch('/api/world')).json();window.open('/api/rooms/'+encodeURIComponent(w.where[member]||'nexus')+'/studio','_blank','noopener');}catch(e){studioButton.textContent='Walls unavailable · try again';}};document.body.append(studioButton);
async function route(){
  const r=await fetch('/api/world');if(!r.ok)return;
  const w=await r.json(),rid=w.where[member],destination=w.rooms[rid]?.destination;
  if(destination){location.replace(destination.url+'&member='+encodeURIComponent(member));return;}
  if(!rid)return;
  const snapshot=await (await fetch('/api/rooms/'+encodeURIComponent(rid))).json();
  let seq=snapshot.last_seq||0;
  while(!document.hidden){
    const response=await fetch(`/api/rooms/${encodeURIComponent(rid)}/events/wait?since=${seq}&member=${encodeURIComponent(member)}`);
    if(!response.ok)return;
    const data=await response.json();
    for(const e of data.events||[]){seq=Math.max(seq,e.seq);if(e.kind==='depart'&&e.member===member){await route();return;}}
  }
}
let running=false;
async function start(){if(running)return;running=true;try{await route();}catch(e){console.warn('World destination routing unavailable',e);}finally{running=false;}}
document.addEventListener('visibilitychange',()=>{if(!document.hidden)start();});
start();
