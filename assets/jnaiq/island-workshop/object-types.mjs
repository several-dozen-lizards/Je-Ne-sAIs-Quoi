import types from './object-types.json' with {type:'json'};
export const OBJECT_TYPES=types;
export function objectTypes(item){
  if(Array.isArray(item.categories))return types.filter(t=>item.categories.includes(t.id)).map(t=>t.id);
  const text=(' '+(item.display_name||'')+' '+(item.kind||'')+' '+(item.filename||'')).replace(/([a-z])([A-Z])/g,'$1 $2').toLowerCase().replace(/([a-z])([0-9])/g,'$1 $2').replace(/[^a-z0-9]+/g,' ');
  const found=types.filter(t=>t.words.some(word=>new RegExp('\\b'+word+'s?\\b').test(text))).map(t=>t.id);
  // Common compounds and workshop tools in the existing asset packs. Whole
  // words avoid turning unrelated names (such as chairman) into furniture.
  const extras={storage:['commode','gothiccabinet','trash can','bucket'],surfaces:['coffeetable','woodentable','coffeecart','cutting board'],decorations:['armillary','shell','fish tank','basking rock'],lights:['candleholder','candlestick','lightbulb'],appliances:['boombox','cassette player','payphone','samovar','heater','turntable'],structural:['screen panels','ladder','electricity poles','fire escape','gutter','cone','wetfloorsign'],handheld:['estoc','baseball','bat','bolt cutters','goblet','pot','camera','cleaner tin','crowbar','handsaw','jug','shield','fire extinguisher','lubricant','machete','dagger','mace','plunger','ratchet','wrench','tea set','watch','axe','vice','vise']};
  for(const [type,words] of Object.entries(extras))if(words.some(word=>new RegExp('\\b'+word+'s?\\b').test(text)))found.push(type);
  const legacy={seating:'seating',beds:'beds',pictures:'decorations'}[item.category];if(legacy)found.push(legacy);
  if(item.capability==='light')found.push('lights');if(item.capability==='portal')found.push('structural');
  if(['writing','private_writing'].includes(item.capability))found.push('surfaces');
  if(item.capability==='sitting')found.push('seating');
  if(!found.length&&/\.(png|jpe?g)$/i.test(item.filename||''))found.push('decorations');
  const result=[...new Set(found)].filter(type=>!(type==='seating'&&/\b(vice|vise)\b/.test(text)));
  return result.length?result:['other'];
}
export function filterObjects(items,type='all',query=''){
  const q=query.trim().toLowerCase();
  return items.filter(i=>(type==='all'||objectTypes(i).includes(type))&&`${i.display_name} ${i.kind}`.toLowerCase().includes(q));
}
export function chooseImportTypes(file){
  return new Promise(resolve=>{
    const dialog=document.createElement('dialog');dialog.className='object-import-types';
    const title=document.createElement('h2');title.textContent='Import object';
    const name=document.createElement('p');name.textContent=file.name;
    const hint=document.createElement('p');hint.textContent='Choose every type this object belongs to. These organize the library; they do not change how the object works.';
    const fields=document.createElement('fieldset'),legend=document.createElement('legend');legend.textContent='Object types';fields.append(legend);
    const guessed=objectTypes({filename:file.name});
    for(const type of types){const label=document.createElement('label'),input=document.createElement('input');input.type='checkbox';input.value=type.id;input.checked=guessed.includes(type.id);label.append(input,' '+type.label);fields.append(label);}
    const cancel=document.createElement('button');cancel.textContent='Cancel';const confirm=document.createElement('button');confirm.textContent='Import';confirm.className='primary';
    cancel.onclick=()=>dialog.close();confirm.onclick=()=>{const selected=[...fields.querySelectorAll('input:checked')].map(i=>i.value);dialog.returnValue=JSON.stringify(selected.length?selected:['other']);dialog.close(dialog.returnValue);};
    dialog.addEventListener('close',()=>{const result=dialog.returnValue?JSON.parse(dialog.returnValue):null;dialog.remove();resolve(result);},{once:true});
    const style=document.createElement('style');style.textContent='.object-import-types fieldset{display:grid;grid-template-columns:1fr 1fr;gap:8px}.object-import-types label{margin:0;display:flex;gap:7px;align-items:center}.object-import-types input[type=checkbox]{width:auto}.object-import-types button{margin:12px 8px 0 0}';dialog.append(style,title,name,hint,fields,cancel,confirm);document.body.append(dialog);dialog.showModal();
  });
}
