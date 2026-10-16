import {specimenVariant} from './plants.mjs?sumac=2';
// Measured highest vertex across near/far geometry, in metres at scale 1.
// The geometry contract test detects changes to these specimen bounds.
export const TREE_HEIGHTS={tree:[7.697101593017578,7.432216644287109,7.709694862365723],maple:[7.578486919403076,7.586884021759033,7.1280670166015625],pine:[6.566260814666748,6.866261005401611,7.166261196136475],sycamore:[8.156112670898438,8.218770980834961,7.990376949310303],palm:[5.900540351867676,5.9005446434021,5.900537490844727],jungle:[8.90634822845459,8.962078094482422,9.222533226013184],bare:[7.25726318359375,7.301792144775391,6.9463210105896],joshua:[3.970785617828369,4.381642818450928,4.4121246337890625],baobab:[13.283892631530762,14.35360336303711,15.40408706665039],coral_tree:[4.967172622680664,5.005194187164307,5.054650783538818]};
export function generatedTreeScale(kind,id,roll,recipe){
  if(!TREE_HEIGHTS[kind]||recipe?.maxTreeHeight===undefined)return null;
  const height=recipe.maxTreeHeight*(1-.9*(recipe.treeHeightVariation??.5)*(1-roll));
  return height/TREE_HEIGHTS[kind][specimenVariant(id)];
}
