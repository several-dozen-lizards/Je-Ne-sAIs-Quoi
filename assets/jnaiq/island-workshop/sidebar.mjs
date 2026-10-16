// Move existing controls rather than recreating them: values, event handlers,
// editor references, and unsaved world state all remain intact.
import {installRibbon} from './ribbon.mjs';
import {installCreationRibbon} from './creation-ribbon.mjs';
import {installGroundMaterialPreview} from './material-previews.mjs';
export function installSidebar(){
  const aside=document.querySelector('aside'),$=id=>document.getElementById(id);
  aside.setAttribute('aria-label','World builder settings');
  const folds=new Map();
  function fold(key,title,nodes,open=false){
    const box=document.createElement('details'),summary=document.createElement('summary');
    box.className='workshop-category';box.dataset.category=key;box.open=open;
    summary.textContent=title;box.append(summary);for(const node of nodes)if(node)box.append(node);
    folds.set(key,box);return box;
  }
  function wrap(node,key,title,open=false){const marker=document.createTextNode('');node.before(marker);const box=fold(key,title,[node],open);marker.replaceWith(box);return box;}
  const land=$('name').closest('section'),scenery=$('prop').closest('section'),shape=$('radius').closest('section');
  const creation=installCreationRibbon(land);
  const rock=$('rockAdd').closest('section'),vines=$('growVine').closest('section'),building=$('build-home'),columns=$('columnStyle').closest('section'),sky=$('skyHour').closest('section');
  const visit=[...aside.children].find(n=>n.tagName==='SECTION'&&n!==land&&n!==scenery&&n!==shape&&n!==rock&&n!==vines&&n!==building&&n!==columns&&n!==sky);
  const routes=$('routeKind').parentElement,steps=$('stepFinish').parentElement;
  steps.dataset.sidebarManaged='true';steps.hidden=false;
  // Regrowth immediately follows generation. Placement remains in the same
  // scenery category, with its size control explicitly grouped with placement.
  const regrowth=document.createElement('div'),placement=document.createElement('div');
  const label=id=>document.querySelector(`label[for="${id}"]`);
  regrowth.append($('treeHeightControls'));
  for(const id of ['sceneryMix','density'])regrowth.append(label(id),$(id));
  regrowth.querySelector('#sceneryMix').after($('rockMixControls'),$('sceneryMixHint'));
  regrowth.append($('clusteringControls'),$('scatter'),scenery.querySelector(':scope > p'));
  if($('groundCoverControls'))regrowth.append($('groundCoverControls'));
  for(const node of [...scenery.children])if(node.tagName!=='H2')placement.append(node);
  scenery.append(fold('placement','Place individual scenery',[placement],true));
  // Ground paint belongs with terrain brushes rather than river authoring.
  const paint=document.createElement('div'),paintKind=$('paintKind');paint.append(label('paintKind'),paintKind,$('applyGroundAll'));
  installGroundMaterialPreview(paint,paintKind);
  const paintBrush=document.createElement('button');paintBrush.id='paintTerrainBrush';paintBrush.textContent='Paint terrain directly';paintBrush.dataset.tool='paint';paintBrush.setAttribute('aria-pressed','false');paintBrush.onclick=()=>$('paintGround').click();paint.querySelector('#applyGroundAll').before(paintBrush);
  const paintHint=document.createElement('p');paintHint.textContent='Choose a ground surface, click Paint terrain directly, then drag over the land. Brush radius and strength are on the right. Apply to all ground fills the landscape while preserving cliff faces. Both actions support Undo.';paint.append(paintHint);
  shape.append(paint);
  routes.querySelector('h3').textContent='Draw paths, rivers & ponds';
  routes.querySelector('p').textContent='Paths and rivers use waypoints. Ponds use a drag brush. Paths and ponds replace overlapping objects; Undo restores terrain and objects together.';
  const terrain=fold('terrain','Shape terrain',[shape,fold('steps','Steps & slopes',[steps]),fold('rock','Sculpt rock',[rock])]);
  // Existing building subpanels retain their own scoped selectors.
  wrap($('floorMaterial').parentElement,'finishes','Materials & textures');
  wrap($('partitionFloor').parentElement,'interiors','Interior walls');
  const pool=$('poolEnabled').closest('div');if(pool&&building.contains(pool))wrap(pool,'pool','Swimming pool');
  aside.replaceChildren(
    fold('land','Island',[land],true),
    fold('communities','Plant communities',[regrowth],true),
    fold('scenery','Scenery & coverage',[scenery],true),
    terrain,fold('routes','Paths & water',[routes]),fold('vines','Vines & brambles',[vines]),
    fold('buildings','Buildings',[building]),fold('columns','Columns & colonnades',[columns]),
    fold('sky','Sky, weather & surroundings',[sky]),fold('visit','Visit this world',[visit])
  );
  const style=document.createElement('style');style.textContent=`
    aside{padding:10px 12px;scroll-padding-top:10px}
    .workshop-category{border:1px solid var(--line);border-radius:8px;margin:0 0 9px;background:var(--panel)}
    .workshop-category>summary{cursor:pointer;padding:12px 10px;color:var(--gold);font-size:12px;font-weight:650;letter-spacing:.025em;list-style:none;display:flex;align-items:center;gap:9px}
    .workshop-category>summary::before{content:'›';font-size:18px;line-height:12px;transition:transform .12s}
    .workshop-category[open]>summary::before{transform:rotate(90deg)}
    .workshop-category>summary:hover{background:#29454a;border-radius:7px}
    .workshop-category>summary:focus-visible{outline:2px solid var(--gold);outline-offset:2px}
    .workshop-category>section,.workshop-category>div{padding:0 10px 12px;margin:0;border:0}
    .workshop-category>section>h2,.workshop-category>div>h3{display:none}
    .workshop-category .workshop-category{margin:8px;border-color:#34484b88;background:#10212755}
    .workshop-category .workshop-category>summary{color:var(--ink);font-weight:500}
    .workshop-category .row{flex-wrap:wrap}.workshop-category .row>*{flex-basis:75px}
    aside button{max-width:100%}aside h3{font-size:13px;margin-top:18px}
    @media(prefers-reduced-motion:reduce){.workshop-category>summary::before{transition:none}}
  `;document.head.append(style);
  const ribbon=installRibbon(aside);
  function reveal(key,scroll=true){const box=folds.get(key);if(!box)return;ribbon.activateFor(box);for(let p=box;p;p=p.parentElement)if(p.tagName==='DETAILS')p.open=true;if(scroll)box.scrollIntoView({block:'nearest',inline:'nearest'});}
  const targets={raise:'terrain',lower:'terrain',cliff:'terrain',flatten:'terrain',smooth:'terrain',paint:'terrain',steps:'steps',rock:'rock',place:'placement',erase:'scenery',vine:'vines',build:'buildings',pond:'routes',route:'routes',removeRoute:'routes'};
  // Open ancestors before the existing shortcut focuses or scrolls its panel.
  document.addEventListener('click',e=>{const button=e.target.closest('button');if(button?.id==='houseSettings'||button?.id==='buildHouse')reveal('buildings',false);if(button?.id==='openColumns')reveal('columns',false);},true);
  return {creation,addPanel:ribbon.addPanel,revealBuildingMaterials(){reveal('finishes');},revealTool(tool){if(targets[tool])reveal(targets[tool]);}};
}
