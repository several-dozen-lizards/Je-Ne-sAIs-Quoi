// First-use help changes only help state, never a design or world.
export function readGuide(storage,key,count){
  try{const value=JSON.parse(storage.getItem(key)||'null');return {off:value?.off===true,step:Number.isInteger(value?.step)?Math.max(0,Math.min(count-1,value.step)):0};}
  catch{return {off:false,step:0};}
}
export function writeGuide(storage,key,state){try{storage.setItem(key,JSON.stringify(state));return true;}catch{return false;}}
export function installGuide({id,title,steps,parent,before=null,savedEvent}){
  let storage;try{storage=window.localStorage;}catch{storage=null;}
  const key='jnaiq.getting-started.'+id+'.v1';let state=readGuide(storage,key,steps.length);
  const box=document.createElement('details');box.className='jnaiq-guide';box.dataset.guide=id;
  const summary=document.createElement('summary');summary.textContent='✦ Help · '+title;
  const body=document.createElement('div'),heading=document.createElement('h2'),copy=document.createElement('p'),notice=document.createElement('p');notice.setAttribute('role','status');notice.className='guide-note';
  const buttons=document.createElement('div');buttons.className='guide-buttons';
  function button(label,run){const b=document.createElement('button');b.type='button';b.textContent=label;b.onclick=run;buttons.append(b);return b;}
  function persist(){if(!writeGuide(storage,key,state))notice.textContent='Your browser cannot remember this preference. Help may appear again next time.';}
  function paint(){heading.textContent=(state.step+1)+' / '+steps.length+' · '+steps[state.step].title;copy.textContent=steps[state.step].text;back.disabled=state.step===0;next.textContent=state.step===steps.length-1?'Finish guide':'Next';show.hidden=!steps[state.step].selector;}
  const back=button('Back',()=>{state.step=Math.max(0,state.step-1);persist();paint();});
  const show=button('Show this control',()=>{const node=document.querySelector(steps[state.step].selector);if(!node){notice.textContent='This control is not ready yet. Wait for the editor to finish loading.';return;}for(let p=node.parentElement;p;p=p.parentElement)if(p.tagName==='DETAILS')p.open=true;node.scrollIntoView({block:'center'});node.focus({preventScroll:true});});
  const next=button('Next',()=>{if(state.step===steps.length-1){state.off=true;persist();box.open=false;}else{state.step++;persist();paint();}});
  button('Turn off guide',()=>{state.off=true;persist();box.open=false;});
  button('Restart guide',()=>{state.step=0;state.off=false;persist();paint();});
  body.append(heading,copy,buttons,notice);box.append(summary,body);parent.insertBefore(box,before);paint();
  box.open=!state.off&&!new URLSearchParams(location.search).has('edit');
  if(new URLSearchParams(location.search).get('guide')==='1')box.open=true;
  box.addEventListener('toggle',()=>{if(box.open&&state.off){state.step=0;paint();}});
  if(savedEvent)window.addEventListener(savedEvent,()=>{state.off=true;state.step=steps.length-1;persist();box.open=false;summary.textContent='✦ Help · '+title+' · first save complete';});
  if(!document.getElementById('jnaiq-guide-style')){const style=document.createElement('style');style.id='jnaiq-guide-style';style.textContent=`
.jnaiq-guide{flex:none;box-sizing:border-box;border:1px solid var(--line,#51415f);border-radius:10px;background:var(--panel,#171322);color:var(--ink,#eae3d2);margin:12px 18px;font:14px/1.55 var(--font-ui,Georgia,serif);text-align:left;max-height:32vh;overflow:auto}.jnaiq-guide summary{padding:12px 16px;cursor:pointer;color:var(--mint,#c9ab77);font-weight:650}.jnaiq-guide>div{padding:0 16px 16px}.jnaiq-guide h2{font:22px/1.3 var(--font-display,Georgia,serif);text-transform:none;letter-spacing:normal;color:var(--gold,#f6ead0);margin:0 0 8px}.jnaiq-guide p{font:14px/1.55 system-ui;color:var(--ink,#eae3d2);max-width:850px;margin:8px 0}.jnaiq-guide .guide-buttons{display:flex;gap:8px;flex-wrap:wrap}.jnaiq-guide button{width:auto;margin:0;padding:8px 12px;border:1px solid var(--line,#63536f);border-radius:6px;background:var(--panel,#211b30);color:var(--ink,#eae3d2);font:600 13px var(--font-ui,Georgia,serif);cursor:pointer}.jnaiq-guide button:disabled{opacity:.45;cursor:default}.jnaiq-guide :focus-visible{outline:3px solid var(--gold,#f6ead0);outline-offset:2px}.jnaiq-guide .guide-note{font-size:12px}.jnaiq-guide [hidden]{display:none!important}
`;document.head.append(style);}
  return box;
}
