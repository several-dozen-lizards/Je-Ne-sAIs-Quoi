const paths={
  createPond:'M3 13c0-5 4-8 9-7s9 3 9 7-5 7-10 6-8-2-8-6z M6 12c2-2 4 2 6 0s4 2 6 0 M7 15c2-2 4 2 6 0s3 1 4 0',
  steps:'M3 21v-6h6V9h6V3h6 M3 21h18',
  orbit:'M4 12a8 8 0 1 0 3-6 M4 4v6h6',
  raise:'M3 19l6-9 4 5 3-4 5 8 M12 9V2m-3 3 3-3 3 3',
  lower:'M3 19l6-5 4 3 3-3 5 5 M12 2v8m-3-3 3 3 3-3',
  cliff:'M3 20h18 M5 20V9l6-5h5v8h3v8',
  flatten:'M3 16h18 M12 3v9m-3-3 3 3 3-3',
  smooth:'M2 16c4-12 7 8 11-3s6 0 9-3 M3 21h18',
  place:'M12 21V10 M12 14C3 15 3 6 3 6s9 0 9 8 M12 11c0-8 9-8 9-8s0 8-9 8',
  vine:'M12 22V10c0-6 7-7 9-7 0 5-3 9-9 9 M12 15C5 16 3 11 3 7c5 0 9 2 9 8 M8 20c2-3 6-3 8 0',
  erase:'m4 14 9-10 8 7-9 10H9z M8 10l8 7 M13 21h9',
  paint:'M4 3h15v7H4z M19 6h3v8H12v7 M10 17h4v5h-4z',
  buildHouse:'M2 11 12 3l10 8 M5 10v11h14V10 M10 21v-7h4v7',
  removeHouse:'M2 11 12 3l10 8 M5 10v11h14V10 M9 15l6 4m0-4-6 4',
  houseSettings:'M3 6h18 M3 12h18 M3 18h18 M8 3v6 M16 9v6 M10 15v6',
  openColumns:'M3 3h18v3H3z M5 6v12m4-12v12m6-12v12m4-12v12 M3 18h18v3H3z',
  undo:'M8 4 3 9l5 5 M3 9h11a6 6 0 0 1 0 12',
  redo:'m16 4 5 5-5 5 M21 9H10a6 6 0 0 0 0 12',
  home:'M3 9V3h6 M15 3h6v6 M21 15v6h-6 M9 21H3v-6 M8 12l4-4 4 4-4 4z',
  top:'M4 10h16v11H4z M12 2v5m-3-3 3 3 3-3',
  horizon:'M2 15h20 M6 11a6 6 0 0 1 12 0 M12 1v2 M3 5l2 2m14 0 2-2'
};
export function compactToolbar(){
  const paint=document.getElementById('paintGround');paint.dataset.tool='paint';paint.setAttribute('aria-pressed','false');document.getElementById('tools').append(paint);
  for(const button of document.querySelectorAll('#tools button,#houseTools button,#viewbar button')){
    const key=button.dataset.tool||button.id||'horizon',path=paths[key];if(!path)continue;
    const label=button.textContent.trim();button.setAttribute('aria-label',label);button.dataset.label=label;button.classList.add('icon-tool');
    button.innerHTML=`<svg aria-hidden="true" focusable="false" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="${path}"/></svg>`;
  }
  const style=document.createElement('style');style.textContent=`
    #workspace>#tools{display:flex;flex-wrap:wrap;gap:5px;padding:6px 10px}
    #workspace .icon-tool,#workspace>#tools .icon-tool{position:relative;display:inline-flex;align-items:center;justify-content:center;flex:none;width:36px;height:36px;padding:7px;font-size:12px}
    .icon-tool svg{width:20px;height:20px;pointer-events:none}
    .icon-tool::after{content:attr(data-label);position:absolute;left:0;top:calc(100% + 7px);width:max-content;max-width:180px;padding:6px 9px;border:1px solid var(--line);border-radius:6px;background:#102127;color:var(--ink);font-size:12px;font-weight:400;white-space:normal;pointer-events:none;opacity:0;visibility:hidden;z-index:30;box-shadow:0 3px 10px #0005}
    .icon-tool:hover::after,.icon-tool:focus-visible::after{opacity:1;visibility:visible}
    #workspace>#tools,#houseTools{position:relative;z-index:5}#workspace>#tools{z-index:6}
    #houseTools{gap:5px!important;padding:5px 10px!important}#houseTools select{max-width:210px!important;padding:6px;font-size:12px}#houseTools label{font-size:11px}
    #viewbar{top:10px;left:10px;gap:5px;z-index:4}#viewbar span{padding:8px;font-size:11px}
    @media(pointer:coarse){#workspace .icon-tool,#workspace>#tools .icon-tool{width:44px;height:44px}}
  `;document.head.append(style);
}
