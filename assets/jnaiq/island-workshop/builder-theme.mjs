const FONT_STACKS={system:'"Segoe UI",system-ui,sans-serif',serif:'"Source Serif 4",Georgia,serif',display:'"Cormorant Garamond",Georgia,serif',mono:'"IBM Plex Mono",Consolas,monospace',humanist:'"Atkinson Hyperlegible","Segoe UI",sans-serif',rounded:'Nunito,"Segoe UI",sans-serif',geometric:'"Space Grotesk","Segoe UI",sans-serif',alegreya:'Alegreya,Georgia,serif',baskerville:'"Libre Baskerville",Georgia,serif',playfair:'"Playfair Display",Georgia,serif',slab:'"Roboto Slab",Rockwell,serif',inter:'Inter,"Segoe UI",sans-serif',lexend:'Lexend,"Segoe UI",sans-serif',quicksand:'Quicksand,"Segoe UI",sans-serif',condensed:'"Bebas Neue","Arial Narrow",sans-serif',handwritten:'Caveat,"Segoe Print",cursive',marker:'"Permanent Marker","Segoe Print",cursive',jetbrains:'"JetBrains Mono",Consolas,monospace',cinzel:'Cinzel,Georgia,serif'};
function apply(theme){
 const tokens=theme?.tokens||theme;if(!tokens||typeof tokens!=='object')return;
 const root=document.documentElement;
 for(const [key,target] of Object.entries({bg:'bg',panel:'panel',line:'line',ink:'ink',dim:'dim',accent:'mint',accent2:'gold'}))if(/^#[0-9a-f]{6}$/i.test(tokens[key]||''))root.style.setProperty('--'+target,tokens[key]);
 if(FONT_STACKS[tokens.font])for(const key of ['font-ui','font-display'])root.style.setProperty('--'+key,FONT_STACKS[tokens.font]);
 root.style.setProperty('--base-font-size',(16*Math.max(.8,Math.min(1.35,Number(tokens.font_scale)||1)))+'px');
 if(/^#[0-9a-f]{6}$/i.test(tokens.bg||'')){const c=tokens.bg.slice(1);root.style.colorScheme=(parseInt(c.slice(0,2),16)+parseInt(c.slice(2,4),16)+parseInt(c.slice(4,6),16))>420?'light':'dark';}
}
fetch('/api/ui/theme',{cache:'no-store'}).then(r=>r.ok?r.json():null).then(apply).catch(()=>{});
addEventListener('message',event=>{if(event.source===parent&&event.origin===location.origin&&event.data?.type==='jnsq-theme-refresh')apply(event.data.tokens);});
