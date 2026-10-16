export const isSpaceEnvironment=environment=>['space','planet','asteroids'].includes(environment);
export const hasOceanSurface=environment=>['ocean','aurora','alien','cavern','cavern-glow','lava','cavern-lava'].includes(environment);
export const hasAtmosphericWeather=environment=>!isSpaceEnvironment(environment)&&!environment.startsWith('cavern');

// Small reflected-light fills keep shaded surfaces legible without giving
// airless scenes the blue daylight dome used by the atmospheric surroundings.
export function environmentLighting(environment,cavernLighting='natural'){
  if(environment==='cavern-lava')return {...environmentLighting('cavern',cavernLighting==='natural'?'amber':cavernLighting),ground:[.85,.16,.025]};
  if(environment.startsWith('cavern'))return {space:false,enclosed:true,...({
    natural:{ambient:1.3,sky:[.39,.44,.47],ground:[.18,.16,.14],exposure:1.1,direct:.65},
    bio:{ambient:1.9,sky:[.20,.70,.48],ground:[.09,.25,.20],exposure:1.15,direct:.65},
    amber:{ambient:2.1,sky:[.95,.61,.29],ground:[.32,.19,.09],exposure:1.15,direct:1.3},
    cool:{ambient:2.2,sky:[.40,.67,.90],ground:[.15,.23,.31],exposure:1.15,direct:1.1}
  }[cavernLighting]||{ambient:1.3,sky:[.39,.44,.47],ground:[.18,.16,.14],exposure:1.1,direct:.65})};
  switch(environment){
    case 'lava':return {space:false,ambient:1.1,sky:[.72,.48,.35],ground:[.85,.16,.025],exposure:1};
    case 'aurora':return {space:false,ambient:1.05,sky:[.50,.78,.89],ground:[.19,.30,.30],exposure:1.05};
    // Keep the alien palette in the authored plants and sky, without washing
    // physically based ground scans into a bright lavender sheet at noon.
    case 'alien':return {space:false,ambient:.48,directScale:.42,reflectionScale:.55,sky:[.53,.68,.76],ground:[.18,.22,.24],exposure:.94};
    case 'cavern-glow':case 'cavern':return {space:false,enclosed:true,ambient:2.4,sky:[.42,.67,.63],ground:[.25,.20,.14],exposure:1.2};
    case 'space':return {space:true,ambient:.13,sky:[.42,.46,.58],ground:[.055,.06,.08],exposure:.95};
    case 'planet':return {space:true,ambient:.25,sky:[.35,.48,.67],ground:[.16,.25,.38],exposure:1};
    case 'asteroids':return {space:true,ambient:.18,sky:[.48,.47,.46],ground:[.18,.145,.11],exposure:.98};
    case 'clouds':return {space:false,ambient:1.12,ground:[.43,.47,.53],exposure:1.02};
    default:return {space:false,ambient:1,ground:[.27,.30,.17],exposure:1.05};
  }
}
