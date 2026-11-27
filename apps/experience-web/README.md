# Orqestra experience web

This React/Vite app is the first goal-oriented experience for the governed
read workflow. It submits only a natural-language goal to
`POST /api/workflows` and renders the evidence-backed report returned by the
control boundary.

The browser sends credentials only through the authenticated session
(`credentials: "include"`). It never sends SQL, connector targets, or
credentials. Set `VITE_CONTROL_API_BASE_URL` when the control API is hosted on
another origin.

```bash
npm install
npm run dev
npm run build
```
