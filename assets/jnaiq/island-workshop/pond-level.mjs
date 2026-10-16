import {N,heightAt} from './terrain.mjs?caves=retired';

// Terrain is piecewise linear. The minimum along a shore segment must occur
// at an endpoint or where it crosses a grid edge / triangle diagonal.
export function pondSpillLevel(w,points){
  let level=Infinity;
  const grid=v=>(v/w.size+.5)*N;
  for(let i=0;i<points.length;i++){
    const a=points[i],b=points[(i+1)%points.length],cuts=[0,1];
    const u=grid(a.x),v=grid(a.z),du=grid(b.x)-u,dv=grid(b.z)-v;
    for(const [start,delta] of [[u,du],[v,dv],[u+v,du+dv]]){
      if(Math.abs(delta)<1e-12)continue;
      for(let k=Math.ceil(Math.min(start,start+delta));k<=Math.floor(Math.max(start,start+delta));k++){
        const t=(k-start)/delta;if(t>0&&t<1)cuts.push(t);
      }
    }
    for(const t of cuts)level=Math.min(level,heightAt(w,a.x+(b.x-a.x)*t,a.z+(b.z-a.z)*t));
  }
  return level;
}

export function settlePonds(w){
  for(const f of w.features||[])if(f.kind==='pond'){
    const level=pondSpillLevel(w,f.points);
    for(const p of f.points)p.y=level;
  }
}
