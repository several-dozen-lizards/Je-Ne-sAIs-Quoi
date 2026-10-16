// Bounded front-to-back cloud integration, shared by sky, reflections and the lower cloud sea.
export const cloudVolumeGLSL=`
// A uniform bound keeps ANGLE from expanding the full density integration at
// every call site. The sample count and cloud shape are unchanged.
uniform int cloudMarchSteps;
float volumeHash(vec3 p){p=fract(p*.1031);p+=dot(p,p.yzx+33.33);return fract((p.x+p.y)*p.z);}
float volumeNoise(vec3 p){
  vec3 i=floor(p),f=fract(p);f=f*f*f*(f*(f*6.-15.)+10.);
  return mix(mix(mix(volumeHash(i),volumeHash(i+vec3(1,0,0)),f.x),mix(volumeHash(i+vec3(0,1,0)),volumeHash(i+vec3(1,1,0)),f.x),f.y),mix(mix(volumeHash(i+vec3(0,0,1)),volumeHash(i+vec3(1,0,1)),f.x),mix(volumeHash(i+vec3(0,1,1)),volumeHash(i+vec3(1,1,1)),f.x),f.y),f.z);
}
float billowDensity(vec3 position,float base,float thickness,float deck){
  float h=(position.y-base)/thickness;
  if(h<=0.||h>=1.)return 0.;
  vec3 drift=vec3(solarTime*.001,0.,solarTime*.0004);
  vec3 p=position*.010+drift;
  // Turn the sampling lattice away from the world axes. Larger coherent
  // masses carry the silhouette; a weaker octave only softens their edges.
  mat3 turn=mat3(.00,.80,.60,-.80,.36,-.48,-.60,-.48,.64);
  vec3 q=turn*p;
  float broad=volumeNoise(q),detail=volumeNoise(turn*q*2.03+19.);
  // The lower bank is a broken field, not uniform overcast. Large clearings
  // separate smaller rounded cells; detail erodes their edges in three dimensions.
  float field=volumeNoise(vec3(p.x*.32,7.,p.z*.32));
  float coverage=smoothstep(.72-cloudCover*.58,.90-cloudCover*.58,field);
  if(deck>.5){
    coverage=smoothstep(.32,.65,field);
  }
  // Rounded lobes rise above a denser, flatter condensation base.
  float envelope=smoothstep(0.,.16,h)*(1.-smoothstep(.40,1.,h));
  float mass=broad*.72+detail*.28+coverage*.24+(0.5-h)*.12;
  return smoothstep(mix(.50,.54,deck),mix(.78,.81,deck),mass)*envelope*mix(.65,1.35,stormAmount)*smoothstep(.12,.55,coverage);
}
vec4 billowClouds(vec3 origin,vec3 ray,float base,float thickness,float deck){
  if(abs(ray.y)<.001||(deck<.5&&cloudCover<.01))return vec4(0.);
  float a=(base-origin.y)/ray.y,b=(base+thickness-origin.y)/ray.y;
  float start=max(0.,min(a,b)),end=min(max(a,b),start+1800.);
  if(end<=start)return vec4(0.);
  float stride=(end-start)/float(cloudMarchSteps),transmission=1.;vec3 colour=vec3(0.);
  float jitter=volumeHash(vec3(gl_FragCoord.xy,13.));
  vec3 sun=normalize(sunDirection);
  float forward=pow(max(dot(ray,sun),0.),8.);
  for(int i=0;i<cloudMarchSteps;i++){
    vec3 p=origin+ray*(start+(float(i)+jitter)*stride);
    float density=billowDensity(p,base,thickness,deck);
    if(density>.005){
      float shadow=billowDensity(p+sun*12.,base,thickness,deck)*16.+billowDensity(p+sun*30.,base,thickness,deck)*28.+billowDensity(p+sun*65.,base,thickness,deck)*40.;
      float sunlit=exp(-shadow*.065);
      float height=clamp((p.y-base)/thickness,0.,1.);
      vec3 ambient=mix(vec3(.015,.021,.044),mix(vec3(.19,.24,.31),vec3(.48,.55,.63),height),dayAmount);
      ambient*=mix(1.,.62,deck);
      vec3 direct=mix(vec3(.055,.065,.10),solarColour*(.82+forward*.65),dayAmount);
      vec3 light=ambient*(1.-stormAmount*.26)+direct*sunlit;
      float alpha=1.-exp(-density*stride*mix(.035,.065,deck));
      colour+=transmission*alpha*light;transmission*=1.-alpha;
      if(transmission<.015)break;
    }
  }
  float horizon=1.-smoothstep(1000.,6000.,start);
  return vec4(colour,1.-transmission)*horizon;
}
`;
