// Reflow existing controls; the canvas, selections and editing state stay alive.
export function installSideDock(main){
  main.classList.add('side-docked');
  const style=document.createElement('style');style.textContent=`
    main.side-docked{--dock-width:390px;display:grid;grid-template-columns:var(--dock-width) minmax(0,1fr) 140px;grid-template-rows:minmax(0,1fr);min-height:0}
    main.side-docked.dock-collapsed{--dock-width:88px}
    main.side-docked #workshopRibbon{grid-column:1;grid-row:1;display:flex;min-height:0;height:100%;border-bottom:0;border-right:1px solid var(--line);overflow:hidden}
    main.side-docked .ribbon-tabs{flex:0 0 88px;width:88px;box-sizing:border-box;display:flex;flex-direction:column;gap:5px;padding:8px 5px;overflow-x:hidden;overflow-y:scroll;scrollbar-gutter:stable;overscroll-behavior-y:contain;touch-action:pan-y;border-right:1px solid var(--line)}
    main.side-docked .ribbon-tabs button{flex:none;width:100%;min-height:42px;white-space:normal;text-align:left;line-height:1.3;border-radius:6px;padding:8px 6px;font-size:11px}
    main.side-docked .ribbon-panels{flex:1;min-width:0;min-height:0;height:100%;overflow:hidden}
    main.side-docked.dock-collapsed .ribbon-panels{display:none}
    main.side-docked #workshopRibbon .ribbon-panel{height:100%;max-height:none;width:100%;overflow-y:scroll;overflow-x:hidden;padding:12px;white-space:normal;scrollbar-gutter:stable;overscroll-behavior-y:contain;touch-action:pan-y}
    main.side-docked #workshopRibbon .ribbon-panel>section,main.side-docked #workshopRibbon .ribbon-panel>div,main.side-docked #workshopRibbon .ribbon-panel>.workshop-category{display:block;width:auto;height:auto;max-height:none;columns:auto;overflow:visible;margin:0 0 12px!important}
    main.side-docked #workshopRibbon .ribbon-panel .workshop-category{max-height:none;column-span:none}
    main.side-docked #workshopRibbon .ribbon-panel input,main.side-docked #workshopRibbon .ribbon-panel select{max-width:100%;box-sizing:border-box;min-width:0}
    main.side-docked #workshopRibbon .ribbon-panel label{margin-top:10px}
    main.side-docked #workshopRibbon .ribbon-panel .generation-picker{max-height:none;overflow:visible}
    main.side-docked #workshopRibbon .ribbon-panel .generation-picker summary{position:static}
    main.side-docked #workspace{grid-column:2;grid-row:1;min-width:0;min-height:0}
    main.side-docked>aside{grid-column:3;grid-row:1;border-right:0;border-left:1px solid var(--line);padding:10px 8px!important;min-height:0;overflow-y:scroll!important;overflow-x:hidden;scrollbar-gutter:stable;overscroll-behavior-y:contain;touch-action:pan-y}
    main.side-docked aside #tools{grid-template-columns:repeat(2,minmax(0,1fr));gap:6px;margin-bottom:14px}
    main.side-docked aside #tools .icon-tool{width:100%;height:40px}
    main.side-docked aside label{font-size:11px}main.side-docked aside p{font-size:11px;line-height:1.4}
    /* Override the horizontal ribbon's ID-scoped overflow lock. */
    main.side-docked #workshopRibbon #ribbon-panel-scenery{overflow-y:scroll;overflow-x:hidden}
    main.side-docked #workshopRibbon #ribbon-panel-scenery .scenery-layout{display:flex;flex-direction:column;gap:12px;height:auto}
    main.side-docked #workshopRibbon #ribbon-panel-scenery .scenery-settings{flex:none;width:auto;height:auto;overflow:visible;padding:0!important}
    main.side-docked #workshopRibbon #ribbon-panel-scenery #sceneryLibrary{flex:none;height:auto;min-width:0}
    main.side-docked #workshopRibbon .scenery-filters{flex-wrap:wrap;overflow:visible}
    main.side-docked #workshopRibbon #sceneryLibrary .scenery-preview-strip{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));overflow:visible;flex:none}
    main.side-docked #workshopRibbon #sceneryLibrary .scenery-preview-strip button{width:auto;min-width:0;height:130px}
    main.side-docked #workshopRibbon #sceneryLibrary .scenery-preview-strip img{width:100%;height:95px;object-fit:contain}
    main.side-docked #workshopRibbon #ribbon-panel-furniture{display:block;overflow-y:auto;overflow-x:hidden}
    main.side-docked #workshopRibbon #ribbon-panel-furniture>div{height:auto;max-height:none;columns:auto;overflow:visible;min-width:0}
    main.side-docked #workshopRibbon #ribbon-panel-furniture>.furniture-gallery{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));height:260px;overflow-y:auto!important;overflow-x:hidden!important;gap:6px}
    main.side-docked #workshopRibbon .furniture-gallery button{width:100%;height:120px;min-width:0}
    main.side-docked #workshopRibbon .building-navigation{display:grid;grid-template-columns:1fr 1fr;gap:6px}
    main.side-docked #workshopRibbon .building-navigation button{width:auto;min-width:0}
    main.side-docked #workshopRibbon .building-navigation span{display:none}
    main.side-docked #workshopRibbon #buildingInspector{height:auto;overflow:visible}
    @media(max-width:1000px){main.side-docked{--dock-width:340px;grid-template-columns:var(--dock-width) minmax(0,1fr) 118px}}
    @media(max-width:700px){main.side-docked,main.side-docked.dock-collapsed{grid-template-columns:88px minmax(0,1fr) 105px;position:relative}main.side-docked #workshopRibbon{width:min(360px,calc(100vw - 115px));z-index:8;box-shadow:5px 0 14px #0005}main.side-docked.dock-collapsed #workshopRibbon{width:88px;box-shadow:none}}
    .visiting main.side-docked{display:block}
  `;document.head.append(style);
}
