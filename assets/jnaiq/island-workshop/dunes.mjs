// Smooth, seeded fields bend the wind-aligned dunes and vary their spacing,
// height and continuity. Work happens only during terrain generation.
function field(x,z,seed){
  const ix=Math.floor(x),iz=Math.floor(z),u=x-ix,v=z-iz;
  const ease=t=>t*t*t*(t*(t*6-15)+10),a=ease(u),b=ease(v);
  const hash=(x,z)=>{const n=Math.sin(x*127.1+z*311.7+seed*73.19)*43758.5453;return n-Math.floor(n);};
  return (hash(ix,iz)*(1-a)+hash(ix+1,iz)*a)*(1-b)+(hash(ix,iz+1)*(1-a)+hash(ix+1,iz+1)*a)*b;
}
export function duneHeight(u,v,phases){
  const angle=phases[5],seed=phases[8];
  const along=u*Math.cos(angle)+v*Math.sin(angle),across=-u*Math.sin(angle)+v*Math.cos(angle);
  const warp=field(along*3.2+9,across*3.2-5,seed)-.5;
  const bend=field(along*6.5-4,across*4.5+7,seed+1)-.5;
  const mass=field(along*4.2+17,across*4.2+3,seed+2);
  const spacing=38+phases[7]*1.2;
  const crest=.5+.5*Math.cos(across*spacing+warp*6+bend*1.8+phases[6]);
  // Broad rounded crests and troughs keep the 128-cell terrain mesh smooth.
  // The mass field tapers some ridges into low saddles instead of a repeated
  // full-height corrugation running from one shore to the other.
  return 2.5+1.6*mass+(1.8+4.4*mass)*crest**1.35;
}
