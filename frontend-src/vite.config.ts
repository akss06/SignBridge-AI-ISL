import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev server proxies API calls to the FastAPI backend so fetch('/health') etc.
// work identically to production, where the built app is served BY that same
// backend (see frontend/main deployment notes in README). No backend changes
// needed either way — the API surface is untouched.
export default defineConfig({
  plugins: [react()],
  // Built asset URLs are prefixed with /static/ — that's where the FastAPI
  // backend mounts the dist/ folder in production (see backend/main.py).
  base: '/static/',
  server: {
    proxy: {
      '/health': 'http://localhost:8000',
      '/pipeline': 'http://localhost:8000',
      '/quiz/': 'http://localhost:8000',
      '/outputs': 'http://localhost:8000',
    },
  },
  build: {
    rollupOptions: {
      // Two-page app, same as the original static frontend (index.html + quiz.html).
      input: {
        main: 'index.html',
        quiz: 'quiz.html',
      },
    },
  },
})
