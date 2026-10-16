// Full-world replacement is available only during an explicit New session.
export function installCreationRibbon(land){
  const ribbon=document.createElement('section');ribbon.id='creationRibbon';ribbon.hidden=true;
  ribbon.setAttribute('aria-labelledby','creationTitle');
  const heading=document.createElement('div');heading.className='creation-heading';
  const title=document.createElement('h2');title.id='creationTitle';title.textContent='New island';
  const hint=document.createElement('p');hint.textContent='Try landscapes here before building. Regenerate replaces this new island; Undo restores the previous version.';
  const done=document.createElement('button');done.id='finishCreation';done.className='primary';done.textContent='Done · close';
  heading.append(title,hint,done);
  const controls=document.createElement('div');controls.className='creation-controls';
  for(const node of [...land.children])if(node.tagName!=='H2'&&node.id!=='name'&&node.htmlFor!=='name')controls.append(node);
  land.querySelector('h2').textContent='Island';
  ribbon.append(heading,controls);document.querySelector('main').before(ribbon);
  const buttons=['generate','surprise'].map(id=>document.getElementById(id));
  buttons[0].textContent='Regenerate island';buttons[1].textContent='Try new seed';
  const style=document.createElement('style');style.textContent=`
    #creationRibbon[hidden]{display:none!important}
    #creationRibbon{flex:none;margin:0;padding:10px 18px;background:var(--panel);border-bottom:2px solid var(--gold);max-height:40vh;overflow:auto}
    .creation-heading{display:flex;align-items:center;gap:18px;margin-bottom:8px}.creation-heading h2,.creation-heading p{margin:0}.creation-heading button{margin-left:auto;white-space:nowrap}
    .creation-controls{height:175px;column-width:230px;column-gap:24px;column-fill:auto;overflow-x:auto}
    .creation-controls>*{break-inside:avoid}.creation-controls label{margin:5px 0 3px}.creation-controls input[type=checkbox]{width:auto}.creation-controls [hidden]{display:none!important}
    .creation-controls p{font-size:11px}.creation-controls button{font-size:12px}.creation-controls .row{flex-wrap:wrap}
    @media(max-width:750px){.creation-heading{flex-wrap:wrap;gap:8px}.creation-heading p{flex-basis:100%;order:3}}
  `;document.head.append(style);
  function close(){ribbon.hidden=true;for(const button of buttons)button.disabled=true;document.getElementById('newIsland')?.setAttribute('aria-expanded','false');}
  done.onclick=()=>{close();document.getElementById('newIsland')?.focus();};
  close();
  return {close,get active(){return !ribbon.hidden;},open(){ribbon.hidden=false;for(const button of buttons)button.disabled=false;document.getElementById('newIsland')?.setAttribute('aria-expanded','true');done.focus();}};
}
