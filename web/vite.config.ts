import { svelte } from '@sveltejs/vite-plugin-svelte'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [tailwindcss(), svelte()],
  // The build ships inside the Python package.
  build: { outDir: '../src/loracraft/web_dist', emptyOutDir: true },
  server: {
    port: 5600,
    proxy: { '/api': 'http://127.0.0.1:8600' },
  },
})
