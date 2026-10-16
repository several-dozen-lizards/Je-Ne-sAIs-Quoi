export const DEFAULT_SKY_COLORS=Object.freeze({enabled:false,horizon:'#8eadd0',zenith:'#2e5999',nightHorizon:'#2d1d48',nightZenith:'#070a21'});
export function normalizedSkyColors(value){
  const result={...DEFAULT_SKY_COLORS,enabled:value?.enabled===true};
  for(const key of ['horizon','zenith','nightHorizon','nightZenith'])if(/^#[0-9a-f]{6}$/i.test(value?.[key]))result[key]=value[key];
  return result;
}
export function installSkyColors(state,parent,save,invalidate){
  const panel=document.createElement('fieldset');panel.id='generatedSkyColors';
  panel.innerHTML='<legend>Generated sky colors</legend><label><input id="skyColorsEnabled" type="checkbox"> Customize sky gradient</label>'+[['horizon','Day horizon'],['zenith','Day overhead'],['nightHorizon','Night horizon'],['nightZenith','Night overhead']].map(([key,label])=>`<label for="skyColor-${key}">${label}</label><input id="skyColor-${key}" type="color" data-color="${key}">`).join('')+'<button type="button" id="resetSkyColors">Reset sky colors</button><p id="skyColorsHint"></p>';
  parent.after(panel);
  function sync(){state.skyColors=normalizedSkyColors(state.skyColors);panel.disabled=!!state.customSky;panel.querySelector('#skyColorsEnabled').checked=state.skyColors.enabled;for(const input of panel.querySelectorAll('[data-color]')){input.value=state.skyColors[input.dataset.color];input.disabled=!state.skyColors.enabled;}panel.querySelector('#skyColorsHint').textContent=state.customSky?'Your custom skybox overrides these colors. They return when you use the generated sky.':'Day and night blend with the time of day. Clouds, sunsets and stars remain visible.';}
  function changed(){sync();save();invalidate();window.dispatchEvent(new CustomEvent('island-atmosphere-change',{detail:'Sky colors changed'}));}
  panel.querySelector('#skyColorsEnabled').onchange=e=>{state.skyColors.enabled=e.target.checked;changed();};
  for(const input of panel.querySelectorAll('[data-color]'))input.oninput=()=>{state.skyColors[input.dataset.color]=input.value;changed();};
  panel.querySelector('#resetSkyColors').onclick=()=>{state.skyColors={...DEFAULT_SKY_COLORS};changed();};
  sync();return sync;
}
