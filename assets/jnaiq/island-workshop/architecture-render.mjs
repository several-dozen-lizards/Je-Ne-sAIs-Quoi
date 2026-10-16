import * as THREE from './vendor/three.module.js';
import {architectureFor} from './architecture.mjs';

// Ornament remains attached to its floor; every roof piece belongs to the roof cutaway.
export function architectureRenderer(b,{add,box,H}){
  const a=architectureFor(b),w=b.width,d=b.depth,top=b.floors*H;
  function beam(p,q,r=.09,level=0,roof=false,material='trim'){
    const start=new THREE.Vector3(...p),end=new THREE.Vector3(...q),v=end.clone().sub(start);
    const m=add(new THREE.CylinderGeometry(r,r,v.length(),6),material,level,roof);
    m.position.copy(start.add(end).multiplyScalar(.5));m.quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0),v.normalize());return m;
  }
  function curve(points,r=.065,level=0,roof=false){
    return add(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(points.map(p=>new THREE.Vector3(...p))),24,r,5,false),'trim',level,roof);
  }
  function opening(cx,cz,angle,width,bottom,upper,y,level){
    if(b.frames===false||a.detail==='none')return;
    const point=(u,v,out=.23)=>[cx+Math.cos(angle)*u+Math.sin(angle)*out,y+v,cz-Math.sin(angle)*u+Math.cos(angle)*out];
    const line=(u,v,s,t,r=.06)=>beam(point(u,v),point(s,t),r,level);
    const mid=(bottom+upper)/2;
    if(['arches','mission'].includes(a.detail))curve(Array.from({length:13},(_,i)=>{const t=i/12*Math.PI;return point(Math.cos(t)*width/2,upper+Math.sin(t)*.48);}),.105,level);
    if(['gothic','dwarven'].includes(a.detail)){
      const apex=upper+(a.detail==='gothic'?.65:.35);line(-width/2,upper,0,apex,.13);line(0,apex,width/2,upper,.13);
      if(bottom>0)line(0,bottom,0,upper,.065);
    }
    if(a.detail==='lattice'&&bottom>0){for(const t of [-.25,0,.25])line(width*t,bottom,width*t,upper,.035);for(const t of [.33,.66])line(-width/2,bottom+(upper-bottom)*t,width/2,bottom+(upper-bottom)*t,.035);}
    if(['vines','branches'].includes(a.detail))for(const sign of [-1,1])curve([point(sign*width*.55,bottom),point(sign*width*.65,mid),point(sign*width*.5,upper),point(sign*width*.18,upper+.45),point(0,upper+.24)],.075,level);
    if(['deco','spire'].includes(a.detail))for(let i=-2;i<=2;i++)line(i*.12,upper+.08,i*.24,upper+.45-Math.abs(i)*.09,.055);
    if(a.detail==='rings'&&bottom>0)curve(Array.from({length:25},(_,i)=>{const t=i/24*Math.PI*2;return point(Math.cos(t)*width*.62,mid+Math.sin(t)*(upper-bottom)*.65);}),.07,level);
  }
  function facade(){
    if(a.detail==='none')return;
    const sides=b.shape==='round'?24:4;
    for(let level=0;level<b.floors;level++){
      const y=level*H;
      for(let i=0;i<sides;i++){
        if(b.wallEdits?.some(p=>p.floor===level&&(b.shape==='round'||p.segment===i)))continue;
        let ax,az,bx,bz;
        if(b.shape==='round'){const t=i/sides*Math.PI*2,u=(i+1)/sides*Math.PI*2;ax=Math.cos(t)*w/2;az=Math.sin(t)*d/2;bx=Math.cos(u)*w/2;bz=Math.sin(u)*d/2;}
        else{const corners=[[-w/2,d/2],[w/2,d/2],[w/2,-d/2],[-w/2,-d/2]];[ax,az]=corners[i];[bx,bz]=corners[(i+1)%4];}
        // Horizontal courses above openings never cover the entrance.
        if(['timber','lattice','cornice','modern','deco','shack','dwarven'].includes(a.detail))beam([ax*1.018,y+H-.13,az*1.018],[bx*1.018,y+H-.13,bz*1.018],['cornice','dwarven'].includes(a.detail)?.19:.095,level);
        if(b.shape==='round')continue; // A circular wall has different bay positions.
        const length=Math.hypot(bx-ax,bz-az),nx=(bz-az)/-length,nz=(bx-ax)/length;
        const bays=Math.max(3,Math.round(length/4.5)|1);
        for(let j=0;j<=bays;j++){
          const x=ax+(bx-ax)*j/bays,z=az+(bz-az)*j/bays;
          if(['timber','lattice','shack','fins','branches','gothic','deco','dwarven'].includes(a.detail)){
            const heavy=['gothic','dwarven','fins'].includes(a.detail),r=heavy?.22:.095;
            beam([x+nx*(heavy?.42:.12),y,z+nz*(heavy?.42:.12)],[x+nx*.15,y+H,z+nz*.15],r,level,false,heavy?'wall':'trim');
            if(['timber','shack','branches','dwarven'].includes(a.detail))for(const sign of [-1,1]){
              const reach=Math.min(1.1,length/bays*.3)*sign;
              if((j===0&&sign<0)||(j===bays&&sign>0))continue;
              beam([x+nx*.22,y+H-.85,z+nz*.22],[x+(bx-ax)/length*reach+nx*.22,y+H-.15,z+(bz-az)/length*reach+nz*.22],r*.7,level);
            }
          }
          if(a.detail==='vigas'&&j<bays)beam([x+nx*.5,y+H-.25,z+nz*.5],[x-nx*.22,y+H-.25,z-nz*.22],.14,level);
        }
        if(a.detail==='shack')for(let j=0;j<bays;j++){
          // Short, uneven battens only occupy the wall above window heads.
          const t=(j+.34)/bays;beam([ax+(bx-ax)*t,y+2.45,az+(bz-az)*t],[ax+(bx-ax)*(t+.015),y+3.15,az+(bz-az)*(t+.015)],.085,level);
        }
      }
    }
  }
  function roof(){
    if(b.roof==='none')return;
    const form=b.roof==='flat'?'flat':a.roofForm,round=b.shape==='round',rx=w/2+a.eaves,rz=d/2+a.eaves,height=Math.min(w,d)*a.pitch;
    const roofBox=(width,h,depth,y)=>{const m=add(new THREE.BoxGeometry(width,h,depth),'roof',b.floors,true);m.position.y=y;return m;};
    function surface(points,indices,material='roof'){
      const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(points.flat(),3));g.setIndex(indices);g.computeVertexNormals();g.setAttribute('uv',new THREE.Float32BufferAttribute(points.flatMap(p=>[p[0],p[2]]),2));return add(g,material,b.floors,true);
    }
    if(['flat','terrace','stepped'].includes(form)){
      if(round){const m=add(new THREE.CylinderGeometry(1,1,.25,48),'roof',b.floors,true);m.scale.set(rx,1,rz);m.position.y=top+.12;}
      else roofBox(rx*2,.25,rz*2,top+.12);
      if(form==='terrace'){
        if(round){curve(Array.from({length:49},(_,i)=>[Math.cos(i/48*Math.PI*2)*w/2,top+.45,Math.sin(i/48*Math.PI*2)*d/2]),.2,b.floors,true);}
        else for(const [p,q] of [[[-w/2,top+.45,-d/2],[w/2,top+.45,-d/2]],[[w/2,top+.45,-d/2],[w/2,top+.45,d/2]],[[w/2,top+.45,d/2],[-w/2,top+.45,d/2]],[[-w/2,top+.45,d/2],[-w/2,top+.45,-d/2]]])beam(p,q,.25,b.floors,true,'wall');
      }
      if(form==='stepped')for(let i=0;i<3;i++){
        const scale=.72-i*.17,h=height/3;
        if(round){const m=add(new THREE.CylinderGeometry(1,1,h,32),'roof',b.floors,true);m.scale.set(rx*scale,1,rz*scale);m.position.y=top+.25+h*(i+.5);}
        else roofBox(w*scale,h,d*scale,top+.25+h*(i+.5));
      }
    }else if(!round&&['gable','shed','wave'].includes(form)){
      if(form==='gable'){
        surface([[-rx,top,-rz],[0,top+height,-rz],[rx,top,-rz],[-rx,top,rz],[0,top+height,rz],[rx,top,rz]],[0,3,4,0,4,1,1,4,5,1,5,2]);
        surface([[-w/2,top,-d/2],[0,top+height,-d/2],[w/2,top,-d/2],[-w/2,top,d/2],[0,top+height,d/2],[w/2,top,d/2]],[0,1,2,3,5,4],'wall');
        for(const z of [-rz,rz])for(const sign of [-1,1])beam([sign*rx,top,z],[0,top+height,z],.12,b.floors,true);
      }else{
        const points=[],indices=[],steps=form==='wave'?24:1;
        for(let j=0;j<=steps;j++){const t=j/steps,x=-rx+t*2*rx,y=top+height*(form==='wave'?.2+.5*t+.28*Math.sin(t*Math.PI*2):t);points.push([x,y,-rz],[x,y,rz]);if(j<steps){const k=j*2;indices.push(k,k+1,k+3,k,k+3,k+2);}}
        surface(points,indices);
        for(const z of [-d/2,d/2]){const p=[],idx=[];for(let j=0;j<=steps;j++){const t=j/steps,x=-w/2+t*w,y=top+height*(form==='wave'?.2+.5*t+.28*Math.sin(t*Math.PI*2):(x+rx)/(2*rx));p.push([x,top,z],[x,y,z]);if(j<steps){const k=j*2;idx.push(k,k+1,k+3,k,k+3,k+2);}}surface(p,idx,'wall');}
        for(const sign of [-1,1]){const x=sign*w/2,t=(x+rx)/(2*rx),h=height*(form==='wave'?.2+.5*t+.28*Math.sin(t*Math.PI*2):t);surface([[x,top,-d/2],[x,top+h,-d/2],[x,top+h,d/2],[x,top,d/2]],[0,1,2,0,2,3],'wall');}
      }
    }else if(form==='dome'||form==='flared'||form==='wave'){
      // Superellipse rings cover rectangular corners; ellipses follow round footprints.
      const points=[],indices=[],rings=16,segments=48;
      const outline=(theta,t)=>{const c=Math.cos(theta),s=Math.sin(theta),k=round?1:(1-t)/Math.max(Math.abs(c),Math.abs(s))+t;return [c*k,s*k];};
      for(let j=0;j<=rings;j++)for(let i=0;i<=segments;i++){
        const t=j/rings,theta=i/segments*Math.PI*2;
        const radius=form==='dome'?Math.cos(t*Math.PI/2):Math.pow(1-t,1.65);
        const y=top+height*(form==='dome'?Math.sin(t*Math.PI/2):t);
        const [c,s]=outline(theta,t);points.push([c*rx*radius,y,s*rz*radius]);
        if(j<rings&&i<segments){const k=j*(segments+1)+i;indices.push(k,k+segments+1,k+1,k+1,k+segments+1,k+segments+2);}
      }
      surface(points,indices);
      if(['fins','branches','vines'].includes(a.detail))for(let i=0;i<8;i++){
        const theta=i/8*Math.PI*2;
        curve(Array.from({length:13},(_,j)=>{const t=j/12,[c,s]=outline(theta,t);return [c*(rx+.04)*Math.cos(t*Math.PI/2),top+height*Math.sin(t*Math.PI/2)+.045,s*(rz+.04)*Math.cos(t*Math.PI/2)];}),.09,b.floors,true);
      }
    }else{
      const g=new THREE.ConeGeometry(1,height,round?48:4);if(!round)g.rotateY(Math.PI/4);
      const m=add(g,'roof',b.floors,true);m.scale.set(rx*(round?1:Math.SQRT2),1,rz*(round?1:Math.SQRT2));m.position.y=top+height/2;
    }
    if(b.roof==='auto'){
      if(a.detail==='spire'){const m=add(new THREE.ConeGeometry(.42,2.4,8),'trim',b.floors,true);m.position.y=top+height+1.05;}
      if(a.detail==='timber'){const m=add(new THREE.BoxGeometry(.85,2.1,.9),'wall',b.floors,true);m.position.set(w*.28,top+height*.58,d*.18);}
      if(a.detail==='rings'){const m=add(new THREE.TorusGeometry(.8,.13,6,32),'trim',b.floors,true);m.position.set(w*.23,top+height+1,0);m.rotation.z=.4;}
      if(a.detail==='mission'&&!round)curve([[-w*.21,top,d/2+.2],[-w*.17,top+.5,d/2+.2],[-w*.09,top+.6,d/2+.2],[0,top+height+.5,d/2+.2],[w*.09,top+.6,d/2+.2],[w*.17,top+.5,d/2+.2],[w*.21,top,d/2+.2]],.22,b.floors,true);
    }
  }
  return {opening,facade,roof};
}
