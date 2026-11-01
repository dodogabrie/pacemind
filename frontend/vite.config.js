import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    // Allow access from nginx proxy container
    allowedHosts: ['frontend', 'localhost'],
    hmr: {
      // HMR connects through nginx on the client side
      clientPort: Number(process.env.VITE_HMR_PORT) || 8080,
    },
  },
})
