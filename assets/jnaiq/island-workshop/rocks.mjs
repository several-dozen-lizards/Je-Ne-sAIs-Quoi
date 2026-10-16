import * as THREE from './vendor/three.module.js';
import {random} from './terrain.mjs?caves=retired';

// Displace shared positions consistently so facets meet without cracks.
export function makeRock(kind,variant=0){
  const rng=random(9031+variant*7919), pieces=[];
  function softenNormals(g,crease=.62){
    const p=g.attributes.position,n=g.attributes.normal,groups=new Map();
    for(let i=0;i<p.count;i++){
      const key=[p.getX(i),p.getY(i),p.getZ(i)].map(v=>Math.round(v*1e5)).join(',');
      if(!groups.has(key))groups.set(key,[]);groups.get(key).push(i);
    }
    for(const indices of groups.values()){
      const faces=indices.map(i=>new THREE.Vector3().fromBufferAttribute(n,i));
      for(let j=0;j<indices.length;j++){
        const blended=new THREE.Vector3();
        for(const face of faces)if(face.dot(faces[j])>crease)blended.add(face);
        blended.normalize();n.setXYZ(indices[j],blended.x,blended.y,blended.z);
      }
    }
  }
  function fractured({x=0,y=0,z=0,sx=1,sy=1,sz=1,sides=7,turn=0,leanX=0,leanZ=0,topX=0,topZ=0,fracture=.075,profile}){
    // Ten perimeter samples retain fractured planes without advertising the
    // primitive's hexagonal silhouette at ordinary viewing distances.
    sides=Math.max(10,sides+3);
    const rings=profile||[[0,.72],[.12,1],[.58,.94],[.84,.7],[1,.36]];
    // One radial signature runs through every stratum. That continuity makes
    // the silhouette read as a fractured mass instead of stacked noise.
    const radial=Array.from({length:sides},()=>.88+rng()*.22);
    const ringRadial=rings.map((_,ring)=>radial.map((base,index)=>base*(1+(rng()-.5)*fracture*(ring===0||ring===rings.length-1?1.35:1))));
    const phase=turn+rng()*.16, positions=[],uv=[];
    const point=(ring,index)=>{
      const [t,r,shiftX=0,shiftZ=0]=rings[ring],angle=phase+index*Math.PI*2/sides;
      const crown=ring===rings.length-1?Math.cos(angle-phase)*topX+Math.sin(angle-phase)*topZ:0;
      return [
        x+sx*(Math.cos(angle)*r*ringRadial[ring][index]+shiftX+leanX*t),
        y+sy*(t+crown),
        z+sz*(Math.sin(angle)*r*ringRadial[ring][index]+shiftZ+leanZ*t),
      ];
    };
    const push=(a,b,c,ta,tb,tc)=>{positions.push(...a,...b,...c);uv.push(...ta,...tb,...tc);};
    for(let ring=0;ring<rings.length-1;ring++)for(let i=0;i<sides;i++){
      const j=(i+1)%sides,a=point(ring,i),b=point(ring,j),c=point(ring+1,j),d=point(ring+1,i);
      const u0=i/sides,u1=(i+1)/sides,v0=rings[ring][0],v1=rings[ring+1][0];
      // Alternating diagonals keep the broad planes irregular without adding
      // the high-frequency dimples that made the old rocks look inflated.
      // Winding is counter-clockwise from outside the mass. The previous
      // order pointed these normals inward, so normal back-face culling made
      // the fractured rocks look partly transparent in the live world.
      if((i+ring)&1){push(a,d,b,[u0,v0],[u0,v1],[u1,v0]);push(b,d,c,[u1,v0],[u0,v1],[u1,v1]);}
      else{push(a,c,b,[u0,v0],[u1,v1],[u1,v0]);push(a,d,c,[u0,v0],[u0,v1],[u1,v1]);}
    }
    const bottom=[x+sx*(rings[0][2]??0),y,z+sz*(rings[0][3]??0)],topRing=rings.length-1;
    const top=[x+sx*((rings[topRing][2]??0)+leanX),y+sy,z+sz*((rings[topRing][3]??0)+leanZ)];
    for(let i=0;i<sides;i++){
      const j=(i+1)%sides;
      push(bottom,point(0,i),point(0,j),[.5,.5],[1,0],[0,0]);
      push(top,point(topRing,j),point(topRing,i),[.5,.5],[1,1],[0,1]);
    }
    const g=new THREE.BufferGeometry();
    g.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));
    g.setAttribute('uv',new THREE.Float32BufferAttribute(uv,2));g.computeVertexNormals();
    if(kind!=='slate_rock')softenNormals(g);
    pieces.push(g);
  }
  function lump(x,y,z,sx,sy,sz,round=false){
    const g=new THREE.IcosahedronGeometry(1,round?3:2),p=g.attributes.position;
    const phase=rng()*7;
    for(let i=0;i<p.count;i++){
      const a=p.getX(i),b=p.getY(i),c=p.getZ(i);
      const coarse=Math.sin(a*4+phase)*Math.cos(b*5+c*3+phase);
      const chips=Math.sin(a*13+c*9+phase)*Math.cos(b*11-a*7);
      const noise=1+(round?.035:.18)*coarse+(round?.008:.055)*chips;
      p.setXYZ(i,x+a*sx*noise,y+b*sy*noise,z+c*sz*noise);
    }
    g.computeVertexNormals();
    if(kind!=='slate_rock'){
      // Smooth tessellation while retaining sharp fractures. Positions and
      // faces stay unchanged, including the authored slate/basalt edges.
      softenNormals(g,round?-1:.5);
    }
    pieces.push(g);
  }
  if(kind==='basalt_rock'){
    for(let i=0;i<7;i++){const a=i*2.4,h=2+rng()*3;const g=new THREE.CylinderGeometry(.48,.56,h,6);g.translate(Math.cos(a)*(i?1:0),h/2,Math.sin(a)*(i?1:0));pieces.push(g.toNonIndexed());g.dispose();}
  }else if(kind==='slate_rock'){
    let rise=0;
    for(let i=0;i<5;i++){
      const h=.22+rng()*.14,w=2.15-i*.13+rng()*.32,d=1.22-i*.055+rng()*.26;
      fractured({x:(rng()-.5)*.48,y:rise,z:(rng()-.5)*.32,sx:w,sy:h,sz:d,sides:7,turn:(rng()-.5)*.3,
        topX:(rng()-.5)*.06,topZ:(rng()-.5)*.045,profile:[[0,.88],[.18,1],[.78,.96],[1,.82]]});
      rise+=h*.72;
    }
    // A couple of shed flakes break the wedding-cake outline at ground level.
    fractured({x:-1.55,y:.02,z:.38,sx:.92,sy:.16,sz:.62,sides:6,turn:-.35,topX:.025,profile:[[0,.75],[.18,1],[.8,.94],[1,.68]]});
    fractured({x:1.45,y:.02,z:-.24,sx:.7,sy:.12,sz:.5,sides:6,turn:.28,topZ:-.025,profile:[[0,.74],[.2,1],[.78,.9],[1,.64]]});
  }else if(kind==='rock_cluster'){
    const stones=[[-.9,0,.05,1.12,.92,.9],[.55,0,-.18,1.3,1.08,1.02],[1.65,0,.38,.82,.7,.72],[-1.7,0,.48,.7,.56,.66],[-.2,.46,.25,.76,.62,.68],[.85,.55,.3,.7,.58,.64]];
    for(const [x,y,z,sx,sy,sz] of stones)fractured({x:x+(rng()-.5)*.18,y,z:z+(rng()-.5)*.16,sx:sx*(.9+rng()*.2),sy:sy*(.9+rng()*.22),sz:sz*(.9+rng()*.2),sides:6,turn:rng()*Math.PI,leanX:(rng()-.5)*.14,leanZ:(rng()-.5)*.12,topX:(rng()-.5)*.055,profile:[[0,.68],[.13,1],[.55,.93],[.82,.7],[1,.32]]});
  }else if(kind==='standing_rock'){
    const forms=[
      {sx:1.08,sy:4.65,sz:.54,sides:7,leanX:.05,topX:.035,topZ:-.075,profile:[[0,.76,-.08,0],[.06,1,-.02,.02],[.28,.98,.02,0],[.67,.92,.08,-.03],[.88,.84,.1,-.05],[1,.58,.17,-.09]]},
      {sx:.82,sy:3.9,sz:.67,sides:6,leanX:-.12,topX:-.09,topZ:.035,profile:[[0,.72,.08,-.03],[.07,1,.02,0],[.4,.93,-.02,.035],[.73,.86,-.07,.02],[.91,.78,-.12,-.02],[1,.7,-.19,-.06]]},
      {sx:1.2,sy:5.15,sz:.46,sides:7,leanX:.09,topX:.08,topZ:-.025,profile:[[0,.8,-.06,.03],[.055,1,-.01,0],[.34,.95,.02,-.02],[.62,.98,.04,-.025],[.86,.88,.1,-.04],[1,.68,.2,-.075]]},
    ],form=forms[((variant%forms.length)+forms.length)%forms.length];
    fractured({...form,x:.05,fracture:.035,turn:.14+(rng()-.5)*.1,leanX:form.leanX+(rng()-.5)*.035,leanZ:(rng()-.5)*.055});
  }else if(kind==='river_rock')lump(0,.42,0,1.3+rng()*.52,.48+rng()*.22,.92+rng()*.38,true);
  else{
    const forms=[
      {sx:1.72,sy:1.55,sz:1.28,profile:[[0,.66,-.06,0],[.1,.93,-.03,.02],[.28,1,0,0],[.61,.94,.06,-.03],[.82,.72,.11,-.06],[1,.35,.17,-.08]]},
      {sx:1.35,sy:2.03,sz:1.18,profile:[[0,.7,.04,-.03],[.08,.95,.01,0],[.34,1,-.04,.03],[.68,.84,-.1,.05],[.9,.61,-.16,.02],[1,.31,-.22,-.02]]},
      {sx:1.98,sy:1.28,sz:1.42,profile:[[0,.64,-.08,.04],[.12,.9,-.04,0],[.24,1,0,-.03],[.56,.96,.07,-.05],[.79,.76,.15,-.08],[1,.4,.24,-.12]]},
    ],form=forms[((variant%forms.length)+forms.length)%forms.length];
    fractured({...form,sides:7,turn:rng()*Math.PI,leanX:(rng()-.5)*.08,leanZ:(rng()-.5)*.07,topX:(rng()-.5)*.07,topZ:(rng()-.5)*.06});
  }
  const g=new THREE.BufferGeometry();
  for(const name of ['position','normal','uv']){
    const size=name==='uv'?2:3,arrays=pieces.map(p=>p.attributes[name].array),out=new Float32Array(arrays.reduce((n,a)=>n+a.length,0));let offset=0;
    for(const a of arrays){out.set(a,offset);offset+=a.length;}g.setAttribute(name,new THREE.BufferAttribute(out,size));
  }
  g.computeBoundingBox();g.translate(0,-g.boundingBox.min.y-.08,0);g.computeBoundingBox();g.computeBoundingSphere();pieces.forEach(p=>p.dispose());return g;
}
