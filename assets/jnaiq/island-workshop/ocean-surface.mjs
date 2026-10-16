// Wind-aligned wave slopes, depth absorption and a filtered sun reflection.
// Surface motion uses the same pausable clock as the rest of the atmosphere.
export const oceanSurfaceGLSL=`
uniform sampler2D reflectedSky;
uniform float reflectedSkyReady;
vec3 reflectedSkyColour(vec3 ray){
  vec2 uv=vec2(fract(.5+atan(ray.z,ray.x)/6.2831853),.5+asin(clamp(ray.y,-1.,1.))/3.14159265);
  // Reuse the sky radiance capture. Recompiling the entire volumetric sky for
  // each water/ice/haze lookup stalls the D3D shader compiler on first entry.
  if(reflectedSkyReady>.5)return texture2D(reflectedSky,uv).rgb;
  if(customSkyAmount>.5){uv.x=fract(uv.x+customSkyRotation/6.2831853);uv.y=1.-uv.y;return texture2D(customSky,uv).rgb*customSkyBrightness;}
  return fogColour;
}
uniform vec3 waterTint;
uniform float waterGlow,waterRipples;
void oceanWave(inout vec2 slope,inout float crest,vec2 p,vec2 direction,float wavelength,float amplitude,float phase,float footprint,float seconds){
  float k=6.2831853/wavelength;
  float theta=dot(p,direction)*k-sqrt(9.81*k)*seconds+phase;
  // Slowly varying wave packets keep a shared wind direction without making
  // the entire ocean repeat as uninterrupted parallel stripes.
  theta+=(noise21(p/wavelength*.8+direction*phase*7.)-.5)*5.;
  amplitude*=.65+.7*noise21(p/wavelength*.35+phase*11.);
  float filtered=exp(-pow(footprint*k*.6,2.));
  slope+=direction*cos(theta)*amplitude*k*filtered;
  crest+=sin(theta)*amplitude*filtered;
}
void main(){
  vec2 p=waterPosition.xz,uv=(p/islandSize+.5)*128./129.+.5/129.;
  vec2 packed=texture2D(terrainHeight,uv).rg;
  float ground=dot(packed,vec2(256.,1.))*255./65535.*77.-12.;
  float beyond=max(0.,max(abs(p.x),abs(p.y))-islandSize*.5);
  if(beyond>0.)ground=-3.-beyond*.12;
  float depth=max(0.,-.04-ground);
  float footprint=max(length(dFdx(p)),length(dFdy(p)));
  if(lavaOcean>.5){
    // Advected crust plates expose molten seams; emissions remain visible
    // at night and in the cavern, independent of direct sunlight.
    vec2 drift=p*.075+vec2(time*.010,-time*.006);
    drift+=vec2(noise21(drift*.65),noise21(drift*.65+29.))*.8;
    vec2 cell=floor(drift),local=fract(drift);float first=10.,second=10.;
    for(int x=-1;x<=1;x++)for(int y=-1;y<=1;y++){
      vec2 offset=vec2(float(x),float(y)),key=cell+offset;
      vec2 centre=offset+vec2(hash21(key),hash21(key+17.));
      float d=length(centre-local);
      if(d<first){second=first;first=d;}else second=min(second,d);
    }
    float fissure=second-first,filterWidth=max(.015,footprint*.025);
    float molten=1.-smoothstep(.045-filterWidth,.14+filterWidth,fissure);
    float grain=cloudNoise(p*.8),heat=noise21(drift*.6+time*.012);
    vec3 crust=mix(vec3(.018,.009,.008),vec3(.075,.029,.014),grain);
    vec3 glow=mix(vec3(1.7,.095,.005),vec3(3.2,.95,.075),heat);
    vec3 lava=mix(crust,glow,molten);
    lava+=vec3(.19,.028,.003)*exp(-fissure*8.);
    float distanceHaze=1.-exp(-length(cameraPosition.xz-p)*.0005);
    lava=mix(lava,vec3(.12,.025,.009),distanceHaze*.65);
    gl_FragColor=vec4(lava,1.);
    #include <tonemapping_fragment>
    #include <colorspace_fragment>
    return;
  }
  float wind=mix(1.,2.2,stormAmount);
  vec2 slope=vec2(0.);float crest=0.;
  oceanWave(slope,crest,p,vec2(.80,.60),32.,.30,0.,footprint,time);
  oceanWave(slope,crest,p,vec2(.96,.28),17.,.16,2.4,footprint,time);
  oceanWave(slope,crest,p,vec2(.52,.85),8.2,.095,5.1,footprint,time);
  oceanWave(slope,crest,p,vec2(-.30,.954),3.7,.045,1.2,footprint,time);
  oceanWave(slope,crest,p,vec2(.87,-.493),1.8,.020,3.7,footprint,time);
  oceanWave(slope,crest,p,vec2(.71,.704),.73,.008,4.3,footprint,time);
  // Long swells attenuate into the shallows; small surface ripples remain.
  slope*=wind*waterRipples*mix(.45,1.,smoothstep(0.,2.,depth));
  if(fantasyMode>2.5)slope*=.28;
  vec3 normal=normalize(vec3(-slope.x,1.,-slope.y));
  vec3 view=normalize(cameraPosition-waterPosition),sun=normalize(sunDirection);
  float nv=max(dot(view,normal),.001);
  float fresnel=.0204+.9796*pow(1.-nv,5.);
  vec3 deep=mix(vec3(.001,.006,.012),waterTint,.24),shallow=mix(vec3(.025,.055,.045),waterTint,.82);
  vec3 transmission=exp(-vec3(.42,.14,.075)*depth);
  vec3 body=mix(deep,shallow,transmission)*(.08+.92*dayAmount);
  body*=solarSkyBrightness;
  body+=waterTint*waterGlow*(.035+.10*(1.-exp(-depth*.45)));
  if(fantasyMode>2.5){
    body=mix(vec3(.002,.009,.012),vec3(.012,.035,.029),exp(-depth*.24));
    if(fantasyMode>3.5){
      float glow=cloudNoise(p*.09+vec2(time*.012,-time*.009));
      body+=vec3(.015,.24,.065)*(.55+glow*.65)*(1.-exp(-depth*.8));
    }
  }
  // Modest refracted light variation in clear, shallow water.
  float caustic=pow(max(0.,sin(dot(p,vec2(.9,.6))*2.1+crest*3.)*sin(dot(p,vec2(-.5,1.))*1.7-crest*2.)),5.);
  body+=vec3(.025,.055,.04)*caustic*exp(-depth*.65)*dayAmount/(1.+footprint*4.);
  vec3 reflection=reflectedSkyColour(reflect(-view,normal));
  vec3 colour=mix(body,reflection,fresnel);
  // GGX highlight broadens as waves become smaller than a pixel. This makes
  // the sun trail stable at distance instead of flickering individual pixels.
  vec3 halfVector=normalize(view+sun);
  float nh=max(dot(normal,halfVector),0.),nl=max(dot(normal,sun),0.);
  float roughness=clamp(.065+stormAmount*.065+sqrt(footprint)*.025,.065,.28);
  float a2=pow(roughness,4.);
  float denominator=nh*nh*(a2-1.)+1.;
  float distribution=a2/(3.14159265*denominator*denominator);
  float vh=max(dot(view,halfVector),0.);
  float specularF=.0204+.9796*pow(1.-vh,5.);
  float masking=nv/(nv*(1.-roughness)+roughness)*nl/(nl*(1.-roughness)+roughness);
  if(fantasyMode<2.5)colour+=solarColour*min(12.,distribution*specularF*masking/max(4.*nv,.08))*dayAmount*solarWeatherTransmission*solarTransmission(waterPosition);
  // Interrupted swash follows depth contours, breaking into patches as the
  // waves arrive. No permanent white outline around the island.
  float shore=1.-smoothstep(.18,1.8,depth);
  float wash=.5+.5*sin(depth*5.5-time*1.5+noise21(p*.16)*3.);
  float lace=cloudNoise(p*.85+vec2(time*.12,-time*.08));
  float foam=shore*smoothstep(.60,.90,wash)*smoothstep(.34,.65,lace);
  float whitecaps=stormAmount*smoothstep(.32,.52,crest)*smoothstep(.54,.73,lace)*smoothstep(1.,4.,depth);
  foam=max(foam,whitecaps*.65);
  if(fantasyMode>2.5)foam*=.08;
  colour=mix(colour,vec3(.67,.77,.78)*(.12+.88*dayAmount),foam*.88);
  vec3 horizon=reflectedSkyColour(normalize(vec3(-view.x,.002,-view.z)));
  float haze=1.-exp(-length(cameraPosition.xz-p)*(.00016+fogAmount*.009));
  colour=mix(colour,horizon,haze);
  float opacity=clamp(1.-exp(-depth*.85)+fresnel+foam,0.,1.);
  if(frozenWater>.5){
    float seams=abs(sin(p.x*.73+sin(p.y*.41)*2.)*sin(p.y*.91+p.x*.21));
    float crack=1.-smoothstep(.008,.034,seams);
    vec3 iceLight=reflectedSkyColour(reflect(-view,vec3(0,1,0)));
    colour=mix(vec3(.25,.43,.50)*(.25+.75*dayAmount),iceLight,.22)+vec3(.18,.23,.25)*crack;
    opacity=1.;
  }
  gl_FragColor=vec4(colour,opacity);
  #include <tonemapping_fragment>
  #include <colorspace_fragment>
}
`;
