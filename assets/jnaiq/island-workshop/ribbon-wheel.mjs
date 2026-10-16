// Route each wheel gesture to one scroll region. Never chain from a preview
// into the surrounding ribbon, including at the preview's first/last card.
export function installRibbonWheel(ribbon){
  const innerSelector='.furniture-gallery,.scenery-preview-strip,[data-ribbon-scroll]';
  const scrollable=(node,axis)=>{
    const style=getComputedStyle(node),overflow=axis==='x'?style.overflowX:style.overflowY;
    return /auto|scroll/.test(overflow)&&(axis==='x'?node.scrollWidth-node.clientWidth:node.scrollHeight-node.clientHeight)>1;
  };
  function wheel(event){
    if(event.defaultPrevented||event.ctrlKey||event.metaKey)return;
    const delta=Math.abs(event.deltaX)>Math.abs(event.deltaY)?event.deltaX:event.deltaY;
    if(!delta)return;
    const target=event.target.closest?.('*');if(!target)return;
    const docked=!!ribbon.closest('.side-docked');
    const panel=target.closest('.ribbon-panel'),tabs=target.closest('.ribbon-tabs');
    let region=null,axis='x';
    for(let node=target;node&&node!==ribbon&&node!==panel&&node!==tabs;node=node.parentElement){
      if(docked&&scrollable(node,'y')){region=node;axis='y';break;}
      if(docked&&node.matches(innerSelector)&&!scrollable(node,'x'))continue;
      if(node.matches(innerSelector)||scrollable(node,'x')){region=node;break;}
      if(scrollable(node,'y')){region=node;axis='y';break;}
    }
    if(!region){
      if(docked){region=tabs||panel;if(!region||!scrollable(region,'y'))return;axis='y';}
      else{
      region=tabs&&scrollable(tabs,'x')?tabs:panel||ribbon.querySelector('.ribbon-panel:not([hidden])');
      if(!region||!scrollable(region,'x'))return;
      }
    }
    event.preventDefault();event.stopPropagation();region.style.scrollSnapType='none';
    const amount=delta*(event.deltaMode===1?16:event.deltaMode===2?(axis==='x'?region.clientWidth:region.clientHeight):1);
    if(axis==='x')region.scrollLeft+=amount;else region.scrollTop+=amount;
  }
  ribbon.addEventListener('wheel',wheel,{passive:false});
  return ()=>ribbon.removeEventListener('wheel',wheel);
}
