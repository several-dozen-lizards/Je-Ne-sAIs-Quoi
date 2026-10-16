export const FINISHES={plaster:'Lime plaster',timber:'Honey oak boards',stone:'Stone masonry',brick:'Red brick',concrete:'Pale concrete',marble:'White marble',parquet:'Parquet wood',tiles:'Terracotta tiles',roof:'Slate shingles',copper:'Aged copper',thatch:'Golden thatch'};
export const validFinish=id=>Object.hasOwn(FINISHES,id)||/^custom_[a-f0-9-]{36}$/.test(id||'');
export function validateTextures(textures=[]){
  if(!Array.isArray(textures)||textures.length>4)throw Error('Use up to four custom textures per island.');
  let total=0;const ids=new Set();
  for(const t of textures){
    if(!t||!/^custom_[a-f0-9-]{36}$/.test(t.id)||ids.has(t.id)||typeof t.name!=='string'||!t.name.length||t.name.length>80||typeof t.data!=='string'||!/^data:image\/jpeg;base64,[A-Za-z0-9+/]+={0,2}$/.test(t.data)||t.data.length>300000)throw Error('Invalid custom texture.');
    ids.add(t.id);total+=t.data.length;
  }
  if(total>1000000)throw Error('Custom textures exceed the island image budget.');
  return ids;
}
export function validatePartitions(b){
  const walls=b.partitions||[];if(!Array.isArray(walls)||walls.length>60)throw Error('Use up to 60 interior walls per structure.');
  const ids=new Set();
  for(const p of walls){
    if(!p||typeof p.id!=='string'||!p.id.length||p.id.length>80||ids.has(p.id)||!Number.isInteger(p.floor)||p.floor<0||p.floor>=b.floors||typeof p.door!=='boolean'||![p.ax,p.az,p.bx,p.bz].every(Number.isFinite)||Math.hypot(p.bx-p.ax,p.bz-p.az)<(p.door?1.6:.5))throw Error('Invalid interior wall or doorway.');
    ids.add(p.id);
    if(p.doorLeaf!==undefined&&!['none','solid'].includes(p.doorLeaf)||p.doorStyle!==undefined&&!['flat','panelled','medieval','glazed'].includes(p.doorStyle)||p.doorColor!==undefined&&!/^#[0-9a-f]{6}$/i.test(p.doorColor)||p.doorImage!==undefined&&!/^custom_[a-f0-9-]{36}$/.test(p.doorImage)||p.doorAngle!==undefined&&(!Number.isFinite(p.doorAngle)||p.doorAngle<0||p.doorAngle>120)||p.frames!==undefined&&typeof p.frames!=='boolean')throw Error('Invalid interior door.');
    for(const [x,z] of [[p.ax,p.az],[p.bx,p.bz]])if(b.shape==='round'?(x/(b.width/2-.18))**2+(z/(b.depth/2-.18))**2>1:Math.abs(x)>b.width/2-.18||Math.abs(z)>b.depth/2-.18)throw Error('Keep interior walls inside the building.');
    // Segment clipping against the stair flight and landing clearance.
    if(b.stairs&&b.floors>1){let lo=0,hi=1;for(const [a,d,min,max] of [[p.ax,p.bx-p.ax,.65,2.95],[p.az,p.bz-p.az,-3.3,3.3]]){if(Math.abs(d)<1e-9){if(a<min||a>max){hi=-1;break;}}else{const t1=(min-a)/d,t2=(max-a)/d;lo=Math.max(lo,Math.min(t1,t2));hi=Math.min(hi,Math.max(t1,t2));}}if(lo<=hi)throw Error('Leave the staircase and its landings clear.');}
  }
}
