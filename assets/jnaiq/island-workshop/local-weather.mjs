export const supportsLocalWeather=environment=>!['space','planet','asteroids'].includes(environment)&&!String(environment).startsWith('cavern');

export function resolveLocalWeather(state,observation){
  if(!state.followLocalWeather||!supportsLocalWeather(state.environment)||!observation?.enabled||!observation.status?.observed_at||!observation.island)return state;
  return {...state,...observation.island};
}

export async function weatherRequest(path='/weather-sync',body){
  const response=await fetch(path,{signal:AbortSignal.timeout(20000),...(body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{})});
  const value=await response.json();
  if(!response.ok)throw Error(value.error||value.status?.error||'Local weather unavailable');
  return value;
}

export async function locateWeather(){
  if(!navigator.geolocation)throw Error('Location is unavailable in this browser.');
  const position=await new Promise((resolve,reject)=>navigator.geolocation.getCurrentPosition(resolve,reject,{enableHighAccuracy:false,timeout:12000,maximumAge:3600000}));
  await weatherRequest('/weather-sync',{enabled:true,latitude:Math.round(position.coords.latitude*100)/100,longitude:Math.round(position.coords.longitude*100)/100,location_label:'local area'});
  return weatherRequest('/weather-sync/refresh',{});
}

export function weatherDescription(value){
  if(!value?.enabled)return 'Choose “Use my approximate location” once to set up the shared weather feed.';
  if(!value.status?.observed_at)return 'Waiting for a local weather observation.';
  const stale=value.status.error||Date.parse(value.status.valid_until)<=Date.now();
  return `${stale?'Holding last observation':'Local weather'} · ${value.island?.weather||value.status.weather} · ${new Date(value.status.observed_at).toLocaleTimeString()}${value.status.error?' · refresh unavailable':''}`;
}

export function watchLocalWeather(changed){
  let value=null,timer=null,inflight=null,stopped=false,failures=0;
  const refresh=()=>{
    if(stopped)return Promise.resolve(value);
    if(inflight)return inflight;
    clearTimeout(timer);
    inflight=(async()=>{
      try{value=await weatherRequest();failures=value.status?.error?failures+1:0;changed(value,weatherDescription(value));}
      catch(error){failures++;changed(value,`${value?.status?.observed_at?'Holding last observation · ':''}${error.message}`);}
      finally{
        inflight=null;
        const remaining=Date.parse(value?.status?.valid_until)-Date.now();
        // Observation validity drives updates. Recovery backs off if the host
        // has not produced the next sample yet; disabled feeds wait for input.
        if(!stopped&&(value?.enabled||failures))timer=setTimeout(refresh,
          failures||!(remaining>0)?Math.min(900000,30000*2**Math.min(failures++,5)):remaining+1000);
      }
      return value;
    })();
    return inflight;
  };
  const visible=()=>{if(!document.hidden)refresh();};
  document.addEventListener('visibilitychange',visible);
  window.addEventListener('focus',refresh);
  window.addEventListener('pagehide',()=>{stopped=true;clearTimeout(timer);document.removeEventListener('visibilitychange',visible);window.removeEventListener('focus',refresh);},{once:true});
  refresh();return {refresh,get value(){return value;}};
}
