import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The dashboard calls the FastAPI backend directly at http://localhost:8000 (CORS allows this origin).
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true },
})
