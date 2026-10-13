import { realpathSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { transformWithEsbuild } from 'vite'

// DevInspector lives in the sibling visual-prompter component library.
const library = realpathSync(fileURLToPath(new URL('../../../visual-prompter/component-library', import.meta.url)))
const source = realpathSync(`${library}/src`)

const entry = [
  `export { default as DevInspector, DevScope } from ${JSON.stringify(`${source}/components/DevInspector/devInspector.jsx`)}`,
  `export { default as Badge } from ${JSON.stringify(`${source}/components/Badge/badge.jsx`)}`,
  `export { default as ScrollingText } from ${JSON.stringify(`${source}/components/ScrollingText/scrollingText.jsx`)}`,
  `export { useFormReady } from ${JSON.stringify(`${source}/components/GenericForm/useFormController.js`)}`,
].join('\n')

const componentLibrary = () => ({
  name: 'component-library-source',
  enforce: 'pre',
  config() {
    return {
      resolve: {
        dedupe: ['react', 'react-dom'],
        alias: [
          { find: /^component-library$/, replacement: '\0component-library-entry' },
          { find: /^component-library\/dist\/component-library\.css$/, replacement: '\0component-library-css' },
        ],
      },
      // The linked source is outside this app; watch and transform it directly.
      server: { fs: { allow: [fileURLToPath(new URL('.', import.meta.url)), library] } },
      optimizeDeps: {
        exclude: ['component-library'],
        esbuildOptions: { loader: { '.js': 'jsx' } },
      },
    }
  },
  resolveId(id) {
    if (id === '\0component-library-css' || id === '\0component-library-entry') return id
  },
  load(id) {
    // Source components import their own CSS. The built stylesheet stays unused.
    if (id === '\0component-library-css') return 'export {}'
    if (id === '\0component-library-entry') return entry
  },
  transform(code, id) {
    const file = id.split('?')[0]
    if (file.startsWith(`${source}/`) && file.endsWith('.js')) {
      return transformWithEsbuild(code, file, {
        loader: 'jsx',
        jsx: 'automatic',
        jsxDev: process.env.NODE_ENV !== 'production',
      })
    }
  },
})

export default componentLibrary
