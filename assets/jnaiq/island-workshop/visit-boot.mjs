// Catch module-link failures too: a catch inside visit.mjs cannot run when one
// of its imports is missing, which otherwise leaves the loading screen forever.
import('./visit.mjs?public=5').catch(error=>{
  console.error('Island startup failed',error);
  document.getElementById('loading-title').textContent='Unable to enter this location';
  document.querySelector('#loading p').textContent='The 3D view could not start. Reload to try again.';
  const status=document.getElementById('status');
  status.textContent=error.message||String(error);
  status.classList.add('error');
  const retry=document.createElement('button');
  retry.textContent='Reload 3D view';
  retry.onclick=()=>location.reload();
  document.getElementById('loading').append(retry);
});
