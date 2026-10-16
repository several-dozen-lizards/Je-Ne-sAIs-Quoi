import * as THREE from './vendor/three.module.js';
import {polyhavenSurface} from './polyhaven-surfaces.mjs';

export const NATURAL_SURFACE_SOURCES=Object.freeze({
  grass:'polyhaven:leafy_grass',
  dirt:'polyhaven:dirt_floor',
  rock:'polyhaven:cliff_side',
  paintedRock:'polyhaven:rocks_ground_01',
  bark:'polyhaven:fir_bark',
  clay:'polyhaven:dirt_floor',
  snow:'polyhaven:snow_02',
  basalt:'polyhaven:rock_01',
  moss:'polyhaven:forest_ground_04',
  gravel:'polyhaven:rocks_ground_01',
  ash:'polyhaven:rock_01',
  alien:'polyhaven:rocks_ground_01',
  enchanted:'polyhaven:forest_ground_04'
});

// World-space presentation footprint for each photographed scan. These spans
// are deliberately broader than the source swatch where island-scale tiling
// would otherwise advertise the image boundary; the normal maps retain the
// close relief while broad colour layers carry variation over larger ground.
export const NATURAL_SURFACE_METRES=Object.freeze({
  grass:3.4,dirt:3.8,rock:5.6,paintedRock:4.5,bark:2,
  clay:3.8,snow:4.2,basalt:5.6,moss:6.8,gravel:4.5,
  ash:5.6,alien:4.5,enchanted:6.8
});

