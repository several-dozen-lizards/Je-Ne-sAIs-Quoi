import sizes from './plant-sizes.json' with {type:'json'};
import options from './generation-options.json' with {type:'json'};
export const PLANT_SIZES=sizes;
export const LAYERS=Object.keys(sizes);
export const layerPlants=(layer,community)=>(options.communities[community]?.plants||[]).filter(p=>sizes[layer].includes(p));
export function validatePlantLayers(layers,communities){
  if(layers===undefined)return;
  if(!layers||typeof layers!=='object'||Array.isArray(layers)||Object.keys(layers).length!==3)throw Error('Invalid plant layers');
  const union=new Set();let total=0;
  for(const layer of LAYERS){
    const value=layers[layer];
    if(!value||!Number.isInteger(value.percentage)||value.percentage<0||value.percentage>100||!Array.isArray(value.communities)||new Set(value.communities).size!==value.communities.length||value.communities.some(id=>!layerPlants(layer,id).length)||(!value.communities.length&&value.percentage!==0))throw Error('Invalid plant layer '+layer);
    value.communities.forEach(id=>union.add(id));total+=value.percentage;
  }
  if(total!==(union.size?100:0)||union.size!==communities.length||communities.some(id=>!union.has(id)))throw Error('Plant layer percentages must total 100% across selected communities');
}
export function layerSampler(layers,communities){
  if(!layers)return null;
  const groups=LAYERS.map(layer=>({weight:layers[layer].percentage,palettes:layers[layer].communities.filter(id=>communities.includes(id)).map(id=>layerPlants(layer,id))})).filter(g=>g.weight>0&&g.palettes.length);
  const total=groups.reduce((sum,g)=>sum+g.weight,0);
  return roll=>{
    let choice=Math.min(roll,1-Number.EPSILON)*total;
    for(const g of groups){
      if(choice<g.weight){const p=choice/g.weight*g.palettes.length,i=Math.floor(p),palette=g.palettes[i];return palette[Math.min(palette.length-1,Math.floor((p-i)*palette.length))];}
      choice-=g.weight;
    }
    return undefined;
  };
}
