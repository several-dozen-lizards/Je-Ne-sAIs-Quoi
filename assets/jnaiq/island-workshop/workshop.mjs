import {installBuilderVR} from './builder-vr.mjs';
import * as THREE from 'three';
import {worldGuide} from './builder-guides.mjs';
import {installFurnitureEditor,validateFurniture} from './furniture.mjs?boundary=1';
import {furnitureWorldRange,removeFurnitureOutsideWorld} from './furniture-boundary.mjs';
let furnitureEditor=null,visitorFurniture=null;
import {OrbitControls} from './vendor/OrbitControls.js';
import {installFirstPerson} from './first-person.mjs';
import {promptNewIsland} from './new-island.mjs';
import {N,STYLES,generate,heightAt,slopeAt,sculpt,scatter,clamp} from './terrain.mjs?caves=retired';
import {islandMaterials} from './materials.mjs?surfaces=16';
import {PLANT_IDS,specimenVariant,GARDEN_IDS,SOLID_TREE_IDS} from './plants.mjs?sumac=2';
import {createFlora,installPlantLibrary} from './flora-render.mjs?surface=3';
import {createCrystalGlow} from './crystal-glow.mjs';
import {installBuildingEditor} from './building-editor.mjs?frame-seams=1';
import {validateStructures,prepareSite} from './structures.mjs?frame-seams=1';
import {objectHeight} from './geology.mjs?caves=retired';
import {removeRetiredCaves} from './retired-content.mjs?caves=retired';
import {createAtmosphere} from './atmosphere.mjs?realism=1';
import {compactToolbar} from './toolbar.mjs?sidebar=1';
import {createWorldLighting} from './world-lighting.mjs?terrain=4';
import {createSkyIllumination} from './sky-illumination.mjs';
import {buildingPickGesture} from './building-navigation.mjs';

