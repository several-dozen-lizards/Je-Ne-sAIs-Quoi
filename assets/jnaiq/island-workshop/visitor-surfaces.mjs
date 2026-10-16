// Filter before raycasting. Testing an attached SkinnedMesh can cache its
// culling bounds while its skin matrices are still awaiting the next draw.
// Residents are never walking surfaces, including a hidden first-person body.
export function walkingSurfaces(roots){
  const meshes=[];
  function visit(object){
    if(object.userData.visitorBody)return;
    if(object.isMesh&&!object.material?.transparent&&!object.userData.walkThrough)meshes.push(object);
    for(const child of object.children)visit(child);
  }
  for(const root of roots)visit(root);
  return meshes;
}
