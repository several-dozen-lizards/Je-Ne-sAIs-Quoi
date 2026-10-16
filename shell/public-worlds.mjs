// Imports and travel remain explicit actions; viewing never moves a person.
export function installPublicWorlds({request,token,refresh,openView,note}){
  const section=document.createElement('section');section.className='card';
  section.innerHTML='<h2>Bring your creations home</h2><p>Export a GLB from Avatar Creator or a JSON world from World Builder, then import it here. Originals stay in Builders for later editing. First run INSTALL_3D_RUNTIME.bat in this JNAIQ folder to install the optional world assets.</p><label>Avatar name<input id="importAvatarName" maxlength="64" value="My avatar"></label><label>Avatar GLB<input id="importAvatarFile" type="file" accept=".glb"></label><button id="importAvatar">Import avatar</button><label>World JSON<input id="importWorldFile" type="file" accept=".json"></label><button id="importWorld">Import and publish world</button><p>Importing an edited avatar adds a new library entry; use Apply avatar to replace your current appearance. Choose Create a new destination or Update an existing world. Keep its name the same, and have everyone leave before updating it.</p><button id="returnNexus" class="secondary">Return to Nexus</button>';
  document.querySelector('footer').before(section);
  const worldTarget=document.createElement('select');worldTarget.setAttribute('aria-label','World import destination');
  section.querySelector('#importWorld').before(worldTarget);
  const headers={'X-JNAIQ-3D-Token':token};
  for(const kind of ['Avatar','World'])section.querySelector('#import'+kind).onclick=async event=>{
    const file=section.querySelector('#import'+kind+'File').files[0];if(!file){note('Choose an exported '+kind.toLowerCase()+' file first.');return;}
    const button=event.currentTarget;button.disabled=true;note('Importing '+file.name+'…');
    try{const name=section.querySelector('#importAvatarName').value;
      const selected=worldTarget.selectedOptions[0];
      await request('/api/3d/import/'+kind.toLowerCase()+'?name='+encodeURIComponent(name)+(kind==='World'?'&replace='+encodeURIComponent(worldTarget.value)+'&revision='+encodeURIComponent(selected?.dataset.revision||''):''),{method:'POST',headers,body:file});
      await refresh();note(kind==='Avatar'?'Avatar imported. Choose a household member and apply it.':'World published. Choose Travel here to enter it.');
    }catch(e){note(e.message)}finally{button.disabled=false}
  };
  section.querySelector('#returnNexus').onclick=async()=>{try{await travel('nexus');note('You returned to the Nexus.');}catch(e){note(e.message)}};
  async function travel(destination){return request('/api/3d/travel',{method:'POST',headers:{...headers,'Content-Type':'application/json'},body:JSON.stringify({destination})});}
  function addTravel(row,world){const button=document.createElement('button');button.textContent='Travel here';button.onclick=async()=>{
    button.disabled=true;
    try{await travel('workshop_'+world.id);const result=await request('/api/3d/environment/'+world.id+'?revision='+world.revision);await openView(result.url,world.name);note('You arrived in '+world.name+'.');}catch(e){note(e.message)}finally{button.disabled=false}
  };row.append(button)};
  addTravel.update=worlds=>{worldTarget.replaceChildren(new Option('Create a new destination',''));for(const world of worlds){const option=new Option('Update '+world.name,world.id);option.dataset.revision=world.revision;worldTarget.add(option)}};
  return addTravel;
}
