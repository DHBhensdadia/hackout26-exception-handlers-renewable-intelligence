import { useEffect, useRef } from "react";
import * as THREE from "three";
import { OBJLoader } from "three/examples/jsm/loaders/OBJLoader.js";
import { MTLLoader } from "three/examples/jsm/loaders/MTLLoader.js";

/*
  Real turbines for the cinematic hero.

  The rotors are the actual WindTurbine.obj rather than a sprite, so the
  blades have real thickness, twist and shading. One WebGL context draws every
  turbine: each gets a scissored viewport and its own orthographic camera,
  which is what lets a hub be pinned to an exact coordinate in the
  photographic plate at an exact on-screen radius. Orthographic also means
  no perspective divergence to fight against a long-lens aerial photo.

  Measured from the mesh, not guessed:
    - the rotor disc is thin along Z, so Z is the shaft axis
    - the three blade tips are equidistant (52.3061) from (-1.1111, 91.3096),
      so that XY point is the shaft centre; it is the pivot used below
    - the hub sits 91.31 units above the tower base, giving the
      hub-height-to-rotor-radius ratio used to place each viewport
*/

const ROTOR_PARTS = ["Hub", "Spinner", "Blade_01", "Blade_02", "Blade_03"];

/** Shaft centre in model space — circumcentre of the three blade tips. */
const PIVOT_X = -1.1111;
const PIVOT_Y = 91.3096;
/** Blade tip radius, identical for all three blades about that centre. */
const TIP_R = 52.3061;
/** Hub height above the tower base, in tip radii. */
const HUB_RISE = PIVOT_Y / TIP_R;

export type HeroTurbine = {
  /** hub position as a percentage of the plate */
  x: number;
  y: number;
  /** rotor radius as a percentage of plate height */
  r: number;
  /** visible tower length below the hub, in plate-height % (clips at the ground) */
  tower: number;
  /** seconds per revolution */
  rev: number;
  /** starting angle in degrees, so no two rotors are ever in step */
  phase: number;
  /** yaw toward the camera, degrees — the farm does not face one way */
  yaw: number;
  /** atmospheric depth: 1 = crisp foreground, 0 = lost in haze */
  tone: number;
};

let cached: Promise<THREE.Group> | null = null;

function loadTurbine(): Promise<THREE.Group> {
  if (!cached) {
    cached = new Promise((resolve, reject) => {
      new MTLLoader().setPath("/models/").load(
        "WindTurbine.mtl",
        (materials) => {
          materials.preload();
          new OBJLoader()
            .setMaterials(materials)
            .setPath("/models/")
            .load("WindTurbine.obj", resolve, undefined, reject);
        },
        undefined,
        reject
      );
    });
  }
  return cached;
}

