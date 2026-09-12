# Re-Forecast — Landing Page

Cinematic landing page for the **Renewable Energy Intelligence Platform**.

## Quick Start

```bash
# Clone only this folder (Git sparse checkout)
git clone --filter=blob:none --sparse https://github.com/DHBhensdadia/hackout26-exception-handlers-renewable-intelligence.git
cd hackout26-exception-handlers-renewable-intelligence
git sparse-checkout set landing-page
cd landing-page

# Install & run
npm install
npm run dev
```

Or, if you already have the full repo:

```bash
cd landing-page
npm install
npm run dev
```

## What's Inside

```
landing-page/
├── public/
│   ├── fonts/          # Self-hosted Satoshi, Quicksand, SUSE, Josefin Sans
│   ├── images/         # Hero sunrise photo & compositing assets
│   ├── models/         # WindTurbine.obj/mtl (real 3D turbines in the hero)
│   └── favicon.svg
├── src/
│   ├── components/
│   │   ├── HeroTurbines.tsx   # WebGL wind-turbine renderer (Three.js)
│   │   └── Shell.tsx          # Scroll-to-top & reveal helpers
│   ├── pages/
│   │   └── Landing.tsx        # The cinematic hero page
│   ├── styles/
│   │   ├── tokens.css         # Design tokens (colors, type, spacing)
│   │   ├── global.css         # Base & component styles
│   │   └── cinematic.css      # Hero-specific animations & layout
│   └── main.tsx               # App entry point
├── index.html
├── package.json
└── vite.config.ts
```

## Tech Stack

- **React 19** + **TypeScript**
- **Vite 6** (dev server + build)
- **Three.js** — real OBJ turbine models rendered in WebGL
- **Tailwind CSS 4** (via Vite plugin)
- Self-hosted fonts (no external CDN dependency)

## Build for Production

```bash
npm run build
npm run preview   # preview the built version
```

The production bundle is output to `dist/`.
