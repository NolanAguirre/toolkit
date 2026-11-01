import { createHarnessPlugin, DevInspector, DevScope } from 'component-library'
import 'component-library/dist/component-library.css'

const harness = createHarnessPlugin({
  baseUrl: import.meta.env.VITE_HARNESS_API_BASE || '/dashboard/harness-api',
  workspace: { name: 'toolkit', cwdPatterns: [/\/toolkit\/?$/, /\/dashboard\/?$/], label: 'toolkit' },
})

const DevTools = ({ children }) => (
  <DevInspector enabled forms={harness.forms} views={harness.views}>
    {children}
  </DevInspector>
)

export { DevTools, DevScope }
