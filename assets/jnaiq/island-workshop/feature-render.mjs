import * as THREE from './vendor/three.module.js';
import {iceMaterial} from './ice.mjs';
import {heightAt} from './terrain.mjs?caves=retired';
import {pondMaterial,pondMesh} from './pond-render.mjs?caves=retired';

export function createLandscapeFeatures(scene){
  const group=new THREE.Group();scene.add(group);
  const time={value:0};
  const stillWater=pondMaterial(time);
  const fluidNoise=`
    float waterHash(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453);}
    float waterNoise(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*(3.-2.*f);return mix(mix(waterHash(i),waterHash(i+vec2(1,0)),f.x),mix(waterHash(i+vec2(0,1)),waterHash(i+vec2(1)),f.x),f.y);}
    float waterFbm(vec2 p){return waterNoise(p)*.57+waterNoise(p*2.03+17.)*.28+waterNoise(p*4.11-8.)*.15;}
  `;
  function material(river){
    const m=new THREE.MeshStandardMaterial({color:river?0x244b43:0x8d7753,roughness:river?.24:.97,metalness:river?.035:0,side:THREE.DoubleSide,transparent:true,opacity:1,depthWrite:!river,polygonOffset:true,polygonOffsetFactor:-1});
    m.onBeforeCompile=s=>{
      s.uniforms.featureTime=time;
      s.vertexShader='attribute vec3 waterData;varying vec3 riverData;varying vec2 routeUV;varying float routeSlope;\n'+s.vertexShader;
      s.vertexShader=s.vertexShader.replace('#include <begin_vertex>','#include <begin_vertex>\nrouteUV=uv;riverData=waterData;routeSlope=1.-abs(normal.y);');
      s.fragmentShader='varying vec3 riverData;varying vec2 routeUV;varying float routeSlope;uniform float featureTime;\n'+fluidNoise+s.fragmentShader;
      s.fragmentShader=s.fragmentShader.replace('#include <color_fragment>',`#include <color_fragment>
        float grain=fract(sin(dot(floor(routeUV*vec2(60.,30.)),vec2(12.9898,78.233)))*43758.5453);
        diffuseColor.a*=smoothstep(0.,.12,routeUV.x)*smoothstep(0.,.12,1.-routeUV.x);
        ${river?`float falling=smoothstep(.08,.55,routeSlope);
          vec2 metres=vec2(routeUV.x*riverData.y,routeUV.y);
          vec2 flow=metres-vec2(0.,featureTime*1.3);
          float eddy=waterFbm(flow*vec2(1.4,.55));
          vec2 warped=flow+vec2(eddy-.5,waterNoise(flow*.4)-.5)*.75;
          float ripples=waterFbm(warped*vec2(2.8,4.2));
          float filaments=waterFbm(vec2(metres.x*9.+eddy*2.,metres.y*.48-featureTime*3.4));
          float broken=waterFbm(vec2(metres.x*3.,metres.y*1.6-featureTime*5.));
          float foam=falling*(.30+.70*smoothstep(.28,.65,filaments))*(.65+.35*broken);
          float bank=1.-smoothstep(.04,.22,min(routeUV.x,1.-routeUV.x));
          foam=max(foam,bank*smoothstep(.58,.76,eddy)*.6);
          float depth=max(0.,riverData.x);
          vec3 body=mix(vec3(.12,.19,.12),vec3(.025,.085,.082),1.-exp(-depth*.85));
          diffuseColor.rgb=mix(body*(.88+eddy*.24),vec3(.70,.79,.75),foam);
          float edgeNoise=waterNoise(flow*vec2(4.,1.2));
          diffuseColor.a*=smoothstep(0.,.16,depth)*(.70+.25*(1.-exp(-depth))+falling*.05);
          diffuseColor.a*=smoothstep(.005,.055+edgeNoise*.045,min(routeUV.x,1.-routeUV.x));
          diffuseColor.a*=smoothstep(0.,1.,riverData.z);
          float waveHeight=(ripples-.5)*.065*(1.-falling*.7);`
          :`vec2 ground=vec2(routeUV.x*riverData.y,routeUV.y);
            float broad=waterFbm(ground*.65),fine=waterNoise(ground*15.);
            float edge=min(routeUV.x,1.-routeUV.x);
            diffuseColor.a*=smoothstep(.01,.11+waterNoise(ground*1.8)*.13,edge)*riverData.z;
            float tracks=exp(-pow((routeUV.x-.29)*15.,2.))+exp(-pow((routeUV.x-.71)*15.,2.));
            vec3 soil=mix(vec3(.19,.125,.065),vec3(.40,.31,.19),broad);
            float pebbles=smoothstep(.79,.9,fine)*waterNoise(ground*4.);
            diffuseColor.rgb=soil*(.93-tracks*.12+grain*.12)+pebbles*.11;
            float waveHeight=broad*.035+fine*.008-tracks*.012;`}
      `);
      {
        s.fragmentShader=s.fragmentShader.replace('#include <normal_fragment_maps>',`#include <normal_fragment_maps>
          vec3 dx=dFdx(vViewPosition),dy=dFdy(vViewPosition),rx=cross(dy,normal),ry=cross(normal,dx);
          float det=dot(dx,rx);vec3 grad=sign(det)*(dFdx(waveHeight)*rx+dFdy(waveHeight)*ry);
          normal=normalize(abs(det)*normal-grad);
        `);
        if(river)s.fragmentShader=s.fragmentShader.replace('#include <roughnessmap_fragment>','#include <roughnessmap_fragment>\nroughnessFactor=mix(.19,.62,foam);');
      }
    };
    m.customProgramCacheKey=()=>river?'jnsq-river-v2':'jnsq-road-v3';
    return m;
  }
  const water=material(true),road=material(false);
  const ice=iceMaterial(),pondIce=iceMaterial(true);
  const foamMaterial=new THREE.MeshStandardMaterial({color:0xb8cbc3,roughness:.85,transparent:true,opacity:.65,depthWrite:false,side:THREE.DoubleSide});
  foamMaterial.onBeforeCompile=s=>{
    s.uniforms.featureTime=time;s.vertexShader='varying vec2 foamUV;\n'+s.vertexShader;s.vertexShader=s.vertexShader.replace('#include <begin_vertex>','#include <begin_vertex>\nfoamUV=uv*2.-1.;');
    s.fragmentShader='varying vec2 foamUV;uniform float featureTime;\n'+fluidNoise+s.fragmentShader;
    s.fragmentShader=s.fragmentShader.replace('#include <color_fragment>',`#include <color_fragment>
      float r=length(foamUV);float churn=waterFbm(foamUV*5.+vec2(featureTime*.12,-featureTime*.25));
      float froth=smoothstep(.38,.65,churn);
      diffuseColor.a*=(1.-smoothstep(.24,1.,r))*froth;
      diffuseColor.rgb*=.8+.2*churn;
    `);
  };
  foamMaterial.customProgramCacheKey=()=> 'jnsq-impact-foam-v1';
  return {
    rebuild(w){
      for(const child of [...group.children]){child.geometry.dispose();group.remove(child);}
      for(const f of w.features||[]){
        if(f.kind==='pond'){group.add(pondMesh(w,f,w.frozenWater?pondIce:stillWater));continue;}
        const river=f.kind==='river',points=[];
        for(let i=1;i<f.points.length;i++){
          const a=f.points[i-1],b=f.points[i],steps=Math.max(1,Math.ceil(Math.hypot(b.x-a.x,b.z-a.z)/.7));
          for(let j=0;j<steps;j++){const t=j/steps;points.push({x:a.x+(b.x-a.x)*t,y:a.y+(b.y-a.y)*t,z:a.z+(b.z-a.z)*t});}
        }
        points.push(f.points.at(-1));
        const p=[],uv=[],data=[],index=[];let distance=0;const across=12;
        const routeLength=points.reduce((sum,v,i)=>i?sum+Math.hypot(v.x-points[i-1].x,v.y-points[i-1].y,v.z-points[i-1].z):0,0);
        for(let i=0;i<points.length;i++){
          const a=points[Math.max(0,i-1)],b=points[Math.min(points.length-1,i+1)],v=points[i],length=Math.hypot(b.x-a.x,b.z-a.z)||1;
          if(i)distance+=Math.hypot(v.x-a.x,v.z-a.z,v.y-a.y);
          for(let j=0;j<=across;j++){
            const offset=(j/across-.5)*f.width,x=v.x-(b.z-a.z)/length*offset,z=v.z+(b.x-a.x)/length*offset;
            p.push(x,river?v.y+.045:heightAt(w,x,z)+.08,z);uv.push(j/across,distance);data.push(Math.max(0,v.y-heightAt(w,x,z)),f.width,Math.max(0,Math.min(1,distance/(f.width*.35),(routeLength-distance)/(f.width*.65))));
          }
          if(i)for(let j=0;j<across;j++){const k=i*(across+1)+j,q=k-across-1;index.push(q,k,q+1,q+1,k,k+1);}
        }
        const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.Float32BufferAttribute(p,3));geometry.setAttribute('uv',new THREE.Float32BufferAttribute(uv,2));geometry.setAttribute('waterData',new THREE.Float32BufferAttribute(data,3));geometry.setIndex(index);geometry.computeVertexNormals();
        const mesh=new THREE.Mesh(geometry,river?(w.frozenWater?ice:water):road);mesh.receiveShadow=true;mesh.renderOrder=river?3:0;group.add(mesh);
        if(river&&!w.frozenWater){
          let previousImpact=-Infinity;
          for(let i=1;i<points.length;i++){
            const a=points[Math.max(0,i-4)],v=points[i],next=points[Math.min(i+2,points.length-1)];
            const drop=a.y-v.y,run=Math.hypot(v.x-a.x,v.z-a.z),slope=drop/Math.max(.1,run),after=(v.y-next.y)/Math.max(.1,Math.hypot(v.x-next.x,v.z-next.z));
            const mouth=i===points.length-1&&v.y<.3;
            if(!mouth&&!(drop>.5&&slope>.3&&after<slope*.4))continue;
            if(i-previousImpact<6&&!mouth)continue;previousImpact=i;
            const patch=new THREE.Mesh(new THREE.PlaneGeometry(1,1),foamMaterial);patch.rotation.x=-Math.PI/2;
            patch.scale.set(f.width*(mouth?1.65:1.),f.width*(mouth?1.45:.85),1);patch.position.set(v.x,v.y+.075,v.z);patch.renderOrder=4;patch.receiveShadow=true;group.add(patch);
          }
        }
      }
    },update(seconds){time.value=seconds;}
  };
}
