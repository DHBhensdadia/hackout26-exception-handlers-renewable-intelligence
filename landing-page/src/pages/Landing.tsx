import { useState } from "react";
import { Link } from "react-router-dom";
import { HeroTurbines, type HeroTurbine } from "../components/HeroTurbines";
import "../styles/cinematic.css";

/**
 * Cinematic landing surface.
 *
 * A single photographic plate, used verbatim, with real 3D turbines
 * composited in front of it. Every hub sits on ground that has no painted
 * turbine under it (open ground, or a turbine retouched out of the plate),
 * so a rotating rotor can never double a painted one.
 *
 * Positions are in plate coordinates (% of the photograph, not the
 * viewport) and live inside the transformed stage, so they stay locked to
 * the image at every aspect ratio and right through the camera move.
 */
const TURBINES: readonly HeroTurbine[] = [
  // Hero turbine: stands exactly where the photographed turbine was retouched
  // out of the plate, so the rotor turns on that turbine's own hub. Radius is
  // set so the model's tower lands on the original foundation pad.
  { x: 75.625, y: 50.469, r: 8.33, tower: 14.6, rev: 6.4, phase: 40, yaw: 22, tone: 1 },
  { x: 63.0, y: 53.0, r: 7.2, tower: 20, rev: 5.4, phase: 0, yaw: -22, tone: 1 },
  { x: 84.5, y: 57.0, r: 5.0, tower: 14, rev: 6.2, phase: 137, yaw: 14, tone: 0.78 },
  { x: 33.0, y: 52.0, r: 4.2, tower: 13, rev: 4.9, phase: 274, yaw: -8, tone: 0.55 },
];

const BANDS = [
  { cls: "cine__band--high", dur: "150s" },
  { cls: "cine__band--mid", dur: "104s" },
  { cls: "cine__band--low", dur: "72s" },
] as const;

export default function Landing() {
  // The veil is a full-screen opaque layer. Once it has parted it is dropped
  // from the tree for good, so nothing can ever replay it into a white-out
  // and the compositor stops carrying it.
  const [veiled, setVeiled] = useState(
    () => !window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );

  return (
    <main className="cine">
      <h1 className="sr-only">
        re-forecast — renewable energy intelligence platform
      </h1>

      <div className="cine__camera">
        <div className="cine__stage">
          <img
            className="cine__poster"
            src="/images/hero-sunrise.webp"
            alt="A wind farm and solar field at sunrise, seen from above the cloud layer across open scrub country."
            width={1920}
            height={1280}
            fetchPriority="high"
            decoding="async"
            draggable={false}
          />
          <HeroTurbines turbines={TURBINES} />
        </div>
      </div>

      <div className="cine__weather" aria-hidden="true">
        {veiled && (
          <div className="cine__veil" onAnimationEnd={() => setVeiled(false)} />
        )}
        {BANDS.map((b) => (
          <div
            key={b.cls}
            className={`cine__band ${b.cls}`}
            style={{ "--dur": b.dur } as React.CSSProperties}
          >
            <i />
            <i />
          </div>
        ))}
      </div>

      <div className="cine__haze" aria-hidden="true" />
      <div className="cine__scrim" aria-hidden="true" />

      <div className="cine__ui">
        <Link to="/" className="cine__mark">
          re-forecast
        </Link>

        <div className="cine__foot">
          <p className="cine__note">Renewable energy intelligence</p>
          <Link to="/dashboard" className="cine__cta">
            Open Dashboard
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M4.5 12h14" />
              <path d="M12.5 5.5 19 12l-6.5 6.5" />
            </svg>
          </Link>
        </div>
      </div>
    </main>
  );
}
