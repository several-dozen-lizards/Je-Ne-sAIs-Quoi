import * as THREE from './vendor/three.module.js';

const TAU=Math.PI*2;
const clamp=(value,low,high)=>Math.max(low,Math.min(high,value));

export const GLASS_CURTAIN_STYLES={
  rainbow:{name:'Rainbow glass bead curtain',colors:[0xef5278,0xffa23d,0xf7dc62,0x54d2a1,0x4db9ef,0x8e78e8],panels:.08},
  tide:{name:'Sea-glass bead curtain',colors:[0x8ce0d1,0x55b9c5,0x8aaed5,0xb4e2d0,0x78a898],panels:.06},
  ember:{name:'Amber and plum bead curtain',colors:[0xffb34f,0xd86d49,0x9a557c,0xe7c16a,0x763e68],panels:.09},
  chimes:{name:'Glass panel chime curtain',colors:[0x68cddd,0xd8a7ed,0xffc86e,0x79d89b,0xf47e91],panels:.24},
};

export const glassCurtainKind=style=>`glass_bead_curtain_${GLASS_CURTAIN_STYLES[style]?style:'rainbow'}`;
export const glassCurtainStyle=kind=>String(kind||'').replace(/^glass_bead_curtain_/,'');
export const isGlassCurtainKind=kind=>kind?.startsWith('glass_bead_curtain_')&&!!GLASS_CURTAIN_STYLES[glassCurtainStyle(kind)];

// Repair the one preview-build record that put a renderer flag in the
// resident-facing, numeric affordance map. Preserve every authored value.
export function normalizeGlassCurtainRecord(record){
  if(!record||!isGlassCurtainKind(record.kind)||record.affordances?.walk_through!==true)return record;
  record.affordances={...record.affordances};delete record.affordances.walk_through;return record;
}

function hash(index,seed){
  const value=Math.sin((index+1)*12.9898+seed*78.233)*43758.5453;
  return value-Math.floor(value);
}

function glassMaterial(){
  return new THREE.ShaderMaterial({
    transparent:true,depthWrite:false,side:THREE.DoubleSide,toneMapped:false,
    vertexShader:`
      attribute vec3 curtainColor;
      varying vec3 glassColor;
      varying vec3 glassNormal;
      varying vec3 glassWorld;
      void main(){
        glassColor=curtainColor;
        vec4 local=vec4(position,1.);
        vec3 localNormal=normal;
        #ifdef USE_INSTANCING
          local=instanceMatrix*local;
          localNormal=mat3(instanceMatrix)*localNormal;
        #endif
        vec4 world=modelMatrix*local;
        glassWorld=world.xyz;glassNormal=normalize(mat3(modelMatrix)*localNormal);
        gl_Position=projectionMatrix*viewMatrix*world;
      }`,
    fragmentShader:`
      varying vec3 glassColor;
      varying vec3 glassNormal;
      varying vec3 glassWorld;
      void main(){
        float edge=pow(1.-abs(dot(normalize(cameraPosition-glassWorld),normalize(glassNormal))),1.8);
        float gleam=pow(edge,3.2);
        vec3 colour=glassColor*(.62+edge*.58)+vec3(gleam*.92);
        gl_FragColor=vec4(colour,.16+edge*.58);
      }`,
  });
}

function pieceMatrix(piece,time,animate,target){
  const heightWeight=.25+.75*(piece.y/2.28);
  const sway=animate?Math.sin(time*.82+piece.phase)*piece.sway*heightWeight:0;
  const twist=animate?Math.sin(time*.47+piece.phase*1.73)*piece.twist:0;
  const position=new THREE.Vector3(piece.x+Math.sin(sway)*piece.y*.06,piece.y,piece.z);
  const rotation=new THREE.Quaternion().setFromEuler(new THREE.Euler(0,twist,sway));
  return target.compose(position,rotation,piece.scale);
}

