// Match the household-scale limits in Godot's _normalize_imported_lights.
// Blender/glTF lantern intensities can otherwise wash the entire room white.
export function normalizeImportedLights(root){
  root.traverse(node=>{
    if(node.isPointLight||node.isSpotLight){
      node.intensity=Math.min(node.intensity,2.2);
      node.distance=node.distance>0?Math.min(node.distance,6):6;
      node.castShadow=false;
    }else if(node.isDirectionalLight)node.intensity=Math.min(node.intensity,1);
  });
  return root;
}
