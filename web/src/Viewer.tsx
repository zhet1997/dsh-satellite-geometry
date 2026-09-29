import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { MeshoptDecoder } from 'three/examples/jsm/libs/meshopt_decoder.module.js';
import { Box, LoaderCircle, RotateCcw } from 'lucide-react';
import { highlightCadMesh, prepareCadMesh } from './cadAppearance';

export type ViewerHandle = { fit: () => void; view: (direction: 'top' | 'front' | 'iso') => void; focus: (ids: string[]) => void };
type Props = {
  url?: string; title: string; subtitle: string; selected: string[]; hidden: string[];
  wireframe: boolean; onSelect: (id: string | null, additive: boolean) => void;
};
type Runtime = { fit: () => void; view: ViewerHandle['view']; focus: ViewerHandle['focus']; highlight: (ids: string[], hidden: string[], wireframe: boolean) => void };

export const Viewer = forwardRef<ViewerHandle, Props>(function Viewer({ url, title, subtitle, selected, hidden, wireframe, onSelect }, ref) {
  const mount = useRef<HTMLDivElement>(null);
  const runtime = useRef<Runtime | null>(null);
  const selectRef = useRef(onSelect); selectRef.current = onSelect;
  const selectionRef = useRef(selected); selectionRef.current = selected;
  const [state, setState] = useState<'empty' | 'loading' | 'ready' | 'error'>('empty');
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  useImperativeHandle(ref, () => ({
    fit: () => runtime.current?.fit(),
    view: (direction) => runtime.current?.view(direction),
    focus: (ids) => runtime.current?.focus(ids),
  }), []);
  useEffect(() => runtime.current?.highlight(selected, hidden, wireframe), [selected, hidden, wireframe]);

  useEffect(() => {
    const element = mount.current;
    if (!element || !url) { setState('empty'); return; }
    setState('loading'); setError('');
    let disposed = false;
    let renderer: THREE.WebGLRenderer;
    try { renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true }); }
    catch { setError('浏览器未能初始化 3D 显示，请确认硬件加速可用'); setState('error'); return; }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75));
    renderer.setClearColor(0xf0f4f2, 1);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.0;
    element.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(36, 1, 0.001, 10000);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.12;
    const ambient = new THREE.HemisphereLight(0xffffff, 0x627181, 0.8); scene.add(ambient);
    const key = new THREE.DirectionalLight(0xffffff, 2.0); key.position.set(4, 8, 5); scene.add(key);
    const fill = new THREE.DirectionalLight(0xb3d4e6, 0.55); fill.position.set(-3, 2, -5); scene.add(fill);
    const meshes: Array<{ mesh: THREE.Mesh; cid: string | null; original: THREE.Material | THREE.Material[] }> = [];
    const highlights = new THREE.Group(); scene.add(highlights);
    let root: THREE.Object3D | null = null;
    let box = new THREE.Box3();
    let frame = 0;
    let currentDirection: 'top' | 'front' | 'iso' = 'iso';
    function clearHighlights() {
      while (highlights.children.length) {
        const item = highlights.children[0] as THREE.LineSegments;
        highlights.remove(item);
        item.geometry.dispose();
        (item.material as THREE.Material).dispose();
      }
    }
    function fit(target = box, direction = currentDirection) {
      if (target.isEmpty()) return;
      const center = target.getCenter(new THREE.Vector3());
      const size = target.getSize(new THREE.Vector3());
      const extent = Math.max(size.x, size.y, size.z, 0.001);
      const distance = extent / Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)) * 0.9;
      const vector = direction === 'top' ? new THREE.Vector3(0.0001, 1, 0)
        : direction === 'front' ? new THREE.Vector3(0, 0.15, 1) : new THREE.Vector3(1.15, 0.75, 1.3);
      camera.position.copy(center).add(vector.normalize().multiplyScalar(distance));
      camera.near = Math.max(extent / 10000, 0.00001); camera.far = extent * 1000;
      camera.updateProjectionMatrix(); controls.target.copy(center); controls.update();
    }
    const highlight = (ids: string[], hiddenIds: string[], wire: boolean) => {
      clearHighlights();
      const selectedSet = new Set(ids); const hiddenSet = new Set(hiddenIds);
      const selectedBoxes = new Map<string, THREE.Box3>();
      for (const { mesh, cid } of meshes) {
        mesh.visible = !cid || !hiddenSet.has(cid);
        highlightCadMesh(mesh, Boolean(cid && selectedSet.has(cid)), wire);
        if (cid && selectedSet.has(cid) && mesh.visible) {
          const bounds = selectedBoxes.get(cid) ?? new THREE.Box3();
          bounds.expandByObject(mesh); selectedBoxes.set(cid, bounds);
          if (!wire) {
            const edges = new THREE.LineSegments(
              new THREE.EdgesGeometry(mesh.geometry, 24),
              new THREE.LineBasicMaterial({ color: 0x164a3d, depthTest: true, transparent: false }),
            );
            edges.matrix.copy(mesh.matrixWorld); edges.matrixAutoUpdate = false;
            highlights.add(edges);
          }
        }
      }
      selectedBoxes.forEach((bounds) => {
        const helper = new THREE.Box3Helper(bounds, new THREE.Color(0x14a37b));
        (helper.material as THREE.LineBasicMaterial).depthTest = false;
        helper.renderOrder = 10; highlights.add(helper);
      });
    };
    runtime.current = {
      fit: () => fit(),
      view: (direction) => { currentDirection = direction; fit(box, direction); },
      focus: (ids) => {
        const bounds = new THREE.Box3();
        meshes.filter(({ cid }) => cid && ids.includes(cid)).forEach(({ mesh }) => bounds.expandByObject(mesh));
        fit(bounds.isEmpty() ? box : bounds);
      }, highlight,
    };
    const loader = new GLTFLoader().setMeshoptDecoder(MeshoptDecoder);
    loader.load(url, (gltf) => {
      if (disposed) { disposeObject(gltf.scene); return; }
      root = gltf.scene; scene.add(root); root.updateMatrixWorld(true);
      root.traverse((object) => {
        if (!(object instanceof THREE.Mesh)) return;
        let cursor: THREE.Object3D | null = object; let cid: string | null = null;
        while (cursor) {
          const candidate = cursor.userData.componentId ?? cursor.userData.component_id;
          if (typeof candidate === 'string') { cid = candidate; break; }
          cursor = cursor.parent;
        }
        const original = object.material;
        prepareCadMesh(object);
        meshes.push({ mesh: object, cid, original });
      });
      box = new THREE.Box3().setFromObject(root); fit();
      highlight(selectionRef.current, hidden, wireframe); setState('ready');
    }, undefined, (reason) => {
      if (!disposed) { setError(reason instanceof Error ? reason.message : '几何模型加载失败'); setState('error'); }
    });
    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2(); let down: { x: number; y: number } | null = null;
    const onDown = (event: PointerEvent) => { down = { x: event.clientX, y: event.clientY }; };
    const onUp = (event: PointerEvent) => {
      if (!down || Math.hypot(event.clientX - down.x, event.clientY - down.y) > 5) return;
      const bounds = renderer.domElement.getBoundingClientRect();
      pointer.set((event.clientX - bounds.left) / bounds.width * 2 - 1, -(event.clientY - bounds.top) / bounds.height * 2 + 1);
      raycaster.setFromCamera(pointer, camera);
      const hits = raycaster.intersectObjects(meshes.filter(({ mesh }) => mesh.visible).map(({ mesh }) => mesh), false);
      const clicked = hits.length ? meshes.find(({ mesh }) => mesh === hits[0].object) : undefined;
      selectRef.current(clicked?.cid ?? null, event.ctrlKey || event.metaKey || event.shiftKey);
    };
    renderer.domElement.addEventListener('pointerdown', onDown);
    renderer.domElement.addEventListener('pointerup', onUp);
    const observer = new ResizeObserver(() => {
      const width = Math.max(element.clientWidth, 1), height = Math.max(element.clientHeight, 1);
      renderer.setSize(width, height, false); camera.aspect = width / height; camera.updateProjectionMatrix();
    }); observer.observe(element);
    const animate = () => { frame = requestAnimationFrame(animate); controls.update(); renderer.render(scene, camera); }; animate();
    return () => {
      disposed = true; runtime.current = null; cancelAnimationFrame(frame); observer.disconnect();
      renderer.domElement.removeEventListener('pointerdown', onDown); renderer.domElement.removeEventListener('pointerup', onUp);
      controls.dispose(); clearHighlights();
      if (root) disposeObject(root);
      meshes.forEach(({ original }) => (Array.isArray(original) ? original : [original]).forEach((m) => m.dispose()));
      renderer.dispose(); renderer.domElement.remove();
    };
    // Each GLB owns its rendering lifetime. Selection and visibility update in place.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, retry]);

  return <div className="viewport">
    <div ref={mount} className="canvas-mount" aria-label={`${title}三维模型`} />
    <div className="viewport-label"><span className="status-dot" /><strong>{title}</strong><small>{subtitle}</small></div>
    {state !== 'ready' && <div className="viewport-placeholder">
      {state === 'loading' ? <LoaderCircle className="spin" size={32} /> : <Box size={36} strokeWidth={1} />}
      <strong>{state === 'loading' ? '正在读取几何模型' : state === 'error' ? '模型暂时无法显示' : '几何模型将在这里显示'}</strong>
      <span>{state === 'loading' ? '保留装配坐标，加载可交互 3D 场景' : state === 'error' ? error : '上传 STEP 文件，开始建立你的几何项目'}</span>
      {state === 'error' && <button className="button subtle" onClick={() => setRetry((v) => v + 1)}><RotateCcw size={14} />重新加载</button>}
    </div>}
    <div className="viewport-axis"><span className="axis-z">Z ↑</span><span className="axis-x">X ↗</span><span className="axis-y">Y ↘</span><small>原始装配坐标</small></div>
  </div>;
});

function disposeObject(root: THREE.Object3D) {
  const geometries = new Set<THREE.BufferGeometry>(); const materials = new Set<THREE.Material>();
  root.traverse((object) => {
    if (!(object instanceof THREE.Mesh)) return;
    geometries.add(object.geometry);
    (Array.isArray(object.material) ? object.material : [object.material]).forEach((m) => materials.add(m));
  });
  geometries.forEach((g) => g.dispose());
  materials.forEach((m) => {
    Object.values(m).forEach((v) => { if (v instanceof THREE.Texture) v.dispose(); }); m.dispose();
  });
}
