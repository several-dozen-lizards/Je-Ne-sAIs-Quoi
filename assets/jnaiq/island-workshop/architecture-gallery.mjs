import * as THREE from './vendor/three.module.js';
import {OrbitControls} from './vendor/OrbitControls.js';
import {ARCHITECTURES,styleDefaults} from './architecture.mjs';
import {makeStructure,disposeStructure} from './structures.mjs?caves=retired';
const $=id=>document.getElementById(id),canvas=document.querySelector('canvas'),view=$('view');
const useStyle=document.createElement('a');useStyle.textContent='Use this style in the island workshop →';useStyle.style.cssText='display:inline-block;padding:9px 12px;background:#d7b477;color:#172824;border-radius:6px;text-decoration:none';document.querySelector('.controls').append(useStyle);
const renderer=new THREE.WebGLRenderer({canvas,antialias:true});renderer.setPixelRatio(Math.min(devicePixelRatio,1.5));renderer.shadowMap.enabled=true;renderer.shadowMap.type=THREE.PCFSoftShadowMap;renderer.toneMapping=THREE.ACESFilmicToneMapping;
const scene=new THREE.Scene();scene.background=new THREE.Color('#a6b8b3');scene.add(new THREE.HemisphereLight(0xe9f2ff,0x78644b,2.3));
const sun=new THREE.DirectionalLight(0xffebcc,3);sun.position.set(-25,38,30);sun.castShadow=true;sun.shadow.mapSize.set(2048,2048);Object.assign(sun.shadow.camera,{left:-30,right:30,top:35,bottom:-30,near:1,far:110});sun.shadow.bias=-.00015;scene.add(sun);
const ground=new THREE.Mesh(new THREE.PlaneGeometry(180,180),new THREE.MeshStandardMaterial({color:0x858e7a,roughness:1}));ground.rotation.x=-Math.PI/2;ground.position.y=-.2;ground.receiveShadow=true;scene.add(ground);
const camera=new THREE.PerspectiveCamera(42,1,.1,250),controls=new OrbitControls(camera,canvas);controls.maxPolarAngle=Math.PI*.49;controls.minDistance=14;controls.maxDistance=100;controls.enableDamping=false;
let selected='cottage',building;
function render(){renderer.render(scene,camera);}
function resize(){const {width,height}=view.getBoundingClientRect();renderer.setSize(width,height,false);camera.aspect=width/height;camera.updateProjectionMatrix();render();}
function reset(){camera.position.set(31,22,37);controls.target.set(0,5,0);controls.update();render();}
function update(){
  if(building){scene.remove(building);disposeStructure(building);}
  const a=ARCHITECTURES[selected],b={id:'preview',x:0,y:0,z:0,rotation:0,width:18,depth:16,shape:$('shape').value,floors:Number($('floors').value),stairs:true,...styleDefaults(selected)};
  building=makeStructure(b);scene.add(building);
  if($('cutaway').value==='0')for(const mesh of building.children)mesh.visible=!mesh.userData.roof&&mesh.userData.level===0;
  $('name').textContent=a.name;$('description').textContent=a.description;
  useStyle.href='./index.html?architecture='+encodeURIComponent(selected)+'#build-home';
  for(const button of $('styles').children)button.setAttribute('aria-pressed',String(button.dataset.style===selected));
  render();$('receipt').textContent=`${b.width} × ${b.depth} m · ${b.floors} floors · ${a.roofForm} roof`;
}
for(const [id,a] of Object.entries(ARCHITECTURES))if(id!=='plain'){const button=document.createElement('button');button.textContent=a.name;button.dataset.style=id;button.onclick=()=>{selected=id;update();};$('styles').append(button);}
for(const id of ['shape','floors','cutaway'])$(id).onchange=update;$('reset').onclick=reset;controls.addEventListener('change',render);new ResizeObserver(resize).observe(view);reset();update();resize();