import {installDaylight} from './daylight.mjs?lava=1';
import {weatherProfile} from './weather.mjs?spacefx=1';
import {LANDSCAPES} from './landscape-profiles.mjs';
import {installGenerationControls} from './generation-controls.mjs';
import {validateGeneration,legacyLandform} from './generation.mjs';
import {validateFeatures} from './landscape-features.mjs?caves=retired';
import {createLandscapeFeatures} from './feature-render.mjs?ice=1';
import {validateTextures} from './building-finishes.mjs';
import {replacementDestination} from './publication-target.mjs';
import {normalizedWater,validateCustomSky} from './sky-water-options.mjs';
import {installColumnEditor} from './column-editor.mjs?caves=retired';
import {validateColumns} from './columns.mjs';
import {addRoute,removeRoute,paintGround,applyGroundSurface,validatePaint,GROUND_SURFACES} from './landscape-edit.mjs?caves=retired';
import {installPondBrush} from './pond-brush-editor.mjs';
import {addPond} from './ponds.mjs?caves=retired';
import {settlePonds} from './pond-level.mjs';
import {installRockSculpt} from './rock-sculpt-editor.mjs?types=1';
import {validateSculpt} from './rock-sculpt.mjs?types=1';
import {createStepSurfaces,validateStepRoutes} from './step-routes.mjs';
import {installStepEditor} from './step-editor.mjs?camera=2';
import {installSidebar} from './sidebar.mjs?ribbon=1';
import {createGroundCover} from './ground-cover.mjs?polyhaven=2';
import {validateGarden} from './garden.mjs';
import {createGardenLayer} from './garden-render.mjs';
import {installGardenEditor} from './garden-editor.mjs';
import {createVineLayer,validateVines} from './vines.mjs';
import {installVineEditor} from './vine-editor.mjs';
const $=id=>document.getElementById(id), clone=v=>structuredClone(v);
const visitId=new URLSearchParams(location.search).get('visit');
// Keep the tool palette outside the canvas so it never covers editable land.
const workspace=document.createElement('div');workspace.id='workspace';
$('stage').before(workspace);
$('tools').setAttribute('role','group');$('tools').setAttribute('aria-label','Landscape tools');
workspace.append($('tools'),$('stage'));
let world=generate('meadow',4271,160),past=[],future=[],dirty=false,activeId=null,revision=null,tool='orbit',stroke=null,busy=false,dirtyFrame=true;
const status=(message,error=false)=>{$('status').textContent=message;$('status').classList.toggle('error',error);};
window.addEventListener('island-texture-ready',()=>dirtyFrame=true);
let renderer,rockEditor=null,stepEditor=null,sidebar=null,generationControls=null,gardenEditor=null,vineEditor=null;
try{renderer=new THREE.WebGLRenderer({canvas:$('viewport'),antialias:true});}catch(e){status('The 3D view could not start. Enable hardware acceleration and reload.',true);throw e;}
renderer.setPixelRatio(Math.min(devicePixelRatio,1.5));renderer.setClearColor(0x88adb2);renderer.outputColorSpace=THREE.SRGBColorSpace;
renderer.shadowMap.enabled=true;renderer.shadowMap.type=THREE.PCFSoftShadowMap;
renderer.shadowMap.autoUpdate=false;renderer.shadowMap.needsUpdate=true;
renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.05;
const naturalMaterials=islandMaterials(renderer,()=>dirtyFrame=true,message=>status(message,true));
const scene=new THREE.Scene();
const camera=new THREE.PerspectiveCamera(43,1,.03,12000),controls=new OrbitControls(camera,renderer.domElement);
let firstPerson=null;
// Placement handlers reserve only unmodified left-clicks; camera gestures stay available.
controls.mouseButtons.RIGHT=THREE.MOUSE.PAN;
controls.mouseButtons.MIDDLE=THREE.MOUSE.ROTATE;
controls.maxPolarAngle=Math.PI*.48;controls.minDistance=.35;controls.maxDistance=500;controls.enableDamping=false;
controls.addEventListener('change',()=>dirtyFrame=true);
const lighting=createWorldLighting({scene,renderer,camera,controls,naturalMaterials,invalidate:()=>dirtyFrame=true});
const sunlight=lighting.sunlight;
const atmosphere=createAtmosphere(scene,naturalMaterials.rock,sunlight.uniforms);
const skyIllumination=createSkyIllumination(renderer,scene,atmosphere,()=>dirtyFrame=true);
lighting.mountQuality(document.querySelector("footer"));
window.addEventListener("pagehide",()=>{skyIllumination.dispose();lighting.dispose();},{once:true});
const landscapeFeatures=createLandscapeFeatures(scene);
const vineLayer=createVineLayer(scene);
const grassCover=createGroundCover(scene,()=>dirtyFrame=true);
const stepSurfaces=createStepSurfaces(scene,naturalMaterials.terrain);
function updateLighting(light){
  grassCover.update(waterTime);
  return lighting.update(light,daylightControl.renderState,waterTime,world.size);
}
const geometry=new THREE.BufferGeometry(),positions=new Float32Array((N+1)**2*3),colors=new Float32Array(positions.length),indices=[];
for(let j=0;j<N;j++)for(let i=0;i<N;i++){const a=j*(N+1)+i,b=a+1,c=a+N+1,d=c+1;indices.push(a,c,b,b,c,d);}
geometry.setAttribute('position',new THREE.BufferAttribute(positions,3));geometry.setAttribute('color',new THREE.BufferAttribute(colors,3));geometry.setIndex(indices);
const land=new THREE.Mesh(geometry,naturalMaterials.terrain);scene.add(land);
land.receiveShadow=true;land.castShadow=true;
const scenery=new THREE.Group();scene.add(scenery);
const gardenLayer=createGardenLayer(scene,()=>{dirtyFrame=true;renderer.shadowMap.needsUpdate=true;});
const ringPoints=Array.from({length:65},(_,i)=>new THREE.Vector3(Math.cos(i/64*Math.PI*2),0,Math.sin(i/64*Math.PI*2)));
const ring=new THREE.Line(new THREE.BufferGeometry().setFromPoints(ringPoints),new THREE.LineBasicMaterial({color:0xffedb3,depthTest:false,transparent:true,opacity:.9}));ring.renderOrder=10;ring.visible=false;scene.add(ring);
const ray=new THREE.Raycaster(),pointer=new THREE.Vector2();
const flora=createFlora(naturalMaterials);
const crystalGlow=createCrystalGlow(scene,flora);
let floraDetail='far';
installPlantLibrary(flora,$('prop'),()=>chooseTool('place'));
// Add sky controls after the building panel has been installed.
const buildingEditor=installBuildingEditor({onSelected:()=>sidebar?.revealBuildingMaterials(),scene,world:()=>world,remember,rebuild,changed,status,chooseTool,frameBuilding:b=>{const span=Math.max(b.width,b.depth,b.floors*3.2);controls.target.set(b.x,b.y+b.floors*1.6,b.z);camera.position.copy(controls.target).add(new THREE.Vector3(span*1.2,span,span*1.5));controls.update();dirtyFrame=true;}});
const daylightControl=installDaylight(()=>dirtyFrame=true);
const columnEditor=installColumnEditor({scene,canvas:renderer.domElement,pick:hit,world:()=>world,remember,rebuild,changed,status,chooseTool,invalidate:()=>{dirtyFrame=true;renderer.shadowMap.needsUpdate=true;},frame:b=>{const span=Math.max(b.width,b.depth,b.floors*3.2);controls.target.set(b.x,b.y+b.floors*1.6,b.z);camera.position.copy(controls.target).add(new THREE.Vector3(span*1.2,span,span*1.5));controls.update();dirtyFrame=true;}});
rockEditor=installRockSculpt({scene,camera,canvas:renderer.domElement,land,material:naturalMaterials.rock,world:()=>world,chooseTool,status,invalidate:()=>{dirtyFrame=true;renderer.shadowMap.needsUpdate=true;},commit:(next,message)=>{remember();world=next;rebuild();changed(message);}});
stepEditor=installStepEditor({scene,canvas:renderer.domElement,controls,pick:hit,world:()=>world,getTool:()=>tool,chooseTool,status,invalidate:()=>dirtyFrame=true,commit:(next,message)=>{remember();world=next;rebuild();changed(message);}});
const sunlightView=document.createElement('button');sunlightView.textContent='Look toward the sun';sunlightView.className='wide';
document.getElementById('sunRays').parentElement.after(sunlightView);
sunlightView.onclick=()=>{const direction=new THREE.Vector3().fromArray(daylightControl.tick(0).direction);direction.y=0;if(direction.lengthSq()<.001)direction.set(-.8,0,-.6);direction.normalize();const h=world.size*.22;controls.target.set(0,h,0);camera.position.copy(direction.multiplyScalar(-world.size*.95));camera.position.y=h;controls.update();dirtyFrame=true;};
controls.addEventListener('change',()=>{const next=controls.getDistance()<world.size*.8?'near':'far';if(next!==floraDetail){floraDetail=next;updateScenery();}});
function updateScenery(){
  crystalGlow.rebuild(world);
  grassCover.rebuild(world);
  renderer.shadowMap.needsUpdate=true;
  while(scenery.children.length){const child=scenery.children[0];scenery.remove(child);child.dispose();}
  let visible=0;const matrix=new THREE.Object3D();
  for(const kind of PLANT_IDS)for(let variant=0;variant<3;variant++){
    const list=world.objects.filter(o=>o.kind===kind&&specimenVariant(o.id)===variant&&heightAt(world,o.x,o.z)>.1);
    visible+=list.length;if(!list.length)continue;
    for(const part of flora.parts(kind,variant,floraDetail)){
      const mesh=new THREE.InstancedMesh(part.geometry,part.material,list.length);
      mesh.userData.walkThrough=!part.solid;
      mesh.castShadow=true;mesh.receiveShadow=true;
      list.forEach((o,i)=>{matrix.position.set(o.x,objectHeight(world,o),o.z);matrix.rotation.set(0,o.rotation,0);matrix.scale.setScalar(o.scale);matrix.updateMatrix();mesh.setMatrixAt(i,matrix.matrix);});
      mesh.instanceMatrix.needsUpdate=true;mesh.computeBoundingSphere();scenery.add(mesh);
    }
  }
  $('stats').textContent=`${world.size} m across · ${visible} scenery objects`;
  dirtyFrame=true;
}
function updateGroundPaint(){
  if(tool==='paint')grassCover.rebuild(world);
  const paint=new Float32Array((N+1)**2*4);
  if(world.groundPaint)world.groundPaint.forEach((v,i)=>paint[i]=v/255);
  geometry.setAttribute('groundPaint',new THREE.BufferAttribute(paint,4));
  for(let group=0;group<2;group++){
    const extra=new Float32Array((N+1)**2*4);
    if(world.groundPaintExtra)for(let i=0;i<(N+1)**2;i++)for(let c=0;c<4;c++)extra[i*4+c]=world.groundPaintExtra[i*8+group*4+c]/255;
    geometry.setAttribute('groundExtra'+group,new THREE.BufferAttribute(extra,4));
  }
  dirtyFrame=true;
}
function rebuild(){
  settlePonds(world);
  gardenLayer.sync(world);gardenEditor?.refresh();
  vineLayer.rebuild(world);
  vineEditor?.refresh();
  furnitureEditor?.refresh();
  rockEditor?.refresh();
  updateGroundPaint();
  landscapeFeatures.rebuild(world);
  stepSurfaces.rebuild(world);
  naturalMaterials.setStyle(world.style);
  atmosphere.updateTerrain(world);
  const sand=new THREE.Color(world.style==='tropical'?0xdacf9c:0xc9bf94),grass=new THREE.Color(world.style==='tropical'?0x769950:world.style==='highland'?0x73816a:0x7e9561),stone=new THREE.Color(0x8f9188),c=new THREE.Color();
  for(let j=0;j<=N;j++)for(let i=0;i<=N;i++){
    const k=j*(N+1)+i,x=(i/N-.5)*world.size,z=(j/N-.5)*world.size,h=world.heights[k];
    positions[k*3]=x;positions[k*3+1]=h;positions[k*3+2]=z;
    c.copy(sand).lerp(grass,clamp((h-.6)/2.4,0,1)).lerp(stone,clamp((slopeAt(world,x,z)-.35)*1.35,0,.92));
    if(h>25)c.lerp(new THREE.Color(0xc1c5b5),clamp((h-25)/25,0,.7));
    colors[k*3]=c.r;colors[k*3+1]=c.g;colors[k*3+2]=c.b;
  }
geometry.attributes.position.needsUpdate=true;geometry.attributes.color.needsUpdate=true;geometry.computeVertexNormals();geometry.computeBoundingSphere();geometry.computeBoundingBox();updateScenery();buildingEditor.refresh();columnEditor.refresh();dirtyFrame=true;
}
function frame(top=false){firstPerson?.exit();controls.target.set(0,4,0);camera.position.set(top?0:world.size*.57,top?world.size*1.12:world.size*.59,top?.01:world.size*.73);controls.update();dirtyFrame=true;}
function historyButtons(){$('undo').disabled=!past.length;$('redo').disabled=!future.length;}
function changed(message='Unsaved changes') {dirty=true;status(message);historyButtons();dirtyFrame=true;renderer.shadowMap.needsUpdate=true;queueMicrotask(cacheDraft);}
function remember(){past.push(clone(world));if(past.length>32)past.shift();future=[];}
function syncInputs(){$('name').value=world.name;$('seed').value=world.seed;$('style').value=world.style;$('size').value=String(world.size);if($('frozenWater'))$('frozenWater').checked=!!world.frozenWater;generationControls?.restore(world);}
function restore(value){stepEditor?.cancel();cancelRoute();world=clone(value);if(world.atmosphere)daylightControl.restore(world.atmosphere);syncInputs();rebuild();changed();}
$('undo').onclick=()=>{if(!past.length)return;future.push(clone(world));restore(past.pop());};
$('redo').onclick=()=>{if(!future.length)return;past.push(clone(world));restore(future.pop());};
$('home').onclick=()=>frame();$('top').onclick=()=>frame(true);
const horizon=document.createElement('button');horizon.textContent='Horizon view';$('top').after(horizon);horizon.onclick=()=>{controls.target.set(0,7,0);camera.position.set(world.size*.75,world.size*.25,world.size*.95);controls.update();dirtyFrame=true;};
const motionLabel=document.createElement('label');motionLabel.style.cssText='display:flex;gap:7px;align-items:center;margin:0';const motion=document.createElement('input');motion.type='checkbox';motion.checked=!matchMedia('(prefers-reduced-motion: reduce)').matches;motionLabel.append(motion,'Animate atmosphere');document.querySelector('footer').append(motionLabel);motion.onchange=()=>dirtyFrame=true;
$('style').replaceChildren(...Object.entries(LANDSCAPES).map(([id,p])=>new Option(p.name,id)));
const featureControls=document.createElement('div');
featureControls.innerHTML='<label>Include in the next island</label><label><input type="checkbox" id="generateCliffs"> Cliff terraces</label><label><input type="checkbox" id="generateRiver" checked> River & cascades</label><label><input type="checkbox" id="generateRoad" checked> Winding dirt road</label><p>Generation replaces the landscape; Undo brings it back. Rivers carve downhill to the sea. Roads stop at riverbanks. Water animates with Animate atmosphere.</p>';
$('generate').parentElement.before(featureControls);
function generateIsland(newSeed=false){
  if(!sidebar?.creation.active||busy)return;
  cancelRoute();
  if(newSeed)$('seed').value=crypto.getRandomValues(new Uint32Array(1))[0];
  if(!$('seed').checkValidity()){status('Use a whole seed between 0 and 4294967295.',true);return;}
  remember();world=generate('meadow',Number($('seed').value),Number($('size').value),{generation:generationControls.recipe(),river:$('generateRiver').checked,road:$('generateRoad').checked});world.name=$('name').value.trim()||'Untitled island';rebuild();frame();changed('New island generated · Undo restores the previous landscape');
}
$('generate').onclick=()=>generateIsland();$('surprise').onclick=()=>generateIsland(true);
function commitName(){const name=$('name').value.trim()||'Untitled island';if(world.name!==name){remember();world.name=name;changed();}}
$('name').onchange=commitName;
const hints={orbit:'Drag to orbit. Middle-drag to rotate · Right-drag to pan. Scroll to zoom.',raise:'Paint to raise soft hills. Alt-drag to orbit.',lower:'Paint to lower the land or make a bay. Alt-drag to orbit.',cliff:'Paint to raise a plateau with a steep edge. Alt-drag to orbit.',flatten:'Paint to level ground to the height where your stroke begins.',smooth:'Paint to soften sharp edges and uneven ground.',place:'Click dry land to place the selected scenery. Choose size below.',erase:'Paint over scenery to remove it within the brush circle.'};
let pondBrush=null;
window.addEventListener('island-building-task',()=>chooseTool('orbit'));
function chooseTool(value,customHint){if(value!=='garden')gardenEditor?.hover(null);if(value!=='pond')pondBrush?.cancel();stepEditor?.select(value);sidebar?.revealTool(value);if(value!=='rock')rockEditor?.cancel();if(value!=='vine')vineEditor?.cancel();if(value!=='build')buildingEditor.cancel();tool=value;const hint=customHint||(value==='build'?'Mark opposite footprint corners on dry land. Escape cancels. Alt-drag to orbit.':hints[tool]);for(const b of document.querySelectorAll('[data-tool]'))b.setAttribute('aria-pressed',String(b.dataset.tool===tool));$('toolHint').textContent=hint;$('help').textContent=hint+(tool==='orbit'?' · Ctrl+Z to undo':' · Middle-drag to rotate · Right-drag to pan · '+(tool==='build'?'Alt-wheel to zoom':'Scroll to zoom')+' · Ctrl+Z to undo');ring.visible=false;dirtyFrame=true;}
vineEditor=installVineEditor({scene,camera,canvas:renderer.domElement,controls,world:()=>world,surfaces:()=>[land,...buildingEditor.surfaceMeshes(),...rockEditor.surfaceMeshes()],vineRoot:vineLayer.root,chooseTool,status,invalidate:()=>{dirtyFrame=true;renderer.shadowMap.needsUpdate=true;},commit:(next,message)=>{remember();world=next;rebuild();changed(message);}});
Object.assign(hints,{vine:'Click a root point, guide the vine over connected surfaces, then click to commit. Escape cancels.'});
Object.assign(hints,{route:'Click route points, then Finish route. Start rivers upstream. Escape cancels.',removeRoute:'Click near a path or river to remove the whole route. River channels remain; Smooth or Raise reshapes them.',paint:'Paint ground with soft edges. Brush radius and strength control each stroke.'});
let routePoints=[];
const routePreview=new THREE.Line(new THREE.BufferGeometry(),new THREE.LineBasicMaterial({color:0xffd477,depthTest:false}));
routePreview.renderOrder=10;scene.add(routePreview);
function previewRoute(){routePreview.geometry.dispose();routePreview.geometry=new THREE.BufferGeometry().setFromPoints(routePoints.map(p=>new THREE.Vector3(p.x,p.y+.3,p.z)));if($('routeFeedback'))routeFeedback(routePoints.length?`${routePoints.length} waypoints · ${routePoints.length<($('routeKind').value==='pond'?3:2)?'Add another point on the landscape.':'Ready to finish.'}`:'Click Draw a route, then click waypoints on the landscape.');dirtyFrame=true;}
function cancelRoute(){routePoints=[];previewRoute();}
const landscapePanel=document.createElement('div');
landscapePanel.innerHTML='<h3>Paths, rivers & ground</h3><label for="routeKind">Route type</label><select id="routeKind"><option value="road">Dirt path</option><option value="river">River</option></select><label for="routeWidth">Route width (metres)</label><input id="routeWidth" type="number" min="1" max="16" step=".5" value="3.5"><button id="startRoute">Draw a route</button><button id="finishRoute">Finish route</button><button id="cancelRoute">Cancel route</button><button id="removeRoute">Remove a path or river</button><label for="paintKind">Ground surface</label><select id="paintKind"><option value="0">Grass</option><option value="1">Sand</option><option value="2">Rock</option><option value="3">Earth / dirt</option><option value="-1">Restore natural surface</option></select><button id="paintGround">Paint ground</button><p>Click waypoints, then Finish route. Rivers start upstream and carve channels. Removal clears the water or path surface; use Raise or Smooth to reshape a riverbed. Routes clear scenery and avoid buildings. Ground paint uses brush radius and strength. Undo restores each edit.</p>';
$('toolHint').after(landscapePanel);
landscapePanel.querySelector('p').textContent='Click waypoints, then Finish route. Paths and ponds replace overlapping scenery, buildings, column rows, steps and water features. Overlapping features are removed in full; dirt paths can cross. Rivers carve channels and avoid buildings. Undo restores the entire edit, including replaced objects.';
$('routeKind').append(new Option('Pond / paint a basin','pond'));
const pondLabel=document.createElement('label');pondLabel.htmlFor='pondDepth';pondLabel.textContent='Pond depth (metres)';
const pondDepth=document.createElement('input');pondDepth.id='pondDepth';pondDepth.type='number';pondDepth.min='.5';pondDepth.max='6';pondDepth.step='.25';pondDepth.value='1';
$('routeWidth').after(pondLabel,pondDepth);
const pondHint=document.createElement('p');pondHint.textContent='Outline the enclosing bank with at least three points, then Create pond. The ground dips inside and water fills to the lowest edge. Reshape the banks to change the water level; exposed shallows dry out. Route width does not affect ponds. Removal leaves the basin; Undo restores the original ground.';
landscapePanel.append(pondHint);$('removeRoute').textContent='Remove path, river or pond';
hints.removeRoute='Click a path, river or pond to remove its surface. Basins and channels remain; Undo restores the feature.';
const pondBrushControls=document.createElement('div');pondBrushControls.innerHTML='<label for="pondRadius">Pond brush radius (metres)</label><input id="pondRadius" type="number" min="4" max="50" step=".5" value="10">';pondDepth.after(pondBrushControls);
pondHint.textContent='Drag to paint a basin, then release to carve and fill it. Overlapping strokes extend the pond. Depth and radius control the basin. Placement clears overlapping objects; Undo restores the whole stroke.';
pondBrush=installPondBrush({canvas:renderer.domElement,scene,controls,active:()=>tool==='pond',hit,world:()=>world,radius:()=>Number($('pondRadius').value),depth:()=>Number(pondDepth.value),invalidate:()=>{dirtyFrame=true;},status,commit:next=>{remember();world=next;rebuild();routeFeedback('Pond painted. Drag another stroke to extend it.');changed('Pond painted · Undo restores terrain and replaced objects');}});
$('routeKind').onchange=()=>{cancelRoute();const pond=$('routeKind').value==='pond';$('routeWidth').disabled=pond;$('routeWidth').hidden=pond;document.querySelector('label[for=routeWidth]').hidden=pond;$('cancelRoute').textContent=pond?'Cancel painting':'Cancel route';pondDepth.disabled=!pond;$('startRoute').textContent=pond?'Paint a pond':'Draw a route';$('finishRoute').textContent='Finish route';$('finishRoute').hidden=pond;$('pondRadius').parentElement.hidden=!pond;};
$('routeKind').onchange();
const iceControl=document.createElement('label');iceControl.innerHTML='<input type="checkbox" id="frozenWater"> Freeze natural water · walkable ice';landscapePanel.append(iceControl);
const iceHint=document.createElement('p');iceHint.textContent='Freezes the sea, rivers and ponds. Pools remain liquid. With ice off, walkers follow the ground beneath water.';landscapePanel.append(iceHint);
$('frozenWater').checked=!!world.frozenWater;$('frozenWater').onchange=()=>{remember();world.frozenWater=$('frozenWater').checked;rebuild();changed(world.frozenWater?'Natural water frozen · solid ice is walkable':'Ice melted · water has no walking surface');};
const routeMessage=document.createElement('p');routeMessage.id='routeFeedback';routeMessage.setAttribute('role','status');routeMessage.setAttribute('aria-live','polite');$('finishRoute').after(routeMessage);
function routeFeedback(message,error=false){const node=$('routeFeedback');if(!node)return;node.textContent=message;node.style.color=error?'#ffb6a5':'';node.style.fontWeight=error?'600':'';}
routeFeedback('Click Draw a route, then click waypoints on the landscape.');
$('startRoute').onclick=()=>{finish();cancelRoute();const pond=$('routeKind').value==='pond';chooseTool(pond?'pond':'route',pond?'Drag to paint a pond. Release to carve and fill. Escape cancels.':undefined);routeFeedback(pond?'Drag on the landscape, then release to create the pond.':'Click waypoints on the landscape, then Finish route.');};
const pondShortcut=document.createElement('button');pondShortcut.id='createPond';pondShortcut.textContent='Paint a pond';
document.querySelector('[data-tool="lower"]').after(pondShortcut);
pondShortcut.onclick=()=>{$('routeKind').value='pond';$('routeKind').onchange();$('startRoute').click();};
$('cancelRoute').onclick=()=>{cancelRoute();chooseTool('orbit');};
$('removeRoute').onclick=()=>{cancelRoute();chooseTool('removeRoute');};
$('paintGround').onclick=()=>{cancelRoute();chooseTool('paint');};
  $('paintKind').replaceChildren(...GROUND_SURFACES.map((label,id)=>new Option(label,String(id))),new Option('Restore natural surface','-1'));
