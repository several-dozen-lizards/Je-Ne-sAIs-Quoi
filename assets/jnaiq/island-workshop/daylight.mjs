import {supportsLocalWeather,resolveLocalWeather,watchLocalWeather,locateWeather} from './local-weather.mjs';
import {normalizedSkyColors,installSkyColors} from './sky-colors.mjs';
import {normalizedWater,prepareSkyPanorama,validateCustomSky} from './sky-water-options.mjs';
export const skyBrightness=value=>Number.isFinite(value)?Math.max(.1,Math.min(2,value)):1;
import {wrapHour,localClockHour,daylight} from './atmosphere-profile.mjs';
export {wrapHour,localClockHour,daylight} from './atmosphere-profile.mjs';
export function advanceHour(hour,seconds,minutesPerDay){return wrapHour(hour+seconds*24/(minutesPerDay*60));}
export function installDaylight(invalidate){
  let saved={};try{saved=JSON.parse(localStorage.getItem('jnsq.atmosphere.v1')||'{}')||{};}catch{}
  const state={hour:Number.isFinite(saved.hour)?wrapHour(saved.hour):18.2,playing:false,minutes:[5,15,60].includes(saved.minutes)?saved.minutes:15,clouds:saved.clouds!==false};
  state.followLocalTime=saved.followLocalTime!==false;
  state.followLocalWeather=saved.followLocalWeather===true;
  if(state.followLocalTime)state.hour=localClockHour();
  state.environment=['clouds','ocean','planet','asteroids','space','aurora','alien','cavern','cavern-glow','lava','cavern-lava'].includes(saved.environment)?saved.environment:state.clouds?'clouds':'ocean';
  state.weather=['clear','scattered','overcast','rain','storm','snow','fog','meteors'].includes(saved.weather)?saved.weather:'scattered';
  state.strength=Number.isFinite(saved.strength)?Math.max(.1,Math.min(1,saved.strength)):.65;
  state.cloudShadows=saved.cloudShadows!==false;state.sunRays=saved.sunRays!==false;
  state.nebulaClouds=saved.nebulaClouds===true;
  state.cavernLighting=['natural','bio','amber','cool'].includes(saved.cavernLighting)?saved.cavernLighting:'natural';
  state.skyBrightness=skyBrightness(saved.skyBrightness);
  state.landBrightness=Number.isFinite(saved.landBrightness)?Math.max(0,Math.min(2,saved.landBrightness)):1;
  state.lightingColor=/^#[0-9a-f]{6}$/i.test(saved.lightingColor)?saved.lightingColor:'#ffffff';
  state.water=normalizedWater(saved.water);
  try{state.customSky=validateCustomSky(saved.customSky);}catch{state.customSky=null;}
  const section=document.createElement('section');section.innerHTML=`<h2>05 / Sky & time</h2><label for="skyHour">Time of day <output id="skyClock"></output></label><input id="skyHour" type="range" min="0" max="24" step=".01"><div class="row"><button id="skyDawn">Dawn</button><button id="skyDay">Day</button><button id="skyDusk">Dusk</button><button id="skyNight">Night</button></div><button id="skyPlay" class="wide">Play day/night cycle</button><label for="skySpeed">Full day lasts</label><select id="skySpeed"><option value="5">5 minutes</option><option value="15">15 minutes</option><option value="60">1 hour</option></select><label for="skyWorld">Surroundings</label><select id="skyWorld"><option value="clouds">Floating above clouds</option><option value="ocean">Ocean island</option></select><p>One sun drives the sky, shadows and surface lighting. Pause or scrub to compose a scene. These viewing settings stay in this browser.</p>`;
  document.querySelector('aside section:last-child').before(section);
  const $=id=>document.getElementById(id);
  const landLights=document.createElement('div');landLights.innerHTML='<label for="landBrightness">Land brightness <output id="landBrightnessValue"></output></label><input id="landBrightness" type="range" min="0" max="2" step=".01"><label for="lightingColor">Lighting color</label><input id="lightingColor" type="color"><button id="resetLandLighting">Reset land lighting</button><p>Darken daytime land or brighten the night without moving the sun. White keeps the natural lighting colors.</p>';
  $('skyHour').after(landLights);
  const authoredSky=document.createElement('div');authoredSky.innerHTML='<label for="customSkyFile">Custom skybox panorama</label><input id="customSkyFile" type="file" accept="image/jpeg,image/png,.jpg,.jpeg,.png"><div class="row"><button type="button" id="removeCustomSky">Use generated sky</button><span id="customSkyName" class="hint"></span></div><label for="customSkyRotation">Sky rotation <output id="customSkyRotationValue"></output></label><input id="customSkyRotation" type="range" min="-180" max="180" step="1"><label for="customSkyBrightness">Sky brightness <output id="customSkyBrightnessValue"></output></label><input id="customSkyBrightness" type="range" min=".1" max="2" step=".05"><p>Balanced and High detail lighting use this sky to illuminate surfaces and reflections. Land brightness and lighting color remain adjustable.</p><details class="panorama-guide"><summary>Panorama image guide</summary><p><strong>Best quality:</strong> 4096 × 2048. <strong>Lighter/faster:</strong> 2048 × 1024. Use an equirectangular image with an exact <strong>2:1 aspect ratio</strong>—not an ordinary wide photo or cube-cross layout. Keep the horizon near the vertical center and make the left and right edges join cleanly to avoid a visible seam. JPEG and PNG are accepted; the workshop resizes images wider than 4096 pixels and stores an optimized JPEG inside the island.</p></details>';
  landLights.before(authoredSky);
  state.skyColors=normalizedSkyColors(saved.skyColors);
  const syncSkyColors=installSkyColors(state,authoredSky,save,invalidate);
  function syncCustomSky(){syncSkyColors();const sky=state.customSky;$('customSkyName').textContent=sky?sky.name:'Generated sky';$('removeCustomSky').disabled=!sky;$('customSkyRotation').disabled=!sky;$('customSkyBrightness').disabled=false;$('customSkyRotation').value=sky?.rotation||0;$('customSkyRotationValue').textContent=(sky?.rotation||0)+'°';$('customSkyBrightness').value=sky?.brightness??state.skyBrightness;$('customSkyBrightnessValue').textContent=Math.round((sky?.brightness??state.skyBrightness)*100)+'%';}
  $('customSkyFile').onchange=async()=>{try{const file=$('customSkyFile').files[0];if(!file)return;state.customSky=await prepareSkyPanorama(file);syncCustomSky();save();invalidate();window.dispatchEvent(new CustomEvent('island-atmosphere-change',{detail:'Custom sky imported'}));}catch(error){window.dispatchEvent(new CustomEvent('island-atmosphere-error',{detail:error.message}));}finally{$('customSkyFile').value='';}};
  $('removeCustomSky').onclick=()=>{state.customSky=null;syncCustomSky();save();invalidate();window.dispatchEvent(new CustomEvent('island-atmosphere-change',{detail:'Generated sky restored'}));};
  for(const [id,key,format] of [['customSkyRotation','rotation',v=>v+'°'],['customSkyBrightness','brightness',v=>Math.round(v*100)+'%']]){$(id).oninput=()=>{if(!state.customSky&&key==='rotation')return;const value=Number($(id).value);if(state.customSky)state.customSky[key]=value;else state.skyBrightness=skyBrightness(value);$(id+'Value').textContent=format(value);invalidate();};$(id).onchange=()=>{if(!state.customSky&&key==='rotation')return;save();window.dispatchEvent(new CustomEvent('island-atmosphere-change',{detail:'Sky adjusted'}));};}
  syncCustomSky();
  const waterPanel=document.createElement('div');waterPanel.innerHTML='<h3>Ocean surface (when used)</h3><label for="waterSurface">Surface</label><select id="waterSurface"><option value="visible">Visible</option><option value="none">No surrounding surface</option></select><label for="waterColor">Water color</label><input id="waterColor" type="color"><label for="waterGlow">Water glow <output id="waterGlowValue"></output></label><input id="waterGlow" type="range" min="0" max="2" step=".05"><label for="waterRipples">Ripple energy <output id="waterRipplesValue"></output></label><input id="waterRipples" type="range" min="0" max="2" step=".05"><p>Ripple energy scales the coupled wave field from mirror-still to rough. Glow is emitted light in the water itself. None leaves open sky below the island edge.</p>';
  $('skyWorld').after(waterPanel);
  function syncWater(){const water=state.water=normalizedWater(state.water);$('waterSurface').value=water.surface;$('waterColor').value=water.color;$('waterGlow').value=water.glow;$('waterGlowValue').textContent=Math.round(water.glow*100)+'%';$('waterRipples').value=water.ripples;$('waterRipplesValue').textContent=Math.round(water.ripples*100)+'%';}
  for(const [id,key] of [['waterSurface','surface'],['waterColor','color'],['waterGlow','glow'],['waterRipples','ripples']])$(id).addEventListener(id==='waterSurface'?'change':'input',()=>{state.water[key]=['glow','ripples'].includes(key)?Number($(id).value):$(id).value;syncWater();save();invalidate();window.dispatchEvent(new CustomEvent('island-atmosphere-change',{detail:key==='surface'&&state.water.surface==='none'?'Ocean surface removed':'Ocean surface adjusted'}));});
  syncWater();
  function syncLandLighting(){$('landBrightness').value=state.landBrightness;$('landBrightnessValue').textContent=Math.round(state.landBrightness*100)+'%';$('lightingColor').value=state.lightingColor;}
  for(const key of ['landBrightness','lightingColor'])$(key).oninput=()=>{state[key]=key==='landBrightness'?Number($(key).value):$(key).value;syncLandLighting();save();invalidate();};
  $('resetLandLighting').onclick=()=>{state.landBrightness=1;state.lightingColor='#ffffff';syncLandLighting();save();invalidate();};
  syncLandLighting();
  const spaceClouds=document.createElement('div');spaceClouds.innerHTML='<label><input type="checkbox" id="nebulaClouds"> Nebula clouds</label><p>Show distant clouds of gas and dust in space. Shooting stars are available under Weather; intensity controls how often they appear.</p>';$('skyWorld').after(spaceClouds);
  $('nebulaClouds').checked=state.nebulaClouds;$('nebulaClouds').onchange=()=>{state.nebulaClouds=$('nebulaClouds').checked;save();invalidate();};
  const caveLights=document.createElement('div');caveLights.innerHTML='<label for="cavernLighting">Cavern lighting</label><select id="cavernLighting"><option value="natural">Dim natural stone</option><option value="bio">Bioluminescent colonies</option><option value="amber">Warm amber light</option><option value="cool">Cool mineral light</option></select><p>Lights the cavern and island, independently of the lake color.</p>';$('skyWorld').after(caveLights);
  $('cavernLighting').value=state.cavernLighting;$('cavernLighting').onchange=()=>{state.cavernLighting=$('cavernLighting').value;save();invalidate();};
  const clockControl=document.createElement('div');clockControl.innerHTML='<label><input type="checkbox" id="skyLocalTime"> Follow local time</label><p>Uses your computer’s clock and time zone. Dawn and dusk use the island’s stylized cycle, not your location’s seasonal sunrise and sunset. Scrubbing or playing a faster cycle switches to manual time.</p>';
  $('skyHour').before(clockControl);
  $('skyWorld').append(new Option('Deep space · stars only','space'),new Option('Orbit above a planet','planet'),new Option('Asteroid field','asteroids'));
  $('skyWorld').append(new Option('Lava ocean','lava'),new Option('Cavern · lava lake','cavern-lava'),new Option('Aurora sky','aurora'),new Option('Alien moons','alien'),new Option('Cavern · dark lake','cavern'),new Option('Cavern · glowing green lake','cavern-glow'));
  const weatherPanel=document.createElement('div');weatherPanel.innerHTML=`<label for="weatherKind">Weather</label><select id="weatherKind"><option value="clear">Clear skies</option><option value="scattered">Scattered clouds</option><option value="overcast">Full cloud cover</option><option value="rain">Rain</option><option value="storm">Storm</option><option value="snow">Snow</option><option value="fog">Fog</option></select><label for="weatherStrength">Weather intensity</label><input id="weatherStrength" type="range" min=".1" max="1" step=".05"><p>Weather is a local visual effect. Precipitation pauses with Animate atmosphere; snow does not accumulate.</p>`;section.append(weatherPanel);
  $('weatherKind').append(new Option('Occasional shooting stars','meteors'));
  $('weatherKind').value=state.weather;$('weatherStrength').value=state.strength;
  const localPanel=document.createElement('div');localPanel.innerHTML='<label><input type="checkbox" id="followLocalWeather"> Follow my local weather</label><button type="button" id="localWeatherLocate">Use my approximate location</button><p id="localWeatherStatus" role="status"></p><p>Shared with linked areas. Your manual weather returns when switched off. Location is rounded and sent to the weather provider; it stays fixed until you update it.</p>';weatherPanel.prepend(localPanel);
  let observation=null,weatherMessage='Reading the shared weather feed…';
  function syncLocalControls(){const supported=supportsLocalWeather(state.environment);$('followLocalWeather').checked=state.followLocalWeather;$('followLocalWeather').disabled=!supported;$('weatherKind').disabled=state.environment.startsWith('cavern')||(supported&&state.followLocalWeather);$('weatherStrength').disabled=state.environment.startsWith('cavern')||(supported&&state.followLocalWeather);$('localWeatherStatus').textContent=!supported?'Local weather does not apply in these surroundings.':weatherMessage;}
  const weatherFeed=watchLocalWeather((value,message)=>{observation=value;weatherMessage=message;syncLocalControls();invalidate();});
  $('followLocalWeather').onchange=()=>{state.followLocalWeather=$('followLocalWeather').checked;syncLocalControls();save();weatherFeed.refresh();invalidate();};
  $('localWeatherLocate').onclick=async()=>{const button=$('localWeatherLocate');button.disabled=true;weatherMessage='Waiting for location and weather…';syncLocalControls();try{await locateWeather();state.followLocalWeather=true;$('followLocalWeather').checked=true;$('followLocalWeather').dispatchEvent(new Event('change',{bubbles:true}));await weatherFeed.refresh();}catch(e){weatherMessage=e.message;}finally{button.disabled=false;syncLocalControls();invalidate();}};
  const coverageHint=document.createElement('p');coverageHint.textContent='For scattered clouds, intensity ranges from a few clouds to a nearly full sky.';$('weatherStrength').after(coverageHint);
  const sunlightPanel=document.createElement('div');
  sunlightPanel.innerHTML='<label><input type="checkbox" id="cloudShadows"> Cloud shadows</label><label><input type="checkbox" id="sunRays"> Crepuscular rays / sunbeams</label><p>Scattered clouds reveal sunbeams, especially when looking toward a low sun. Cloud shadows drift with Animate atmosphere. Both effects fade at night and switch off in space.</p>';
  section.append(sunlightPanel);
  for(const key of ['cloudShadows','sunRays']){$(key).checked=state[key];$(key).onchange=()=>{state[key]=$(key).checked;save();invalidate();};}
  $('weatherKind').onchange=()=>{state.weather=$('weatherKind').value;save();invalidate();};$('weatherStrength').oninput=()=>{state.strength=Number($('weatherStrength').value);save();invalidate();};
  function sync(){const total=Math.floor(state.hour*60+1e-8)%1440;$('skyClock').textContent=String(Math.floor(total/60)).padStart(2,'0')+':'+String(total%60).padStart(2,'0');$('skyHour').value=state.hour;$('skyLocalTime').checked=state.followLocalTime;$('skySpeed').disabled=state.followLocalTime;$('skyPlay').textContent=state.playing?'Pause day/night cycle':'Play day/night cycle';$('skyPlay').setAttribute('aria-pressed',String(state.playing));}
  function save(){try{localStorage.setItem('jnsq.atmosphere.v1',JSON.stringify({...state}));}catch{}}
  $('skyLocalTime').onchange=()=>{state.followLocalTime=$('skyLocalTime').checked;state.playing=false;if(state.followLocalTime)state.hour=localClockHour();sync();save();invalidate();};
  $('skyHour').oninput=()=>{state.hour=wrapHour(Number($('skyHour').value));state.playing=false;state.followLocalTime=false;sync();save();invalidate();};
  for(const [id,h] of [['skyDawn',5.8],['skyDay',12],['skyDusk',18.2],['skyNight',0]])$(id).onclick=()=>{state.hour=h;state.playing=false;state.followLocalTime=false;sync();save();invalidate();};
  $('skyPlay').onclick=()=>{state.followLocalTime=false;state.playing=!state.playing;sync();save();invalidate();};
  $('skySpeed').value=state.minutes;$('skySpeed').onchange=()=>{state.minutes=Number($('skySpeed').value);save();};
  const spaceHint=document.createElement('p');spaceHint.textContent='Space has direct starlight and little ambient fill. Weather applies to ocean and cloud surroundings.';$('skyWorld').after(spaceHint);
  function environmentControls(){syncLocalControls();caveLights.hidden=!state.environment.startsWith('cavern');const cavern=state.environment.startsWith('cavern'),airless=['space','planet','asteroids'].includes(state.environment);waterPanel.hidden=airless||['lava','cavern-lava'].includes(state.environment);spaceClouds.hidden=!airless;$('weatherKind').disabled=cavern||(!airless&&state.followLocalWeather);$('weatherStrength').disabled=cavern||(!airless&&state.followLocalWeather);for(const option of $('weatherKind').options)option.disabled=airless&&!['clear','meteors'].includes(option.value);if(airless&&!['clear','meteors'].includes(state.weather)){state.weather='clear';$('weatherKind').value='clear';}spaceHint.hidden=!airless&&!cavern;spaceHint.textContent=cavern?'A vast decorative cavern surrounds the island. Mineral light replaces the sun; the distant walls and ceiling are not editable or walkable.':'Space has direct starlight and little ambient fill. Toggle nebula clouds, or choose occasional shooting stars below.';}
  $('skyWorld').value=state.environment;$('skyWorld').onchange=()=>{state.environment=$('skyWorld').value;state.clouds=state.environment==='clouds';environmentControls();save();invalidate();};environmentControls();
  window.addEventListener('pagehide',save);sync();
  return {state,get renderState(){return resolveLocalWeather(state,observation);},restore(value){
    Object.assign(state,value,{playing:false});
    state.followLocalWeather=value.followLocalWeather===true;
    state.skyBrightness=skyBrightness(value.skyBrightness);
    state.landBrightness=Number.isFinite(value.landBrightness)?Math.max(0,Math.min(2,value.landBrightness)):1;
    state.lightingColor=/^#[0-9a-f]{6}$/i.test(value.lightingColor)?value.lightingColor:'#ffffff';
    state.water=normalizedWater(value.water);
    state.skyColors=normalizedSkyColors(value.skyColors);
    try{state.customSky=validateCustomSky(value.customSky);}catch{state.customSky=null;}
    for(const [id,key] of [['skyWorld','environment'],['weatherKind','weather'],['weatherStrength','strength'],['cavernLighting','cavernLighting']])$(id).value=state[key];
    for(const key of ['cloudShadows','sunRays','nebulaClouds'])$(key).checked=state[key];
    environmentControls();syncLandLighting();syncWater();syncCustomSky();sync();invalidate();
  },tick(seconds){if(state.followLocalTime){const hour=localClockHour();if(hour!==state.hour){state.hour=hour;sync();invalidate();}}else if(state.playing){state.hour=advanceHour(state.hour,seconds,state.minutes);sync();}return daylight(state.hour);}};
}
