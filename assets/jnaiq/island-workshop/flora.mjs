import * as THREE from './vendor/three.module.js';
import {GARDEN_GROUPS,ROSE_IDS,ROSE_STYLES,SUMAC_IDS} from './plants.mjs?sumac=2';
import {random} from './terrain.mjs?caves=retired';
export {PLANTS,PLANT_IDS,specimenVariant} from './plants.mjs?sumac=2';

// Each specimen compiles into one woody mesh and one leaf mesh. Branches and
// leaves are real geometry; they do not create individual draw calls.
const V=(x=0,y=0,z=0)=>new THREE.Vector3(x,y,z);
class Surface {
  constructor(){this.p=[];this.c=[];this.uv=[];}
  tri(a,b,c,colour,uv=[[0,0],[1,0],[.5,1]]){for(const [i,v] of [a,b,c].entries()){this.p.push(v.x,v.y,v.z);this.c.push(...colour);this.uv.push(...uv[i]);}}
  finish(smooth=false){const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(this.p,3));g.setAttribute('color',new THREE.Float32BufferAttribute(this.c,3));g.setAttribute('uv',new THREE.Float32BufferAttribute(this.uv,2));g.computeVertexNormals();
    if(smooth){const groups=new Map(),norm=g.attributes.normal;for(let i=0;i<this.p.length;i+=3){const key=this.p.slice(i,i+3).map(x=>Math.round(x*100000)).join(',');if(!groups.has(key))groups.set(key,{n:V(),indices:[]});const group=groups.get(key);group.n.add(V(norm.getX(i/3),norm.getY(i/3),norm.getZ(i/3)));group.indices.push(i/3);}for(const group of groups.values()){group.n.normalize();for(const i of group.indices)norm.setXYZ(i,group.n.x,group.n.y,group.n.z);}}
    g.computeBoundingBox();g.computeBoundingSphere();return g;}
}
function tube(out,points,radii,colour,sides=6,ribs=0,minimumSides=6){
  // Spend extra silhouette detail where it is visible. Fine twigs keep their
  // lean budget; trunks, pods and mushroom stems receive a rounder section.
  sides=Math.max(Math.max(...radii)>.30?8:minimumSides,sides);
  const rings=points.map((p,i)=>{
    const tangent=points[Math.min(i+1,points.length-1)].clone().sub(points[Math.max(i-1,0)]).normalize();
    const a=new THREE.Vector3().crossVectors(tangent,Math.abs(tangent.y)>.95?V(1,0,0):V(0,1,0)).normalize(),b=new THREE.Vector3().crossVectors(tangent,a).normalize();
    return Array.from({length:sides},(_,j)=>{const angle=j/sides*Math.PI*2,r=radii[i]*(1+ribs*(j%2?-.13:.13));return p.clone().addScaledVector(a,Math.cos(angle)*r).addScaledVector(b,Math.sin(angle)*r);});
  });
  const distance=[0];for(let i=1;i<points.length;i++)distance.push(distance[i-1]+points[i].distanceTo(points[i-1]));
  const tex=(row,column)=>[column/sides*Math.PI*2*radii[row]*.65,distance[row]*.65];
  for(let i=0;i<rings.length-1;i++)for(let j=0;j<sides;j++){
    const k=(j+1)%sides,c=colour.map(v=>v*(j%2?.93:1));
    out.tri(rings[i][j],rings[i][k],rings[i+1][j],c,[tex(i,j),tex(i,j+1),tex(i+1,j)]);
    out.tri(rings[i][k],rings[i+1][k],rings[i+1][j],c,[tex(i,j+1),tex(i+1,j+1),tex(i+1,j)]);
  }
  for(let j=0;j<sides;j++)out.tri(points.at(-1),rings.at(-1)[j],rings.at(-1)[(j+1)%sides],colour);
}
function branch(out,a,b,r,colour,bend=0){const mid=a.clone().lerp(b,.48);mid.y+=bend;tube(out,[a,mid,b],[r,r*.63,r*.14],colour);}
// Folded, tapered leaves with a central midrib. Broad blades can have torn edges.
function blade(out,start,direction,length,width,colour,{lobes=0,curve=.15,segments=5,roll=0,tear=0,veins=true}={}){
  // Large architectural leaves expose every bend in silhouette. Give those
  // a continuous curve while small canopy leaves retain the cheap far mesh.
  if(length>1&&width>.5)segments=Math.max(segments,8);
  else if(length>1&&width>.3)segments=Math.max(segments,6);
  const d=direction.clone().normalize();let side=new THREE.Vector3().crossVectors(d,Math.abs(d.y)>.96?V(1,0,0):V(0,1,0)).normalize();
  side.applyAxisAngle(d,roll);const up=new THREE.Vector3().crossVectors(side,d).normalize(),rows=[];
  for(let i=0;i<=segments;i++){
    const t=i/segments,center=start.clone().addScaledVector(d,length*t).addScaledVector(up,curve*Math.sin(t*Math.PI)*length);
    let shape=Math.pow(Math.sin(Math.PI*t),.72);if(lobes)shape*=.7+.3*Math.cos(t*Math.PI*lobes*2);
    if(tear&&i%3===2)shape*=1-tear;
    const half=width*shape*.5,edge=center.clone().addScaledVector(up,-half*.19);
    rows.push([edge.clone().addScaledVector(side,-half),center,edge.clone().addScaledVector(side,half)]);
  }
  // Negative V marks real leaf blades; caps, stems and petals keep ordinary UVs.
  const tex=(row,column)=>[column*.5,veins?-1-row/segments:row/segments];
  for(let i=0;i<segments;i++)for(let j=0;j<2;j++){
    const c=colour.map(v=>v*(j?.92:1.04));out.tri(rows[i][j],rows[i+1][j],rows[i][j+1],c,[tex(i,j),tex(i+1,j),tex(i,j+1)]);out.tri(rows[i][j+1],rows[i+1][j],rows[i+1][j+1],c,[tex(i,j+1),tex(i+1,j),tex(i+1,j+1)]);
  }
}

