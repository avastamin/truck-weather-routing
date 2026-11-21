import { copyFileSync, mkdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import react from '@vitejs/plugin-react'
import { defineConfig, type Plugin } from 'vite'

// MapLibre runs tile parsing in a web worker. Vite's dev server rewrites the worker file and
// breaks it, so we serve an untouched copy from public/ instead (see RouteMap.tsx).
function maplibreWorker(): Plugin {
  return {
    name: 'maplibre-worker',
    buildStart() {
      const src = fileURLToPath(
        new URL('./node_modules/maplibre-gl/dist/maplibre-gl-worker.mjs', import.meta.url),
      )
      mkdirSync(new URL('./public', import.meta.url), { recursive: true })
      copyFileSync(src, new URL('./public/maplibre-gl-worker.mjs', import.meta.url))
    },
  }
}

export default defineConfig({
  plugins: [react(), maplibreWorker()],
})
