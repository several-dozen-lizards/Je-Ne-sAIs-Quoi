import * as THREE from './vendor/three.module.js';
import {openingOutline} from './opening-shapes.mjs';

export const DOOR_STYLES={
  flat:'Flat slab',
  panelled:'Raised panels',
  medieval:'Medieval planks & iron',
  glazed:'Glazed door with windows',
};

function extrude(shape,depth=.07){
  const geometry=new THREE.ExtrudeGeometry(shape,{depth,bevelEnabled:false,curveSegments:24});
  geometry.translate(0,0,-depth/2);return geometry;
}
function box(width,height,depth,x,y,z=0){
  const geometry=new THREE.BoxGeometry(width,height,depth);geometry.translate(x,y,z);return geometry;
}
function cylinder(radius,depth,x,y,z=0,segments=12){
  const geometry=new THREE.CylinderGeometry(radius,radius,depth,segments);geometry.rotateX(Math.PI/2);geometry.translate(x,y,z);return geometry;
}
function ring(radius,tube,x,y,z=0){
  const geometry=new THREE.TorusGeometry(radius,tube,8,20);geometry.translate(x,y,z);return geometry;
}

/** Door geometry is authored in hinge-local coordinates: x=0 is the hinge,
 * y=0 is the threshold, and positive x runs toward the latch. */
export function doorLeafParts({shape='rectangle',style='flat',width,height}){
  const selected=Object.hasOwn(DOOR_STYLES,style)?style:'flat',outline=openingOutline(shape,width-.04,height-.03);
  for(const point of outline)point.x+=width/2;
  const slab=new THREE.Shape(outline);slab.closePath();
  const parts=[];
  if(selected==='glazed'&&width>=.7&&height>=1.5){
    const gap=.055,x0=width*.19,x1=width*.47-gap/2,x2=width*.53+gap/2,x3=width*.81,y0=height*.5,y1=height*.79;
    for(const [a,b] of [[x0,x1],[x2,x3]]){const hole=new THREE.Path();hole.moveTo(a,y0);hole.lineTo(b,y0);hole.lineTo(b,y1);hole.lineTo(a,y1);hole.closePath();slab.holes.push(hole);const pane=new THREE.Shape();pane.moveTo(a,y0);pane.lineTo(b,y0);pane.lineTo(b,y1);pane.lineTo(a,y1);pane.closePath();const geometry=new THREE.ShapeGeometry(pane);geometry.translate(0,0,.042);parts.push({geometry,material:'doorGlass',solid:true,feature:'glass'});}
  }
  parts.unshift({geometry:extrude(slab,selected==='medieval'?.09:.07),material:'door',solid:true,feature:'leaf'});

  const raised=(w,h,x,y,depth=.035)=>parts.push({geometry:box(w,h,depth,x,y,.052),material:'door',solid:false,feature:'panel'});
  const iron=(geometry,feature='iron')=>parts.push({geometry,material:'iron',solid:false,feature});
  if(selected==='panelled'){
    const margin=width*.12,gap=width*.07,panelWidth=(width-margin*2-gap)/2;
    for(const [y,h] of [[height*.25,height*.31],[height*.68,height*.39]])for(const x of [margin+panelWidth/2,width-margin-panelWidth/2])raised(panelWidth,h,x,y);
    raised(width*.065,height*.83,width/2,height*.47,.025);raised(width-margin*2,height*.055,width/2,height*.465,.025);
  }else if(selected==='medieval'){
    const planks=Math.max(3,Math.min(7,Math.round(width/.22))),plankWidth=width/planks;
    for(let i=1;i<planks;i++)iron(box(.012,height*.91,.012,i*plankWidth,height*.455,.052),'plank-seam');
    for(const y of [height*.22,height*.72]){iron(box(width*.9,.065,.035,width*.47,y,.074),'strap');iron(box(width*.34,.055,.035,width*.22,y+(y<height/2?.1:-.1),.074),'brace');}
    for(let i=0;i<planks;i++)for(const y of [height*.22,height*.72])iron(cylinder(.018,.018,(i+.5)*plankWidth,y,.098,8),'stud');
    iron(ring(Math.min(.085,width*.08),.012,width*.78,height*.48,.105),'ring-pull');
  }else if(selected==='glazed'){
    raised(width*.07,height*.37,width*.5,height*.645,.025);raised(width*.69,height*.045,width*.5,height*.49,.025);raised(width*.69,height*.045,width*.5,height*.8,.025);
  }
  if(selected!=='medieval'){
    iron(cylinder(Math.min(.035,width*.035),.035,width*.82,height*.47,.105,12),'handle');
    iron(cylinder(Math.min(.055,width*.05),.018,width*.82,height*.47,.078,16),'backplate');
  }
  return parts;
}
