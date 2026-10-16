import {installRibbonWheel} from './ribbon-wheel.mjs';
import {installBuildingNavigation} from './building-navigation.mjs';
import {installSideDock} from './side-dock.mjs';
export function installRibbon(aside){
  const $=id=>document.getElementById(id),main=aside.parentElement;
  const ribbon=document.createElement('div');ribbon.id='workshopRibbon';
  const removeWheel=installRibbonWheel(ribbon);window.addEventListener('pagehide',removeWheel,{once:true});
  const tabs=document.createElement('div');tabs.className='ribbon-tabs';tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label','World builder sections');
  const panels=document.createElement('div');panels.className='ribbon-panels';ribbon.append(tabs,panels);main.prepend(ribbon);
  const labels={land:'Island',scenery:'Place scenery',communities:'Plant communities',terrain:'Terrain',routes:'Paths & water',buildings:'Buildings',columns:'Columns',sky:'Sky & weather',visit:'Visit'};
  const entries=[];let activeKey=null;
  tabs.setAttribute('aria-orientation','vertical');
  function addPanel(key,label,panel){
    panel.dataset.category=key;
    panel.open=true;panel.classList.add('ribbon-panel');panel.id='ribbon-panel-'+key;panel.setAttribute('role','tabpanel');panel.setAttribute('aria-labelledby','ribbon-tab-'+key);
    const tab=document.createElement('button');tab.id='ribbon-tab-'+key;tab.textContent=label;tab.setAttribute('role','tab');tab.setAttribute('aria-controls',panel.id);tabs.append(tab);panels.append(panel);entries.push({key,panel,tab});
    tab.onclick=()=>activate(activeKey===key?null:key);
    tab.onkeydown=e=>{const i=entries.findIndex(v=>v.tab===tab);let next;if(e.key==='ArrowDown'||e.key==='ArrowRight')next=(i+1)%entries.length;else if(e.key==='ArrowUp'||e.key==='ArrowLeft')next=(i+entries.length-1)%entries.length;else if(e.key==='Home')next=0;else if(e.key==='End')next=entries.length-1;else return;e.preventDefault();activate(entries[next].key);entries[next].tab.focus();};
    panel.hidden=true;tab.setAttribute('aria-selected','false');tab.tabIndex=-1;
    return ()=>activate(key);
  }
  for(const panel of [...aside.children]){const key=panel.dataset.category;if(key)addPanel(key,labels[key]||key,panel);}
  const title=document.createElement('h2');title.textContent='Brush tools';aside.append(title,$('tools'));
  for(const button of $('tools').querySelectorAll('button'))button.title=button.getAttribute('aria-label')||button.textContent;
  for(const id of ['radius','strength'])aside.append(document.querySelector(`label[for="${id}"]`),$(id));
  aside.append($('toolHint'));aside.setAttribute('aria-label','Brush tools and controls');
  const help=document.createElement('p');help.textContent='Radius and strength apply to terrain and paint brushes. Open a tab on the left for more settings. Click its tab again to collapse it.';aside.append(help);
  // Building shortcuts belong with their settings, not over the canvas.
  $('build-home').prepend($('houseTools'));
  const sceneryPanel=$('ribbon-panel-scenery'),scenerySection=sceneryPanel.querySelector('section'),sceneryLibrary=$('sceneryLibrary');
  const scenerySettings=document.createElement('div');scenerySettings.className='scenery-settings';
  const sceneryLayout=document.createElement('div');sceneryLayout.className='scenery-layout';
  scenerySettings.append(scenerySection);sceneryLayout.append(scenerySettings,sceneryLibrary);sceneryPanel.append(sceneryLayout);
  let buildingNavigation;
  function activate(key){activeKey=key;main.classList.toggle('dock-collapsed',!key);for(const e of entries){const selected=e.key===key;e.panel.hidden=!selected;e.tab.setAttribute('aria-selected',String(selected));e.tab.tabIndex=selected||(!key&&e===entries[0])?0:-1;}buildingNavigation?.setActive(key==='buildings');}
  buildingNavigation=installBuildingNavigation(aside,$('ribbon-panel-buildings'),activate);
  const requested=new URLSearchParams(location.search).get('panel');
  activate(entries.some(entry=>entry.key===requested)?requested:'land');
  const style=document.createElement('style');style.textContent=`
    main{grid-template-columns:170px minmax(0,1fr);grid-template-rows:auto minmax(0,1fr)}
    #workshopRibbon{grid-column:1/-1;min-width:0;background:var(--panel);border-bottom:1px solid var(--line)}
    .ribbon-tabs{display:flex;gap:3px;padding:5px 10px 0;overflow-x:auto}
    .ribbon-tabs button{white-space:nowrap;border-radius:6px 6px 0 0;padding:7px 14px;font-size:12px}
    .ribbon-tabs button[aria-selected=true]{background:var(--gold);color:#18271f}
    .ribbon-panels{height:205px;overflow:hidden}
    #workshopRibbon .ribbon-panel{height:205px;overflow:auto;border:0;border-radius:0;margin:0;padding:8px 12px;box-sizing:border-box}
    #workshopRibbon .ribbon-panel[hidden]{display:none!important}
    #workshopRibbon .ribbon-panel>summary{display:none}
    .ribbon-panel>section,.ribbon-panel>div{height:175px;column-width:215px;column-gap:22px;column-fill:auto;padding:0!important}
    .ribbon-panel>section>h2{display:none}
    .ribbon-panel label{margin:5px 0 3px;break-after:avoid}
    .ribbon-panel input,.ribbon-panel select,.ribbon-panel button,.ribbon-panel p,.ribbon-panel .row,.ribbon-panel .workshop-category{break-inside:avoid}
    .panorama-guide{break-inside:avoid;font-size:11px;color:var(--dim);margin-top:5px}.panorama-guide summary{cursor:pointer;color:var(--green)}.panorama-guide strong{color:var(--ink)}
    .ribbon-panel input:not([type=range]),.ribbon-panel select{padding:5px;font-size:12px}
    .ribbon-panel input[type=checkbox]{width:auto}
    .ribbon-panel button{padding:6px 9px;font-size:12px}
    .ribbon-panel p{font-size:11px;line-height:1.35;margin:6px 0}
    .ribbon-panel .wide{margin-top:5px}
    .ribbon-panel .workshop-category{max-height:170px;overflow:auto;column-span:none;margin:0 0 6px!important}
    .ribbon-panel .workshop-category>summary{position:sticky;top:0;z-index:2;background:var(--panel)}
    .ribbon-panel>.workshop-category{display:inline-block;vertical-align:top;width:245px;margin-right:12px!important}
    #ribbon-panel-terrain>section{display:inline-block;width:235px;vertical-align:top;margin-right:12px;columns:auto;overflow-y:auto;overflow-x:hidden;box-sizing:border-box;scrollbar-gutter:stable}
    #ribbon-panel-terrain [data-category=steps]>div{display:grid;grid-template-columns:minmax(0,1fr);gap:5px}
    #ribbon-panel-terrain [data-category=steps] label{margin:3px 0 0}
    #ribbon-panel-terrain [data-category=steps] input,#ribbon-panel-terrain [data-category=steps] select{width:100%;min-width:0;box-sizing:border-box;margin:0}
    #ribbon-panel-terrain [data-category=steps] p{margin:5px 0 0}
    #ribbon-panel-terrain{white-space:nowrap}#ribbon-panel-terrain>*{white-space:normal}
    #houseTools{padding:4px!important;break-inside:avoid}#houseTools label{display:none}
    aside{grid-column:1;grid-row:2;min-height:0;padding:12px 9px!important;overflow-y:auto;overflow-x:hidden}
    aside #tools{display:grid;grid-template-columns:repeat(3,1fr);gap:5px;margin-bottom:18px}
    aside .icon-tool{width:43px;height:38px;padding:7px}aside .icon-tool svg{width:22px;height:22px}
    aside #tools button{position:relative}aside #tools .icon-tool::after{display:none}
    aside label{margin-top:14px}aside h2{font-size:11px;margin-bottom:10px}
    #workspace{grid-column:2;grid-row:2;min-height:0}#viewbar{top:8px!important}
    .visiting #workshopRibbon{display:none!important}
    @media(max-height:700px){.ribbon-panels,#workshopRibbon .ribbon-panel{height:165px}.ribbon-panel>section,.ribbon-panel>div{height:135px}.ribbon-panel .workshop-category{max-height:130px}}
    @media(max-width:750px){main{grid-template-columns:140px minmax(0,1fr)}aside .icon-tool{width:35px}.ribbon-tabs button{padding:7px 10px}}
    #workshopRibbon #ribbon-panel-scenery{overflow:hidden;--scenery-height:189px}
    @media(max-height:700px){#workshopRibbon #ribbon-panel-scenery{--scenery-height:149px}}
    #ribbon-panel-scenery>.scenery-layout{display:flex;gap:16px;columns:auto;height:var(--scenery-height);min-height:0}
    #ribbon-panel-scenery .scenery-settings{flex:0 0 225px;height:100%;min-height:0;columns:auto;overflow-y:scroll;overflow-x:hidden;scrollbar-gutter:stable;padding-right:8px!important}
    .scenery-settings section{padding:0;border:0}.scenery-settings h2{display:none}
    .generation-picker{border:1px solid var(--line);border-radius:5px;padding:6px;font-size:12px;white-space:normal;box-sizing:border-box;max-height:calc(var(--scenery-height,175px) - 30px);overflow-y:auto;overscroll-behavior-y:contain;scrollbar-gutter:stable;scroll-padding-top:30px;break-inside:avoid}
    .generation-picker summary{cursor:pointer;color:var(--ink);position:sticky;top:-6px;background:var(--panel);padding:5px 0;z-index:1}
    .generation-picker label{display:flex;align-items:center;gap:6px;padding:4px 0;line-height:1.3}
    .generation-picker input{flex:none;margin:0}
    #sceneryMix fieldset{min-width:0;border:0;border-top:1px solid var(--line);margin:8px 0;padding:8px 0}
    #sceneryMix legend{font-weight:600;padding:0 4px}
    #sceneryMix input[type="range"]{display:block;width:100%;box-sizing:border-box}
    #sceneryMix output{margin-left:auto;font-variant-numeric:tabular-nums}
    #workshopRibbon [hidden]{display:none!important}
    #generatedSkyColors{min-width:0;break-inside:avoid;border:1px solid var(--line);padding:8px;margin:0 0 8px}#generatedSkyColors label:has(input[type=checkbox]){display:flex;align-items:center;gap:6px}#generatedSkyColors input[type=checkbox]{width:auto;margin:0}
    #ribbon-panel-scenery .workshop-category{max-height:none;overflow:visible}
    #ribbon-panel-scenery #sceneryLibrary{flex:1;min-width:0;height:100%;columns:auto;display:flex;flex-direction:column;gap:4px}
    .scenery-filters{display:flex;gap:4px;overflow-x:auto;flex:none;padding-bottom:2px}
    .scenery-filters button{white-space:nowrap;flex:none}
    #sceneryLibrary button[aria-pressed=true]{border-color:var(--gold);background:#3c5145;color:var(--ink)}
    .scenery-preview-strip{display:flex;gap:8px;overflow-x:auto;overflow-y:hidden;min-height:0;flex:1;scroll-snap-type:x proximity}
    #sceneryLibrary .scenery-preview-strip button{flex:0 0 112px;min-width:0;scroll-snap-align:start;justify-content:flex-start;gap:3px!important}
    #sceneryLibrary .scenery-preview-strip img{height:calc(100% - 32px);min-height:20px;aspect-ratio:auto!important}
    .scenery-preview-strip span{font-size:10px;line-height:12px}
    #sceneryLibrary .scenery-preview-hint{margin:0;flex:none}
    .scenery-preview-strip:focus-visible{outline:2px solid var(--gold);outline-offset:-2px}
  `;document.head.append(style);
  installSideDock(main);
  return {addPanel,activateFor(node){if(buildingNavigation.reveal(node))return;const panel=node.closest('.ribbon-panel');if(panel)activate(panel.dataset.category);else if(node.id==='build-home'||node.dataset.category==='buildings')activate('buildings');}};
}
