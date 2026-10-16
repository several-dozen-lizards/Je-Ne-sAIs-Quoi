import * as THREE from './vendor/three.module.js';
import {polyhavenSurface} from './polyhaven-surfaces.mjs';

export const BUILDING_SURFACE_SOURCES=Object.freeze({
  brick:'polyhaven:brick_wall_006',
  plaster:'polyhaven:grey_plaster',
  timber:'polyhaven:wood_planks',
  parquet:'polyhaven:old_wood_floor',
  concrete:'polyhaven:concrete_wall_004',
  stone:'polyhaven:white_sandstone_blocks_02',
  marble:'polyhaven:marble_01',
  tiles:'polyhaven:terracotta_floor_tiles',
  roof:'polyhaven:grey_roof_01',
  copper:'polyhaven:metal_plate_02',
  thatch:'polyhaven:thatch_roof_angled'
});

export const BUILDING_SURFACE_METRES=Object.freeze({brick:2.4,plaster:3.2,timber:1.5,parquet:2.8,concrete:3.4,stone:2.6,marble:1.5,tiles:2.1,roof:8,copper:2,thatch:.5});
const POLYHAVEN_FINISHES=Object.freeze({brick:'brick_wall_006',plaster:'grey_plaster',timber:'wood_planks',parquet:'old_wood_floor',concrete:'concrete_wall_004',stone:'white_sandstone_blocks_02',marble:'marble_01',tiles:'terracotta_floor_tiles',roof:'grey_roof_01',copper:'metal_plate_02',thatch:'thatch_roof_angled'});

