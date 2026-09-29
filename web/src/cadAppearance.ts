import * as THREE from 'three';

/** Engineering display treatment only; source geometry and CAD materials stay intact. */
export function prepareCadMesh(mesh: THREE.Mesh) {
  if (!mesh.geometry.getAttribute('normal')) mesh.geometry.computeVertexNormals();
  const originals = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
  const materials = originals.map((original) => {
    const material = original instanceof THREE.MeshStandardMaterial
      ? original.clone()
      : new THREE.MeshStandardMaterial({ color: 0x7292a5 });
    // GLB colours are linear. Keep solid engineering surfaces distinct from the pale canvas.
    material.color.multiplyScalar(0.62);
    material.metalness = 0.05;
    material.roughness = 0.76;
    material.transparent = false;
    material.opacity = 1;
    material.depthWrite = true;
    material.side = THREE.DoubleSide;
    material.emissive.set(0x000000);
    material.emissiveIntensity = 0;
    material.userData.cadBaseColor = material.color.clone();
    material.needsUpdate = true;
    return material;
  });
  mesh.material = Array.isArray(mesh.material) ? materials : materials[0];
}

export function highlightCadMesh(mesh: THREE.Mesh, selected: boolean, wireframe: boolean) {
  const materials = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
  for (const material of materials) {
    if (!(material instanceof THREE.MeshStandardMaterial)) continue;
    const base = material.userData.cadBaseColor as THREE.Color | undefined;
    if (base) material.color.copy(base);
    if (selected) material.color.lerp(new THREE.Color(0x168360), 0.65);
    material.emissive.set(selected ? 0x0b4936 : 0x000000);
    material.emissiveIntensity = selected ? 0.08 : 0;
    material.wireframe = wireframe;
    material.transparent = false;
    material.opacity = 1;
  }
}
