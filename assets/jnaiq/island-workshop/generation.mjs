import options from './generation-options.json' with {type:'json'};
import {duneHeight} from './dunes.mjs';
import {validatePlantLayers} from './plant-layers.mjs';
export const GENERATION_OPTIONS=options;
export function validateGeneration(value){
  if(value===undefined)return;
  if(!value||typeof value!=='object')throw Error('Invalid generation recipe');
  for(const key of ['landforms','communities','rocks']){
    const list=value[key];
    if(!Array.isArray(list)||list.length>Object.keys(options[key]).length||new Set(list).size!==list.length||list.some(id=>!Object.hasOwn(options[key],id))||key==='landforms'&&!list.length)throw Error('Invalid generation '+key);
  }
  if(!Number.isFinite(value.density)||value.density<0||value.density>1)throw Error('Invalid generation coverage');
  validatePlantLayers(value.plantLayers,value.communities);
  if(value.maxTreeHeight!==undefined&&(!Number.isFinite(value.maxTreeHeight)||value.maxTreeHeight<5||value.maxTreeHeight>120))throw Error('Choose a maximum tree height from 5 to 120 metres.');
  if(value.treeHeightVariation!==undefined&&(!Number.isFinite(value.treeHeightVariation)||value.treeHeightVariation<0||value.treeHeightVariation>1))throw Error('Invalid tree height variation');
  if(value.clustering!==undefined&&(!Number.isFinite(value.clustering)||value.clustering<0||value.clustering>1))throw Error('Invalid scenery clustering');
}
export const legacyLandform=style=>({craggy:'cliffs',highland:'uplands',desert:'mesas',alien:'uplands',rainforest:'ridges'}[style]||'hills');
// Same coast and seeded field for every component: blending alters relief,
// while plant and rock choices never participate in height generation.
export function landformHeight(kind,{x,z,size,h,noise,phases}){
  const u=x/size,v=z/size,r=Math.hypot(u,v),angle=phases[5];
  const along=u*Math.cos(angle)+v*Math.sin(angle),across=-u*Math.sin(angle)+v*Math.cos(angle);
  switch(kind){
    case 'flat':return 3;
    case 'hills':return h*.30+noise*.4;
    case 'uplands':return 7+h*.90+noise*.8;
    case 'cliffs':{const base=h*.75;return Math.floor(base/5)*5+1+noise*.12;}
    case 'ridges':return 4+h*.22+24*Math.exp(-Math.pow((across+Math.sin(along*12+phases[6])*.035)/.07,2))*(.7+.3*Math.cos(along*10))+noise*.4;
    case 'mesas':return 3+22/(1+Math.exp((r-(.15+.025*Math.sin(Math.atan2(v,u)*4+phases[6])))/.012))+noise*.15;
    case 'crater':return 2+25*Math.exp(-Math.pow((r-.20)/.045,2))+noise*.15;
    case 'dunes':return duneHeight(u,v,phases);
    default:throw Error('Unknown landform');
  }
}