export function createGlassBeadCurtain(style='rainbow'){
  const profile=GLASS_CURTAIN_STYLES[style]||GLASS_CURTAIN_STYLES.rainbow;
  const group=new THREE.Group();group.name=profile.name;
  const width=2.15,height=2.36,strands=17,top=height-.08;
  const rail=new THREE.Mesh(new THREE.CylinderGeometry(.012,.012,width,8),new THREE.MeshStandardMaterial({color:0x342b27,roughness:.48,metalness:.68}));
  rail.rotation.z=Math.PI/2;rail.position.y=height;rail.castShadow=true;group.add(rail);

  const stringPositions=[];
  for(let strand=0;strand<strands;strand++){
    const x=(strand/(strands-1)-.5)*width*.94;
    stringPositions.push(x,top,0,x,.12,0);
  }
  const strings=new THREE.LineSegments(new THREE.BufferGeometry().setAttribute('position',new THREE.Float32BufferAttribute(stringPositions,3)),new THREE.LineBasicMaterial({color:0x392d2b,transparent:true,opacity:.62}));
  strings.raycast=()=>{};group.add(strings);

  const pieces={tiny:[],prism:[],panel:[]};let serial=0;
  for(let strand=0;strand<strands;strand++){
    const x=(strand/(strands-1)-.5)*width*.94;
    const count=5+(strand%4),bottom=.12+hash(strand,13)*.46,step=(top-.10-bottom)/(count-1);
    for(let row=0;row<count;row++,serial++){
      const chance=hash(serial,style.length),panel=chance<profile.panels&&row>0;
      const prism=!panel&&(chance<profile.panels+.27||row===count-1),type=panel?'panel':prism?'prism':'tiny';
      const y=top-.11-row*step+(hash(serial,9)-.5)*.045;
      const base=type==='tiny'?.021+.016*hash(serial,2):type==='prism'?.043+.029*hash(serial,3):.055+.038*hash(serial,4);
      const scale=type==='panel'?new THREE.Vector3(base*(.72+hash(serial,5)*.5),base*(2.5+hash(serial,6)*1.7),.014+base*.08):type==='prism'?new THREE.Vector3(base,base*(1.35+hash(serial,7)*1.05),base*.78):new THREE.Vector3(base,base,base);
      pieces[type].push({x,y,z:0,scale,phase:strand*.41+row*.23,sway:.025+.035*hash(serial,8),twist:.08+.18*hash(serial,10),color:profile.colors[(strand+row*2)%profile.colors.length]});
    }
  }
  const forms={tiny:new THREE.SphereGeometry(1,8,6),prism:new THREE.CylinderGeometry(.64,.86,1,6),panel:new THREE.BoxGeometry(1,1,1)};
  const matrix=new THREE.Matrix4();
  for(const type of Object.keys(pieces)){
    const list=pieces[type],geometry=forms[type].clone(),colours=new Float32Array(list.length*3),mesh=new THREE.InstancedMesh(geometry,glassMaterial(),list.length);mesh.name=type+' glass';mesh.castShadow=false;mesh.receiveShadow=false;
    list.forEach((piece,index)=>{pieceMatrix(piece,0,false,matrix);mesh.setMatrixAt(index,matrix);new THREE.Color(piece.color).toArray(colours,index*3);});
    geometry.setAttribute('curtainColor',new THREE.InstancedBufferAttribute(colours,3));mesh.instanceMatrix.needsUpdate=true;group.add(mesh);pieces[type].mesh=mesh;
  }

  const all=[...pieces.tiny,...pieces.prism,...pieces.panel];
  const causticMaterial=new THREE.ShaderMaterial({uniforms:{stainOpacity:{value:0}},transparent:true,depthWrite:false,depthTest:true,side:THREE.DoubleSide,toneMapped:false,
    vertexShader:`
      attribute vec3 curtainColor;
      varying vec3 stainColor;
      varying vec2 stainUv;
      void main(){
        stainColor=curtainColor;stainUv=uv;
        vec4 local=vec4(position,1.);
        #ifdef USE_INSTANCING
          local=instanceMatrix*local;
        #endif
        gl_Position=projectionMatrix*modelViewMatrix*local;
      }`,
    fragmentShader:`uniform float stainOpacity;varying vec3 stainColor;varying vec2 stainUv;void main(){vec2 p=abs(stainUv-.5)*2.;float edge=1.-smoothstep(.72,1.,max(p.x,p.y));gl_FragColor=vec4(stainColor,stainOpacity*edge);}`});
  const causticGeometry=new THREE.PlaneGeometry(1,1),stainColours=new Float32Array(all.length*3);
  all.forEach((piece,index)=>new THREE.Color(piece.color).multiplyScalar(.82).toArray(stainColours,index*3));causticGeometry.setAttribute('curtainColor',new THREE.InstancedBufferAttribute(stainColours,3));
  const caustics=new THREE.InstancedMesh(causticGeometry,causticMaterial,all.length);caustics.name='Transmitted coloured light';caustics.renderOrder=2;caustics.raycast=()=>{};group.add(caustics);
  // The visible work is intentionally fine enough that it would otherwise be
  // frustrating to select. This colourless proxy gives the whole hanging area
  // a humane click/drag target without changing its silhouette or shadows.
  const selectionProxy=new THREE.Mesh(new THREE.BoxGeometry(width,height,.12),new THREE.MeshBasicMaterial({transparent:true,opacity:0,depthWrite:false,colorWrite:false,side:THREE.DoubleSide}));
  selectionProxy.name='Glass curtain selection surface';selectionProxy.position.y=height/2;selectionProxy.userData.selectionProxy=true;selectionProxy.castShadow=false;selectionProxy.receiveShadow=false;group.add(selectionProxy);
  group.userData.glassCurtain={pieces,all,caustics,selectionProxy,lastTime:null};
  updateGlassBeadCurtain(group,{direction:[-.5,.8,.3],day:1,elevation:.8},0,3.6,false);
  return group;
}

