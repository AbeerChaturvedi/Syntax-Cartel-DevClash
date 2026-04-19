/**
 * ContagionNetwork — Three.js 3D spherical network graph
 *
 * Features:
 * - 3D sphere with thick nodes and cylinder connections
 * - Theme-aware labels: dark slate in light mode, white in dark mode
 * - Manual orbit controls (drag to rotate)
 * - Auto-rotate toggle with tilted orbital wobble
 * - Fullscreen mode with smooth camera zoom enabled
 * - Camera reset animation on exit fullscreen
 * - Mouse wheel zoom disabled in standard mode, enabled in fullscreen
 */
'use client';

import { useRef, useEffect, useState, memo, useCallback } from 'react';
import * as THREE from 'three';
import { RotateCcw, Maximize2, X } from 'lucide-react';

const DEFAULT_CAM_Z = 4.5;
const FULLSCREEN_CAM_Z = 3.8;

/* ── Fibonacci sphere point distribution ──────────── */
function fibonacciSphere(n) {
  const points = [];
  if (n <= 0) return points;
  if (n === 1) {
    points.push(new THREE.Vector3(0, 0, 0));
    return points;
  }
  const goldenAngle = Math.PI * (3 - Math.sqrt(5));
  for (let i = 0; i < n; i++) {
    const y = 1 - (i / (n - 1)) * 2;
    const radiusAtY = Math.sqrt(1 - y * y);
    const theta = goldenAngle * i;
    points.push(new THREE.Vector3(
      Math.cos(theta) * radiusAtY,
      y,
      Math.sin(theta) * radiusAtY,
    ));
  }
  return points;
}

/* ── Detect current theme ────────────────────────────── */
function isDarkMode() {
  if (typeof document === 'undefined') return false;
  return document.documentElement.classList.contains('dark');
}

