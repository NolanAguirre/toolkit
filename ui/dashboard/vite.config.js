import { readFileSync } from 'node:fs'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import componentLibrary from './component-library.js'

// envdir (make start) or explicit environment values override these defaults.
const env = (name) => process.env[name] || readFileSync(new URL(`./env-dir/default/${name}`, import.meta.url), 'utf8').trim()
const apiEnv = (name) => {
  const user = process.env.ENV_USER || process.env.USER || 'default'
  const directory = /^[a-zA-Z0-9_-]+$/.test(user) ? user : 'default'
  try {
    return readFileSync(new URL(`../../services/api/env-dir/${directory}/${name}`, import.meta.url), 'utf8').trim()
  } catch {
    return readFileSync(new URL(`../../services/api/env-dir/default/${name}`, import.meta.url), 'utf8').trim()
  }
}

export default defineConfig({
  base: '/dashboard/',
  plugins: [componentLibrary(), react()],
  server: {
    host: env('HOST'), port: Number(env('PORT')), strictPort: true,
    proxy: {
      '/api': { target: process.env.API_URL || `http://${apiEnv('HOST')}:${apiEnv('PORT')}` },
      '/dashboard/harness-api': {
        target: process.env.HARNESS_PROXY_TARGET || 'http://127.0.0.1:6000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/dashboard\/harness-api/, '/api'),
      },
    },
  },
})
