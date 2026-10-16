// Shared numerical atmosphere model; no renderer or browser dependencies.
export const wrapHour=h=>((h%24)+24)%24;
export const localClockHour=(date=new Date())=>date.getHours()+date.getMinutes()/60+date.getSeconds()/3600;
export function daylight(hour){
  const angle=(wrapHour(hour)-6)/24*Math.PI*2,elevation=Math.sin(angle);
  const smooth=(a,b,x)=>{const t=Math.max(0,Math.min(1,(x-a)/(b-a)));return t*t*(3-2*t);};
  return {direction:[Math.cos(angle)*.8,elevation,Math.cos(angle)*.6],day:smooth(-.16,.22,elevation),twilight:Math.exp(-Math.pow(elevation/.23,2)),elevation};
}
export function weatherProfile(kind,strength=.65){
  if(kind==='meteors')kind='clear';
  const amount=Math.max(.1,Math.min(1,strength));
  // Map the complete slider range to sparse through nearly overcast. Coverage
  // is shared by cloud density, shadows, sunlight, sky colour and reflections.
  const scatteredCover=.08+.89*(amount-.1)/.9;
  return {cover:({clear:0,scattered:scatteredCover,overcast:1,rain:.92,storm:1,snow:.95,fog:.85})[kind]??.5,storm:kind==='storm'?amount:kind==='rain'?amount*.35:0,snow:kind==='snow',precipitation:['rain','storm','snow'].includes(kind)?amount:0,fog:kind==='fog'?amount:kind==='storm'?amount*.45:0};
}
export function solarProfile(light,weather,space=false){
  if(space)return {direct:1,colour:[1,.97,.92],transmission:1,skyBrightness:1,skyNeutral:0,ambientScale:1,ambientColour:[.42,.46,.58],sunsetVisibility:0,shadows:0,rays:0};
  const elevation=Math.max(0,light.elevation),air=1/Math.max(.10,elevation);
  const cover=space?0:weather.cover,storm=space?0:weather.storm;
  const transmission=Math.exp(-cover*(1.15+storm*1.8));
  const direct=light.day*Math.min(1,elevation*8)*Math.exp(-.10*(air-1))*transmission;
  return {direct,colour:[1,Math.exp(-.035*(air-1)),Math.exp(-.085*(air-1))],
    transmission,skyBrightness:1-cover*.28-storm*.30,skyNeutral:cover*.72,
    ambientScale:(1+cover*.20)*(1-storm*.55),
    ambientColour:[.66+cover*.18,.81+cover*.06,1-cover*.10],
    sunsetVisibility:1-cover*.75,
    shadows:space?0:light.day,
    rays:space?0:direct*cover*(1-cover*.96)*(1-storm*.8)*2.4};
}
