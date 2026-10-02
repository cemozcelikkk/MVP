import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // maplibre-gl kendi Web Worker'ını içeriden import ediyor; Vite'ın
  // dependency pre-bundling'i (esbuild) bu worker dosyasını yanlış
  // chunk'lıyor ve "maplibre-gl-worker.mjs" 404 ile sonuçlanıyor -
  // harita sessizce boş kalıyor (tile yok, load event tetiklenmiyor).
  // Bilinen bir maplibre-gl+Vite uyumsuzluğu; paketi optimizasyon
  // dışında bırakmak worker'ın olduğu gibi (bundle edilmeden) servis
  // edilmesini sağlıyor.
  optimizeDeps: {
    exclude: ['maplibre-gl'],
  },
})
