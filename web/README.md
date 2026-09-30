# EdgeForge web

Angular app for the match comparison. It reads everything from the Python API
(`/api/...`).

```bash
npm ci
npm start            # http://localhost:4200, proxies /api to `uv run edgeforge serve` on :8000
npm test             # unit tests (Vitest)
npm run build        # production build into dist/web/browser, served by `edgeforge serve`
```
