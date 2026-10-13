import { DevInspector, DevScope } from 'component-library'
import 'component-library/dist/component-library.css'
import SessionExplorer from './components/HarnessInspector/sessionExplorer'
import harnessForms from './components/HarnessInspector/harnessForms'

const harnessViews = [{ id: 'harness-sessions', title: 'Harness sessions', icon: '☷', component: SessionExplorer }]

const DevTools = ({ children }) => (
  <DevInspector enabled forms={harnessForms} views={harnessViews}>
    {children}
  </DevInspector>
)

export { DevTools, DevScope }
