import * as THREE from 'three';
import {objectAssetURL} from './object-asset-url.mjs';
import {GLTFLoader} from './vendor/GLTFLoader.js';
import {OrbitControls} from './vendor/OrbitControls.js';

export function furniturePreview(container){
  const canvas=document.createElement('canvas'),caption=document.createElement('p');
  canvas.setAttribute('aria-label','Furniture model preview');canvas.title='Drag to inspect this model';
  container.append(canvas,caption);
  let renderer,scene,camera,controls,model,wanted=null,loaded=null,failed=false,token=0;
  function dispose(root){root?.traverse(n=>{n.geometry?.dispose();for(const m of (Array.isArray(n.material)?n.material:[n.material]))if(m){for(const v of Object.values(m))if(v?.isTexture)v.dispose();m.dispose();}});}
  function render(){if(renderer&&container.clientWidth&&container.clientHeight)renderer.render(scene,camera);}
  async function update(){
    if(!container.getClientRects().length||!container.clientWidth)return;
    if(!renderer){
      renderer=new THREE.WebGLRenderer({canvas,antialias:true});renderer.setPixelRatio(Math.min(devicePixelRatio,1.5));renderer.setClearColor(0x15272d);renderer.toneMapping=THREE.ACESFilmicToneMapping;
      scene=new THREE.Scene();camera=new THREE.PerspectiveCamera(35,1,.01,10000);
      scene.add(new THREE.HemisphereLight(0xffffff,0x68776b,1.5));const light=new THREE.DirectionalLight(0xffeedc,2);light.position.set(3,5,4);scene.add(light);
      controls=new OrbitControls(camera,canvas);controls.enablePan=false;controls.enableZoom=false;controls.addEventListener('change',render);
    }
    const width=container.clientWidth,height=Math.max(90,container.clientHeight-30);renderer.setSize(width,height,false);canvas.style.height=height+'px';camera.aspect=width/height;camera.updateProjectionMatrix();render();
    if(loaded===wanted?.filename&&!failed)return;
    const item=wanted,current=++token;loaded=item?.filename;failed=false;dispose(model);if(model)scene.remove(model);model=null;render();
    if(!item){caption.textContent='Choose a model to preview';return;}
    caption.textContent='Loading '+item.display_name+'…';
    try{
      const url=await objectAssetURL(item.filename);let root;
      if(item.filename.endsWith('.glb'))root=(await new GLTFLoader().loadAsync(url)).scene;
      else{const map=await new THREE.TextureLoader().loadAsync(url);map.colorSpace=THREE.SRGBColorSpace;root=new THREE.Mesh(new THREE.PlaneGeometry(1,map.image.height/map.image.width),new THREE.MeshStandardMaterial({map,side:THREE.DoubleSide}));}
      if(current!==token){dispose(root);return;}
      root.traverse(n=>{if(n.isLight)n.visible=false;});model=root;scene.add(root);
      const box=new THREE.Box3().setFromObject(root),center=box.getCenter(new THREE.Vector3()),radius=Math.max(.1,box.getSize(new THREE.Vector3()).length()/2);
      const distance=radius/Math.sin(Math.atan(Math.tan(THREE.MathUtils.degToRad(17.5))*Math.min(1,camera.aspect)))*1.1;
      controls.target.copy(center);camera.near=Math.max(.001,radius/1000);camera.far=distance+radius*10;camera.position.copy(center).add(new THREE.Vector3(1,.65,1).normalize().multiplyScalar(distance));camera.updateProjectionMatrix();controls.update();caption.textContent=item.display_name+' · drag to inspect';render();
    }catch(error){if(current===token){failed=true;loaded=null;caption.textContent='Preview unavailable · point here to retry';console.warn('Furniture preview failed',item.filename,error);render();}}
  }
  const retry=()=>{if(failed&&wanted)void update();};
  container.addEventListener('pointerenter',retry);window.addEventListener('focus',retry);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)retry();});
  new ResizeObserver(()=>{void update();}).observe(container);
  return {show(item){wanted=item;void update();}};
}
