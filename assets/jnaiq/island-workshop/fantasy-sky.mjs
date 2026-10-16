// Procedural surroundings only. The cavern is scenery, not editable collision
// geometry; none of the retired cave-building system is involved.
export const fantasySkyGLSL=`
uniform float fantasyMode;
uniform float cavernLightMode;
uniform sampler2D cavernRock;
float cavernRelief(vec3 p){
  vec3 q=p*vec3(.0025,.006,.0025);
  float folds=1.-abs(volumeNoise(q)*2.-1.);
  float ribs=pow(1.-abs(volumeNoise(q*2.1+9.)*2.-1.),3.);
  return folds*190.+ribs*100.+volumeNoise(q*8.7)*24.;
}
vec3 cavernSurroundings(vec3 origin,vec3 ray){
  vec3 radii=vec3(1600.,650.,1600.),centre=vec3(0.,-30.,0.);
  vec3 o=(origin-centre)/radii,d=ray/radii;
  float b=dot(o,d),a=dot(d,d),c=dot(o,o)-1.;
  float travel=(-b+sqrt(max(0.,b*b-a*c)))/a;
  vec3 p=origin+ray*max(travel,0.);
  // Intersect successive relief estimates so buttresses and recesses have
  // different distances, rather than shading a uniformly smooth enclosure.
  float shellTravel=travel;
  for(int step=0;step<4;step++){
    vec3 inward=-normalize((p-centre)/(radii*radii));
    float nextTravel=shellTravel-cavernRelief(p)/max(.3,dot(-ray,inward));
    travel=mix(travel,max(1.,nextTravel),.65);p=origin+ray*travel;
  }
  vec3 q=p*.004;
  float broad=volumeNoise(q),grain=volumeNoise(q*4.1+7.);
  float strata=volumeNoise(p*vec3(.012,.05,.012));
  vec3 normal=-normalize((p-centre)/(radii*radii));
  float relief=cavernRelief(p);
  vec3 rough=vec3(cavernRelief(p+vec3(3,0,0))-relief,cavernRelief(p+vec3(0,3,0))-relief,cavernRelief(p+vec3(0,0,3))-relief)/3.;
  normal=normalize(normal-rough*.6);
  vec3 lamp=vec3(-250.,260.,-150.);
  float lit=.12+.95*max(dot(normal,normalize(lamp-p)),0.);
  float crevice=smoothstep(.22,.8,broad)*.75+.25;
  float grit=volumeNoise(p*.19);
  float fissure=smoothstep(.16,.40,volumeNoise(p*.022));
  vec3 stone=mix(vec3(.105,.115,.12),vec3(.34,.29,.22),strata*.45+grain*.55)*lit*crevice;
  stone*=mix(.48,1.,fissure)*(.78+grit*.44);
  vec3 weights=pow(abs(normal),vec3(4.));weights/=max(.001,dot(weights,vec3(1.)));
  vec3 photographed=texture2D(cavernRock,p.yz*.028).rgb*weights.x+texture2D(cavernRock,p.xz*.028).rgb*weights.y+texture2D(cavernRock,p.xy*.028).rgb*weights.z;
  float detail=dot(photographed,vec3(.2126,.7152,.0722));
  stone*=.35+detail*3.2;
  float damp=exp(-abs(p.y)*.014);
  stone*=1.-damp*.25;
  vec3 lightTint=cavernLightMode>2.5?vec3(.60,.82,1.15):cavernLightMode>1.5?vec3(1.25,.83,.42):cavernLightMode>.5?vec3(.35,.75,.59):vec3(.65,.71,.76);
  stone*=lightTint;
  float vein=1.-smoothstep(.018,.075,abs(sin(p.y*.022+broad*11.+grain*.8)));
  float colony=smoothstep(.58,.76,volumeNoise(q*.65+31.));
  vec3 glow=mix(vec3(.015,.35,.31),vec3(.17,.10,.45),volumeNoise(q+52.));
  if(cavernLightMode>.5&&cavernLightMode<1.5){
    float specks=pow(max(0.,volumeNoise(p*.14)-.46)*1.85,4.);
    stone+=glow*(vein*.8+specks*5.)*colony;
  }
  // Warm pools of distant light break up the cold mineral glow.
  float lantern=pow(max(0.,volumeNoise(q*.45+82.)-.4)*2.,3.);
  if(cavernLightMode>1.5&&cavernLightMode<2.5)stone+=vec3(.44,.20,.05)*lantern;
  float haze=1.-exp(-travel*.00025);
  vec3 mist=fantasyMode>3.5?vec3(.013,.043,.022):vec3(.016,.025,.032);
  return mix(stone*.8,mist,haze*.75);
}
vec3 fantasyAtmosphere(vec3 ray,vec3 colour,vec3 airColour){
  if(fantasyMode<.5)return colour;
  if(fantasyMode<1.5){
    // Continuous direction-space ribbons avoid a longitude seam.
    float curtain=ray.y-.25-.10*sin(ray.x*6.+ray.z*4.+solarTime*.018)-.05*sin(ray.z*15.-solarTime*.011);
    float ribbons=exp(-abs(curtain)*28.)*(.35+.65*pow(.5+.5*sin(ray.x*90.+ray.z*55.+solarTime*.025),2.));
    float veil=smoothstep(.02,.25,ray.y)*(.32+.68*(1.-dayAmount));
    colour+=mix(vec3(.035,.55,.29),vec3(.35,.06,.65),.5+.5*sin(ray.x*4.+ray.z*3.))*ribbons*veil;
    colour=mix(colour,colour*vec3(.85,.92,1.2),.35);
  }else if(fantasyMode<2.5){
    colour=mix(colour,colour*vec3(1.5,.68,1.35)+vec3(.035,.008,.065)*dayAmount,.6);
    airColour=mix(airColour,airColour*vec3(1.5,.68,1.35)+vec3(.035,.008,.065)*dayAmount,.6);
    // A continuous foreground veil covers the surrounding sky as well as
    // the discs: haze must not look like a separate halo glued to each moon.
    float airMass=1./sqrt(max(ray.y,0.)*max(ray.y,0.)+.025);
    float wisps=volumeNoise(ray*5.+vec3(solarTime*.0015,0.,0.));
    float opticalDepth=(.13+.18*dayAmount+.10*cloudCover+.22*fogAmount)*(.8+wisps*.4);
    float haze=1.-exp(-airMass*opticalDepth);
    vec3 veilColour=mix(airColour,vec3(.23,.24,.34)*(.035+.65*dayAmount),.38);
    colour=mix(colour,veilColour,haze*.70);
    airColour=mix(airColour,veilColour,haze*.70);
    for(int i=0;i<3;i++){
      vec3 centre=normalize(i==0?vec3(-.55,.20,-.82):i==1?vec3(.38,.64,-.67):vec3(.75,.23,.61));
      float radius=i==0?.19:i==1?.095:.055;
      float facing=dot(ray,centre),edge=sqrt(1.-radius*radius);
      float edgeWidth=max(fwidth(facing),radius*(.001+.002*haze));
      float mask=smoothstep(edge-edgeWidth,edge+edgeWidth,facing);
      if(mask<=0.)continue;
      vec3 tangent=(ray-centre*facing)/radius;
      vec3 normal=normalize(tangent-centre*sqrt(max(0.,1.-dot(tangent,tangent))));
      // Fixed surface coordinates keep maria and impact bowls still as the
      // camera moves. Only fragments inside a lunar disc pay for this detail.
      vec3 surface=normal+float(i)*21.;
      float maria=smoothstep(.36,.62,volumeNoise(surface*4.));
      float grain=volumeNoise(surface*38.)-.5;
      float relief=0.;
      for(int crater=0;crater<18;crater++){
        vec3 seed=starHash(vec3(float(crater),float(i),17.));
        vec3 site=normalize(seed*2.-1.);
        float r=mix(.045,.22,seed.z*seed.z);
        float d=length(normal-site)/r;
        float rim=exp(-pow((d-.86)*10.,2.));
        float bowl=1.-smoothstep(.12,.83,d);
        relief+=rim*.12-bowl*.13;
      }
      vec3 moon=i==0?vec3(.39,.36,.33):i==1?vec3(.35,.38,.39):vec3(.40,.38,.42);
      moon*=.65+maria*.30+grain*.13+relief;
      float incidence=max(dot(normal,normalize(sunDirection)),0.);
      moon*=.008+.72*pow(incidence,.7);
      // A long path through air washes out low moons. Daylight airlight
      // remains in front of the unlit hemisphere instead of a black cutout.
      float transmission=exp(-airMass*(.10+.20*dayAmount+.12*stormAmount))*(1.-haze);
      vec3 behindAir=airColour+moon*transmission*.65;
      colour=mix(colour,behindAir,mask);
    }
  }
  return colour;
}
`;
