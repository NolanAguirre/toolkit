import { realpathSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { transformWithEsbuild } from 'vite'

export default function componentLibrary() {
  let source
  return {
    name: 'component-library-source',
    enforce: 'pre',
    config(_, { command, isPreview }) {
      const shared = { dedupe: ['react', 'react-dom', 'react-virtuoso'] }
      if (command !== 'serve' || isPreview) return { resolve: shared }
      source = realpathSync(fileURLToPath(new URL('../../component-library/src', import.meta.url)))
      return {
        resolve: {
          ...shared,
          alias: [
            { find: /^component-library$/, replacement: `${source}/index.js` },
            { find: /^component-library\/dist\/component-library\.css$/, replacement: '\0component-library-css' },
          ],
        },
        // The linked source is outside this app; watch and transform it directly.
        server: { fs: { allow: [fileURLToPath(new URL('.', import.meta.url)), source] } },
        optimizeDeps: {
          exclude: ['component-library'],
          esbuildOptions: { loader: { '.js': 'jsx' } },
        },
      }
    },
    resolveId(id) {
      if (id === '\0component-library-css') return id
    },
    load(id) {
      // Source components import their own CSS during development.
      if (id === '\0component-library-css') return 'export {}'
    },
    transform(code, id) {
      const file = id.split('?')[0]
      if (source && file.startsWith(`${source}/`) && file.endsWith('.js')) {
        return transformWithEsbuild(code, file, { loader: 'jsx', jsx: 'automatic', jsxDev: true })
      }
    },
  }
}
