# BrandGuard web console

React + Vite + TypeScript + Tailwind. Talks to the Python API under `/api`.

    npm install
    npm run dev      # http://localhost:5173, proxies /api to http://127.0.0.1:8000
    npm run build    # writes dist/, which python -m brandguard.api serves at /

No component library: `src/index.css` holds the design tokens (one accent,
category colours only on badges, light and dark) and the few primitives the
pages use. `src/api.ts` mirrors `brandguard/api/schemas.py`.
