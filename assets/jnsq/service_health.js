(()=>{
  "use strict";
  if(window.JNSQServiceHealth)return;
  const esc=value=>String(value??"").replace(/[&<>"']/g,char=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
  const storeKey="jnsq.service-health.dismissed.v1";
  let incidents=[],inFlight=null;
  function dismissed(){try{return JSON.parse(sessionStorage.getItem(storeKey)||"{}")||{}}catch(_){return {}}}
  function saveDismissed(value){try{sessionStorage.setItem(storeKey,JSON.stringify(value))}catch(_){}}
  function mount(){let root=document.getElementById("jnsq-service-health");if(root)return root;
    root=document.createElement("aside");root.id="jnsq-service-health";root.hidden=true;root.dataset.open="false";
    root.innerHTML='<button class="jnsq-health-chip" type="button" aria-label="Open service health"></button><section class="jnsq-health-panel" role="status" aria-live="polite"><div class="jnsq-health-head"><div><strong>Service needs attention</strong><span>JNSQ kept the diagnosis content-free.</span></div><button class="jnsq-health-close" type="button" aria-label="Dismiss service health">×</button></div><div class="jnsq-health-list"></div><div class="jnsq-health-foot"><span>Checks follow real UI work—not a timer.</span><button type="button" data-health-refresh>Check again</button></div></section>';
    document.body.appendChild(root);root.querySelector(".jnsq-health-chip").onclick=()=>{root.dataset.open="true"};
    root.querySelector(".jnsq-health-close").onclick=()=>close(root);root.querySelector("[data-health-refresh]").onclick=()=>check(true);return root}
  function close(root=mount()){const seen=dismissed();for(const incident of incidents)seen[incident.id]=incident.revision;
    saveDismissed(seen);root.dataset.open="false"}
  function incidentHtml(incident){const action=incident.action||{},people=(incident.personas||[]).length?` · ${(incident.personas||[]).join(", ")}`:"";
    return `<article class="jnsq-health-item" data-severity="${esc(incident.severity)}"><div class="jnsq-health-title">${esc(incident.title)}</div><div class="jnsq-health-copy">${esc(incident.explanation)}</div><div class="jnsq-health-fix">${esc(incident.fix)}</div><div class="jnsq-health-meta">${esc(incident.occurrences)} recent failure${Number(incident.occurrences)===1?"":"s"}${esc(people)}</div><div class="jnsq-health-actions">${action.href?`<a href="${esc(action.href)}" target="_blank" rel="noopener">${esc(action.label||"Open settings")}</a>`:""}<a href="/model-calls" target="_blank" rel="noopener">Actual model calls</a></div></article>`}
  function render(report,{forceOpen=false}={}){const root=mount();incidents=Array.isArray(report?.incidents)?report.incidents:[];
    if(!incidents.length){root.hidden=true;root.dataset.open="false";return}
    root.hidden=false;root.querySelector(".jnsq-health-chip").textContent=`${incidents.length} service issue${incidents.length===1?"":"s"}`;
    root.querySelector(".jnsq-health-list").innerHTML=incidents.map(incidentHtml).join("");
    const seen=dismissed(),unseen=incidents.some(incident=>seen[incident.id]!==incident.revision);
    if(forceOpen||unseen)root.dataset.open="true"}
  function connectionReport(error){return {incidents:[{id:"jnsq-health-endpoint",revision:"unreachable",severity:"warning",title:"JNSQ health check could not be reached",explanation:"The workspace is open, but its local health endpoint did not answer.",fix:"Check whether the JNSQ router is still running, then restart JNSQ if the problem persists.",occurrences:1,personas:[],action:{label:"Open Household",href:"/"}}]}}
  async function check(forceOpen=false){if(inFlight)return inFlight;inFlight=(async()=>{try{const response=await fetch("/api/provider-health?hours=24",{cache:"no-store"});
      if(!response.ok)throw new Error(String(response.status));render(await response.json(),{forceOpen})}catch(error){render(connectionReport(error),{forceOpen:true})}finally{inFlight=null}})();return inFlight}
  window.JNSQServiceHealth={check,open:()=>{const root=mount();root.dataset.open="true"}};
  window.addEventListener("focus",()=>check());document.addEventListener("visibilitychange",()=>{if(!document.hidden)check()});
  window.addEventListener("message",event=>{if(event.data?.type==="jnsq-service-health-check")check()});
  window.addEventListener("jnsq-service-health-check",()=>check());
  const bootstrap=window.JNSQ_SERVICE_HEALTH_BOOTSTRAP;
  try{delete window.JNSQ_SERVICE_HEALTH_BOOTSTRAP}catch(_){}
  const initial=()=>bootstrap&&Array.isArray(bootstrap.incidents)?render(bootstrap):check();
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",initial,{once:true});else initial();
})();
