import options from './generation-options.json' with {type:'json'};
import {LAYERS,layerPlants} from './plant-layers.mjs';
const titles={large:'Large plants',medium:'Medium plants',small:'Small plants'};
const descriptions={large:'Trees, tall cacti & giant fungi',medium:'Shrubs, ferns & tall flowers',small:'Ground plants & small mushrooms'};
const defaults={large:50,medium:30,small:20};
export function installPlantLayerControls(saved,onchange){
  const label=document.createElement('label');label.htmlFor='sceneryMix';label.textContent='Plant communities';
  const box=document.createElement('details');box.id='sceneryMix';box.className='generation-picker';
  const summary=document.createElement('summary');box.append(summary);
  const note=document.createElement('p');note.textContent='Percentages are target shares of plants, excluding rocks. Mixed communities appear in each relevant size group; each checkbox selects only that size. Space and terrain can affect the final proportions.';box.append(note);
  const controls={},shares={...defaults};
  const checked=layer=>[...controls[layer].section.querySelectorAll('input[type="checkbox"]:checked')].map(i=>i.value);
  const active=()=>LAYERS.filter(layer=>checked(layer).length);
  function normalize(changed,value){
    const enabled=active();for(const layer of LAYERS)if(!enabled.includes(layer))shares[layer]=0;
    if(!enabled.length)return;
    if(enabled.length===1){shares[enabled[0]]=100;return;}
    const rest=enabled.filter(l=>l!==changed),budget=changed?100-value:100;
    if(changed)shares[changed]=value;
    const total=rest.reduce((n,l)=>n+shares[l],0);let remaining=budget;
    rest.forEach((l,i)=>{const n=i===rest.length-1?remaining:Math.round(budget*(total?shares[l]/total:1/rest.length));shares[l]=n;remaining-=n;});
  }
  function sync(){
    const enabled=active();
    for(const layer of LAYERS){const c=controls[layer];c.slider.value=shares[layer];c.slider.disabled=!enabled.includes(layer);c.output.textContent=shares[layer]+'%';}
    summary.textContent=enabled.length?enabled.map(l=>`${titles[l]} ${shares[l]}%`).join(' · '):'No plants';
  }
  for(const layer of LAYERS){
    const section=document.createElement('fieldset'),legend=document.createElement('legend');legend.textContent=titles[layer];section.append(legend);
    const hint=document.createElement('p');hint.textContent=descriptions[layer];section.append(hint);
    const shareLabel=document.createElement('label'),output=document.createElement('output'),slider=document.createElement('input');
    slider.type='range';slider.id='plantShare-'+layer;slider.min=0;slider.max=100;slider.step=1;
    shareLabel.htmlFor=slider.id;shareLabel.append('Share of plants ',output);section.append(shareLabel,slider);
    controls[layer]={section,slider,output};
    for(const [id,community] of Object.entries(options.communities))if(layerPlants(layer,id).length){
      const row=document.createElement('label'),input=document.createElement('input');input.type='checkbox';input.value=id;
      input.setAttribute('aria-label',community.name+' — '+titles[layer].toLowerCase());row.append(input,community.name);section.append(row);
      input.onchange=()=>{if(checked(layer).length&&shares[layer]===0)shares[layer]=defaults[layer];normalize();sync();onchange();};
    }
    slider.oninput=()=>{normalize(layer,Number(slider.value));sync();onchange();};box.append(section);
  }
  function set(communities,layers){
    for(const layer of LAYERS){
      const selected=layers?.[layer]?.communities??communities;
      for(const input of controls[layer].section.querySelectorAll('input[type="checkbox"]'))input.checked=selected.includes(input.value);
      shares[layer]=layers?.[layer]?.percentage??defaults[layer];
    }
    normalize();sync();
  }
  set(Array.isArray(saved.communities)?saved.communities:['auto'],saved.plantLayers);
  return {label,box,set,selected:()=>[...new Set(LAYERS.flatMap(checked))],layers:()=>Object.fromEntries(LAYERS.map(l=>[l,{communities:checked(l),percentage:shares[l]}]))};
}
