(()=>{
  "use strict";
  if(window.JNSQServiceHealth)return;
  const esc=value=>String(value??"").replace(/[&<>"']/g,char=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
  const storeKey="jnaiq.service-health.dismissed.v1";
  let incidents=[],inFlight=null;
  function dismissed(){try{return JSON.parse(sessionStorage.getItem(storeKey)||"{}")||{}}catch(_){return {}}}
  function saveDismissed(value){try{sessionStorage.setItem(storeKey,JSON.stringify(value))}catch(_){}}
  function mount(){let root=document.getElementById("jnaiq-service-health");if(root)return root;
    root=document.createElement("aside");root.id="jnaiq-service-health";root.hidden=true;root.dataset.open="false";
    root.innerHTML='<button class="jnaiq-health-chip" type="button" aria-label="Open service health"></button><section class="jnaiq-health-panel" role="status" aria-live="polite"><div class="jnaiq-health-head"><div><strong>Service needs attention</strong><span>JNAIQ kept the diagnosis content-free.</span></div><button class="jnaiq-health-close" type="button" aria-label="Dismiss service health">×</button></div><div class="jnaiq-health-list"></div><div class="jnaiq-health-foot"><span>Checks follow real UI work—not a timer.</span><button type="button" data-health-refresh>Check again</button></div></section>';
    document.body.appendChild(root);root.querySelector(".jnaiq-health-chip").onclick=()=>{root.dataset.open="true"};
    root.querySelector(".jnaiq-health-close").onclick=()=>close(root);root.querySelector("[data-health-refresh]").onclick=()=>check(true);return root}
  function close(root=mount()){const seen=dismissed();for(const incident of incidents)seen[incident.id]=incident.revision;
    saveDismissed(seen);root.dataset.open="false"}
  function incidentHtml(incident){const action=incident.action||{},people=(incident.personas||[]).length?` · ${(incident.personas||[]).join(", ")}`:"";
    return `<article class="jnaiq-health-item" data-severity="${esc(incident.severity)}"><div class="jnaiq-health-title">${esc(incident.title)}</div><div class="jnaiq-health-copy">${esc(incident.explanation)}</div><div class="jnaiq-health-fix">${esc(incident.fix)}</div><div class="jnaiq-health-meta">${esc(incident.occurrences)} recent failure${Number(incident.occurrences)===1?"":"s"}${esc(people)}</div><div class="jnaiq-health-actions">${action.href?`<a href="${esc(action.href)}" target="_blank" rel="noopener">${esc(action.label||"Open settings")}</a>`:""}<a href="/model-calls" target="_blank" rel="noopener">Actual model calls</a></div></article>`}
  function render(report,{forceOpen=false}={}){const root=mount();incidents=Array.isArray(report?.incidents)?report.incidents:[];
    if(!incidents.length){root.hidden=true;root.dataset.open="false";return}
    root.hidden=false;root.querySelector(".jnaiq-health-chip").textContent=`${incidents.length} service issue${incidents.length===1?"":"s"}`;
    root.querySelector(".jnaiq-health-list").innerHTML=incidents.map(incidentHtml).join("");
    const seen=dismissed(),unseen=incidents.some(incident=>seen[incident.id]!==incident.revision);
    if(forceOpen||unseen)root.dataset.open="true"}
  function connectionReport(error){return {incidents:[{id:"jnaiq-health-endpoint",revision:"unreachable",severity:"warning",title:"JNAIQ health check could not be reached",explanation:"The workspace is open, but its local health endpoint did not answer.",fix:"Check whether the JNAIQ router is still running, then restart JNAIQ if the problem persists.",occurrences:1,personas:[],action:{label:"Open Household",href:"/"}}]}}
  async function check(forceOpen=false){if(inFlight)return inFlight;inFlight=(async()=>{try{const response=await fetch("/api/provider-health?hours=24",{cache:"no-store"});
      if(!response.ok)throw new Error(String(response.status));render(await response.json(),{forceOpen})}catch(error){render(connectionReport(error),{forceOpen:true})}finally{inFlight=null}})();return inFlight}
  window.JNSQServiceHealth={check,open:()=>{const root=mount();root.dataset.open="true"}};
  window.addEventListener("focus",()=>check());document.addEventListener("visibilitychange",()=>{if(!document.hidden)check()});
  window.addEventListener("message",event=>{if(event.data?.type==="jnaiq-service-health-check")check()});
  window.addEventListener("jnaiq-service-health-check",()=>check());
  const bootstrap=window.JNSQ_SERVICE_HEALTH_BOOTSTRAP;
  try{delete window.JNSQ_SERVICE_HEALTH_BOOTSTRAP}catch(_){}
  const initial=()=>bootstrap&&Array.isArray(bootstrap.incidents)?render(bootstrap):check();
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",initial,{once:true});else initial();
})();