export function updateGlassBeadCurtain(group,light,seconds=0,sunStrength=1,animate=true){
  const state=group?.userData?.glassCurtain;if(!state||!light)return false;
  const time=animate?seconds:0;if(state.lastTime===time&&state.lastDirection?.every((v,i)=>v===light.direction?.[i])&&state.lastStrength===sunStrength)return false;
  state.lastTime=time;state.lastDirection=[...(light.direction||[0,1,0])];state.lastStrength=sunStrength;
  const matrix=new THREE.Matrix4();
  for(const type of ['tiny','prism','panel']){
    const list=state.pieces[type],mesh=list.mesh;
    list.forEach((piece,index)=>mesh.setMatrixAt(index,pieceMatrix(piece,time,animate,matrix)));
    mesh.instanceMatrix.needsUpdate=true;
  }
  const source=new THREE.Vector3().fromArray(light.direction||[0,1,0]).normalize(),ray=source.multiplyScalar(-1);
  const inverse=group.getWorldQuaternion(new THREE.Quaternion()).invert();ray.applyQuaternion(inverse).normalize();
  const elevation=Math.max(0,Number(light.elevation)||0),day=clamp(Number(light.day)||0,0,1),direct=clamp(Number(sunStrength)||0,0,3.6)/3.6;
  const visible=ray.y<-.04&&day>0&&direct>.002;
  state.caustics.visible=visible;state.caustics.material.uniforms.stainOpacity.value=visible?(.30+.30*elevation)*Math.sqrt(day*direct):0;
  const flatRotation=new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0,1,0),Math.atan2(ray.x,ray.z)).multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1,0,0),-Math.PI/2));
  state.all.forEach((piece,index)=>{
    const sway=animate?Math.sin(time*.82+piece.phase)*piece.sway:0;
    const travel=visible?clamp(-piece.y/ray.y,0,5.5):0,spread=1+travel*(.10+(1-elevation)*.08);
    const long=piece.scale.y*(piece.scale.y>.25?2.2:1.35)*spread,wide=Math.max(.035,piece.scale.x*(piece.scale.y>.25?1.1:1.65)*spread);
    matrix.compose(new THREE.Vector3(piece.x+Math.sin(sway)*piece.y*.06+ray.x*travel,.035,ray.z*travel),flatRotation,new THREE.Vector3(wide,long,1));
    state.caustics.setMatrixAt(index,matrix);
  });
  state.caustics.instanceMatrix.needsUpdate=true;return true;
}

export function glassCurtainRecord(id,style='rainbow',x=0,z=0){
  const profile=GLASS_CURTAIN_STYLES[style]||GLASS_CURTAIN_STYLES.rainbow;
  return {id,name:profile.name,kind:glassCurtainKind(style),position_m:[x,-z],size_m:2.15,rot_deg:0,y_off_m:0,support_surface:'island_ground',support_oid:null,
    description:'Mixed-scale glass beads, prisms and hanging panels that cast coloured transmitted light.',texture:'glass',mass_kg:8,affordances:{},capability:null,power:1,owner:null};
}
