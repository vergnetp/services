import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'

export default defineConfig({
  plugins: [svelte()],
  base: '/static/',  // Assets served from /static/ in FastAPI
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        secure: false,
        configure: (proxy, options) => {
          proxy.on('proxyReq', (proxyReq, req, res) => {
            // Log requests for debugging
            console.log(`[Proxy] ${req.method} ${req.url} -> ${options.target}${req.url}`)
          })
        }
      }
    }
  },
  build: {
    outDir: '../static',             // Output directly to FastAPI static folder
    emptyOutDir: true,               // Clean before build
    assetsDir: 'assets',
    sourcemap: false,
    minify: 'esbuild'
  }
})