export function makePlant(kind,variant=0,detail='near'){
  const far=detail==='far';
  const wood=new Surface(),leaves=new Surface(),rng=random(21931+variant*737+Array.from(kind).reduce((n,c)=>n+c.charCodeAt(0),0));
  const bark=[.8,.74,.64],green=[.065,.19,.035],pineGreen=[.035,.115,.045];
  const jitter=()=>rng()-.5;
  function cap(center,radius,colour,profile='dome'){
    const rings=far?7:10,sides=far?24:36;
    function point(row,j){const t=row/rings,a=j/sides*Math.PI*2,r=radius*t*(1+.035*Math.sin(a*7+variant));return center.clone().add(V(Math.cos(a)*r,profile==='cup'?radius*(t*t*.55):radius*.43*Math.sqrt(Math.max(0,1-t*t)),Math.sin(a)*r));}
    for(let row=0;row<rings;row++)for(let j=0;j<sides;j++){
      const c=colour.map(v=>v*(.8+.2*Math.sin(row*.8+j*.5)**2));
      leaves.tri(point(row,j),point(row+1,j+1),point(row+1,j),c);leaves.tri(point(row,j),point(row,j+1),point(row+1,j+1),c);
    }
    for(let j=0;j<sides;j++){
      const a=j/sides*Math.PI*2,b=(j+1)/sides*Math.PI*2;
      const edge=point(rings,j),next=point(rings,j+1),inner=center.clone().add(V(0,-radius*(profile==='cup'?.55:.13),0));
      leaves.tri(inner,edge,next,[.30,.19,.28]);
      // Radial gill ridges extend below the cap instead of a flat underside.
      const inset=center.clone().add(V(Math.cos(a)*radius*.27,-radius*(profile==='cup'?.45:.11),Math.sin(a)*radius*.27)),ridge=edge.clone().lerp(inset,.5);ridge.y-=radius*.065;
      leaves.tri(inset,edge,ridge,[.48,.29,.40]);leaves.tri(inset,ridge,next,[.34,.20,.30]);
    }
  }
  function pod(center,scale,colour){
    const pts=Array.from({length:9},(_,i)=>center.clone().add(V(0,(i/8-.5)*scale*1.6,0)));
    tube(leaves,pts,pts.map((_,i)=>Math.max(.012,Math.sin(i/8*Math.PI)*scale*.48)),colour,far?8:12);
  }
  function cluster(center,radius,count,colour=green,lobes=0){
    count=Math.ceil(count*(far?.45:.8));
    for(let i=0;i<count;i++){
      const angle=rng()*Math.PI*2,y=jitter()*1.5,r=Math.sqrt(rng())*radius;
      const p=center.clone().add(V(Math.cos(angle)*r,y*radius*.5,Math.sin(angle)*r));
      blade(leaves,p,V(jitter(),.15+jitter()*.6,jitter()),(.35+rng()*.35)*(far?1.3:1),(.22+rng()*.18)*(far?1.3:1),colour.map(c=>c*(.75+rng()*.5)),{lobes,segments:far?2:lobes?4:3,roll:rng()*6,curve:.13});
    }
  }
  function deciduous(type){
    if(type==='baobab'){
      // An adult bottle trunk carrying a broad, irregular crown of heavy arms.
      // Variant changes proportions, not just the orientation of one silhouette.
      const h=11.8+variant*1.1,base=2.35+variant*.24,colour=[.80,.77,.70];
      const lean=V(jitter()*.55,0,jitter()*.45);
      const trunk=[V(0,-.08,0),V(.08,h*.12,-.04),V(-.12,h*.38,.1),V(lean.x,h*.62,lean.z),V(lean.x*.8,h*.74,lean.z*.8)];
      tube(wood,trunk,[base*1.13,base,base*1.08,base*.72,base*.38],colour,16);
      for(let i=0;i<7;i++){
        const a=i*2.399+variant*.5,reach=base*(1.32+rng()*.27);
        tube(wood,[V(Math.cos(a)*base*.7,.6,Math.sin(a)*base*.7),V(Math.cos(a)*base,.20,Math.sin(a)*base),V(Math.cos(a)*reach,.015,Math.sin(a)*reach)],[.48,.30,.035],colour,7);
      }
      for(let i=0;i<9;i++){
        const angle=i*2.399+variant*.6,spread=4.5+rng()*1.6;
        const a=V(lean.x+Math.cos(angle)*base*.32,h*(.60+rng()*.12),lean.z+Math.sin(angle)*base*.32);
        const elbow=V(Math.cos(angle)*spread*.63,h*(.79+rng()*.10),Math.sin(angle)*spread*.63);
        const tip=V(Math.cos(angle)*spread,h*(.89+rng()*.09),Math.sin(angle)*spread);
        tube(wood,[a,elbow,tip],[base*.36,.42,.13],colour,9);
        for(let j=0;j<3;j++){
          const side=angle+(j-1)*.68,origin=elbow.clone().lerp(tip,.35+j*.25);
          const end=origin.clone().add(V(Math.cos(side)*(1.1+rng()*.8),.45+rng()*.8,Math.sin(side)*(1.1+rng()*.8)));
          branch(wood,origin,end,.16,colour,.28);
          cluster(end,1.05+rng()*.28,24,[.15,.24,.075]);
          // Exposed forked twigs retain the characteristic branching outline.
          const fork=end.clone().add(V(Math.cos(side+.7)*.6,.45,Math.sin(side+.7)*.6));
          branch(wood,end.clone().lerp(origin,.2),fork,.065,colour,.12);
        }
      }
      return;
    }
    const syc=type==='sycamore',jungle=type==='jungle',baobab=type==='baobab',bare=type==='bare',shrub=type==='shrub';
    const h=shrub?1.1:baobab?5.6:jungle?7.8:syc?6.5:5.8;
    const base=baobab?1.3:shrub?.1:syc?.32:.24;
    const trunk=[V(),V(jitter()*.25,h*.33,jitter()*.25),V(jitter()*.5,h*.65,jitter()*.5),V(jitter()*.55,h*.85,jitter()*.55)];
    const colour=syc?[1.15,1.13,1.02]:baobab?[1,.94,.84]:bark;
    tube(wood,trunk,[base,base*(baobab?1.12:.76),base*.51,base*.23],colour,baobab?12:8);
    if(baobab||jungle)for(let i=0;i<5;i++){const a=i*Math.PI*2/5,tip=V(Math.cos(a)*base*1.65,.04,Math.sin(a)*base*1.65),left=V(Math.cos(a-.23)*base,.03,Math.sin(a-.23)*base),right=V(Math.cos(a+.23)*base,.03,Math.sin(a+.23)*base),top=V(Math.cos(a)*base*.88,baobab?.8:1.5,Math.sin(a)*base*.88);wood.tri(left,tip,top,colour);wood.tri(top,tip,right,colour);}
    const limbs=shrub?5:baobab?7:8;
    for(let i=0;i<limbs;i++){
      const layer=i/(limbs-1),angle=i*2.399+variant*.7,spread=(shrub?.8:baobab?2.6:jungle?3.2:2.55)*( .8+rng()*.4)*(baobab||jungle||shrub?1:1-layer*.5);
      const a=trunk[2].clone();a.y=h*(baobab?.67:.36+i/limbs*.31);
      const b=V(Math.cos(angle)*spread*.55,h*(.65+rng()*.2),Math.sin(angle)*spread*.55);
      const tip=V(Math.cos(angle)*spread,h*(.81+rng()*.25),Math.sin(angle)*spread);
      if(!baobab&&!jungle&&!shrub){tip.y=h*(.60+layer*.5)+jitter()*.35;b.y=(a.y+tip.y)*.5+.15;}
      tube(wood,[a,b,tip],[base*.45,base*.23,.025],colour,6);
      for(let j=0;j<3;j++){
        const ang=angle+(j-1)*.65,origin=b.clone().lerp(tip,j*.3);
        const end=origin.clone().add(V(Math.cos(ang)*spread*.5,.35+rng()*.6,Math.sin(ang)*spread*.5));
        branch(wood,origin,end,shrub?.028:.052,colour,.13);
        if(bare){for(let k=0;k<3;k++){const p=origin.clone().lerp(end,.4+k*.2);branch(wood,p,p.clone().add(V(jitter()*.75,.3+rng()*.6,jitter()*.75)),.016,colour);}}
        else cluster(end,shrub?.45:baobab?.7:jungle?1.05:.7,shrub?12:baobab?20:jungle?26:24,type==='maple'?[.095,.21,.025]:green,type==='maple'||syc?3:0);
      }
    }
  }
  if(['woodland_fern','lady_fern','sword_fern'].includes(kind)){
    const sword=kind==='sword_fern',lace=kind==='lady_fern';
    const count=(far?5:8)+variant,spread=(sword?.85:lace?1.4:1.2)*(1+variant*.12);
    // A crown of unequal, arching fronds: broad lower pinnae taper to fine tips.
    // The pinnae themselves carry paired pinnules, leaving real gaps in the mesh.
    for(let i=0;i<count;i++){
      const angle=i*2.399+jitter()*.5,reach=spread*(.75+rng()*.5),height=(sword?1.5:lace?1.05:1.25)*(.7+rng()*.35);
      const forward=V(Math.cos(angle),0,Math.sin(angle)),side=V(-Math.sin(angle),0,Math.cos(angle));
      const point=t=>forward.clone().multiplyScalar(reach*t**1.25).addScaledVector(side,Math.sin(t*Math.PI)*jitter()*.015).add(V(0,.04+height*Math.sin(t*Math.PI*(sword?.61:.87)),0));
      const segments=far?10:18,points=Array.from({length:segments+1},(_,j)=>point(j/segments));
      // Interpolate the same central stem for the leaf attachments.
      const at=t=>{const u=t*segments,j=Math.min(segments-1,Math.floor(u));return points[j].clone().lerp(points[j+1],u-j);};
      tube(wood,points,points.map((_,j)=>.012*(1-j/(segments+1))),[.22,.32,.07],4);
      const pairs=far?9:16;
      for(let j=0;j<pairs;j++){
        const t=.16+j/pairs*.80,width=(sword?.22:lace?.46:.38)*Math.sin(Math.PI*((t-.08)/.94))**.75*(1-t*.45);
        const colour=[.065+rng()*.04,.24+rng()*.10,.075+rng()*.04];
        for(const sign of [-1,1]){
          const start=at(t+(sign===1?.009:0)),direction=side.clone().multiplyScalar(sign).addScaledVector(forward,.20+t*.4).normalize();
          if(sword||far){blade(leaves,start,direction,width,width*(sword?.22:.29),colour,{segments:far?2:5,lobes:sword?5:4,curve:.08});continue;}
          const end=start.clone().addScaledVector(direction,width),rib=forward.clone().multiplyScalar(.009);
          leaves.tri(start.clone().sub(rib),start.clone().add(rib),end,colour);
          for(let k=0;k<5;k++){
            const u=.12+k*.16,base=start.clone().lerp(end,u),length=width*.25*Math.sin(Math.PI*(u+.10));
            for(const edge of [-1,1]){
              const tip=base.clone().addScaledVector(forward,edge*length).addScaledVector(direction,length*.35);
              const a=base.clone().addScaledVector(direction,-width*.043),b=base.clone().addScaledVector(direction,width*.067);
              const mid=base.clone().lerp(tip,.5);mid.y+=.012;
              leaves.tri(a,mid,tip,colour);leaves.tri(mid,b,tip,colour.map(c=>c*.9));
            }
          }
        }
      }
      blade(leaves,at(.94),forward.clone().add(V(0,-.4,0)),.12,.035,[.12,.32,.08],{segments:3});
    }
    // A couple of young curled croziers among the mature fronds.
    for(let i=0;i<2;i++){
      const angle=i*2.4+variant,forward=V(Math.cos(angle),0,Math.sin(angle)),h=.35+rng()*.3,points=[V(),V(0,h*.7,0)];
      for(let j=0;j<=10;j++){const a=j/10*Math.PI*1.7,r=.09*(1-j/14);points.push(forward.clone().multiplyScalar(Math.sin(a)*r).add(V(0,h+Math.cos(a)*r,0)));}
      tube(wood,points,points.map(()=>.012),[.20,.32,.06],4);
    }
  }else if(kind==='tree_stump'||kind==='fallen_log'){
    const fallen=kind==='fallen_log',radius=.32+variant*.09,length=3.8+variant*1.3;
    const points=fallen?Array.from({length:7},(_,i)=>V((i/6-.5)*length,radius*(.9+.12*Math.sin(i)),Math.sin(i*.8)*.12)):[V(0,-.06,0),V(.025,.3,0),V(-.035,.72+variant*.16,.04)];
    const radii=points.map((_,i)=>radius*(fallen?1-i/points.length*.24:i===0?1.6:1-i*.12));
    tube(wood,points,radii,[.60,.52,.39],far?8:13,.8);
    // Pale irregular end grain, concentric rings and radial splits.
    for(const index of [0,points.length-1]){
      const center=points[index],r=radii[index]*.96,axis=fallen?V(index?1:-1,0,0):V(0,index?1:-1,0),a=fallen?V(0,1,0):V(1,0,0),b=fallen?V(0,0,1):V(0,0,1);
      const face=center.clone().addScaledVector(axis,.014);
      for(let ring=0;ring<5;ring++)for(let j=0;j<16;j++){
        const angle=j/16*Math.PI*2,next=(j+1)/16*Math.PI*2;
        const p=(t,u)=>face.clone().addScaledVector(a,Math.cos(u)*r*t).addScaledVector(b,Math.sin(u)*r*t);
        const colour=ring%2?[.42,.30,.15]:[.60,.46,.27];
        // Both windings keep end grain visible on either broken end.
        const x=p(ring/5,angle),y=p((ring+1)/5,angle),z=p((ring+1)/5,next),q=p(ring/5,next);
        for(const tri of [[x,y,z],[x,z,q],[z,y,x],[q,z,x]])wood.tri(...tri,colour);
      }
    }
    for(let i=0;i<(fallen?3:6);i++){
      const angle=i*2.399+variant,base=fallen?points[1+i*2].clone():V(Math.cos(angle)*radius*.5,.2,Math.sin(angle)*radius*.5);
      const end=fallen?base.clone().add(V(.1,.35+rng()*.3,(i%2?1:-1)*.45)):V(Math.cos(angle)*radius*2.3,.015,Math.sin(angle)*radius*2.3);
      branch(wood,base,end,.10,[.52,.44,.32],.04);
    }
    // Small moss patches hug the upper bark without making a leafy canopy.
    for(let i=0;i<(far?5:12);i++){
      const x=fallen?(rng()-.5)*length*.85:jitter()*radius,z=jitter()*radius;
      const y=fallen?radius*1.85:.76+variant*.16;
      blade(leaves,V(x,y,z),V(jitter(),.05,jitter()),.12+rng()*.13,.09,[.12,.22,.045],{segments:2,curve:.06});
    }
  }else if(ROSE_IDS.includes(kind)){
    const style=ROSE_STYLES[kind],habit=style.habit,colour=style.colour;
    const roseGreen=[.075,.27,.055],stemGreen=[.26,.40,.10];
    const branchCount=far?(habit==='climbing'?10:8):(habit==='climbing'?16:13);
    const height={rounded:1.22,arching:1.45,vase:1.72,spreading:.78,airy:1.58,climbing:3.35}[habit]*(.94+variant*.055);
    const spread={rounded:1.05,arching:1.38,vase:.86,spreading:1.72,airy:1.16,climbing:1.52}[habit]*(.95+variant*.045);
    function roseBloom(center,radius,bloomColour,open=1){
      const rings=far?2:3;
      for(let ring=0;ring<rings;ring++){
        const petals=(far?6:8)-ring,petalRadius=radius*(1-ring*.22),lift=.15+ring*.36+(1-open)*.26;
        for(let j=0;j<petals;j++){
          const angle=j*Math.PI*2/petals+ring*1.17+variant*.19;
          const start=center.clone().add(V(Math.cos(angle)*radius*ring*.055,ring*radius*.075,Math.sin(angle)*radius*ring*.055));
          blade(leaves,start,V(Math.cos(angle),lift,Math.sin(angle)),petalRadius,petalRadius*(ring?.75:.92),bloomColour.map(c=>c*(.86+ring*.07)),{segments:far?2:3,curve:.34+ring*.10,roll:angle,veins:false});
        }
      }
      tube(leaves,[center.clone().add(V(0,-radius*.12,0)),center.clone().add(V(0,radius*.08,0)),center.clone().add(V(0,radius*.22,0))],[radius*.15,radius*.22,.008],[.78,.54,.08],5);
    }
    function roseLeaf(origin,direction,size){
      const d=direction.clone().normalize(),side=V(-d.z,0,d.x).normalize();
      const tip=origin.clone().addScaledVector(d,size*.46);
      branch(leaves,origin,tip,.008,stemGreen);
      for(const [t,sign] of [[.18,-1],[.18,1],[.48,-1],[.48,1]]){
        const at=origin.clone().lerp(tip,t),out=d.clone().multiplyScalar(.35).addScaledVector(side,sign).add(V(0,.12,0));
        blade(leaves,at,out,size*(.38+t*.08),size*.22,roseGreen.map(c=>c*(.86+rng()*.24)),{segments:2,curve:.08,roll:sign*.18});
      }
      blade(leaves,tip,d.clone().add(V(0,.14,0)),size*.46,size*.22,roseGreen,{segments:2,curve:.09});
    }
    function roseFiller(center,angle,size){
      for(let j=0;j<3;j++){
        const a=angle+(j-1)*.82+jitter()*.22,start=center.clone().add(V(jitter()*.055,jitter()*.045,jitter()*.055));
        blade(leaves,start,V(Math.cos(a),.10+rng()*.16,Math.sin(a)),size*(.76+rng()*.18),size*.42,roseGreen.map(c=>c*(.82+rng()*.25)),{segments:2,curve:.07,roll:jitter()*.22});
      }
    }
    const primaryCount=far?Math.max(6,branchCount-3):({rounded:8,arching:9,vase:8,spreading:9,airy:8,climbing:8}[habit]);
    const flowerSites=[];
    const pointAlong=(points,u)=>{const scaled=u*(points.length-1),index=Math.min(points.length-2,Math.floor(scaled));return points[index].clone().lerp(points[index+1],scaled-index);};
    for(let i=0;i<primaryCount;i++){
      const phase=(i+.35)/primaryCount,angle=i*2.399+variant*.71+jitter()*.22;
      let reach=spread*(.58+rng()*.36),topY=height*(.75+rng()*.23);
      if(habit==='rounded'){reach*=.73+.18*Math.sin(phase*Math.PI);topY=height*(.78+.18*Math.cos((phase-.5)*Math.PI));}
      if(habit==='arching'){reach*=.88+rng()*.22;topY=height*(.72+rng()*.20);}
      if(habit==='vase'){reach*=.48+.28*phase;topY=height*(.80+rng()*.19);}
      if(habit==='spreading'){reach*=.98+rng()*.16;topY=height*(.60+rng()*.24);}
      if(habit==='airy'){reach*=.60+rng()*.42;topY=height*(.72+rng()*.27);}
      if(habit==='climbing'){reach*=.28+rng()*.42;topY=height*(.70+rng()*.30);}
      const base=V(jitter()*.16,.025,jitter()*.16),bend=angle+jitter()*.28;
      const points=[base,V(Math.cos(bend)*reach*.12,topY*.30,Math.sin(bend)*reach*.12),V(Math.cos(angle)*reach*.48,topY*(habit==='arching'?.77:.66),Math.sin(angle)*reach*.48),V(Math.cos(angle)*reach,topY,Math.sin(angle)*reach)];
      if(habit==='arching'){points[2].y+=height*.12;points[3].y-=height*.08;}
      tube(leaves,points,[.041,.034,.020,.007],stemGreen,far?5:6);
      for(let fill=0;fill<(far?2:3);fill++)roseFiller(pointAlong(points,.34+fill*(far?.30:.20)),angle+fill*1.1,.34+(habit==='climbing'?.02:.05));
      for(let leaf=0;leaf<(far?3:5);leaf++){
        const u=.20+leaf*(far?.24:.145),at=pointAlong(points,u),side=angle+(leaf%2?1:-1)*(1.0+jitter()*.18);
        roseLeaf(at,V(Math.cos(side),.12+jitter()*.12,Math.sin(side)),.48+rng()*.08);
      }
      const lateralCount=far?1:2;
      for(let lateral=0;lateral<lateralCount;lateral++){
        const u=.46+lateral*.22+jitter()*.035,origin=pointAlong(points,u),side=angle+(lateral%2?1:-1)*(.70+rng()*.24),length=spread*(.23+rng()*.15);
        const tip=origin.clone().add(V(Math.cos(side)*length,height*(.09+rng()*.09),Math.sin(side)*length));
        branch(leaves,origin,tip,.015,stemGreen,.035);
        roseLeaf(origin.clone().lerp(tip,.44),V(Math.cos(side+(lateral%2?-1:1)*.95),.14,Math.sin(side+(lateral%2?-1:1)*.95)),.44+rng()*.07);
        roseLeaf(origin.clone().lerp(tip,.76),V(Math.cos(side-(lateral%2?-1:1)*.82),.16,Math.sin(side-(lateral%2?-1:1)*.82)),.40+rng()*.06);
        flowerSites.push({tip,angle:side});
      }
      flowerSites.push({tip:points.at(-1),angle});
      if(!far)for(let thorn=0;thorn<2;thorn++){
        const at=pointAlong(points,.26+thorn*.23),side=V(Math.cos(angle+Math.PI/2),0,Math.sin(angle+Math.PI/2)).multiplyScalar(thorn?1:-1);
        const rootA=at.clone().add(V(0,-.025,0)),rootB=at.clone().add(V(0,.025,0)),point=at.clone().addScaledVector(side,.07).add(V(0,-.035,0));leaves.tri(rootA,point,rootB,[.32,.27,.08]);
      }
    }
    const bloomCount=far?(habit==='airy'?13:11):(habit==='airy'?21:habit==='climbing'?20:18);
    for(let i=0;i<bloomCount;i++){
      const stem=flowerSites[(i*5+variant*3)%flowerSites.length],center=stem.tip.clone().add(V(Math.cos(stem.angle)*.025,.035,Math.sin(stem.angle)*.025));
      const tint=colour.map((c,index)=>Math.min(1,c*(.88+rng()*.22)+(index===0?rng()*.055:0)));
      if(i%7===6)tube(leaves,[center.clone().add(V(0,-.10,0)),center,center.clone().add(V(0,.13,0))],[.028,.075,.008],roseGreen,5);
      else roseBloom(center,(habit==='airy'?.13:.16)*(far?1.18:1)*(1+rng()*.18),tint,i%5===0?.62:1);
    }
  }else if(SUMAC_IDS.includes(kind)){
    const winter=kind==='staghorn_sumac_winter',height=(5.1+variant*.34),crown=(3.5+variant*.28);
    const sumacBark=[.46,.43,.36],twig=[.34,.31,.25],summerGreen=[.055,.235,.035],terminals=[],coneSites=[];
    const pointAt=(points,u)=>{const scaled=u*(points.length-1),index=Math.min(points.length-2,Math.floor(scaled));return points[index].clone().lerp(points[index+1],scaled-index);};
    function sumacCone(center,scale){
      const points=[center.clone().add(V(0,-scale*.34,0)),center.clone().add(V(0,-scale*.06,0)),center.clone().add(V(0,scale*.34,0)),center.clone().add(V(0,scale*.68,0)),center.clone().add(V(0,scale*.82,0))];
      tube(leaves,points,[scale*.10,scale*.18,scale*.15,scale*.07,.006],[.35,.035,.025],far?6:9,.72);
    }
    function sumacFrond(start,direction,scale){
      const d=direction.clone().normalize(),side=V(-d.z,0,d.x).normalize(),tip=start.clone().addScaledVector(d,scale);
      // Centimetre-wide leaf stalks need fewer radial faces than woody limbs.
      // Keep every frond and leaflet while respecting the specimen budget.
      tube(leaves,[start,start.clone().lerp(tip,.55).add(V(0,.035,0)),tip],[.013,.009,.003],[.22,.35,.075],4,0,4);
      const pairs=far?4:7;
      for(let pair=0;pair<pairs;pair++){
        const t=.12+pair/pairs*.77,at=start.clone().lerp(tip,t),length=scale*(.34-.12*t),colour=summerGreen.map(c=>c*(.78+rng()*.44));
        for(const sign of [-1,1]){
          const out=side.clone().multiplyScalar(sign).addScaledVector(d,.18).add(V(0,-.10+rng()*.14,0));
          blade(leaves,at,out,length,length*.48,colour,{segments:2,curve:.055,roll:sign*(.38+rng()*.34)+jitter()*.18});
        }
      }
      blade(leaves,tip,d.clone().add(V(0,.08,0)),scale*.22,scale*.075,summerGreen,{segments:2,curve:.04,roll:.34+jitter()*.22});
    }
    const trunks=[];
    for(let trunkIndex=0;trunkIndex<3;trunkIndex++){
      const angle=trunkIndex*2.19+variant*.48,lean=crown*(.15+trunkIndex*.045),base=V(Math.cos(angle)*.20,.01,Math.sin(angle)*.20);
      const points=[base],fractions=[.14,.27,.40,.53,.66],turns=[.82,-.64,1.02,-.78,.47];
      for(let segment=0;segment<fractions.length;segment++){
        const previous=points.at(-1),bend=angle+turns[segment]+Math.sin(variant*1.7+trunkIndex+segment)*.18,step=lean*(.38+segment*.055);
        points.push(previous.clone().add(V(Math.cos(bend)*step,height*fractions[segment]-previous.y,Math.sin(bend)*step)));
      }
      tube(wood,points,[.20-trunkIndex*.018,.18-trunkIndex*.016,.15-trunkIndex*.014,.12-trunkIndex*.011,.085-trunkIndex*.008,.052],sumacBark,far?7:9,.20);
      trunks.push(points);
    }
    const limbCount=far?10:(winter?18:15);
    for(let i=0;i<limbCount;i++){
      const trunk=trunks[i%trunks.length],layer=(i+.6)/limbCount,angle=i*2.399+variant*.63+jitter()*.38;
      const origin=pointAt(trunk,.48+(i%5)*.105),reach=crown*(.38+rng()*.30),topY=height*(.69+rng()*.27);
      const elbowAngle=angle+(i%2?-.34:.31)+jitter()*.17;
      const points=[origin,origin.clone().add(V(Math.cos(elbowAngle)*reach*.34,(topY-origin.y)*.39,Math.sin(elbowAngle)*reach*.34)),origin.clone().add(V(Math.cos(angle-.16)*reach*.70,(topY-origin.y)*.72,Math.sin(angle-.16)*reach*.70)),origin.clone().add(V(Math.cos(angle)*reach,topY-origin.y,Math.sin(angle)*reach))];
      tube(wood,points,[.064,.043,.023,.006],twig,far?5:6,.18);
      terminals.push({tip:points.at(-1),angle,scale:.82+rng()*.22});
      coneSites.push(points.at(-1));
      const lateralCount=far?1:2;
      for(let lateral=0;lateral<lateralCount;lateral++){
        const u=.43+lateral*.25+jitter()*.035,start=pointAt(points,u),sideAngle=angle+(lateral%2?1:-1)*(.72+rng()*.30),length=crown*(.20+rng()*.13);
        const mid=start.clone().add(V(Math.cos(sideAngle+.20)*length*.52,.13+rng()*.20,Math.sin(sideAngle+.20)*length*.52));
        const end=start.clone().add(V(Math.cos(sideAngle)*length,.32+rng()*.34,Math.sin(sideAngle)*length));
        tube(wood,[start,mid,end],[.025,.014,.004],twig,far?4:5,.14);
        terminals.push({tip:end,angle:sideAngle,scale:.62+rng()*.22});
        if((i+lateral)%2===0)coneSites.push(end);
        if(!far){
          const forkAngle=sideAngle+(lateral?-.58:.55),forkStart=mid.clone(),forkEnd=forkStart.clone().add(V(Math.cos(forkAngle)*length*.48,.20+rng()*.22,Math.sin(forkAngle)*length*.48));
          branch(wood,forkStart,forkEnd,.010,twig,.045);terminals.push({tip:forkEnd,angle:forkAngle,scale:.50+rng()*.16});
        }
      }
    }
    if(winter)for(const [i,site] of terminals.entries()){
      const forkAngle=site.angle+(i%2?-.48:.55)+jitter()*.24,length=.32+rng()*.36,end=site.tip.clone().add(V(Math.cos(forkAngle)*length,.18+rng()*.30,Math.sin(forkAngle)*length));
      branch(wood,site.tip,end,.006,twig,.055);if(i%4===0)coneSites.push(end);
    }
    if(!winter)for(const [i,site] of terminals.entries()){
      if(i%5===4)continue;
      const lift=.20+jitter()*.28,direction=V(Math.cos(site.angle+jitter()*.42),lift,Math.sin(site.angle+jitter()*.42));
      sumacFrond(site.tip,direction,site.scale*(1.10+rng()*.26));
    }
    const cones=winter?coneSites:coneSites.filter((_,i)=>i%3===0);
    for(const [i,site] of cones.entries())sumacCone(site.clone().add(V(0,.08,0)),(winter?.28:.24)*(1+(i%3)*.08));
  }else if(GARDEN_GROUPS[kind]){
    const low=GARDEN_GROUPS[kind]==='low',large=GARDEN_GROUPS[kind]==='large';
    const grass=['meadow_grass','pampas_grass'].includes(kind),umbrella=kind==='giant_rhubarb';
    const h=low?(kind==='creeping_thyme'?.15:.38):large?(umbrella?3.2:3.6):kind==='lavender'?.95:1.65;
    const spread=low?1.55:large?1.45:1.05;
    const colours={meadow_daisies:[.94,.90,.72],creeping_thyme:[.63,.21,.45],wildflower_carpet:[.8,.3,.08],lavender:[.38,.19,.62],flowering_heath:[.86,.51,.59],hibiscus_bush:[.8,.025,.08],firewheel_bush:[1,.25,.015],foxglove:[.68,.15,.49],rainbow_protea:[.85,.12,.48]};
    const count=far?12:low?32:grass?48:umbrella?13:18;
    function bud(at,r,col){
      tube(leaves,[at.clone().add(V(0,-r*.5,0)),at,at.clone().add(V(0,r*.8,0))],[r*.3,r,r*.12],col,5);
    }
    function flower(at,r,col,petals=7){
      for(let j=0;j<petals;j++){const a=j*Math.PI*2/petals;blade(leaves,at,V(Math.cos(a),.18,Math.sin(a)),r,r*.65,col,{segments:far?2:4,curve:.27,veins:false});}
      bud(at.clone().add(V(0,r*.08,0)),r*.22,[.7,.39,.025]);
    }
    for(let i=0;i<count;i++){
      const a=rng()*Math.PI*2,r=Math.sqrt(rng())*spread,base=V(Math.cos(a)*r,.025,Math.sin(a)*r);
      const height=h*(.6+rng()*.4),top=base.clone().add(V(jitter()*.4,height,jitter()*.4));
      const foliage=[.075+rng()*.045,.20+rng()*.12,.045+rng()*.035];
      if(grass){
        blade(leaves,base,V(Math.cos(a)*.4,1,Math.sin(a)*.4),height,low?.055:.12,foliage,{segments:far?3:6,curve:.32});
        if(!low&&i%3===0){branch(leaves,base,top,.022,[.26,.32,.09]);for(let j=0;j<9;j++){const t=j/9,at=top.clone().add(V(0,-.7+t*.7,0));for(let k=0;k<3;k++){const b=k*2.399+j;blade(leaves,at,V(Math.cos(b)*.5,.7,Math.sin(b)*.5),.3*(1-t)+.06,.085,[.71,.65,.43],{segments:2,curve:.12});}}}
        continue;
      }
      branch(leaves,base,top,low?.009:umbrella?.075:.025,foliage,.08);
      if(!low&&!large&&kind!=='lavender'){
        const fork=base.clone().lerp(top,.56);
        branch(leaves,V(0,.08,0),fork,.032,foliage,.12);
        cluster(fork,.4,far?7:16,foliage);
      }
      if(umbrella){for(let k=0;k<9;k++){const b=k*Math.PI*2/9;blade(leaves,top,V(Math.cos(b),-.25,Math.sin(b)),1.35,.7,foliage,{lobes:3,segments:6,curve:.22});}continue;}
      for(let j=0;j<(low?2:5);j++){const at=base.clone().lerp(top,.12+j*(low?.3:.16)),b=a+j*2.399;blade(leaves,at,V(Math.cos(b),.2,Math.sin(b)),low?.23:.48,low?.1:.22,foliage,{segments:3,lobes:kind==='hibiscus_bush'?2:0});}
      let col=colours[kind];
      if(kind==='wildflower_carpet')col=[[.85,.76,.13],[.56,.2,.61],[.94,.87,.7],[.85,.19,.08]][i%4];
      if(kind==='lavender'||kind==='foxglove'){
        for(let j=0;j<(far?5:10);j++){const at=top.clone().add(V(Math.cos(j*2.399)*.07,-j*h*.038,Math.sin(j*2.399)*.07));bud(at,kind==='lavender'?.055:.14,col);}
      }else if(kind==='rainbow_protea'){
        for(let tier=0;tier<3;tier++)for(let j=0;j<9;j++){const b=j*Math.PI*2/9+tier*.3;blade(leaves,top,V(Math.cos(b),.3+tier*.4,Math.sin(b)),.66-tier*.12,.23,[[.9,.16,.25],[.98,.46,.08],[.47,.14,.65]][tier],{segments:far?2:4,curve:.28,veins:false});}
        bud(top.clone().add(V(0,.2,0)),.2,[.91,.7,.2]);
      }else flower(top,low?.09:kind==='flowering_heath'?.12:.28,col,kind==='firewheel_bush'?12:7);
    }
  }else if(kind==='pine'){
    const h=6.5+variant*.3,trunkTop=V(jitter()*.2,h,jitter()*.2);
    tube(wood,[V(),V(.08,h*.5,0),trunkTop],[.2,.115,.025],bark,7);
    for(let tier=0;tier<(far?6:8);tier++){
      const y=1.3+tier*(far?.8:.61),tierReach=(h-y)*.4;
      for(let arm=0;arm<(far?5:6);arm++){
        const reach=tierReach*(.78+rng()*.4),angle=arm*Math.PI*2/(far?5:6)+tier*.87+variant*.3,a=V(.03,y+jitter()*.15,0),tip=V(Math.cos(angle)*reach,y+.12+jitter()*.4,Math.sin(angle)*reach);
        branch(wood,a,tip,.047*(1-tier*.07),bark,-.17);
        // Broad, serrated needle sprays retain the branch silhouette at distance.
        for(const roll of [-.24,.36])blade(leaves,a.clone().lerp(tip,.12),tip.clone().sub(a),reach*.95,reach*.66,pineGreen.map(c=>c*(.85+rng()*.3)),{lobes:4,segments:far?4:6,curve:.05,roll});
        for(let twig=0;twig<(far?2:3);twig++){
          const t=.22+twig*(far?.38:.25),p=a.clone().lerp(tip,t),side=angle+(twig%2?1:-1)*.7,extent=reach*(1-t)*.65+.15;
          const end=p.clone().add(V(Math.cos(side)*extent,.12,Math.sin(side)*extent));
          branch(wood,p,end,.013,bark);
          for(let n=0;n<(far?1:2);n++){
            const origin=p.clone().lerp(end,n/(far?1:2)),d=V(Math.cos(side+(n%2?.8:-.8)),.25,Math.sin(side+(n%2?.8:-.8)));
            blade(leaves,origin,d,.3+rng()*.19,far?.19:.12,pineGreen.map(c=>c*(.8+rng()*.5)),{segments:2,curve:.06});
          }
        }
      }
    }
    for(let i=0;i<8;i++){const a=i*Math.PI/4;blade(leaves,trunkTop.clone().add(V(0,-.7,0)),V(Math.cos(a)*.3,1,Math.sin(a)*.3),.8,.12,pineGreen,{segments:2});}
  }else if(kind==='palm'){
    const tip=V(.6+variant*.15,5.3,.25);
    tube(wood,[V(),V(.08,1.7,0),V(.3,3.5,.08),tip],[.23,.2,.16,.13],[1.05,.94,.75],9);
    for(let i=0;i<11;i++){
      const a=i*2.399,len=2.5+rng()*.8,points=[];
      for(let j=0;j<=8;j++){const t=j/8;points.push(tip.clone().add(V(Math.cos(a)*len*t,Math.sin(t*Math.PI)*.75-t*t*.8,Math.sin(a)*len*t)));}
      tube(wood,points,points.map((_,j)=>.035*(1-j/9)),[.48,.53,.23],4);
      for(let j=1;j<8;j++)for(const sign of [-1,1]){
        const t=j/8,spread=.7*Math.sin(t*Math.PI)+.18;
        blade(leaves,points[j],V(Math.cos(a+sign*1.05),-.3,Math.sin(a+sign*1.05)),spread,.17,[.07,.2,.035],{segments:3,curve:-.16});
      }
    }
  }else if(kind==='banana'||kind==='bird_of_paradise'){
    const banana=kind==='banana',h=banana?2.25:.55;
    if(banana)tube(wood,[V(),V(.05,h*.5,0),V(.09,h,0)],[.23,.17,.1],[.52,.7,.31],8);
    for(let i=0;i<(banana?9:8);i++){
      const a=banana?i*2.399:(i%2?Math.PI:0)+jitter()*.5,t=i/9;
      const base=V(.09,h,0),end=base.clone().add(V(Math.cos(a)*.5,.6+t*.8,Math.sin(a)*.5));
      branch(wood,base,end,.035,[.48,.64,.25]);
      blade(leaves,end,V(Math.cos(a),.13+t*.45,Math.sin(a)),banana?1.8+rng():1.15+rng()*.5,banana?.72:.43,[.065,.23,.035],{segments:9,curve:-.2,tear:banana?.17:0});
    }
    if(!banana)for(let i=0;i<3;i++){
      const tip=V((i-1)*.24,1.65+i*.15,.25),a=V((i-1)*.15,0,.15);branch(wood,a,tip,.018,[.4,.6,.22]);
      blade(leaves,tip,V(1,.12,0),.5,.13,[.3,.32,.15],{segments:3});
      for(let j=0;j<3;j++)blade(leaves,tip.clone().add(V(j*.06,.02,0)),V(.2+j*.2,1,.04),.35,.075,[1,.37,.045],{segments:2,veins:false});
      blade(leaves,tip,V(.9,.6,0),.32,.045,[.18,.29,.85],{segments:2,veins:false});
    }
  }else if(kind==='joshua'){
    const grey=[.84,.79,.67];tube(wood,[V(),V(.05,1.2,0),V(.12,2.4,.03)],[.3,.23,.15],grey,8);
    for(let i=0;i<6;i++){
      const a=i*2.399,tip=V(Math.cos(a)*(1+rng()*.55),2.6+rng()*1.4,Math.sin(a)*(1+rng()*.55));
      tube(wood,[V(.08,1.7+i*.1,0),tip.clone().multiply(V(.8,.72,.8)),tip],[.15,.1,.045],grey,7);
      for(let j=0;j<32;j++){
        const angle=j*2.399,up=1-j/20;
        blade(leaves,tip,V(Math.cos(angle),up,Math.sin(angle)),.6+rng()*.3,.085,[.15,.25,.085],{segments:2,curve:0});
      }
    }
  }else if(kind==='cactus'){
    const c=[.065,.19,.095];tube(leaves,[V(),V(0,2.2,0),V(0,3.9,0),V(0,4.06,0),V(0,4.17,0),V(0,4.22,0)],[.35,.32,.29,.25,.15,.01],c,20,1);
    for(let i=0;i<3;i++){
      const a=i*2.35+variant*.4,r=.85+i*.16,y=1.25+i*.58;
      tube(leaves,[V(0,y,0),V(Math.cos(a)*r*.7,y+.05,Math.sin(a)*r*.7),V(Math.cos(a)*r*.93,y+.18,Math.sin(a)*r*.93),V(Math.cos(a)*r,y+.4,Math.sin(a)*r),V(Math.cos(a)*r,y+1.25,Math.sin(a)*r),V(Math.cos(a)*r,y+1.39,Math.sin(a)*r),V(Math.cos(a)*r,y+1.48,Math.sin(a)*r)],[.2,.2,.195,.19,.17,.13,.01],c,16,1);
    }
  }else if(['button_mushrooms','toadstool_patch','chanterelle_patch','glowcap_patch'].includes(kind)){
    const red=kind==='toadstool_patch',gold=kind==='chanterelle_patch',glow=kind==='glowcap_patch';
    for(let i=0;i<6;i++){
      const angle=i*2.399+variant*.5,spread=Math.sqrt(i)*.25,x=Math.cos(angle)*spread,z=Math.sin(angle)*spread;
      const h=(glow?.16:red?.24:.12)+rng()*(red?.28:.18),r=(red?.14:glow?.075:.11)+rng()*.09;
      const tip=V(x+.035,h,z);
      tube(wood,[V(x,0,z),V(x+.01,h*.55,z+.025),tip],[r*.24,r*.17,r*.2],gold?[.65,.39,.12]:[.68,.61,.49],far?5:7);
      cap(tip,r,red?[.62,.055,.025]:gold?[.88,.43,.065]:glow?[.17,.62,.51]:[.44,.28,.15],gold?'cup':'dome');
      if(red)for(let j=0;j<10;j++){
        const a=rng()*Math.PI*2,t=.12+rng()*.68,s=.013+rng()*.012;
        const centre=tip.clone().add(V(Math.cos(a)*r*t,r*.43*Math.sqrt(1-t*t)+.003,Math.sin(a)*r*t));
        for(let k=0;k<5;k++)leaves.tri(centre,centre.clone().add(V(Math.cos(k*1.2566)*s,0,Math.sin(k*1.2566)*s)),centre.clone().add(V(Math.cos((k+1)*1.2566)*s,0,Math.sin((k+1)*1.2566)*s)),[.92,.84,.66]);
      }
    }
  }else if(kind==='giant_mushroom'||kind==='glow_shrooms'){
    const colony=kind==='glow_shrooms',count=colony?7:1;
    for(let i=0;i<count;i++){
      const a=i*2.399,x=colony?Math.cos(a)*Math.sqrt(i)*.55:0,z=colony?Math.sin(a)*Math.sqrt(i)*.55:0,h=colony?1.2+rng()*2.2:6.8+variant*.45,r=colony?.7+rng()*.65:3.1+variant*.15;
      const tip=V(x+.2,h,z);
      tube(wood,[V(x,0,z),V(x-.15,h*.45,z+.08),tip],[r*.21,r*.13,r*.11],[.42,.31,.40],10);
      cap(tip,r,colony?[.08,.42,.45]:[.48,.06,.18]);
      if(!colony)for(let k=0;k<22;k++){
        const t=.12+rng()*.76,angle=rng()*Math.PI*2,p=tip.clone().add(V(Math.cos(angle)*r*t,r*.43*Math.sqrt(1-t*t),Math.sin(angle)*r*t));
        const spot=.08+rng()*.12;for(let j=0;j<7;j++)leaves.tri(p.clone().add(V(0,.015,0)),p.clone().add(V(Math.cos(j/7*Math.PI*2)*spot,.01,Math.sin(j/7*Math.PI*2)*spot)),p.clone().add(V(Math.cos((j+1)/7*Math.PI*2)*spot,.01,Math.sin((j+1)/7*Math.PI*2)*spot)),[.7,.48,.52]);
      }
    }
  }else if(kind==='shelf_fungus'){
    tube(wood,[V(),V(.15,3,0),V(-.12,6.7,.1)],[.56,.38,.13],[.26,.16,.25],9);
    for(let i=0;i<9;i++){const a=i*2.399,r=1.1+rng()*.65;cap(V(Math.cos(a)*.5,.7+i*.64,Math.sin(a)*.5),r,[.18+i*.026,.12,.3+i*.02]);}
  }else if(kind==='coral_tree'){
    function fork(a,d,len,r,depth){const b=a.clone().addScaledVector(d,len);branch(wood,a,b,r,[.34,.09,.30],len*.15);if(!depth){pod(b,.22,[.1,.5,.48]);return;}for(let i=0;i<3;i++){const angle=i*Math.PI*2/3+rng(),next=V(d.x*.35+Math.cos(angle)*.6,.5+rng()*.5,d.z*.35+Math.sin(angle)*.6).normalize();fork(b,next,len*.64,r*.56,depth-1);}}
    fork(V(),V(.05,1,.03),2.3,.33,3);
  }else if(kind==='lantern_plant'){
    const h=4.3+variant*.25;branch(wood,V(),V(.1,h,0),.16,[.12,.23,.23]);
    for(let i=0;i<7;i++){const a=i*2.399,start=V(0,1.4+i*.4,0),tip=V(Math.cos(a)*1.5,start.y+.7,Math.sin(a)*1.5),end=tip.clone().add(V(0,-.8,0));tube(wood,[start,tip,end],[.065,.04,.015],[.1,.25,.22],6);pod(end.clone().add(V(0,-.4,0)),.56,[.8,.27,.035]);blade(leaves,start,V(Math.cos(a),.3,Math.sin(a)),1.3,.45,[.07,.27,.25],{segments:5,curve:.25});}
  }else if(kind==='spiral_fern'){
    for(let i=0;i<7;i++){
      const a=i*2.399,height=2.5+rng()*1.5,pts=[];
      for(let j=0;j<=20;j++){const t=j/20,turn=t*Math.PI*2.05,r=.95*(1-t*.7);pts.push(V(Math.cos(a)*r*Math.sin(turn),height*t,Math.sin(a)*r*Math.sin(turn)));}
      tube(wood,pts,pts.map((_,j)=>.09*(1-j/24)),[.13,.22,.31],5);
      for(let j=2;j<19;j++)for(const sign of [-1,1])blade(leaves,pts[j],V(Math.cos(a+sign*1.15),.2,Math.sin(a+sign*1.15)),.6*(1-j/25),.19,[.13,.35,.42],{segments:3,curve:.16});
    }
  }else if(kind==='crystal_lotus'){
    for(let tier=0;tier<3;tier++)for(let i=0;i<9;i++){
      const a=i*Math.PI*2/9+tier*.35,start=V(0,.12+tier*.12,0),d=V(Math.cos(a)*(1-tier*.23),.22+tier*.45,Math.sin(a)*(1-tier*.23));
      blade(leaves,start,d,2.6-tier*.5,.9-tier*.16,[.18+tier*.09,.14+tier*.06,.5],{segments:4,curve:.13,veins:false});
    }
    pod(V(0,1.1,0),.7,[.12,.55,.61]);
  }else if(kind==='star_bloom'){
    const top=V(.12,3.1,0);tube(wood,[V(),V(-.2,1.6,.1),top],[.21,.14,.08],[.17,.15,.26],8);
    for(let i=0;i<11;i++){const a=i*Math.PI*2/11;blade(leaves,top,V(Math.cos(a),.3,Math.sin(a)),2.2,.58,[.42,.11,.4],{segments:7,curve:.3,veins:false});const tip=top.clone().add(V(Math.cos(a)*1.8,.35,Math.sin(a)*1.8));pod(tip,.18,[.12,.6,.55]);}
    pod(top.clone().add(V(0,.5,0)),.62,[.08,.48,.56]);
    for(let i=0;i<4;i++){const a=i*2.399;blade(leaves,V(0,.5+i*.35,0),V(Math.cos(a),.2,Math.sin(a)),1.4,.36,[.13,.18,.32],{segments:5});}
  }else if(['tree','maple','sycamore','jungle','bare','baobab','shrub'].includes(kind))deciduous(kind);
  else throw Error('Unknown plant: '+kind);
  return [{geometry:wood.finish(true),material:'wood'},{geometry:leaves.finish(true),material:'leaves'}].filter(p=>p.geometry.attributes.position.count);
}
