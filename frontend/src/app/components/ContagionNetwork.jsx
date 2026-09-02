/**
 * ContagionNetwork — glowing 3D contagion graph (redesign)
 *
 * Build once, update in place. OrbitControls with damping for smooth
 * rotation. UnrealBloomPass so nodes and edges glow. Crisp HTML labels via
 * CSS2DRenderer. Render loop pauses when the tab is hidden.
 */
'use client';

import { useRef, useEffect, useState, memo, useCallback } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js';
import { CSS2DRenderer, CSS2DObject } from 'three/examples/jsm/renderers/CSS2DRenderer.js';
import { RotateCcw, Maximize2, X } from 'lucide-react';

const R = 1.5;                 // sphere radius
const CALM = new THREE.Color(0x3b82f6);
const WARN = new THREE.Color(0xf59e0b);
const HOT = new THREE.Color(0xf43f5e);

function fibonacciSphere(n) {
  const pts = [];
  if (n <= 0) return pts;
  if (n === 1) return [new THREE.Vector3(0, 0, 0)];
  const ga = Math.PI * (3 - Math.sqrt(5));
  for (let i = 0; i < n; i++) {
    const y = 1 - (i / (n - 1)) * 2;
    const r = Math.sqrt(1 - y * y);
    pts.push(new THREE.Vector3(Math.cos(ga * i) * r, y, Math.sin(ga * i) * r));
  }
  return pts;
}

