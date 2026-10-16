import {GENERATION_OPTIONS as options,validateGeneration,legacyLandform} from './generation.mjs';
import {installPlantLayerControls} from './plant-layer-controls.mjs';
export function installGenerationControls(){
  const $=id=>document.getElementById(id);
  let saved={};try{saved=JSON.parse(localStorage.getItem('jnsq.generation.v1')||'{}');}catch{}
  if(!saved||typeof saved!=='object')saved={};
  if(!Array.isArray(saved.communities))try{const old=JSON.parse(localStorage.getItem('jnsq.scenery.communities.v1'));if(Array.isArray(old))saved.communities=old;}catch{}
  const pickers={};
  function picker(key,id,title,defaults,empty){
    const label=document.createElement('label');label.htmlFor=id;label.textContent=title;
    const box=document.createElement('details');box.id=id;box.className='generation-picker';
    const summary=document.createElement('summary');box.append(summary);
    const values=Array.isArray(saved?.[key])?saved[key]:defaults;
    for(const [value,definition] of Object.entries(options[key])){
      const row=document.createElement('label'),input=document.createElement('input');input.type='checkbox';input.value=value;input.checked=values.includes(value);
      row.append(input,typeof definition==='string'?definition:definition.name);box.append(row);
    }
    const selected=()=>[...box.querySelectorAll('input:checked')].map(input=>input.value);
    const sync=()=>{const ids=selected();summary.textContent=ids.length===0?empty:ids.length===1?(options[key][ids[0]].name||options[key][ids[0]]):`${ids.length} ${title.toLowerCase()} mixed`;};
    const set=ids=>{for(const input of box.querySelectorAll('input'))input.checked=ids.includes(input.value);sync();};
    pickers[key]={selected,set,sync};
    box.onchange=()=>{if(key==='landforms'&&!selected().length)set(['hills']);sync();updateSummary();try{localStorage.setItem('jnsq.generation.v1',JSON.stringify(recipe()));}catch{}};
    if(key==='landforms'&&!selected().length)set(['hills']);sync();return {label,box};
  }
  const land=picker('landforms','landformMix','Landforms',['hills'],'Choose a landform');
  $('style').hidden=true;document.querySelector('label[for="style"]').hidden=true;$('style').after(land.label,land.box);
  const landHint=document.createElement('p');landHint.textContent='Choose one shape or blend several. Plants and rocks are selected separately under Plant communities.';land.box.after(landHint);
  const cliffs=$('generateCliffs');cliffs.checked=false;cliffs.closest('label').hidden=true;
  const plants=installPlantLayerControls(saved,()=>{updateSummary();saveSettings();});pickers.communities=plants;
  const rocks=picker('rocks','rockMix','Rocks & crystals',['rock','river_rock','slate_rock'],'No rocks');
  const hint=document.createElement('p');hint.id='sceneryMixHint';hint.textContent='Generation and regrowth use these choices on any landform. Clear all plants or rocks to omit them. Ground colors are set under Terrain.';
  const rockControls=document.createElement('div');rockControls.id='rockMixControls';rockControls.append(rocks.label,rocks.box);
  $('scatter').before(plants.label,plants.box,hint,rockControls);
  let clustering=Number.isFinite(saved.clustering)?Math.max(0,Math.min(1,saved.clustering)):.5;
  if(Number.isFinite(saved.density))$('density').value=Math.max(0,Math.min(1,saved.density));
  function slider(id,title,parent){
    const label=document.createElement('label');label.htmlFor=id;label.append(title+' ');
    const output=document.createElement('output');output.id=id+'Value';label.append(output);
    const input=document.createElement('input');input.id=id;input.type='range';input.min=0;input.max=1;input.step=.05;parent.append(label,input);return input;
  }
  const landscapeSettings=document.createElement('div');landscapeSettings.id='generationCoverageControls';
  const landCoverage=slider('generationCoverage','Scenery coverage',landscapeSettings);
  const landClusters=slider('generationClustering','Scenery clustering',landscapeSettings);
  const treeSettings=document.createElement('div');treeSettings.id='treeHeightControls';
  const treeHeight=slider('maxTreeHeight','Max tree height',treeSettings);
  treeHeight.min=5;treeHeight.max=120;treeHeight.step=1;treeHeight.value=Number.isFinite(saved.maxTreeHeight)?saved.maxTreeHeight:18;
  const treeVariation=slider('treeHeightVariation','Tree height variation',treeSettings);
  treeVariation.value=Number.isFinite(saved.treeHeightVariation)?saved.treeHeightVariation:.5;
  const treeHint=document.createElement('p');treeHint.textContent='Tree height: up to 120 m for towering forests. Variation: 0% gives an even canopy; 100% mixes trees from 10% to 100% of the maximum. Applies to Generate and Regrow; shrubs and rocks keep their sizes.';landscapeSettings.append(treeHint);
  const clusterHint=document.createElement('p');clusterHint.textContent='Coverage sets the amount. Clustering: evenly spread → tight patches. Shared with regrowth; changes apply when you Generate or Regrow.';landscapeSettings.append(clusterHint);
  treeSettings.append(treeHint);
  $('generate').closest('.row').before(landscapeSettings,treeSettings);
  const sceneryClusters=document.createElement('div');sceneryClusters.id='clusteringControls';
  const clusterInput=slider('sceneryClustering','Scenery clustering',sceneryClusters);$('scatter').before(sceneryClusters);
  function syncSliders(){
    $('maxTreeHeightValue').textContent=treeHeight.value+' m';
    $('treeHeightVariationValue').textContent=Math.round(Number(treeVariation.value)*100)+'%';
    landCoverage.value=$('density').value;
    for(const id of ['density','generationCoverage'])$(id+'Value').textContent=Math.round(Number($('density').value)*100)+'%';
    for(const input of [landClusters,clusterInput]){input.value=clustering;$(input.id+'Value').textContent=Math.round(clustering*100)+'%';}
  }
  function saveSettings(){try{localStorage.setItem('jnsq.generation.v1',JSON.stringify(recipe()));}catch{}}
  for(const input of [treeHeight,treeVariation])input.oninput=()=>{syncSliders();saveSettings();};
  landCoverage.oninput=()=>{$('density').value=landCoverage.value;syncSliders();saveSettings();};
  $('density').addEventListener('input',()=>{syncSliders();saveSettings();});
  for(const input of [landClusters,clusterInput])input.oninput=()=>{clustering=Number(input.value);syncSliders();saveSettings();};
  syncSliders();
  const summary=document.createElement('button');summary.id='generationScenery';summary.onclick=()=>{const tab=document.getElementById('ribbon-tab-communities');if(tab?.getAttribute('aria-selected')!=='true')tab?.click();};$('generate').before(summary);
  function updateSummary(){const plants=pickers.communities.selected().length,rocks=pickers.rocks.selected().length;summary.textContent=`Scenery: ${plants} plant ${plants===1?'group':'groups'} · ${rocks} rock ${rocks===1?'type':'types'}`;}
  function recipe(){return {landforms:pickers.landforms.selected(),communities:pickers.communities.selected(),plantLayers:plants.layers(),rocks:pickers.rocks.selected(),density:Number($('density').value),clustering,maxTreeHeight:Number(treeHeight.value),treeHeightVariation:Number(treeVariation.value)};}
  updateSummary();
  return {recipe,restore(world){
    treeHeight.value=world.generation?.maxTreeHeight??18;treeVariation.value=world.generation?.treeHeightVariation??.5;
    if(world.generation){validateGeneration(world.generation);for(const key of Object.keys(pickers))pickers[key].set(world.generation[key],key==='communities'?world.generation.plantLayers:undefined);$('density').value=world.generation.density;clustering=world.generation.clustering??0;}
    else pickers.landforms.set([legacyLandform(world.style)]);
    syncSliders();updateSummary();
  }};
}