const applyGround=document.createElement('button');applyGround.id='applyGroundAll';applyGround.textContent='Apply to all ground';$('paintKind').after(applyGround);
applyGround.onclick=()=>{
  finish();const next=clone(world),count=applyGroundSurface(next,Number($('paintKind').value));
  if(!count){status('Ground already matches this surface · cliff faces preserved');return;}
  remember();world=next;updateGroundPaint();changed('Ground surface applied · cliff faces preserved · Undo restores the previous surface');
};
$('finishRoute').onclick=()=>{
  try{const width=Number($('routeWidth').value);if($('routeKind').value!=='pond'&&(width<1||width>16||!Number.isFinite(width)))throw Error('Choose a width from 1 to 16 metres.');
    const kind=$('routeKind').value,next=clone(world);if(kind==='pond')addPond(next,routePoints,Number(pondDepth.value));else addRoute(next,kind,routePoints,width);remember();world=next;cancelRoute();rebuild();chooseTool('orbit');const message=(kind==='road'?'Path':kind==='pond'?'Pond':'River')+' added · Undo restores terrain and scenery';routeFeedback(message);changed(message);
  }catch(e){routeFeedback('Route not added: '+e.message+' Your waypoints are still here.',true);status(e.message,true);}
};
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!e.target.matches('input,select,textarea'))cancelRoute();});
hints.place='Click or hold left-drag to paint scenery. Spacing follows scenery size; Undo removes the whole stroke. Alt-drag to orbit.';
for(const b of document.querySelectorAll('[data-tool]'))if(!['steps','vine'].includes(b.dataset.tool))b.onclick=()=>{finish();chooseTool(b.dataset.tool);};
compactToolbar();
const firstPersonButton=document.createElement('button');firstPersonButton.id='firstPerson';firstPersonButton.textContent='First person';firstPersonButton.title='Walk through the world at standing height';$('viewbar').insertBefore(firstPersonButton,$('stats'));
firstPerson=installFirstPerson({camera,controls,canvas:renderer.domElement,world:()=>world,button:firstPersonButton,help:$('help'),invalidate:()=>dirtyFrame=true,onEnter:()=>{finish();ring.visible=false;if(floraDetail!=='near'){floraDetail='near';updateScenery();}},allowEditorEvent:event=>{
  const furnitureOpen=!!furnitureEditor?.primaryActionActive;
  if(event.type==='wheel')return furnitureOpen;
  const buildingsOpen=document.getElementById('ribbon-panel-buildings')?.hidden===false;
  return event.button===0&&(tool!=='orbit'||furnitureOpen||buildingsOpen);
}});
window.addEventListener('pagehide',()=>firstPerson.dispose(),{once:true});
for(const [id,format] of [['radius',v=>v+' m'],['strength',v=>v],['propSize',v=>v+'×'],['density',v=>Math.round(v*100)+'%']])$(id).oninput=()=>{$(id+'Value').textContent=format($(id).value);};
generationControls=installGenerationControls();
$('scatter').onclick=()=>{
  const density=Number($('density').value),next=clone(world);
  try{
    const recipe=generationControls.recipe();
    next.generation={...recipe,landforms:world.generation?.landforms||[legacyLandform(world.style)]};
    scatter(next,density,recipe.communities,crypto.getRandomValues(new Uint32Array(1))[0],recipe.rocks,recipe.clustering);
    const count=next.objects.filter(o=>o.source==='scatter').length;
    if(JSON.stringify(next.objects)===JSON.stringify(world.objects)&&JSON.stringify(next.generation)===JSON.stringify(world.generation)){
      status(density===0?'Natural coverage is 0% · raise it to grow scenery':count===0?'No room to grow here · scenery needs dry, gentle ground clear of paths, rivers, buildings':'Scenery already matches these settings');
      return;
    }
    remember();world=next;updateScenery();changed(count?count+' natural objects placed in a fresh arrangement · hand-placed scenery kept · Undo restores the previous layout':density===0?'Natural scenery cleared at 0% coverage · hand-placed scenery kept · Undo restores it':'No suitable planting space · hand-placed scenery kept · Undo restores the previous layout');
  }catch(e){status('Scenery could not regrow: '+e.message,true);}
};
function hit(event){const box=renderer.domElement.getBoundingClientRect();pointer.set((event.clientX-box.left)/box.width*2-1,-(event.clientY-box.top)/box.height*2+1);ray.setFromCamera(pointer,camera);if(tool==='build'){const p=buildingEditor.surfaceHit(ray);if(p!==undefined)return p;}return ray.intersectObject(land)[0]?.point;}
function brushRing(point){ring.visible=tool!=='orbit';const arr=ring.geometry.attributes.position;const radius=Number($('radius').value);for(let i=0;i<=64;i++){const a=i/64*Math.PI*2,x=point.x+Math.cos(a)*radius,z=point.z+Math.sin(a)*radius;arr.setXYZ(i,x,Math.max(.1,heightAt(world,x,z))+.2,z);}arr.needsUpdate=true;ring.geometry.computeBoundingSphere();dirtyFrame=true;}
function dab(point,refresh=true){
  const radius=Number($('radius').value);
  if(tool==='paint'){paintGround(world,point.x,point.z,radius,Number($('paintKind').value),Number($('strength').value));if(refresh)updateGroundPaint();return;}
  if(tool==='erase'){world.objects=world.objects.filter(o=>Math.hypot(o.x-point.x,o.z-point.z)>radius);if(refresh)updateScenery();}
  else{sculpt(world,point.x,point.z,radius,Number($('strength').value),tool,stroke.target);if(refresh)rebuild();}
}
function placeScenery(point,refresh=true,record=true){
    if(point.y<.1){status('Choose dry land to place scenery.',true);return;}
    if(world.objects.length>=2500){status('This island has reached its 2,500 scenery limit.',true);return;}
    const kind=$('prop').value,scale=Number($('propSize').value);
    const o={id:crypto.randomUUID(),kind,x:point.x,z:point.z,scale,rotation:Math.random()*Math.PI*2,source:'manual'};
    if(record)remember();world.objects.push(o);if(refresh){updateScenery();changed('Scenery placed');}return true;
}
renderer.domElement.addEventListener('wheel',event=>{
  if(tool!=='build'||!buildingEditor.rotatePlacement(event))return;
  event.preventDefault();event.stopImmediatePropagation();dirtyFrame=true;
},{capture:true,passive:false});
let buildingPickStart=null;
renderer.domElement.addEventListener('pointerdown',event=>{
  buildingPickStart=buildingPickGesture(tool,event,!!furnitureEditor?.primaryActionActive);
});
renderer.domElement.addEventListener('pointerup',event=>{
  const start=buildingPickStart;buildingPickStart=null;
  if(!start||start.id!==event.pointerId||tool!=='orbit'||Math.hypot(event.clientX-start.x,event.clientY-start.y)>4)return;
  const box=renderer.domElement.getBoundingClientRect();pointer.set((event.clientX-box.left)/box.width*2-1,-(event.clientY-box.top)/box.height*2+1);ray.setFromCamera(pointer,camera);
  const editable=buildingEditor.pickEditable(ray);if(editable)buildingEditor.selectEditable(editable);else{const vineId=vineEditor?.pick(ray);if(vineId)vineEditor.select(vineId);else{const id=buildingEditor.pickStructure(ray);buildingEditor.selectBuilding(id);}}dirtyFrame=true;
});
renderer.domElement.addEventListener('pointercancel',()=>{buildingPickStart=null;});
for(const type of ['keydown','keyup'])document.addEventListener(type,event=>{
  if(event.key==='Shift'&&tool==='build'&&!event.target.closest('input,select,textarea,[contenteditable="true"]')){
    if(buildingEditor.updateConstraint(type==='keydown'))dirtyFrame=true;
  }
});
window.addEventListener('blur',()=>{if(buildingEditor.updateConstraint(false))dirtyFrame=true;});
// Capture listener prevents orbit controls from also consuming a paint stroke.
renderer.domElement.addEventListener('pointerdown',event=>{
  if(event.button!==0||tool==='orbit'||event.altKey)return;
  event.stopImmediatePropagation();event.preventDefault();const point=hit(event);if(!point)return;
  if(tool==='build'){buildingEditor.click(point,event);dirtyFrame=true;return;}
  if(tool==='garden'){gardenEditor?.click(point);return;}
  if(tool==='route'){if(routePoints.length>=128){status('Finish this route before adding more points.',true);return;}if(!routePoints.length||point.distanceTo(routePoints.at(-1))>.4){routePoints.push(point.clone());previewRoute();status(routePoints.length+' route points · Finish route to commit');}return;}
  if(tool==='removeRoute'){const next=clone(world);if(removeRoute(next,point.x,point.z,Number($('radius').value))){remember();world=next;rebuild();changed('Route removed · channel shape remains · Undo restores the route');}else status('Click closer to a path or river.');return;}
  if(tool==='place'){
    if(!placeScenery(point))return;
    const bounds=new THREE.Box3();
    for(const part of flora.parts($('prop').value)){part.geometry.computeBoundingBox();bounds.union(part.geometry.boundingBox);}
    const size=bounds.getSize(new THREE.Vector3()),spacing=Math.max(.5,Math.max(size.x,size.z)*Number($('propSize').value)*.65);
    stroke={placing:true,last:point.clone(),spacing,placed:[point.clone()]};
    renderer.domElement.setPointerCapture(event.pointerId);controls.enabled=false;return;
  }
  remember();stroke={target:point.y,last:point.clone()};renderer.domElement.setPointerCapture(event.pointerId);controls.enabled=false;dab(point);changed('Sculpting · release to finish this stroke');
},true);
renderer.domElement.addEventListener('pointermove',event=>{
  if(tool==='orbit'||tool==='steps'||(!stroke&&(event.altKey||(event.buttons&6))))return;const point=hit(event);if(!point){gardenEditor?.hover(null);ring.visible=false;dirtyFrame=true;return;}if(tool==='garden'){gardenEditor?.hover(point);ring.visible=false;return;}if(tool==='build'){buildingEditor.hover(point,event);dirtyFrame=true;return;}brushRing(point);
  if(stroke?.placing){
    const distance=Math.hypot(point.x-stroke.last.x,point.z-stroke.last.z),count=Math.min(48,Math.floor(distance/stroke.spacing));
    if(!count)return;
    const start=stroke.last.clone();let added=0;
    for(let i=1;i<=count;i++){
      const p=start.clone().lerp(point,i*stroke.spacing/distance);p.y=heightAt(world,p.x,p.z);
      if(!stroke.placed.some(q=>Math.hypot(p.x-q.x,p.z-q.z)<stroke.spacing*.8)&&placeScenery(p,false,false)){stroke.placed.push(p);added++;}
    }
    stroke.last=start.lerp(point,count*stroke.spacing/distance);
    if(added){updateScenery();changed('Painting scenery · release to finish · Undo removes the whole stroke');}return;
  }
  if(stroke){const spacing=Math.max(world.size/N*.5,Number($('radius').value)*.16),distance=Math.hypot(point.x-stroke.last.x,point.z-stroke.last.z);if(distance>=spacing){const start=stroke.last.clone(),count=Math.min(48,Math.floor(distance/spacing));for(let i=1;i<=count;i++)dab(start.clone().lerp(point,i/count),false);if(tool==='erase')updateScenery();else if(tool==='paint')updateGroundPaint();else rebuild();stroke.last=point.clone();}}
});
function finish(){if(!stroke)return;const placing=stroke.placing;stroke=null;controls.enabled=!firstPerson?.active;if(tool==='erase')buildingEditor.refresh();changed(placing?'Scenery painted · Undo removes the whole stroke':'Landscape edited · Undo restores the whole stroke');}
renderer.domElement.addEventListener('pointerup',finish);renderer.domElement.addEventListener('pointercancel',finish);renderer.domElement.addEventListener('lostpointercapture',finish);
renderer.domElement.addEventListener('pointerleave',()=>{ring.visible=false;dirtyFrame=true;});
document.addEventListener('keydown',e=>{if(e.target.matches('input,select,textarea'))return;if(e.key==='Escape'){chooseTool('orbit');finish();}if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='z'){e.preventDefault();$(e.shiftKey?'redo':'undo').click();}});
function validate(w){
  validateGarden(w?.garden,w?.size,w?.furniture);
  validateGeneration(w?.generation);
  validateFurniture(w?.furniture);
  removeRetiredCaves(w);
  validateColumns(w?.columns,w?.size);
  validateSculpt(w?.rockSculpt,w?.size);
  validatePaint(w?.groundPaint,w?.groundPaintExtra);
  if(!w||w.schema!=='jnsq-island/1'||w.resolution!==N||![100,160,240].includes(w.size)||!STYLES.includes(w.style)||typeof w.name!=='string'||w.name.length>80||!Number.isInteger(w.seed)||w.seed<0||w.seed>4294967295)throw Error('This is not a supported island file.');
  if(!Array.isArray(w.heights)||w.heights.length!==(N+1)**2||w.heights.some(h=>!Number.isFinite(h)||h< -12||h>65))throw Error('The terrain geometry is invalid.');
  if(!Array.isArray(w.objects)||w.objects.length>2500)throw Error('Too many scenery objects.');
  const ids=new Set();for(const o of w.objects){if(!o||typeof o.id!=='string'||o.id.length>80||ids.has(o.id)||!PLANT_IDS.includes(o.kind)||!['manual','scatter'].includes(o.source)||![o.x,o.z,o.scale,o.rotation].every(Number.isFinite)||Math.abs(o.x)>w.size/2||Math.abs(o.z)>w.size/2||o.scale<(SOLID_TREE_IDS.includes(o.kind)?.03:.4)||o.scale>(SOLID_TREE_IDS.includes(o.kind)?32:3)||Math.abs(o.rotation)>Math.PI*2)throw Error('Invalid scenery in this file.');ids.add(o.id);}
  const textureIds=validateTextures(w.textures);for(const b of w.structures||[])for(const key of ['material','floorMaterial','roofMaterial','trimMaterial'])if(b[key]?.startsWith('custom_')&&!textureIds.has(b[key]))throw Error('A building texture is missing from this island.');
  if(w.atmosphere){w.atmosphere.water=normalizedWater(w.atmosphere.water);validateCustomSky(w.atmosphere.customSky);}
  validateStepRoutes(w.stepRoutes,w.size);validateFeatures(w.features,w.size);validateStructures(w.structures,w.size);validateVines(w.vines,w.size);return w;
}
function captureAtmosphere(){world.atmosphere=Object.fromEntries(['environment','weather','hour','strength','followLocalWeather','followLocalTime','cloudShadows','sunRays','cavernLighting','nebulaClouds','landBrightness','skyBrightness','lightingColor','water','customSky','skyColors'].map(k=>[k,clone(daylightControl.state[k])]));}
function download(){commitName();captureAtmosphere();const blob=new Blob([JSON.stringify(world)],{type:'application/json'}),url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download=(world.name.replace(/[^a-z0-9_-]/gi,'_')||'island')+'.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);status('Island exported · includes sculpted terrain and scenery');}
$('export').onclick=download;$('import').onclick=()=>{if(!busy)$('file').click();};
$('file').onchange=async()=>{try{const file=$('file').files[0];if(!file)return;if(file.size>4000000)throw Error('Choose an island file smaller than 4 MB.');const value=validate(JSON.parse(await file.text()));sidebar?.creation.close();remember();restore(value);activeId=null;revision=null;frame();status('Island imported · Save to add it to My islands');}catch(e){status(e.message,true);}finally{$('file').value='';}};
async function api(path,options){let response;try{response=await fetch('/api/islands'+path,options);}catch{throw Error('The local save service disconnected. Your draft is still safe in this tab. Run START_WORLD_BUILDER again, then press Save. Export also preserves it.');}let value;try{value=await response.json();}catch{throw Error('Island storage is unavailable on this host. Export preserves your work.');}if(!response.ok)throw Error(value.error||'Island storage request failed');return value;}
async function saveIsland(asCopy=false){
  if(busy)return false;commitName();captureAtmosphere();busy=true;$('save').disabled=true;let removedFurniture=[];
  try{const cleanup=removeFurnitureOutsideWorld(world.furniture||{},furnitureWorldRange(world.size));
    if(cleanup.removed.length){remember();removedFurniture=cleanup.removed.map(id=>world.furniture[id]?.name||id);world.furniture=cleanup.objects;dirty=true;furnitureEditor?.refresh();cacheDraft();}
    const snapshot=clone(world);validate(snapshot);const capabilities=(await api('')).capabilities||[];
    if(snapshot.garden&&!capabilities.includes('shared-garden-v1'))throw Error('This host needs the shared garden update. Restart World Builder or JNAIQ; Export preserves your layout.');
    if(snapshot.vines?.length&&!capabilities.includes('clinging-vines-v1'))throw Error('This host needs the clinging vines update. Restart World Builder or JNAIQ; Export preserves your vines.');
    if(snapshot.structures?.some(b=>b.wallEdits?.length||b.roofSections||b.partitions?.some(p=>p.doorLeaf||p.frames!==undefined))&&!capabilities.includes('building-components-v1'))throw Error('This host needs the building components update. Open the standalone World Builder or restart this host. Export preserves your edits.');
    if(snapshot.generation&&!capabilities.includes('generation-recipe-v1'))throw Error('This host needs the landform update. Export preserves your island and generation choices.');
    if(snapshot.generation?.clustering!==undefined&&!capabilities.includes('clustered-scenery-v1'))throw Error('This host needs the scenery clustering update. Export preserves your island and generation choices.');
    if((snapshot.atmosphere.landBrightness!==1||snapshot.atmosphere.lightingColor!=='#ffffff')&&!capabilities.includes('land-lighting-v1'))throw Error('This host needs the lighting update. Export preserves your lighting and island.');
    if(snapshot.atmosphere.skyColors?.enabled&&!capabilities.includes('generated-sky-colors-v1'))throw Error('This host needs the sky-color update. Export preserves your colors and island.');
    if((snapshot.atmosphere.customSky||snapshot.atmosphere.water)&&!capabilities.includes('sky-water-authoring-v1'))throw Error('This host needs the custom sky and ocean update. Export preserves your world.');
    if(snapshot.stepRoutes?.length&&!capabilities.includes('step-routes-v1'))throw Error('This host needs the steps update. Export preserves your stairs and slopes.');
    if(snapshot.rockSculpt?.length&&!capabilities.includes('rock-sculpt-v1'))throw Error('This host needs the rock sculpting update. Export preserves your sculpted rock.');
    if((snapshot.columns?.length||snapshot.structures?.some(b=>b.enclosure==='columns'))&&!capabilities.includes('columns-v1'))throw Error('This host needs the column update. Export preserves your columns and pavilions.');
    if(snapshot.structures?.some(b=>b.pool)&&!capabilities.includes('pools-v1'))throw Error('This host needs the pool update. Export preserves your pool and steps.');
    if(snapshot.structures?.some(b=>b.architecture&&b.architecture!=='plain')&&!capabilities.includes('architecture-v1'))throw Error('This host needs the architecture update. Export preserves your building styles.');
    if(snapshot.features?.some(f=>f.kind==='pond')&&!capabilities.includes('ponds-v1'))throw Error('This host needs the pond update. Export preserves your complete draft.');
    if(snapshot.structures?.some(b=>b.windowShape||b.doorShape)&&!capabilities.includes('opening-shapes-v1'))throw Error('This host needs the opening shapes update. Export preserves your complete draft.');
    if(snapshot.groundPaintExtra&&!capabilities.includes('ground-surfaces-v1'))throw Error('This host needs the expanded ground surfaces update. Export preserves your complete draft.');
    if(snapshot.groundPaint&&!capabilities.includes('landscape-paint-v1'))throw Error('This host needs the ground painting update. Export preserves your complete draft.');
    if(snapshot.objects.some(o=>GARDEN_IDS.includes(o.kind))&&!capabilities.includes('garden-plants-v1'))throw Error('This host needs the garden plants update. Export preserves your complete draft.');
    if((snapshot.objects.some(o=>['amethyst','quartz','azure_crystal'].includes(o.kind)))&&!capabilities.includes('crystals-v1'))throw Error('This host needs the crystal update. Export preserves your complete draft.');
    if((snapshot.textures?.length||snapshot.structures?.some(b=>b.partitions||b.floorMaterial||b.roofMaterial||b.trimMaterial||b.frames!==undefined||!['plaster','timber','stone'].includes(b.material)))&&!capabilities.includes('building-interiors-v1'))throw Error('This host needs the building interiors update. Export preserves all your textures and interior walls.');
    if((snapshot.features?.length||!['meadow','craggy','tropical','highland'].includes(snapshot.style))&&!capabilities.includes('landscape-features-v1'))throw Error('This host needs the landscape update. Export preserves your complete draft.');if(snapshot.structures?.length&&!capabilities.includes('structures-v1'))throw Error('This host needs the structure update. Export keeps your complete building draft.');const targetId=asCopy?null:activeId;const result=await api(targetId?'/'+targetId:'',{method:targetId?'PUT':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({world:snapshot,revision})});activeId=result.id;revision=result.revision;dirty=JSON.stringify(world)!==JSON.stringify(snapshot);cacheDraft();status(removedFurniture.length?`Saved · removed ${removedFurniture.join(', ')} from beyond this world's object limit · Undo restores them`:dirty?'Saved · newer edits still need saving':'Saved to My islands');}
  catch(e){status(e.message,true);return false;}finally{busy=false;$('save').disabled=false;}
  if(!dirty)window.dispatchEvent(new Event('jnaiq-world-saved'));
  return !dirty;
}
$('save').onclick=()=>saveIsland();
const newButton=document.createElement('button');newButton.id='newIsland';newButton.textContent='New';newButton.setAttribute('aria-controls','creationRibbon');newButton.setAttribute('aria-expanded','false');$('library').before(newButton);
newButton.onclick=async()=>{
  if(busy||document.getElementById('newIslandDialog'))return;
  await promptNewIsland({name:$('name').value,save:()=>saveIsland(),errorMessage:()=>$('status').textContent,create:()=>{
    const fresh=generate('meadow',crypto.getRandomValues(new Uint32Array(1))[0],160);
    firstPerson?.exit();finish();stepEditor?.cancel();cancelRoute();chooseTool('orbit');furnitureEditor?.select(null);
    world=fresh;activeId=null;revision=null;past=[];future=[];dirty=true;recoveryBackupPending=false;waterTime=0;
    daylightControl.restore({environment:'ocean',weather:'clear',hour:12,strength:.5,followLocalTime:true,followLocalWeather:false,clouds:true,cloudShadows:true,sunRays:true,cavernLighting:'natural',nebulaClouds:false,landBrightness:1,skyBrightness:1,lightingColor:'#ffffff',customSky:null});
    captureAtmosphere();syncInputs();rebuild();historyButtons();frame();cacheDraft();sidebar.creation.open();
    status('New unsaved island · Save to add it to My islands');
  }});
};
const copyButton=document.createElement('button');copyButton.textContent='Save a copy';copyButton.onclick=()=>saveIsland(true);$('save').before(copyButton);
$('library').onclick=async()=>{
  if(busy){status('Finishing this save…');return;}
  $('shelf').showModal();$('savedList').textContent='Loading…';
  try{const data=await api('');$('savedList').replaceChildren();if(!data.islands.length)$('savedList').textContent='Your saved islands will appear here.';
    for(const item of data.islands){const row=document.createElement('div');row.className='saved';const name=document.createElement('span');name.textContent=item.name;const detail=document.createElement('small');detail.textContent=`${item.style} · ${item.size} m`;name.append(detail);const load=document.createElement('button');load.textContent='Edit';load.setAttribute('aria-label','Edit '+item.name);load.onclick=async()=>{if(busy)return;busy=true;load.disabled=true;try{const data=await api('/'+item.id);validate(data.world);if(dirty&&!confirm('Replace your unsaved draft with this saved world? Cancel to save or export your draft first.'))return;sidebar?.creation.close();remember();restore(data.world);activeId=data.id;revision=data.revision;dirty=false;frame();$('shelf').close();status('Saved island opened for editing · Save island updates this draft; Save a copy keeps a separate variation.');}catch(e){status(e.message,true);}finally{busy=false;load.disabled=false;}};row.append(name,load);$('savedList').append(row);}
  }catch(e){$('savedList').textContent=e.message;}
};
$('closeShelf').onclick=()=>$('shelf').close();
// Recover the working draft across reloads, even if the host has not restarted.
const recoveryKey='jnaiq.island.workshop.draft.v1';
const legacyRecoveryKey='jnsq.island.workshop.draft.v1';
let recoveryBackupPending=false,recoveredFurnitureUndo=null,recoveredFurnitureNames=[];
try{let storedDraft=visitId?null:localStorage.getItem(recoveryKey);if(!storedDraft&&!visitId){storedDraft=localStorage.getItem(legacyRecoveryKey);if(storedDraft)try{localStorage.setItem(recoveryKey,storedDraft);}catch{recoveryBackupPending=true;}}
const saved=visitId?null:JSON.parse(storedDraft||'null');if(saved){
  const original=JSON.stringify(saved),before=JSON.stringify(saved.world);
  world=validate(saved.world);const needsResave=before!==JSON.stringify(world),cleanup=removeFurnitureOutsideWorld(world.furniture||{},furnitureWorldRange(world.size));
  if(cleanup.removed.length){recoveredFurnitureUndo=clone(world);recoveredFurnitureNames=cleanup.removed.map(id=>world.furniture[id]?.name||id);world.furniture=cleanup.objects;}
  const migrated=before!==JSON.stringify(world);
  if(migrated)try{if(!localStorage.getItem(recoveryKey+'-before-cave-retirement'))localStorage.setItem(recoveryKey+'-before-cave-retirement',original);}catch{recoveryBackupPending=true;}
  activeId=saved.id;revision=saved.revision;dirty=!!saved.dirty||needsResave;
}}catch(e){status('The previous browser draft could not be read. Import an exported island to recover it.',true);}
if(world.atmosphere)daylightControl.restore(world.atmosphere);
window.addEventListener('island-atmosphere-change',event=>{captureAtmosphere();changed(event.detail||'Sky and water changed');});
window.addEventListener('island-atmosphere-error',event=>status(event.detail||'The sky image could not be imported.',true));
for(const id of ['landBrightness','lightingColor','resetLandLighting','followLocalWeather'])$(id).addEventListener(id==='resetLandLighting'?'click':id==='followLocalWeather'?'change':'input',()=>{captureAtmosphere();changed('Land lighting changed');});
let lastCachedDraft=JSON.stringify({world,id:activeId,revision,dirty});
function cacheDraft(){if(visitId)return;commitName();if(recoveryBackupPending){status('Browser storage is full. Your original draft is preserved; Save or Export to keep these edits.',true);return;}try{const snapshot=JSON.stringify({world,id:activeId,revision,dirty});if(snapshot===lastCachedDraft)return;localStorage.setItem(recoveryKey,snapshot);lastCachedDraft=snapshot;}catch{status('Browser draft storage is full. Save or export your island.',true);}}
document.addEventListener('pointerup',cacheDraft);document.addEventListener('change',cacheDraft);
window.addEventListener('pagehide',cacheDraft);window.addEventListener('beforeunload',event=>{cacheDraft();if(dirty){event.preventDefault();event.returnValue='';}});
new ResizeObserver(()=>{const box=$('stage').getBoundingClientRect();renderer.setSize(box.width,box.height,false);camera.aspect=box.width/box.height;camera.updateProjectionMatrix();dirtyFrame=true;}).observe($('stage'));
let waterTime=0,lastFrame=null;
document.addEventListener('visibilitychange',()=>{lastFrame=null;});
function render(now=performance.now()){const delta=lastFrame===null?0:Math.max(0,(now-lastFrame)/1000);lastFrame=now;if(document.hidden)return;firstPerson?.update(delta);if(motion.checked)waterTime+=delta;const light=daylightControl.tick(delta);if(!renderer.xr.isPresenting&&!dirtyFrame&&!motion.checked&&!daylightControl.state.playing)return;const rig=updateLighting(light);furnitureEditor?.layer.update(light,waterTime,lighting.sun.intensity,motion.checked);visitorFurniture?.update(light,waterTime,lighting.sun.intensity,motion.checked);landscapeFeatures.update(waterTime);atmosphere.update(camera,waterTime,light,daylightControl.renderState);skyIllumination.update(light,daylightControl.renderState,rig);rig.applySky();renderer.render(scene,camera);dirtyFrame=false;}
sidebar=installSidebar();
if(!visitId){
  const gardenPanel=document.createElement('section');sidebar.addPanel('garden','Garden',gardenPanel);
  gardenEditor=installGardenEditor({panel:gardenPanel,scene,world:()=>world,status,chooseTool,invalidate:()=>{dirtyFrame=true;},
    commit:(next,message)=>{remember();world=next;rebuild();changed(message);},
    frame:b=>{firstPerson?.exit();controls.target.set(b.x,heightAt(world,b.x,b.z),b.z);camera.position.copy(controls.target).add(new THREE.Vector3(3.5,3.5,4));controls.update();dirtyFrame=true;}});
}
if(!visitId){
  if(!window.JNAIQ_STANDALONE){const roomsLink=document.createElement('a');roomsLink.className='action';roomsLink.href='./room.html';roomsLink.textContent='Existing worlds';roomsLink.title='Edit objects in JNAIQ worlds, including rooms and published landscapes';document.querySelector('header .actions').prepend(roomsLink);}
  const panel=document.createElement('section');
  const openFurniture=sidebar.addPanel('furniture','Furniture & objects',panel);
  document.getElementById('ribbon-tab-furniture').addEventListener('click',()=>{if(!firstPerson?.active)chooseTool('orbit');});
  const css=document.createElement('style');css.textContent='.furniture-grid{display:grid;grid-template-columns:1fr 1fr;gap:0 8px}#workshopRibbon #ribbon-panel-furniture{display:flex;gap:16px;overflow-x:auto;overflow-y:hidden}#ribbon-panel-furniture>div{columns:auto;height:100%;min-height:0;flex:0 0 250px;overflow-y:auto;box-sizing:border-box}#ribbon-panel-furniture>.furniture-preview{flex-basis:220px;margin:0}#ribbon-panel-furniture>.furniture-placement{flex:1 0 300px}#ribbon-panel-furniture button{margin:3px 4px 3px 0}#ribbon-panel-furniture input,#ribbon-panel-furniture select{max-width:100%}';document.head.append(css);
  furnitureEditor=installFurnitureEditor({scene,camera,canvas:renderer.domElement,controls,panel,objects:()=>world.furniture||{},textures:()=>world.textures||[],commit:(objects,message)=>{remember();world.furniture=objects;changed(message);},status,invalidate:()=>{dirtyFrame=true;renderer.shadowMap.needsUpdate=true;},ground:(x,z)=>heightAt(world,x,z),placementRange:()=>furnitureWorldRange(world.size),activate:()=>{chooseTool('orbit');openFurniture();},isActive:()=>tool==='orbit'&&!panel.hidden,canPickHandle:()=>tool==='orbit'&&!firstPerson?.active});
  const library=document.createElement('div'),placement=document.createElement('div'),preview=panel.querySelector('.furniture-preview');placement.className='furniture-placement';
  const selectionLabel=panel.querySelector('[data-f="selection"]').parentElement;
  let inPlacement=false;for(const child of [...panel.children]){if(child===selectionLabel)inPlacement=true;if(child===preview)continue;(inPlacement?placement:library).append(child);}
  library.querySelector('h2').remove();const gestureHint=library.querySelector('p');placement.append(gestureHint);
  panel.append(library,preview,placement);
  if(new URLSearchParams(location.search).get('furniture')==='1')openFurniture();
}
if(recoveredFurnitureUndo)past.push(recoveredFurnitureUndo);
syncInputs();rebuild();historyButtons();frame();renderer.setAnimationLoop(render);status(recoveredFurnitureNames.length?`Removed ${recoveredFurnitureNames.join(', ')} from beyond this world's object limit · Undo restores them`:dirty?'Recovered your unsaved island draft':'Ready · shape this island, or choose New to start another');
const requestedArchitecture=new URLSearchParams(location.search).get('architecture');
if(requestedArchitecture&&[...$('buildingArchitecture').options].some(o=>o.value===requestedArchitecture)){
  $('buildingArchitecture').value=requestedArchitecture;$('buildingArchitecture').onchange();
  status($('buildingArchitecture').selectedOptions[0].textContent+' ready · click Build house, then mark two opposite corners on land.');
}
if(visitId){
  try{
    const r=await fetch('/api/world-destinations/'+encodeURIComponent(visitId)),published=await r.json();if(!r.ok)throw Error(published.error);
    world=validate(published.world);dirty=false;if(world.atmosphere)daylightControl.restore(world.atmosphere);syncInputs();rebuild();
    const {installVisitor}=await import('./visitor.mjs?natural=1');
    installVisitor({scene,camera,controls,canvas:renderer.domElement,world,arrival:published.arrival,id:visitId,status,applyEnvironment:value=>daylightControl.restore(value),onFurnitureLayer:layer=>{visitorFurniture=layer;},invalidate:()=>{dirtyFrame=true;}});
  }catch(e){status(e.message,true);}
}else if(!window.JNAIQ_STANDALONE){
  let publishedId=null;
  async function publicationTarget(){
    const response=await fetch('/api/world-destinations'),value=await response.json();
    if(!response.ok)throw Error(value.error||'JNAIQ destination storage is unavailable.');
    return replacementDestination(value.destinations,activeId,world.name);
  }
  const publish=document.createElement('button');publish.textContent='Add to JNAIQ';$('save').after(publish);
  const unpublish=document.createElement('button');unpublish.textContent='Remove from JNAIQ';publish.after(unpublish);
  unpublish.onclick=async()=>{if(busy||!activeId)return;unpublish.disabled=true;try{const target=publishedId||await publicationTarget()||activeId;await api('/'+target+'/unpublish',{method:'POST'});publishedId=null;publish.textContent='Add to JNAIQ';status('World removed from travel. Your editable draft is preserved.');}catch(e){status(e.message,true);}finally{unpublish.disabled=false;}};
  publish.onclick=async()=>{if(busy)return;publish.disabled=true;try{
    await saveIsland();if(dirty||!activeId)throw Error('Save the island successfully before adding it to JNAIQ.');
    const replace=await publicationTarget(),query=replace?'?replace='+encodeURIComponent(replace):'';
    const result=await api('/'+activeId+'/publish'+query,{method:'POST'});if(!result.load_ready||!result.content_sha256||!result.load_url)throw Error('JNAIQ could not verify the published world. Your saved draft is preserved; restart JNAIQ before travelling.');publishedId=result.id;
    publish.textContent='Update JNAIQ world';status(result.replaced?result.name+' updated and load-verified in JNAIQ. The existing destination was preserved and the duplicate was retired.':result.name+' published and load-verified. Its teleporters are shared across JNAIQ; add one under Furniture & objects if needed. Your draft stays editable.');
  }catch(e){status(e.message,true);}finally{publish.disabled=false;}};
}

if(!visitId){worldGuide();if(new URLSearchParams(location.search).has('edit'))$('library').click();}

installBuilderVR({renderer,scene,camera,controls,beforeEnter:()=>firstPerson?.exit(),ground:(x,z)=>heightAt(world,x,z),status,invalidate:()=>{dirtyFrame=true;}});