export function HeroTurbines({ turbines }: { turbines: readonly HeroTurbine[] }) {
  const hostRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = hostRef.current;
    if (!canvas) return;

    let disposed = false;
    let frame = 0;
    let visible = true;

    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)");
    const phone = window.matchMedia("(max-width: 760px)");

    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
    } catch {
      // No WebGL: the photograph alone is a complete composition.
      canvas.style.display = "none";
      return;
    }
    renderer.setClearAlpha(0);
    renderer.setScissorTest(true);

    const scene = new THREE.Scene();

    /* Sunrise from the upper left, matching the plate. Warm key, warm
       bounce, neutral sky fill — deliberately no cool rim, because a blue
       edge on a blade is the exact tell that a model was pasted on. */
    scene.add(new THREE.HemisphereLight(0xfff1d6, 0x6d5f46, 1.85));
    const key = new THREE.DirectionalLight(0xfff0cf, 3.0);
    key.position.set(-7, 8, 6);
    scene.add(key);
    const bounce = new THREE.DirectionalLight(0xf3e8d6, 0.55);
    bounce.position.set(6, -2, 3);
    scene.add(bounce);

    type Rig = { model: THREE.Group; rotor: THREE.Group; cam: THREE.OrthographicCamera; spec: HeroTurbine };
    const rigs: Rig[] = [];

    const layout = () => {
      const w = canvas.clientWidth;
      const h = canvas.clientHeight;
      if (!w || !h) return;
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, phone.matches ? 1 : 1.75));
      renderer.setSize(w, h, false);

      for (const rig of rigs) {
        const { spec, cam } = rig;
        const R = (spec.r / 100) * h;            // rotor radius in CSS px
        const hx = (spec.x / 100) * w;           // hub, in canvas px
        const hy = (spec.y / 100) * h;
        const towerPx = Math.min((spec.tower / 100) * h, HUB_RISE * R);

        // Box the turbine: rotor sweep above, tower clipped at the ground line.
        const pad = R * 1.3;
        const vx = hx - pad;
        const vy = hy - pad;
        const vw = pad * 2;
        const vh = pad + towerPx;

        const scale = R / TIP_R;                 // px per world unit
        const cx = PIVOT_X + (vx + vw / 2 - hx) / scale;
        const cy = PIVOT_Y - (vy + vh / 2 - hy) / scale;

        cam.left = -vw / 2 / scale;
        cam.right = vw / 2 / scale;
        cam.top = vh / 2 / scale;
        cam.bottom = -vh / 2 / scale;
        cam.position.set(cx, cy, 400);
        cam.lookAt(cx, cy, 0);
        cam.updateProjectionMatrix();

        rig.model.userData.rect = [vx, h - (vy + vh), vw, vh];
      }
    };

    loadTurbine()
      .then((source) => {
        if (disposed) return;

        for (const spec of turbines) {
          const model = source.clone(true);

          // Lift the rotor parts onto a pivot sitting exactly on the shaft.
          const rotor = new THREE.Group();
          rotor.position.set(PIVOT_X, PIVOT_Y, 0);
          model.add(rotor);
          for (const name of ROTOR_PARTS) {
            const part = model.getObjectByName(name);
            if (!part) continue;
            part.position.sub(rotor.position);
            rotor.add(part);
          }
          rotor.rotation.z = (spec.phase * Math.PI) / 180;
          model.rotation.y = (spec.yaw * Math.PI) / 180;

          // Own the materials per instance so haze can vary with depth.
          model.traverse((o) => {
            const mesh = o as THREE.Mesh;
            if (!mesh.isMesh) return;
            const src = mesh.material as THREE.Material | THREE.Material[];
            const copy = (m: THREE.Material) => {
              const c = m.clone() as THREE.MeshPhongMaterial;
              if (c.color) c.color.lerp(new THREE.Color(0xffe6c4), (1 - spec.tone) * 0.55);
              c.transparent = true;
              c.opacity = 0.55 + 0.45 * spec.tone;
              c.shininess = 12;
              if (c.specular) c.specular.setScalar(0.06);
              return c;
            };
            mesh.material = Array.isArray(src) ? src.map(copy) : copy(src);
          });

          scene.add(model);
          rigs.push({ model, rotor, cam: new THREE.OrthographicCamera(-1, 1, 1, -1, 0.1, 900), spec });
        }

        layout();
        start();
      })
      .catch(() => {
        if (!disposed) canvas.style.display = "none";
      });

    const still = reduce.matches;
    let last = 0;

    const tick = (now: number) => {
      frame = requestAnimationFrame(tick);
      // Delta-time, so the rate is real rpm rather than a per-frame constant
      // and a slow frame cannot make the rotor stutter.
      const dt = last ? Math.min((now - last) / 1000, 0.1) : 0;
      last = now;
      renderer.clear();
      for (const rig of rigs) {
        if (!still) rig.rotor.rotation.z += (2 * Math.PI * dt) / rig.spec.rev;
        const rect = rig.model.userData.rect as number[] | undefined;
        if (!rect) continue;
        // Draw only this turbine's box, so one context serves the whole farm.
        renderer.setViewport(rect[0], rect[1], rect[2], rect[3]);
        renderer.setScissor(rect[0], rect[1], rect[2], rect[3]);
        for (const other of rigs) other.model.visible = other === rig;
        renderer.render(scene, rig.cam);
      }
    };

    function start() {
      if (!frame && visible && !document.hidden && !disposed && rigs.length) {
        last = 0;
        frame = requestAnimationFrame(tick);
      }
    }
    function stop() {
      if (frame) cancelAnimationFrame(frame);
      frame = 0;
    }

    // A hero that has scrolled away must not keep a GPU busy.
    const io = new IntersectionObserver(
      ([e]) => {
        visible = e.isIntersecting;
        if (visible) start();
        else stop();
      },
      { threshold: 0.02 }
    );
    io.observe(canvas);

    const onVisibility = () => (document.hidden ? stop() : start());
    document.addEventListener("visibilitychange", onVisibility);

    const ro = new ResizeObserver(() => layout());
    ro.observe(canvas);

    return () => {
      disposed = true;
      stop();
      io.disconnect();
      ro.disconnect();
      document.removeEventListener("visibilitychange", onVisibility);
      scene.traverse((o) => {
        const m = o as THREE.Mesh;
        if (m.geometry) m.geometry.dispose();
        const mat = m.material;
        if (Array.isArray(mat)) mat.forEach((x) => x.dispose());
        else if (mat) (mat as THREE.Material).dispose();
      });
      renderer.dispose();
    };
  }, [turbines]);

  return <canvas ref={hostRef} className="cine__webgl" aria-hidden="true" />;
}