// Metre-based projection: details retain their size when buildings are resized.
export function buildingMaterial(kind,roundRadius=0,texture=null,tileMetres=2){
  const material=new THREE.MeshStandardMaterial({roughness:.87});
  const phName=!texture&&POLYHAVEN_FINISHES[kind];
  const phTile=BUILDING_SURFACE_METRES[kind]||2;
  const ph=phName?polyhavenSurface(phName,()=>globalThis.dispatchEvent?.(new Event('island-texture-ready'))):null;
  let uploaded=null;
  if(texture){uploaded=new THREE.TextureLoader().load(texture.data,()=>globalThis.dispatchEvent?.(new Event('island-texture-ready')));uploaded.colorSpace=THREE.SRGBColorSpace;uploaded.wrapS=uploaded.wrapT=THREE.RepeatWrapping;material.addEventListener('dispose',()=>uploaded.dispose());}
  material.onBeforeCompile=shader=>{
    if(uploaded)shader.uniforms.uploadedSurface={value:uploaded};
    if(ph)for(const role of ['albedo','normal','rough','height'])shader.uniforms['ph_'+role]={value:ph[role]};
    shader.vertexShader=shader.vertexShader.replace('#include <common>','#include <common>\nvarying vec3 surfacePosition;varying vec3 surfaceNormal;');
    shader.vertexShader=shader.vertexShader.replace('#include <begin_vertex>','#include <begin_vertex>\nsurfacePosition=position;surfaceNormal=normal;');
    shader.fragmentShader=shader.fragmentShader.replace('#include <common>',`#include <common>
    varying vec3 surfacePosition;varying vec3 surfaceNormal;
    ${uploaded?'uniform sampler2D uploadedSurface;':''}
    ${ph?'uniform sampler2D ph_albedo,ph_normal,ph_rough,ph_height;':''}
    float bh(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453);}
    float bn(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*(3.-2.*f);return mix(mix(bh(i),bh(i+vec2(1,0)),f.x),mix(bh(i+vec2(0,1)),bh(i+vec2(1)),f.x),f.y);}
    vec4 surface(vec2 uv){
      ${uploaded?`return vec4(texture2D(uploadedSurface,uv/${Number(tileMetres).toFixed(4)}).rgb,0.);`:
        ph?`vec2 p=uv/${phTile.toFixed(4)};return vec4(texture2D(ph_albedo,p).rgb,texture2D(ph_height,p).r*.004);`:
        kind==='concrete'?`float g=bn(uv*65.);return vec4(vec3(.52,.54,.53)*(.85+g*.2+bn(uv)*.1),g*.002);`:
        kind==='marble'?`float vein=pow(.5+.5*sin(uv.x*3.+uv.y+bn(uv*2.)*7.),18.);return vec4(mix(vec3(.80,.79,.73),vec3(.29,.34,.36),vein*.7),0.);`:
        kind==='copper'?`float patina=bn(uv*.38)*.7+bn(uv*2.)*.3;return vec4(mix(vec3(.24,.19,.115),vec3(.12,.24,.19),smoothstep(.1,.85,patina)),patina*.002);`:
        kind==='thatch'?`float reed=bn(vec2(uv.x*95.,uv.y*2.));return vec4(mix(vec3(.30,.20,.07),vec3(.65,.48,.19),reed),reed*.006);`:
        kind==='brick'||kind==='tiles'?`vec2 cell=uv*vec2(${kind==='brick'?'3.,6.':'2.,2.'});cell.x+=mod(floor(cell.y),2.)*.5;vec2 f=fract(cell);float joint=smoothstep(.025,.065,min(min(f.x,1.-f.x),min(f.y,1.-f.y)));return vec4(mix(vec3(.39,.35,.29),vec3(.48,.18,.085)*(.75+bh(floor(cell))*.45),joint),joint*.012);`:
        kind==='plaster'?`float grain=bn(uv*45.)*.6+bn(uv*130.)*.4;float mottling=bn(uv*.9);return vec4(vec3(.72,.65,.51)*(.86+mottling*.16+grain*.13),grain*.0015);`:
        kind==='stone'?`vec2 cell=vec2(uv.x*1.4+mod(floor(uv.y*2.7),2.)*.5,uv.y*2.7);vec2 f=fract(cell);float edge=min(min(f.x,1.-f.x),min(f.y,1.-f.y));float stone=smoothstep(.025,.06,edge);float grain=bn(uv*32.);vec3 block=mix(vec3(.29,.32,.30),vec3(.52,.50,.43),bh(floor(cell)));return vec4(mix(vec3(.22,.21,.18),block*(.86+grain*.26),stone),stone*.026+grain*.004);`:
        kind==='roof'?`vec2 cell=vec2(uv.x*3.+mod(floor(uv.y*4.),2.)*.5,uv.y*4.);vec2 f=fract(cell);float edge=min(min(f.x,1.-f.x),min(f.y,1.-f.y));float tile=smoothstep(.025,.065,edge);vec3 slate=mix(vec3(.075,.105,.11),vec3(.12,.16,.16),bh(floor(cell)));return vec4(slate*(.65+.35*tile),tile*.006+f.y*.003);`:
        `return vec4(.35,.23,.12,0.);`}
    }
    `);
    shader.fragmentShader=shader.fragmentShader.replace('#include <color_fragment>',`#include <color_fragment>
    vec3 an=abs(normalize(surfaceNormal));vec2 uv=an.y>.65?surfacePosition.xz:an.x>an.z?surfacePosition.zy:surfacePosition.xy;
    ${roundRadius?`if(an.y<.65)uv=vec2(atan(surfacePosition.z,surfacePosition.x)*${roundRadius.toFixed(5)},surfacePosition.y);`:''}
    ${ph&&kind==='parquet'?`if(mod(floor(uv.x*1.3)+floor(uv.y*1.3),2.)>.5)uv=uv.yx;`:''}
    vec4 finish=surface(uv);
    ${ph&&kind==='copper'?`float metalGrain=dot(finish.rgb,vec3(.2126,.7152,.0722));float patina=smoothstep(.80,.96,1.-metalGrain);finish.rgb=mix(vec3(.42,.18,.065)*(.65+metalGrain*1.2),vec3(.06,.32,.22)*(.72+metalGrain),patina*.58);`:''}
    diffuseColor.rgb=finish.rgb;`);
    if(ph)shader.fragmentShader=shader.fragmentShader.replace('#include <roughnessmap_fragment>',`#include <roughnessmap_fragment>
      roughnessFactor=clamp(texture2D(ph_rough,uv/${phTile.toFixed(4)}).r,.3,1.);`);
    shader.fragmentShader=shader.fragmentShader.replace('#include <normal_fragment_maps>',`#include <normal_fragment_maps>
    ${ph?`vec3 q0=dFdx(-vViewPosition),q1=dFdy(-vViewPosition);vec2 st0=dFdx(uv/${phTile.toFixed(4)}),st1=dFdy(uv/${phTile.toFixed(4)});
    vec3 cr1=cross(q1,normal),cr0=cross(normal,q0),t=cr1*st0.x+cr0*st1.x,b=cr1*st0.y+cr0*st1.y;
    float frameScale=inversesqrt(max(max(dot(t,t),dot(b,b)),1e-10));vec3 detail=texture2D(ph_normal,uv/${phTile.toFixed(4)}).xyz*2.-1.;
    normal=normalize(normal*max(detail.z,.1)+(t*detail.x+b*detail.y)*frameScale*.65);`:''}
    vec3 dpdx=dFdx(vViewPosition),dpdy=dFdy(vViewPosition);vec3 r1=cross(dpdy,normal),r2=cross(normal,dpdx);float determinant=dot(dpdx,r1);
    float reliefFade=1./(1.+length(fwidth(uv))*20.);vec3 gradient=sign(determinant)*(dFdx(finish.a)*r1+dFdy(finish.a)*r2)*reliefFade;normal=normalize(max(abs(determinant),1e-8)*normal-gradient);`);
  };
  material.customProgramCacheKey=()=>`building-surface-${kind}-${roundRadius}-${tileMetres}-8`;
  return material;
}
