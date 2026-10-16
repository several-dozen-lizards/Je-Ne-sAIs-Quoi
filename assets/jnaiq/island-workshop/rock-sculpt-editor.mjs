import * as THREE from './vendor/three.module.js';
import {sculptStroke,sculptGeometry,ROCK_LIMIT,ROCK_TYPES} from './rock-sculpt.mjs?types=1';
import {weatherStone} from './stone-surface.mjs?types=1';

export function installRockSculpt({scene,camera,canvas,land,material,world,commit,chooseTool,status,invalidate}){
  const panel=document.createElement('section');panel.innerHTML=`<h2>Sculpt rock</h2><p>Hold the left mouse button to add or remove sculpted rock.</p><div class="row"><button id="rockAdd">Add rock</button><button id="rockCarve">Carve rock</button></div><label>Rock brush radius (m)<input id="rockRadius" type="range" min="1.5" max="8" step=".5" value="3"></label><output id="rockRadiusValue">3 m</output><label>Brush placement<select id="rockPlacement"><option value="surface">On terrain / sculpted rock</option><option value="layer">At a chosen height</option></select></label><label>Height above sea level (m)<input id="rockHeight" type="number" min="0" max="64" step=".5" value="8"></label><p id="rockBudget"></p><p>Middle-drag or Alt + left-drag to rotate; right-drag to pan; scroll to zoom. Escape finishes the stroke and exits. Undo restores a whole stroke. Carving affects painted rock only. Place buildings on the landscape.</p>`;
  document.getElementById('build-home').before(panel);const $=id=>panel.querySelector('#'+id);
  const typeLabel=document.createElement('label');typeLabel.textContent='Rock type';
  const typeSelect=document.createElement('select');typeSelect.id='rockType';typeSelect.setAttribute('aria-label','Rock type');
  ROCK_TYPES.forEach((name,index)=>{const option=document.createElement('option');option.value=String(index);option.textContent=name;typeSelect.append(option);});
  typeLabel.append(typeSelect);$('rockAdd').parentElement.before(typeLabel);
  const stone=material.clone();stone.color.setHex(0xffffff);stone.vertexColors=true;weatherStone(stone,{neutralColor:true});
  const mesh=new THREE.Mesh(new THREE.BufferGeometry(),stone);mesh.castShadow=true;mesh.receiveShadow=true;scene.add(mesh);
  const cursor=new THREE.Mesh(new THREE.SphereGeometry(1,16,10),new THREE.MeshBasicMaterial({color:0xa9e8ba,wireframe:true,transparent:true,opacity:.45,depthWrite:false}));cursor.visible=false;scene.add(cursor);
  const ray=new THREE.Raycaster(),pointer=new THREE.Vector2();let active=false,carve=false,drawing=false,points=[],before=null,last=null,framePending=false,strokeSurface=null;
  function render(){framePending=false;mesh.geometry.dispose();mesh.geometry=sculptGeometry(points);$('rockBudget').textContent=`${points.length.toLocaleString()} / ${ROCK_LIMIT.toLocaleString()} rock detail points`;invalidate();}
  function refresh(){points=world().rockSculpt||[];render();}
  function finish(){if(!drawing)return;drawing=false;last=null;strokeSurface?.geometry.dispose();strokeSurface=null;if(before!==points){const next=structuredClone(world());next.rockSculpt=points;commit(next,carve?'Rock carved · Undo restores the stroke':'Rock painted · Undo restores the stroke');}before=null;}
  function cancel(){finish();active=false;cursor.visible=false;invalidate();}
  function begin(remove){chooseTool('rock','Drag to sculpt rock. Alt-drag to orbit; scroll to zoom. Escape exits.');active=true;carve=remove;cursor.material.color.setHex(remove?0xffa08c:0xa9e8ba);status(remove?'Carve painted rock to open a tunnel or hollow':'Paint rock on the surface, or choose a height to bridge a roof');}
  $('rockAdd').onclick=()=>begin(false);$('rockCarve').onclick=()=>begin(true);$('rockRadius').oninput=()=>{$('rockRadiusValue').textContent=$('rockRadius').value+' m';};
  function target(e){const b=canvas.getBoundingClientRect();pointer.set((e.clientX-b.left)/b.width*2-1,-(e.clientY-b.top)/b.height*2+1);ray.setFromCamera(pointer,camera);
    if($('rockPlacement').value==='layer')return ray.ray.intersectPlane(new THREE.Plane(new THREE.Vector3(0,1,0),-Number($('rockHeight').value)),new THREE.Vector3());
    const surface=strokeSurface||mesh,hits=ray.intersectObjects(carve?[surface]:[surface,land],false),hit=hits[0];if(!hit)return null;
    return hit.point.clone().addScaledVector(hit.face.normal,Number($('rockRadius').value)*(carve?-.3:.35));
  }
  function paint(p){const radius=Number($('rockRadius').value);if(last&&last.distanceTo(p)<radius*.25)return;try{points=sculptStroke(points,p,radius,carve,world().size,Number(typeSelect.value));last=p.clone();if(!framePending){framePending=true;requestAnimationFrame(render);}}catch(e){status(e.message,true);}}
  canvas.addEventListener('pointerdown',e=>{if(!active||e.button!==0||e.altKey)return;e.stopImmediatePropagation();e.preventDefault();const p=target(e);if(!p)return;strokeSurface=new THREE.Mesh(mesh.geometry.clone(),stone);strokeSurface.updateMatrixWorld();drawing=true;before=points;last=null;canvas.setPointerCapture(e.pointerId);paint(p);},{capture:true});
  canvas.addEventListener('pointermove',e=>{if(!active||e.altKey||(e.buttons&&!drawing))return;const p=target(e);cursor.visible=!!p;if(p){cursor.position.copy(p);cursor.scale.setScalar(Number($('rockRadius').value));if(drawing)paint(p);}invalidate();e.stopImmediatePropagation();},{capture:true});
  canvas.addEventListener('pointerleave',()=>{cursor.visible=false;invalidate();});
  for(const event of ['pointerup','pointercancel','lostpointercapture'])canvas.addEventListener(event,e=>{if(!drawing)return;e.stopImmediatePropagation();finish();},{capture:true});
  document.addEventListener('keydown',e=>{if(active&&(e.key==='Escape'||((e.ctrlKey||e.metaKey)&&['z','y'].includes(e.key.toLowerCase()))))finish();},{capture:true});
  window.addEventListener('blur',finish);refresh();return {refresh,cancel,surfaceMeshes:()=>mesh.geometry.attributes.position?.count?[mesh]:[]};
}