const ContagionNetwork = memo(function ContagionNetwork({ correlationMatrix, assets, crisisMode }) {
  const mount = useRef(null);
  const R3 = useRef({});           // three refs bag
  const [autoRotate, setAutoRotate] = useState(true);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const autoRef = useRef(true);
  const crisisRef = useRef(false);
  useEffect(() => { autoRef.current = autoRotate; if (R3.current.controls) R3.current.controls.autoRotate = autoRotate; }, [autoRotate]);
  useEffect(() => { crisisRef.current = crisisMode; }, [crisisMode]);

  // ── setup (once) ──────────────────────────────────
  useEffect(() => {
    const el = mount.current;
    if (!el) return;
    const w = el.clientWidth || 300;
    const h = el.clientHeight || 260;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(50, w / h, 0.1, 100);
    camera.position.z = 4.4;

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    renderer.setSize(w, h);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setClearColor(0x090a10, 1);
    el.appendChild(renderer.domElement);

    // labels overlay
    const labelRenderer = new CSS2DRenderer();
    labelRenderer.setSize(w, h);
    Object.assign(labelRenderer.domElement.style, { position: 'absolute', top: '0', left: '0', pointerEvents: 'none' });
    el.appendChild(labelRenderer.domElement);

    const group = new THREE.Group();
    group.rotation.x = 0.25;
    scene.add(group);

    // bloom composer
    const composer = new EffectComposer(renderer);
    composer.addPass(new RenderPass(scene, camera));
    const bloom = new UnrealBloomPass(new THREE.Vector2(w, h), 0.9, 0.5, 0.08);
    composer.addPass(bloom);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.06;
    controls.enablePan = false;
    controls.autoRotate = autoRef.current;
    controls.autoRotateSpeed = 1.1;
    controls.minDistance = 2.6;
    controls.maxDistance = 8;

    // faint wireframe shell
    const shell = new THREE.Mesh(
      new THREE.IcosahedronGeometry(R * 1.03, 1),
      new THREE.MeshBasicMaterial({ color: 0x3b82f6, wireframe: true, transparent: true, opacity: 0.07 })
    );
    group.add(shell);

    const clock = new THREE.Clock();
    let raf;
    const animate = () => {
      raf = requestAnimationFrame(animate);
      const t = clock.getElapsedTime();
      controls.autoRotateSpeed = crisisRef.current ? 2.2 : 1.1;
      bloom.strength = crisisRef.current ? 1.5 : 0.9;
      shell.material.color.setHex(crisisRef.current ? 0xf43f5e : 0x3b82f6);
      shell.material.opacity = 0.07 + (crisisRef.current ? 0.06 + Math.sin(t * 3) * 0.03 : 0);
      controls.update();
      composer.render();
      labelRenderer.render(scene, camera);
    };
    animate();

    const onResize = () => {
      const W = el.clientWidth, H = el.clientHeight;
      if (!W || !H) return;
      camera.aspect = W / H; camera.updateProjectionMatrix();
      renderer.setSize(W, H); composer.setSize(W, H); labelRenderer.setSize(W, H);
    };
    window.addEventListener('resize', onResize);

    // pause when tab hidden
    const onVis = () => {
      if (document.hidden) { if (raf) cancelAnimationFrame(raf); raf = null; }
      else if (!raf) animate();
    };
    document.addEventListener('visibilitychange', onVis);

    R3.current = { scene, camera, renderer, labelRenderer, group, composer, bloom, controls, nodes: [], edges: null, onResize };

    return () => {
      if (raf) cancelAnimationFrame(raf);
      window.removeEventListener('resize', onResize);
      document.removeEventListener('visibilitychange', onVis);
      controls.dispose();
      composer.dispose?.();
      renderer.dispose();
      scene.traverse((o) => { o.geometry?.dispose?.(); o.material?.dispose?.(); });
      if (renderer.domElement.parentNode === el) el.removeChild(renderer.domElement);
      if (labelRenderer.domElement.parentNode === el) el.removeChild(labelRenderer.domElement);
      R3.current = {};
    };
  }, []);

  // ── build / update nodes when the asset set changes ──
  useEffect(() => {
    const r = R3.current; if (!r.group) return;
    const tickers = Object.keys(assets || {});
    const sameSet = r.nodes.length === tickers.length && r.nodes.every((n, i) => n.ticker === tickers[i]);
    if (sameSet || tickers.length === 0) return;

    // clear old nodes + labels
    r.nodes.forEach((n) => { r.group.remove(n.mesh); n.mesh.geometry.dispose(); n.mesh.material.dispose(); if (n.label) r.group.remove(n.label); });
    const pos = fibonacciSphere(tickers.length);
    const nodeGeo = new THREE.SphereGeometry(0.055, 20, 20);
    r.nodes = tickers.map((ticker, i) => {
      const p = pos[i].clone().multiplyScalar(R);
      const mesh = new THREE.Mesh(nodeGeo.clone(), new THREE.MeshBasicMaterial({ color: CALM.clone() }));
      mesh.position.copy(p);
      r.group.add(mesh);
      const div = document.createElement('div');
      div.textContent = ticker;
      div.style.cssText = 'font:600 10px/1 var(--font-mono),monospace;color:#c7ceda;text-shadow:0 1px 4px #000;white-space:nowrap;';
      const label = new CSS2DObject(div);
      label.position.copy(p.clone().multiplyScalar(1.14));
      r.group.add(label);
      return { ticker, mesh, label, p };
    });
  }, [assets]);

  // ── update edges + node heat on correlation change ──
  useEffect(() => {
    const r = R3.current; if (!r.group || !r.nodes.length) return;
    const m = correlationMatrix || [];
    const N = r.nodes.length;

    // node heat = mean abs correlation to others
    r.nodes.forEach((n, i) => {
      let s = 0, c = 0;
      for (let j = 0; j < N; j++) { if (i !== j && m[i] && m[i][j] != null) { s += Math.abs(m[i][j]); c++; } }
      const heat = c ? s / c : 0;
      const col = heat > 0.55 ? HOT : heat > 0.32 ? WARN : CALM;
      n.mesh.material.color.copy(col);
      const sc = 0.85 + heat * 0.9;
      n.mesh.scale.setScalar(sc);
    });

    // rebuild edges as one LineSegments (cheap, disposed in place)
    if (r.edges) { r.group.remove(r.edges); r.edges.geometry.dispose(); r.edges.material.dispose(); r.edges = null; }
    const verts = [], cols = [];
    for (let i = 0; i < N; i++) {
      for (let j = i + 1; j < N; j++) {
        const corr = m[i] && m[i][j] != null ? Math.abs(m[i][j]) : 0;
        if (corr < 0.12) continue;
        const a = r.nodes[i].p, b = r.nodes[j].p;
        const col = corr > 0.55 ? HOT : corr > 0.32 ? WARN : CALM;
        verts.push(a.x, a.y, a.z, b.x, b.y, b.z);
        for (let k = 0; k < 2; k++) cols.push(col.r * (0.4 + corr * 0.6), col.g * (0.4 + corr * 0.6), col.b * (0.4 + corr * 0.6));
      }
    }
    if (verts.length) {
      const geo = new THREE.BufferGeometry();
      geo.setAttribute('position', new THREE.Float32BufferAttribute(verts, 3));
      geo.setAttribute('color', new THREE.Float32BufferAttribute(cols, 3));
      r.edges = new THREE.LineSegments(geo, new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.55 }));
      r.group.add(r.edges);
    }
  }, [correlationMatrix]);

  // resize after fullscreen transition
  useEffect(() => { const t = setTimeout(() => R3.current.onResize?.(), 60); return () => clearTimeout(t); }, [isFullscreen]);
  useEffect(() => {
    if (!isFullscreen) return;
    const onKey = (e) => { if (e.key === 'Escape') setIsFullscreen(false); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [isFullscreen]);

  const toggleFullscreen = useCallback(() => setIsFullscreen((v) => !v), []);

  return (
    <div className={`cn-wrapper ${isFullscreen ? 'cn-fullscreen' : ''}`}>
      {isFullscreen && <div className="cn-overlay" onClick={toggleFullscreen} />}
      <div className={`cn-inner ${isFullscreen ? 'cn-inner-fs' : ''}`}>
        <div ref={mount} className={`contagion-canvas-container ${isFullscreen ? 'cn-canvas-fs' : ''}`} style={{ position: 'relative' }} />
        <div className="cn-controls">
          <button className={`cn-btn ${autoRotate ? 'cn-btn-active' : ''}`} onClick={() => setAutoRotate((v) => !v)}>
            <RotateCcw size={13} /> Auto Rotate
          </button>
          <button className={`cn-btn ${isFullscreen ? 'cn-btn-active' : ''}`} onClick={toggleFullscreen}>
            {isFullscreen ? <X size={13} /> : <Maximize2 size={13} />} {isFullscreen ? 'Exit Fullscreen' : 'Fullscreen'}
          </button>
        </div>
        {isFullscreen && <div className="cn-fs-hint">Scroll to zoom. Drag to rotate. Press ESC to exit.</div>}
      </div>
    </div>
  );
});

export default ContagionNetwork;