// Existing JNAIQ photographed surfaces. Colour is sRGB; other maps are data.
export function islandMaterials(renderer,invalidate,reportError){
  const textures={};
  for(const kind of ['grass','dirt','rock','tree_bark']){
    const name=({grass:'leafy_grass',dirt:'dirt_floor',rock:'cliff_side',tree_bark:'fir_bark'})[kind];
    const surface=polyhavenSurface(name,invalidate,reportError);
    textures[kind]={albedo:surface.albedo,normal:surface.normal,rough:surface.rough};
    for(const t of Object.values(textures[kind]))t.anisotropy=Math.min(8,renderer.capabilities.getMaxAnisotropy());
  }
  const gravel=polyhavenSurface('rocks_ground_01',invalidate,reportError);
  textures.paintedRock={albedo:gravel.albedo,normal:gravel.normal,rough:gravel.rough};
  const snow=polyhavenSurface('snow_02',invalidate,reportError);
  textures.snow={albedo:snow.albedo,normal:snow.normal,rough:snow.rough};
  const moss=polyhavenSurface('forest_ground_04',invalidate,reportError);
  textures.moss={albedo:moss.albedo,normal:moss.normal,rough:moss.rough};
  const terrain=new THREE.MeshStandardMaterial({roughness:1});
  const spaceMode={value:0};
  const grassTint={value:new THREE.Vector3(.74,.96,.78)},sandTint={value:new THREE.Vector3(.61,.52,.35)},terrainTone={value:1},alienSurface={value:0};
  terrain.onBeforeCompile=shader=>{
    shader.uniforms.grassTint=grassTint;shader.uniforms.sandTint=sandTint;shader.uniforms.terrainTone=terrainTone;shader.uniforms.alienSurface=alienSurface;
    shader.uniforms.spaceMode=spaceMode;
    // Keep custom terrain samplers below the WebGL1/low-end WebGL2 floor of
    // 16 texture units after the shadow map and reflected-sky map are counted.
    for(const k of ['grass','dirt','rock'])for(const c of ['albedo','normal','rough'])shader.uniforms[`${k}_${c}`]={value:textures[k][c]};
    for(const c of ['albedo','normal'])shader.uniforms[`paintedRock_${c}`]={value:textures.paintedRock[c]};
    for(const k of ['snow','moss'])shader.uniforms[`${k}_albedo`]={value:textures[k].albedo};
    shader.vertexShader=shader.vertexShader.replace('#include <common>',`#include <common>
      attribute vec4 groundPaint;varying vec4 paintedGround;
      attribute vec4 groundExtra0,groundExtra1;varying vec4 extraGround0,extraGround1;
      varying vec3 vLandPosition;
      varying vec3 vLandNormal;`);
    shader.vertexShader=shader.vertexShader.replace('#include <begin_vertex>',`#include <begin_vertex>
      paintedGround=groundPaint;
      extraGround0=groundExtra0;extraGround1=groundExtra1;
      vLandPosition=(modelMatrix*vec4(position,1.0)).xyz;
      vLandNormal=normalize(mat3(modelMatrix)*normal);`);
    shader.fragmentShader=shader.fragmentShader.replace('#include <common>',`#include <common>
      varying vec4 paintedGround;
      varying vec4 extraGround0,extraGround1;
      varying vec3 vLandPosition;
      varying vec3 vLandNormal;
      uniform sampler2D grass_albedo,grass_normal,grass_rough;
      uniform sampler2D dirt_albedo,dirt_normal,dirt_rough;
      uniform sampler2D rock_albedo,rock_normal,rock_rough;
      uniform sampler2D paintedRock_albedo,paintedRock_normal;
      uniform sampler2D snow_albedo,moss_albedo;
      uniform vec3 grassTint,sandTint;uniform float spaceMode,terrainTone,alienSurface;
      float landHash(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453);}
      float landNoise(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*(3.0-2.0*f);return mix(mix(landHash(i),landHash(i+vec2(1,0)),f.x),mix(landHash(i+vec2(0,1)),landHash(i+vec2(1,1)),f.x),f.y);}
      // A slow, continuous phase warp breaks the obvious grid of identical
      // photographs without extra texture reads.  It never changes the scan's
      // metre scale and remains deterministic across editing, saves and visits.
      vec2 antiTileUV(vec2 p,float seed){vec2 q=p*.09;vec2 warp=vec2(landNoise(q+vec2(seed,seed*.37)),landNoise(q.yx+vec2(seed*.61,seed+19.7)));return p+(warp-.5)*.88;}
      vec2 rotateSurface(vec2 p,float angle){float c=cos(angle),s=sin(angle);return mat2(c,-s,s,c)*p;}
      vec2 quarterTurn(vec2 p,float turn){if(turn<.5)return p;if(turn<1.5)return vec2(-p.y,p.x);if(turn<2.5)return -p;return vec2(p.y,-p.x);}
      vec2 quarterUntwist(vec2 n,float turn){if(turn<.5)return n;if(turn<1.5)return vec2(n.y,-n.x);if(turn<2.5)return -n;return vec2(-n.y,n.x);}
      vec4 photoTap(sampler2D tex,vec2 p,float index,float seed){float turn=floor(landHash(vec2(index+23.1,seed+5.9))*4.);vec2 offset=vec2(landHash(vec2(index,seed)),landHash(vec2(seed+3.7,index+11.)));return texture2D(tex,quarterTurn(p,turn)+offset);}
      vec2 photoNormalTap(sampler2D tex,vec2 p,float index,float seed){float turn=floor(landHash(vec2(index+23.1,seed+5.9))*4.);vec2 offset=vec2(landHash(vec2(index,seed)),landHash(vec2(seed+3.7,index+11.)));return quarterUntwist(texture2D(tex,quarterTurn(p,turn)+offset).xy*2.-1.,turn);}
      vec3 photoSample(sampler2D tex,vec2 p,float seed){float choice=landNoise(p*.42+vec2(seed*.17,seed*.31))*7.;float index=floor(choice),blend=smoothstep(.18,.82,fract(choice));return mix(photoTap(tex,p,index,seed),photoTap(tex,p,index+1.,seed),blend).rgb;}
      vec2 photoNormalSample(sampler2D tex,vec2 p,float seed){float choice=landNoise(p*.42+vec2(seed*.17,seed*.31))*7.;float index=floor(choice),blend=smoothstep(.18,.82,fract(choice));return mix(photoNormalTap(tex,p,index,seed),photoNormalTap(tex,p,index+1.,seed),blend);}
      vec3 triSample(sampler2D tex,vec3 p,vec3 w,float seed){return texture2D(tex,antiTileUV(p.zy,seed)).rgb*w.x+texture2D(tex,antiTileUV(p.xz,seed+7.3)).rgb*w.y+texture2D(tex,antiTileUV(p.xy,seed+13.1)).rgb*w.z;}
      vec3 triPhotoSample(sampler2D tex,vec3 p,vec3 w,float seed){return photoSample(tex,p.zy,seed)*w.x+photoSample(tex,p.xz,seed+7.3)*w.y+photoSample(tex,p.xy,seed+13.1)*w.z;}
      float triBroadNoise(vec3 p,vec3 w,float seed){return landNoise(p.zy+vec2(seed,seed*.37))*w.x+landNoise(p.xz+vec2(seed*.61,seed+7.3))*w.y+landNoise(p.xy+vec2(seed+13.1,seed*.23))*w.z;}
      vec3 triDetail(sampler2D tex,vec3 p,vec3 w,float seed){vec2 x=texture2D(tex,antiTileUV(p.zy,seed)).xy*2.0-1.0,y=texture2D(tex,antiTileUV(p.xz,seed+7.3)).xy*2.0-1.0,z=texture2D(tex,antiTileUV(p.xy,seed+13.1)).xy*2.0-1.0;return vec3(0,x.y,x.x)*w.x+vec3(y.x,0,y.y)*w.y+vec3(z.x,z.y,0)*w.z;}
      vec3 triPhotoDetail(sampler2D tex,vec3 p,vec3 w,float seed){vec2 x=photoNormalSample(tex,p.zy,seed),y=photoNormalSample(tex,p.xz,seed+7.3),z=photoNormalSample(tex,p.xy,seed+13.1);return vec3(0,x.y,x.x)*w.x+vec3(y.x,0,y.y)*w.y+vec3(z.x,z.y,0)*w.z;}`);
    shader.fragmentShader=shader.fragmentShader.replace('#include <color_fragment>',`#include <color_fragment>
      if(spaceMode>.5&&vLandPosition.y<=0.)discard;
      vec3 landN=normalize(vLandNormal);
      vec3 tw=pow(abs(landN),vec3(6.0));tw/=max(dot(tw,vec3(1)),.0001);
      float macro=landNoise(vLandPosition.xz*.055);
      float rw=1.0-smoothstep(.55,.88,abs(landN.y));
      float gw=smoothstep(.7,3.4,vLandPosition.y+(macro-.5)*2.0)*(1.0-rw);
      float sw=1.0-rw-gw;
      float extraWeight=dot(extraGround0+extraGround1,vec4(1.));
      float naturalWeight=max(0.,1.-dot(paintedGround,vec4(1.))-extraWeight);
      gw=gw*naturalWeight+paintedGround.x;
      float naturalRock=rw*naturalWeight;
      float paintedRockWeight=paintedGround.z;
      rw=naturalRock+paintedRockWeight;
      sw=sw*naturalWeight+paintedGround.y;
      float dw=paintedGround.w;
      vec2 uvGrass=antiTileUV(vLandPosition.xz/${NATURAL_SURFACE_METRES.grass.toFixed(4)},2.1);
      vec2 uvDirt=antiTileUV(vLandPosition.xz/${NATURAL_SURFACE_METRES.dirt.toFixed(4)},11.7);
      float groundDistance=distance(cameraPosition,vLandPosition);
      float nearSoil=1.-smoothstep(8.,32.,groundDistance);
      // Keep close texture character, then progressively favor the broader
      // scan as the texel footprint shrinks. This removes distance shimmer
      // and coloured stipple without blurring the source maps themselves.
      float groundLowPass=smoothstep(5.,38.,groundDistance);
      float rockLowPass=smoothstep(9.,42.,groundDistance);
      vec3 uvRock=vLandPosition/${NATURAL_SURFACE_METRES.rock.toFixed(4)};
      vec3 uvPaintedRock=vLandPosition/${NATURAL_SURFACE_METRES.paintedRock.toFixed(4)};
      vec3 grassFine=texture2D(grass_albedo,uvGrass).rgb;
      vec3 grassBroad=texture2D(grass_albedo,antiTileUV(vLandPosition.xz/12.0,29.2)).rgb;
      float grassLuma=dot(grassFine,vec3(.2126,.7152,.0722)),broadGrassLuma=dot(grassBroad,vec3(.2126,.7152,.0722));
      float grassBroadMix=mix(.38,.72,groundLowPass);
      vec3 gc=mix(grassFine,grassBroad,grassBroadMix)*grassTint*(.9+macro*.18);
      float patches=landNoise(vLandPosition.xz*.19+vec2(macro*3.));
      vec3 dirtFine=texture2D(dirt_albedo,uvDirt).rgb;
      vec3 dirtBroad=texture2D(dirt_albedo,antiTileUV(vLandPosition.xz/13.5,41.3)).rgb;
      float dirtBroadMix=mix(.42,.76,groundLowPass);
      vec3 dirtBase=mix(dirtFine,dirtBroad,dirtBroadMix);
      float fineSoil=dot(dirtBase,vec3(.2126,.7152,.0722));
      vec3 earth=dirtBase*vec3(.48,.40,.27);
      gc=mix(gc,earth,smoothstep(.53,.78,patches)*.58);
      gc*=.91+broadGrassLuma*.18;
      float grains=fineSoil;
      // Preserve the photograph's colour variation. The former scalar-luma
      // tint reduced every sand/lowland texel to one flat pastel colour.
      vec3 sc=dirtBase*mix(vec3(1.),sandTint*2.0,.68);
      vec3 alienLowland=texture2D(moss_albedo,antiTileUV(vLandPosition.xz/${NATURAL_SURFACE_METRES.moss.toFixed(4)},47.9)).rgb*vec3(.48,.64,.62);
      sc=mix(sc,alienLowland,alienSurface*.72);
      vec3 rc=triSample(rock_albedo,uvRock,tw,53.1);rc=mix(vec3(dot(rc,vec3(.2126,.7152,.0722))),rc,.18)*vec3(.88,.94,1.0);
      vec2 rockTurn=rotateSurface(vLandPosition.xz,.67);
      vec3 rockBroadPosition=vec3(rockTurn.x,vLandPosition.y,rockTurn.y)/16.0;
      rc=mix(rc,triSample(rock_albedo,rockBroadPosition,tw,67.4),.64);
      // Painted rock can cover horizontal treads and vertical risers. Project
      // by face orientation so a tread's X/Z scan is not stretched into long
      // stripes when the same surface turns down a stair or cliff face.
      vec3 paintedRc=triPhotoSample(paintedRock_albedo,uvPaintedRock,tw,79.6);
      paintedRc=mix(paintedRc,triSample(paintedRock_albedo,vLandPosition/14.0,tw,83.2),.30);
      // At viewing distance the photographed block boundaries can combine
      // across adjacent triplanar faces into a faint checkerboard. Preserve
      // the close cracks, but let continuous world-space stone variation
      // carry the silhouette once individual scan features are sub-pixel.
      float rockMacroTone=triBroadNoise(vLandPosition*.055,tw,91.7);
      vec3 naturalRockFar=vec3(.35,.37,.40)*(.86+rockMacroTone*.27);
      vec3 paintedRockFar=vec3(.36,.37,.38)*(.86+rockMacroTone*.25);
      rc=mix(rc,naturalRockFar,rockLowPass*.46);
      paintedRc=mix(paintedRc,paintedRockFar,rockLowPass*.42);
      // The photographed cliff already contains real bedding, cracks and
      // erosion.  Keep only a broad tonal drift here: the old narrow noise
      // contours embossed rounded maze-like grooves across every cliff face.
      float erosion=landNoise(vLandPosition.xz*.24+vec2(vLandPosition.y*.045));
      rc*=.90+erosion*.18;
      float relief=((erosion-.5)*.035)*naturalRock+((broadGrassLuma-.5)*.075+patches*.03+(fineSoil-.5)*.018)*gw+(fineSoil-.5)*.015*sw;
      // Every painted family now derives its detail from Poly Haven scans.
      float rockyGrain=dot(rc,vec3(.2126,.7152,.0722));
      vec3 dirtScan=dirtBase;
      vec3 snowScan=texture2D(snow_albedo,antiTileUV(vLandPosition.xz/${NATURAL_SURFACE_METRES.snow.toFixed(4)},97.1)).rgb;
      vec3 mossScan=texture2D(moss_albedo,antiTileUV(vLandPosition.xz/${NATURAL_SURFACE_METRES.moss.toFixed(4)},101.8)).rgb;
      vec3 gravelFine=photoSample(paintedRock_albedo,vLandPosition.xz/${NATURAL_SURFACE_METRES.gravel.toFixed(4)},109.3);
      vec3 gravelBroad=texture2D(paintedRock_albedo,antiTileUV(rotateSurface(vLandPosition.xz,.71)/13.0,113.7)).rgb;
      vec3 gravelScan=mix(gravelFine,gravelBroad,.58);
      vec3 grassScan=mix(grassFine,grassBroad,grassBroadMix);
      float snowGrain=dot(snowScan,vec3(.2126,.7152,.0722));
      float mossGrain=dot(mossScan,vec3(.2126,.7152,.0722));
      float gravelGrain=dot(gravelScan,vec3(.2126,.7152,.0722));
      float grassGrain=dot(grassScan,vec3(.2126,.7152,.0722));
      vec3 clay=dirtScan*vec3(1.18,.52,.30)*(.82+grains*.3);
      vec3 snowColor=snowScan*vec3(.91,.97,1.08);
      vec3 basalt=vec3(.025,.029,.035)+rc*.16+vec3(rockyGrain)*.12;
      vec3 mossColor=mossScan*vec3(.52,.79,.28);
      vec3 gravelColor=gravelScan*.88;
      vec3 ash=vec3(.11,.115,.13)+vec3(rockyGrain)*.34;
      // Alien ground keeps its teal identity, but the photographed stones must
      // remain legible instead of collapsing into the former flat cell colour.
      vec3 alien=mix(gravelScan,gravelScan*vec3(.20,.72,.68)+vec3(.018,.075,.095),.48);
      vec3 enchanted=vec3(.12,.025,.18)+mossScan*vec3(.62,.25,.74)+vec3(mossGrain)*vec3(.08,.01,.10);
      vec3 extras=clay*extraGround0.x+snowColor*extraGround0.y+basalt*extraGround0.z+mossColor*extraGround0.w
        +gravelColor*extraGround1.x+ash*extraGround1.y+alien*extraGround1.z+enchanted*extraGround1.w;
      relief+=(fineSoil-.5)*.018*dw;
      relief+=(gravelGrain-.5)*.018*paintedRockWeight;
      relief+=nearSoil*((grassLuma-.5)*.008+(fineSoil-.5)*.006)*(gw+dw+sw*.35);
      relief+=(grains-.5)*.045*extraGround0.x+(snowGrain-.5)*.025*extraGround0.y
        +(rockyGrain-.5)*.10*extraGround0.z+(mossGrain-.5)*.055*extraGround0.w
        +(gravelGrain-.5)*.04*extraGround1.x+(rockyGrain-.5)*.035*extraGround1.y
        +(gravelGrain-.5)*.07*extraGround1.z+(mossGrain-.5)*.045*extraGround1.w;
      float wet=1.0-smoothstep(-.3,1.1,vLandPosition.y);
      vec3 dc=texture2D(dirt_albedo,uvDirt).rgb*vec3(.62,.49,.35);
      // Ground receives direct sun, hemisphere fill and reflected sky. Keep
      // scanned albedo in a terrestrial range so that combination cannot turn
      // the terrain into a pale self-lit sheet under stylized environments.
      diffuseColor.rgb=(gc*gw+sc*sw+rc*naturalRock+paintedRc*paintedRockWeight+dc*dw+extras)*(1.0-wet*.32)*.62*terrainTone;
      sw+=dw;`);
    shader.fragmentShader=shader.fragmentShader.replace('#include <roughnessmap_fragment>',`#include <roughnessmap_fragment>
      float extraRough=texture2D(dirt_rough,uvDirt).r*extraGround0.x+.92*extraGround0.y
        +triSample(rock_rough,uvRock,tw,53.1).r*extraGround0.z+texture2D(grass_rough,uvGrass).r*extraGround0.w
        +photoSample(rock_rough,vLandPosition.xz/${NATURAL_SURFACE_METRES.gravel.toFixed(4)},109.3).r*extraGround1.x+triSample(rock_rough,uvRock,tw,53.1).r*extraGround1.y
        +photoSample(rock_rough,vLandPosition.xz/${NATURAL_SURFACE_METRES.gravel.toFixed(4)},109.3).r*extraGround1.z+texture2D(grass_rough,uvGrass).r*extraGround1.w;
      roughnessFactor=clamp(texture2D(grass_rough,uvGrass).r*gw+texture2D(dirt_rough,uvDirt).r*sw+triSample(rock_rough,uvRock,tw,53.1).r*naturalRock+triPhotoSample(rock_rough,uvPaintedRock,tw,79.6).r*paintedRockWeight+extraRough,.55,1.0);
      roughnessFactor=mix(roughnessFactor,.88,rockLowPass*clamp(naturalRock+paintedRockWeight,0.,1.)*.34);
      roughnessFactor=mix(roughnessFactor,.42,wet*.65);`);
    shader.fragmentShader=shader.fragmentShader.replace('#include <normal_fragment_maps>',`#include <normal_fragment_maps>
      vec2 gd=texture2D(grass_normal,uvGrass).xy*2.0-1.0,sd=texture2D(dirt_normal,uvDirt).xy*2.0-1.0;
      vec2 snd=sd*.28,md=gd;
      float earthMix=smoothstep(.53,.78,patches)*.58;
      vec3 paintedDetail=triPhotoDetail(paintedRock_normal,uvPaintedRock,tw,79.6);
      float rockDetailDistance=mix(1.,.55,rockLowPass);
      vec3 detail=vec3(mix(gd,sd,earthMix).x,0,mix(gd,sd,earthMix).y)*gw*.38+vec3(sd.x,0,sd.y)*sw*.16+triDetail(rock_normal,uvRock,tw,53.1)*naturalRock*.8*rockDetailDistance+paintedDetail*paintedRockWeight*.62*rockDetailDistance;
      detail+=vec3(sd.x,0,sd.y)*extraGround0.x*.34+vec3(snd.x,0,snd.y)*extraGround0.y*.26+triDetail(rock_normal,uvRock,tw,53.1)*(extraGround0.z*.72+extraGround1.y*.34)
        +vec3(md.x,0,md.y)*(extraGround0.w*.46+extraGround1.w*.38)+paintedDetail*(extraGround1.x*.58+extraGround1.z*.48);
      detail-=landN*dot(detail,landN);
      normal=normalize(mat3(viewMatrix)*normalize(landN+detail));`);
    shader.fragmentShader=shader.fragmentShader.replace('#include <lights_physical_fragment>',`vec3 reliefX=dFdx(-vViewPosition),reliefY=dFdy(-vViewPosition);
      vec3 reliefRX=cross(reliefY,normal),reliefRY=cross(normal,reliefX);
      float reliefDet=dot(reliefX,reliefRX);
      normal=normalize(max(abs(reliefDet),1e-8)*normal-sign(reliefDet)*(dFdx(relief)*reliefRX+dFdy(relief)*reliefRY));
      #include <lights_physical_fragment>`);
  };
  terrain.customProgramCacheKey=()=> 'jnsq-natural-terrain-surfaces-v23';
  function prop(kind,scale){const t=textures[kind];return new THREE.MeshStandardMaterial({map:t.albedo,normalMap:t.normal,roughnessMap:t.rough,roughness:1,normalScale:new THREE.Vector2(scale,scale)});}
  function setStyle(style){
    grassTint.value.set(...({meadow:[.66,1.05,.72],highland:[.74,.96,.78],craggy:[.82,.95,.77],tropical:[.58,1.13,.72],woodland:[.71,.96,.54],desert:[1.55,1.02,.45],savanna:[1.3,1.13,.48],rainforest:[.43,.90,.58],enchanted:[.57,.87,.93],alien:[.32,.48,.40],fungi:[.85,.69,.94]}[style]||[.74,.96,.78]));
    sandTint.value.set(...({tropical:[.78,.70,.49],alien:[.20,.27,.27],enchanted:[.43,.31,.46],fungi:[.38,.38,.29]}[style]||[.61,.52,.35]));
    terrainTone.value=({alien:.55,enchanted:.68,fungi:.72})[style]||1;
    alienSurface.value=style==='alien'?1:0;
  }
  return {terrain,rock:prop('rock',.55),bark:prop('tree_bark',.6),setStyle,setSpace:enabled=>{spaceMode.value=enabled?1:0;}};
}
