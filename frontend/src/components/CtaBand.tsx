import { HudButton } from "./ui";

export function CtaBand() {
  return (
    <section className="cta-band section" id="cta">
      <div className="wrap">
        <span className="eyebrow reveal">From forecast to decision</span>
        <h2 className="h1 reveal d1">Predict renewable power. Act on it.</h2>
        <p className="lead reveal d2" style={{ textAlign: "center" }}>
          Failure to act on a &ldquo;surplus&rdquo; or &ldquo;shortage&rdquo; warning is the
          only wrong decision. Open the dashboard to see the 24–72 hour forecast
          and the operational calls it supports.
        </p>
        <div className="reveal d3">
          <HudButton to="/dashboard">Open the dashboard</HudButton>
        </div>
      </div>
    </section>
  );
}