const ContagionNetwork = memo(function ContagionNetwork({ correlationMatrix, assets, crisisMode }) {
  const containerRef = useRef(null);
  const rendererRef = useRef(null);
  const sceneRef = useRef(null);
  const cameraRef = useRef(null);
  const animRef = useRef(null);
  const isDragging = useRef(false);
  const prevMouse = useRef({ x: 0, y: 0 });
  const sphereGroupRef = useRef(null);
  const rotationSpeed = useRef({ x: 0, y: 0 });
  const autoRotateRef = useRef(true);
  const fullscreenRef = useRef(false);
  const sceneInitialized = useRef(false);
  const timeRef = useRef(0);
  const labelSpritesRef = useRef([]);
  const targetCamZ = useRef(DEFAULT_CAM_Z);

  const [autoRotate, setAutoRotate] = useState(true);
  const [isFullscreen, setIsFullscreen] = useState(false);

  // Keep refs in sync
  useEffect(() => { autoRotateRef.current = autoRotate; }, [autoRotate]);
  useEffect(() => {
    fullscreenRef.current = isFullscreen;
    targetCamZ.current = isFullscreen ? FULLSCREEN_CAM_Z : DEFAULT_CAM_Z;
  }, [isFullscreen]);

  // ── Handle theme changes for label colors ─────────
  useEffect(() => {
    const observer = new MutationObserver(() => {
      updateLabelColors();
    });
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['class'],
    });
    return () => observer.disconnect();
  }, []);

  function updateLabelColors() {
    const dark = isDarkMode();
    const color = dark ? '#d4d8e0' : '#1f2937';
    labelSpritesRef.current.forEach(({ sprite, ticker }) => {
      const canvas = document.createElement('canvas');
      canvas.width = 128;
      canvas.height = 40;
      const ctx = canvas.getContext('2d');
      ctx.font = 'bold 22px Inter, system-ui, sans-serif';
      ctx.fillStyle = color;
      ctx.textAlign = 'center';
      ctx.fillText(ticker, 64, 28);
      if (sprite.material.map) sprite.material.map.dispose();
      sprite.material.map = new THREE.CanvasTexture(canvas);
      sprite.material.needsUpdate = true;
    });
  }

  // ── Mouse wheel handler ───────────────────────────
  const onWheel = useCallback((e) => {
    if (!fullscreenRef.current) return; // Block zoom in standard mode
    e.preventDefault();
    const camera = cameraRef.current;
    if (!camera) return;
    const delta = e.deltaY * 0.005;
    const newZ = Math.max(1.5, Math.min(8, camera.position.z + delta));
    camera.position.z = newZ;
    targetCamZ.current = newZ;
  }, []);

  // ── Scene setup (runs once) ───────────────────────
  useEffect(() => {
    const container = containerRef.current;
    if (!container || sceneInitialized.current) return;
    sceneInitialized.current = true;

    const width = container.clientWidth;
    const height = container.clientHeight;

    const scene = new THREE.Scene();
    scene.background = null;
    sceneRef.current = scene;

    const camera = new THREE.PerspectiveCamera(50, width / height, 0.1, 100);
    camera.position.z = DEFAULT_CAM_Z;
    cameraRef.current = camera;

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setClearColor(0x000000, 0);
    container.appendChild(renderer.domElement);
    rendererRef.current = renderer;

    // Lighting
    scene.add(new THREE.AmbientLight(0xffffff, 0.6));
    const dirLight = new THREE.DirectionalLight(0xffffff, 0.8);
    dirLight.position.set(5, 5, 5);
    scene.add(dirLight);
    const backLight = new THREE.DirectionalLight(0xffffff, 0.3);
    backLight.position.set(-3, -3, -3);
    scene.add(backLight);

    // Network group
    const sphereGroup = new THREE.Group();
    sphereGroup.rotation.x = 0.3;
    sphereGroup.rotation.z = 0.15;
    scene.add(sphereGroup);
    sphereGroupRef.current = sphereGroup;

    // Manual orbit controls
    const onPointerDown = (e) => {
      isDragging.current = true;
      prevMouse.current = { x: e.clientX, y: e.clientY };
      rotationSpeed.current = { x: 0, y: 0 };
    };
    const onPointerMove = (e) => {
      if (!isDragging.current) return;
      const dx = e.clientX - prevMouse.current.x;
      const dy = e.clientY - prevMouse.current.y;
      rotationSpeed.current = { x: dy * 0.005, y: dx * 0.005 };
      sphereGroup.rotation.x += dy * 0.005;
      sphereGroup.rotation.y += dx * 0.005;
      prevMouse.current = { x: e.clientX, y: e.clientY };
    };
    const onPointerUp = () => { isDragging.current = false; };

    container.addEventListener('pointerdown', onPointerDown);
    container.addEventListener('pointermove', onPointerMove);
    container.addEventListener('pointerup', onPointerUp);
    container.addEventListener('pointerleave', onPointerUp);
    container.addEventListener('wheel', onWheel, { passive: false });

    // Animation loop
    const clock = new THREE.Clock();
    const animate = () => {
      animRef.current = requestAnimationFrame(animate);
      const delta = clock.getDelta();
      timeRef.current += delta;

      // Smooth camera Z interpolation (zoom transitions)
      const camDiff = targetCamZ.current - camera.position.z;
      if (Math.abs(camDiff) > 0.01) {
        camera.position.z += camDiff * 0.08;
      }

      if (!isDragging.current) {
        if (autoRotateRef.current) {
          sphereGroup.rotation.y += 0.008;
          sphereGroup.rotation.x = 0.3 + Math.sin(timeRef.current * 0.3) * 0.12;
          sphereGroup.rotation.z = 0.15 + Math.cos(timeRef.current * 0.2) * 0.08;
        } else {
          sphereGroup.rotation.x += rotationSpeed.current.x;
          sphereGroup.rotation.y += rotationSpeed.current.y;
          rotationSpeed.current.x *= 0.95;
          rotationSpeed.current.y *= 0.95;
        }
      }

      renderer.render(scene, camera);
    };
    animate();

    // Resize
    const handleResize = () => {
      const w = container.clientWidth;
      const h = container.clientHeight;
      if (w === 0 || h === 0) return;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    };
    window.addEventListener('resize', handleResize);

    return () => {
      sceneInitialized.current = false;
      if (animRef.current) cancelAnimationFrame(animRef.current);
      window.removeEventListener('resize', handleResize);
      container.removeEventListener('pointerdown', onPointerDown);
      container.removeEventListener('pointermove', onPointerMove);
      container.removeEventListener('pointerup', onPointerUp);
      container.removeEventListener('pointerleave', onPointerUp);
      container.removeEventListener('wheel', onWheel);
      if (renderer.domElement && container.contains(renderer.domElement)) {
        container.removeChild(renderer.domElement);
      }
      renderer.dispose();
      scene.clear();
    };
  }, [onWheel]);

  // ── Resize renderer when fullscreen toggles ───────
  useEffect(() => {
    const container = containerRef.current;
    const renderer = rendererRef.current;
    const camera = cameraRef.current;
    if (!container || !renderer || !camera) return;

    // Small delay to let CSS transition finish
    const timer = setTimeout(() => {
      const w = container.clientWidth;
      const h = container.clientHeight;
      if (w === 0 || h === 0) return;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    }, 50);

    return () => clearTimeout(timer);
  }, [isFullscreen]);

  // ── Update network data ───────────────────────────
  useEffect(() => {
    const sphereGroup = sphereGroupRef.current;
    if (!sphereGroup) return;

    // Clear previous meshes
    while (sphereGroup.children.length > 0) {
      const child = sphereGroup.children[0];
      sphereGroup.remove(child);
      if (child.geometry) child.geometry.dispose();
      if (child.material) {
        if (child.material.map) child.material.map.dispose();
        child.material.dispose();
      }
    }
    labelSpritesRef.current = [];

    const tickers = Object.keys(assets || {});
    if (tickers.length === 0) return;

    const nodeCount = tickers.length;
    const positions = fibonacciSphere(nodeCount);
    const sphereRadius = 1.5;
    const nodeColor = new THREE.Color(0xEF4444);
    const dark = isDarkMode();
    const labelColor = dark ? '#d4d8e0' : '#1f2937';

    // Nodes + labels
    const nodeMeshes = [];
    const nodeGeometry = new THREE.SphereGeometry(0.08, 16, 16);

    for (let i = 0; i < nodeCount; i++) {
      const pos = positions[i].clone().multiplyScalar(sphereRadius);
      const ticker = tickers[i];

      const nodeMaterial = new THREE.MeshPhongMaterial({
        color: nodeColor,
        emissive: nodeColor,
        emissiveIntensity: 0.3,
        shininess: 80,
      });

      const mesh = new THREE.Mesh(nodeGeometry, nodeMaterial);
      mesh.position.copy(pos);
      sphereGroup.add(mesh);
      nodeMeshes.push({ mesh, ticker, position: pos });

      // Theme-aware label
      const canvas = document.createElement('canvas');
      canvas.width = 128;
      canvas.height = 40;
      const ctx = canvas.getContext('2d');
      ctx.font = 'bold 22px Inter, system-ui, sans-serif';
      ctx.fillStyle = labelColor;
      ctx.textAlign = 'center';
      ctx.fillText(ticker, 64, 28);

      const texture = new THREE.CanvasTexture(canvas);
      const spriteMaterial = new THREE.SpriteMaterial({
        map: texture,
        transparent: true,
        opacity: 0.9,
      });
      const sprite = new THREE.Sprite(spriteMaterial);
      sprite.position.copy(pos.clone().multiplyScalar(1.15));
      sprite.scale.set(0.5, 0.16, 1);
      sphereGroup.add(sprite);
      labelSpritesRef.current.push({ sprite, ticker });
    }

    // Connections
    const matrix = correlationMatrix || [];
    for (let i = 0; i < nodeMeshes.length; i++) {
      for (let j = i + 1; j < nodeMeshes.length; j++) {
        let corr = 0;
        if (matrix[i] && matrix[i][j] !== undefined) {
          corr = Math.abs(matrix[i][j]);
        }
        if (corr < 0.1) continue;

        const strength = Math.min(corr, 1);
        const p1 = nodeMeshes[i].position;
        const p2 = nodeMeshes[j].position;
        const distance = new THREE.Vector3().subVectors(p2, p1).length();
        const midpoint = new THREE.Vector3().addVectors(p1, p2).multiplyScalar(0.5);
        const tubeRadius = 0.008 + strength * 0.025;

        let edgeColor;
        if (strength > 0.6) edgeColor = new THREE.Color(0xEF4444);
        else if (strength > 0.35) edgeColor = new THREE.Color(0xc55a0e);
        else edgeColor = new THREE.Color(0x8e93a0);

        const edgeGeometry = new THREE.CylinderGeometry(tubeRadius, tubeRadius, distance, 6, 1);
        const edgeMaterial = new THREE.MeshPhongMaterial({
          color: edgeColor,
          emissive: edgeColor,
          emissiveIntensity: strength > 0.5 ? 0.15 : 0.03,
          transparent: true,
          opacity: 0.3 + strength * 0.5,
        });

        const edgeMesh = new THREE.Mesh(edgeGeometry, edgeMaterial);
        edgeMesh.position.copy(midpoint);
        edgeMesh.lookAt(p2);
        edgeMesh.rotateX(Math.PI / 2);
        sphereGroup.add(edgeMesh);
      }
    }

    // Wireframe sphere
    const wireGeometry = new THREE.IcosahedronGeometry(sphereRadius * 1.02, 1);
    const wireMaterial = new THREE.MeshBasicMaterial({
      color: dark ? 0x4a4f5c : 0xc0c4cc,
      wireframe: true,
      transparent: true,
      opacity: 0.06,
    });
    sphereGroup.add(new THREE.Mesh(wireGeometry, wireMaterial));
  }, [correlationMatrix, assets, crisisMode]);

  // ── Fullscreen toggle ─────────────────────────────
  const toggleFullscreen = useCallback(() => {
    setIsFullscreen((prev) => {
      const next = !prev;
      if (!next) {
        // Exiting fullscreen: reset camera to default
        targetCamZ.current = DEFAULT_CAM_Z;
      }
      return next;
    });
  }, []);

  // ESC key to exit fullscreen
  useEffect(() => {
    if (!isFullscreen) return;
    const onKey = (e) => {
      if (e.key === 'Escape') setIsFullscreen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [isFullscreen]);

  return (
    <div className={`cn-wrapper ${isFullscreen ? 'cn-fullscreen' : ''}`}>
      {/* Fullscreen overlay backdrop */}
      {isFullscreen && (
        <div className="cn-overlay" onClick={toggleFullscreen} />
      )}

      <div className={`cn-inner ${isFullscreen ? 'cn-inner-fs' : ''}`}>
        {/* Canvas */}
        <div
          ref={containerRef}
          className={`contagion-canvas-container ${isFullscreen ? 'cn-canvas-fs' : ''}`}
        />

        {/* Button row */}
        <div className="cn-controls">
          <button
            className={`cn-btn ${autoRotate ? 'cn-btn-active' : ''}`}
            onClick={() => setAutoRotate(prev => !prev)}
          >
            <RotateCcw size={13} />
            Auto Rotate
          </button>
          <button
            className={`cn-btn ${isFullscreen ? 'cn-btn-active' : ''}`}
            onClick={toggleFullscreen}
          >
            {isFullscreen ? <X size={13} /> : <Maximize2 size={13} />}
            {isFullscreen ? 'Exit Fullscreen' : 'Fullscreen'}
          </button>
        </div>

        {/* Fullscreen hint */}
        {isFullscreen && (
          <div className="cn-fs-hint">
            Scroll to zoom. Drag to rotate. Press ESC to exit.
          </div>
        )}
      </div>
    </div>
  );
});

export default ContagionNetwork;
