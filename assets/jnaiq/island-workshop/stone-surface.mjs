// Project grain from three directions to avoid stretched stone UVs.
// Wrap existing hooks so material effects and scene lighting can coexist.
export function weatherStone(material,{neutralColor=false}={}){
  const previous=material.onBeforeCompile,cache=material.customProgramCacheKey();
  material.onBeforeCompile=function(shader,renderer){
    previous.call(this,shader,renderer);
    shader.vertexShader=shader.vertexShader.replace('#include <common>',`#include <common>
      varying vec3 stoneP;varying vec3 stoneN;`);
    shader.vertexShader=shader.vertexShader.replace('#include <begin_vertex>',`#include <begin_vertex>
      stoneP=position;stoneN=normal;`);
    shader.fragmentShader=shader.fragmentShader.replace('#include <common>',`#include <common>
      varying vec3 stoneP;varying vec3 stoneN;
      vec3 stoneSample(sampler2D tex,vec3 p,vec3 w){return texture2D(tex,p.yz).rgb*w.x+texture2D(tex,p.xz).rgb*w.y+texture2D(tex,p.xy).rgb*w.z;}
      // Derivative frames follow each projection through instance rotations and
      // nonuniform scaling. A flat normal map leaves the smooth mesh normal intact.
      vec3 stoneNormal(sampler2D tex,vec2 strength,vec2 uv,vec3 base){
        vec3 q0=dFdx(-vViewPosition),q1=dFdy(-vViewPosition);
        vec2 st0=dFdx(uv),st1=dFdy(uv);
        vec3 r1=cross(q1,base),r0=cross(base,q0);
        vec3 t=r1*st0.x+r0*st1.x,b=r1*st0.y+r0*st1.y;
        float inv=inversesqrt(max(max(dot(t,t),dot(b,b)),1e-10));
        vec3 detail=texture2D(tex,uv).xyz*2.-1.;detail.xy*=strength;
        return normalize(base*max(detail.z,.1)+(t*detail.x+b*detail.y)*inv);
      }`);
    shader.fragmentShader=shader.fragmentShader.replace('#include <map_fragment>',`
      vec3 stoneW=pow(abs(normalize(stoneN)),vec3(4.));stoneW/=max(dot(stoneW,vec3(1.)),.0001);
      // Spend the former second albedo projection on actual normal-map relief.
      vec3 stoneColor=stoneSample(map,stoneP*.42,stoneW);
      ${neutralColor?'stoneColor=vec3(.48+dot(stoneColor,vec3(.2126,.7152,.0722))*.7);':''}
      float stoneLayer=sin(stoneP.y*5.+sin(stoneP.x*1.7)+sin(stoneP.z*1.3));
      diffuseColor.rgb*=stoneColor*(.94+stoneLayer*.06);`);
    shader.fragmentShader=shader.fragmentShader.replace('#include <roughnessmap_fragment>',`
      float stoneGrain=stoneSample(roughnessMap,stoneP*.42,stoneW).g;
      float roughnessFactor=roughness*clamp(stoneGrain,.65,1.);`);
    shader.fragmentShader=shader.fragmentShader.replace('#include <normal_fragment_maps>',`
      vec3 stoneBase=normal;
      #ifdef USE_NORMALMAP
      normal=normalize(stoneNormal(normalMap,normalScale,stoneP.yz*.42,stoneBase)*stoneW.x+stoneNormal(normalMap,normalScale,stoneP.xz*.42,stoneBase)*stoneW.y+stoneNormal(normalMap,normalScale,stoneP.xy*.42,stoneBase)*stoneW.z);
      #endif
      float stoneHeight=dot(stoneColor,vec3(.2126,.7152,.0722))*.06+stoneGrain*.055+stoneLayer*.012;
      vec3 stoneX=dFdx(-vViewPosition),stoneY=dFdy(-vViewPosition);
      vec3 stoneRX=cross(stoneY,normal),stoneRY=cross(normal,stoneX);
      float stoneDet=dot(stoneX,stoneRX);
      normal=normalize(max(abs(stoneDet),1e-8)*normal-sign(stoneDet)*(dFdx(stoneHeight)*stoneRX+dFdy(stoneHeight)*stoneRY));`);
  };
  material.customProgramCacheKey=()=>cache+'-weathered-stone-v2'+(neutralColor?'-neutral':'');
}
