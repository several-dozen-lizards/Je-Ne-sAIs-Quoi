let delivery;
async function deliveryMode(){
  try {
    const response=await fetch('/api/room-workshop/asset-delivery',{cache:'no-store'});
    if(response.ok&&(await response.json()).schema==='jnaiq-asset-delivery/1')return null;
  } catch {}
  // A household host already running during an update retains its old routes.
  // Keep its existing optimized assets usable until its normal restart.
  try {
    const response=await fetch(new URL('./optimized-objects/files.json',import.meta.url));
    return new Set(response.ok?await response.json():[]);
  } catch {return new Set();}
}
export async function objectAssetURL(filename){
  // The shared endpoint selects the prepared tier and invalidates it when a
  // source changes. Public installations already contain the selected tier.
  if(!delivery)delivery=deliveryMode();
  const legacy=await delivery;
  return legacy?.has(filename)?new URL('./optimized-objects/'+encodeURIComponent(filename),import.meta.url).href:'/api/room-workshop/assets/objects/'+encodeURIComponent(filename);
}
