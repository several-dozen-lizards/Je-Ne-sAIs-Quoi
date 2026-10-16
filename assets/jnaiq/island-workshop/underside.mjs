import {N} from './terrain.mjs?caves=retired';

// Coordinate-seeded fracture fields stay put when the surface is sculpted.
export function undersidePoints(w){
  const stride=N+1, distance=new Float32Array(w.heights.length);
  const hash=(x,z)=>{let n=Math.imul(x,374761393)^Math.imul(z,668265263)^(w.seed>>>0);n=Math.imul(n^(n>>>13),1274126177);return ((n^(n>>>16))>>>0)/4294967295;};
  const noise=(x,z)=>{
    const i=Math.floor(x),j=Math.floor(z),u=x-i,v=z-j;
    // Linear triangular interpolation makes rock planes rather than soft blobs.
    const a=hash(i,j),b=hash(i+1,j),c=hash(i,j+1),d=hash(i+1,j+1);
    return u+v<=1?a+(b-a)*u+(c-a)*v:d+(c-d)*(1-u)+(b-d)*(1-v);
  };
  for(let j=0;j<=N;j++)for(let i=0;i<=N;i++){
    const k=j*stride+i;distance[k]=w.heights[k]<=0||!i||!j||i===N||j===N?0:N;
  }
  // Distance to the actual edited shoreline, including inlets and separate land.
  for(let j=1;j<=N;j++)for(let i=1;i<=N;i++){
    const k=j*stride+i;distance[k]=Math.min(distance[k],distance[k-1]+1,distance[k-stride]+1,distance[k-stride-1]+Math.SQRT2);
  }
  for(let j=N-1;j>=0;j--)for(let i=N-1;i>=0;i--){
    const k=j*stride+i;distance[k]=Math.min(distance[k],distance[k+1]+1,distance[k+stride]+1,distance[k+stride+1]+Math.SQRT2);
  }
  return w.heights.map((height,k)=>{
    const x=(k%stride/N-.5)*w.size,z=(Math.floor(k/stride)/N-.5)*w.size;
    const u=x/w.size,v=z/w.size,inland=1-Math.exp(-distance[k]/(N*.13));
    const mass=noise(u*7+19,v*7-31),fracture=1-Math.abs(2*noise(u*19-7,v*19+13)-1);
    const chips=noise(u*43+41,v*43+23);
    const depth=w.size*(.018+.035*mass+inland*(.10+.20*mass+.075*fracture**3)+.014*chips);
    return [x,-depth-Math.max(0,height)*.18,z];
  });
}
