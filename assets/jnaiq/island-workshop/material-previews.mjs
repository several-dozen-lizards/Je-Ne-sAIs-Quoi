import {FINISHES} from './building-finishes.mjs';
import {BUILDING_SURFACE_SOURCES} from './building-materials.mjs';
import {GROUND_SURFACES} from './landscape-edit.mjs?caves=retired';
import {NATURAL_SURFACE_SOURCES} from './materials.mjs';

const albedoUrl=source=>{
  const name=String(source||'').replace(/^polyhaven:/,'');
  return name?new URL(`./textures/polyhaven-v1/${name}_albedo.jpg`,import.meta.url).href:'';
};

export const GROUND_PREVIEW_KINDS=Object.freeze([
  'grass','dirt','rock','dirt','clay','snow','basalt','moss','gravel','ash','alien','enchanted'
]);

function addStyles(){
  if(document.getElementById('materialPreviewStyles'))return;
  const style=document.createElement('style');style.id='materialPreviewStyles';style.textContent=`
    .material-preview{margin:9px 0 12px}.material-preview>p{margin:6px 0;color:var(--muted);font-size:12px}
    .material-preview-targets{display:flex;gap:5px;flex-wrap:wrap;margin:7px 0}
    .material-preview-targets button{width:auto;padding:5px 8px;font-size:12px}
    .material-preview-targets button[aria-pressed=true]{border-color:var(--gold);background:#3d5149;color:var(--ink)}
    .material-swatches{display:grid;grid-template-columns:repeat(auto-fill,minmax(74px,1fr));gap:6px}
    .material-swatch{position:relative;min-width:0;padding:0;overflow:hidden;text-align:left;background:#17272c;border:1px solid var(--line);border-radius:7px}
    .material-swatch img{display:block;width:100%;height:54px;object-fit:cover;background:#26383a}
    .material-swatch span{display:block;padding:5px 6px;font-size:11px;line-height:1.15;white-space:normal}
    .material-swatch[aria-pressed=true]{border-color:var(--gold);box-shadow:0 0 0 2px #d7b47755}
    .material-swatch[aria-pressed=true]::after{content:'✓';position:absolute;right:4px;top:4px;width:20px;height:20px;border-radius:50%;display:grid;place-items:center;background:#172824dd;color:#f3cf8b;font-weight:700}
    .material-swatch[data-ground="sand"] img{filter:sepia(.35) saturate(.8) brightness(1.2)}
    .material-swatch[data-ground="clay"] img{filter:sepia(.75) saturate(1.65) hue-rotate(330deg)}
    .material-swatch[data-ground="basalt"] img{filter:grayscale(.8) brightness(.38) contrast(1.3)}
    .material-swatch[data-ground="moss"] img{filter:saturate(1.25) brightness(.78)}
    .material-swatch[data-ground="ash"] img{filter:grayscale(1) brightness(.55)}
    .material-swatch[data-ground="alien"] img{filter:hue-rotate(125deg) saturate(1.45) brightness(.72)}
    .material-swatch[data-ground="enchanted"] img{filter:hue-rotate(235deg) saturate(1.35) brightness(.72)}
  `;document.head.append(style);
}

function swatch({id,label,url,ground},choose){
  const button=document.createElement('button');button.type='button';button.className='material-swatch';button.dataset.value=id;
  if(ground)button.dataset.ground=ground;
  const image=document.createElement('img');image.alt='';image.loading='lazy';image.decoding='async';image.src=url;
  const text=document.createElement('span');text.textContent=label;button.append(image,text);button.onclick=()=>choose(id);return button;
}

function syncPressed(grid,value){for(const button of grid.querySelectorAll('.material-swatch'))button.setAttribute('aria-pressed',String(button.dataset.value===value));}

export function installBuildingMaterialPreview(container,selects,getTextures=()=>[]){
  addStyles();let target='buildingMaterial';
  const root=document.createElement('div');root.className='material-preview';root.innerHTML='<p><strong>Material preview</strong> · choose where to apply it, then choose a surface. Sunlight changes its final relief and sheen.</p>';
  const targets=document.createElement('div');targets.className='material-preview-targets';targets.setAttribute('role','group');targets.setAttribute('aria-label','Building surface to preview');
  const targetLabels={buildingMaterial:'Walls',floorMaterial:'Floors',roofMaterial:'Roof',trimMaterial:'Frames'};
  for(const [id,label] of Object.entries(targetLabels)){const button=document.createElement('button');button.type='button';button.textContent=label;button.dataset.target=id;button.onclick=()=>{target=id;render();};targets.append(button);}
  const grid=document.createElement('div');grid.className='material-swatches';grid.setAttribute('aria-label','Building material previews');root.append(targets,grid);container.append(root);
  function render(){
    const selected=selects[target]?.value;grid.replaceChildren(...Object.entries(FINISHES).map(([id,label])=>swatch({id,label,url:albedoUrl(BUILDING_SURFACE_SOURCES[id])},choose)),...(getTextures()||[]).map(t=>swatch({id:t.id,label:'Custom · '+t.name,url:t.data},choose)));
    for(const button of targets.children)button.setAttribute('aria-pressed',String(button.dataset.target===target));syncPressed(grid,selected);
  }
  function choose(value){const select=selects[target];if(!select)return;select.value=value;select.dispatchEvent(new Event('change',{bubbles:true}));syncPressed(grid,value);}
  for(const select of Object.values(selects))select.addEventListener('change',()=>{if(select.id===target)syncPressed(grid,select.value);});
  render();return {refresh:render,setTarget:id=>{if(selects[id]){target=id;render();}}};
}

export function installGroundMaterialPreview(container,select){
  addStyles();const root=document.createElement('div');root.className='material-preview';root.innerHTML='<p><strong>Ground previews</strong> · representative colour and pattern from the same photographed terrain sources.</p>';
  const grid=document.createElement('div');grid.className='material-swatches';grid.setAttribute('aria-label','Ground material previews');
  const entries=GROUND_SURFACES.map((label,index)=>{const kind=GROUND_PREVIEW_KINDS[index];return {id:String(index),label,ground:kind,url:albedoUrl(NATURAL_SURFACE_SOURCES[kind])};});
  grid.append(...entries.map(entry=>swatch(entry,value=>{select.value=value;select.dispatchEvent(new Event('change',{bubbles:true}));syncPressed(grid,value);})));root.append(grid);container.append(root);
  select.addEventListener('change',()=>syncPressed(grid,select.value));syncPressed(grid,select.value);return root;
}
