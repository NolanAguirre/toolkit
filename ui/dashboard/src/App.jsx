import { useEffect, useState } from 'react'

let DevTools = ({ children }) => children
let DevScope = ({ children }) => children
if (import.meta.env.DEV) {
  const dev = await import('./devInspector.jsx')
  DevTools = dev.DevTools
  DevScope = dev.DevScope
}

async function api(url, body, signal) {
  const response = await fetch(url, {
    signal,
    ...(body === undefined ? {} : {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Toolkit-Request': '1' },
      body: JSON.stringify(body),
    }),
  })
  const data = await response.json()
  if (!response.ok) throw new Error(data.error || 'The request failed.')
  return data
}

const options = {
  create: [['nginx', 'Nginx reverse proxy']],
  services: [['http', 'HTTP port'], ['fs', 'Filesystem storage'], ['db', 'Same-name database']],
  uis: [['component-library', 'Existing component library']],
}
const labels = { create: 'New repository', import: 'Import repository', services: 'Add Node.js service', uis: 'Add React UI', databases: 'Add database' }

function CreateForm({ kind, repo, parentPath, busy, setBusy, onComplete, onClose }) {
  const [name, setName] = useState('')
  const [directory, setDirectory] = useState(kind === 'create' ? parentPath : '')
  const [support, setSupport] = useState(kind === 'services' ? ['http'] : [])
  const [engine, setEngine] = useState('sqlite')
  const [error, setError] = useState('')
  const [created, setCreated] = useState(false)
  const pattern = kind === 'databases' ? '[a-z][a-z0-9_]{0,62}' : kind === 'create' ? '[A-Za-z0-9][A-Za-z0-9._-]*' : '[a-z0-9][a-z0-9._-]*'

  async function submit(event) {
    event.preventDefault()
    setBusy(true)
    setError('')
    let result
    try {
      const endpoint = kind === 'create' ? '/api/repos' : kind === 'import' ? '/api/repos/import' : `/api/repos/${encodeURIComponent(repo.name)}/${kind}`
      const body = kind === 'import' ? { path: directory } : { name, support: kind === 'databases' ? [engine] : support, ...(kind === 'create' ? { parentPath: directory } : {}) }
      result = await api(endpoint, body)
      setCreated(true)
    } catch (failure) {
      setError(failure.message)
    }
    if (result) await onComplete(result.path, kind)
    setBusy(false)
  }

  return <DevScope id="s5d2f6g" state={{ kind, busy, created, error: Boolean(error) }}><section className="panel form-panel" aria-labelledby="form-title">
    <div className="panel-heading"><div><p className="eyebrow">{repo && !['create', 'import'].includes(kind) ? repo.name : 'WORKSPACE'}</p><h2 id="form-title">{labels[kind]}</h2></div><button type="button" disabled={busy} onClick={onClose}>Cancel</button></div>
    <form onSubmit={submit}>
      <fieldset disabled={busy || created}>
        {kind !== 'import' && <label>Name<input required autoFocus value={name} onChange={event => setName(event.target.value)} pattern={pattern} maxLength={kind === 'databases' ? 63 : 128} placeholder={kind === 'create' ? 'my-project' : kind === 'services' ? 'api' : kind === 'uis' ? 'dashboard' : 'app'} /></label>}
        {['create', 'import'].includes(kind) && <label>{kind === 'create' ? 'Parent directory' : 'Existing repository path'}<input required autoFocus={kind === 'import'} value={directory} onChange={event => setDirectory(event.target.value)} placeholder="/home/you/projects/my-project" pattern="/.*" /><span className="hint">{kind === 'create' ? `Creates a new directory${name ? ` named ${name}` : ''} here using your shared ~/.s6craft rules.` : 'Must contain a services/ directory. Existing files are preserved; ports are discovered and registered.'}</span></label>}
        {kind === 'databases' && <label>Database backend<select value={engine} onChange={event => setEngine(event.target.value)}><option value="sqlite">SQLite</option><option value="postgres">PostgreSQL</option></select><span className="hint">Creates a Sqitch scaffold and registers it. Does not run migrations.</span></label>}
        {options[kind] && <div className="options">{options[kind].map(([value, label]) => <label className="checkbox" key={value}><input type="checkbox" checked={support.includes(value)} onChange={event => setSupport(event.target.checked ? [...support, value] : support.filter(option => option !== value))} />{label}</label>)}</div>}
        {kind === 'services' && <p className="hint">Creates the Node.js package and environment files. Add application code before starting it. Database support requires a database with this service’s name.</p>}
        {kind === 'uis' && <p className="hint">Creates a React/Vite app. Component library support requires component-library/ in this repo. Install dependencies after scaffolding.</p>}
        <button className="primary" type="submit">{busy ? 'Working…' : labels[kind]}</button>
      </fieldset>
      {error && <div className="form-error" role="alert"><p>{error}</p><span className="hint">Check the repository before retrying if bootstrap reports partial work.</span></div>}
    </form>
  </section></DevScope>
}

function ResourceList({ title, items, kind, onAdd, busy, devId }) {
  return <DevScope id={devId} state={{ kind, count: items.length }}><section className="panel resource-panel">
    <div className="panel-heading"><h2>{title} <span className="count">{items.length}</span></h2><button aria-label={labels[kind]} disabled={busy} onClick={() => onAdd(kind)}>+ Add</button></div>
    {items.length === 0 ? <p className="empty">No {title.toLowerCase()} yet.</p> : <ul className="resources">{items.map(item => <li key={item.name}><div><strong>{item.name}</strong><span className="path">{item.path}</span></div>{item.port && <span className="badge">Port {item.port}</span>}</li>)}</ul>}
  </section></DevScope>
}

function ReleaseIdentity({ title, release }) {
  return <div className="release-identity"><h4>{title}</h4><dl>
    <dt>Release</dt><dd>{release.release || 'Unknown'}</dd>
    <dt>{release.commit_source === 'artifact' ? 'Packaged commit' : 'Checkout commit at deployment'}</dt><dd><code>{release.commit || 'Unknown'}</code></dd>
    <dt>Archive SHA-256</dt><dd><code>{release.archive_sha256 || 'Unknown'}</code></dd>
    {release.dirty && <><dt>Checkout changes</dt><dd>{release.dirty === 'true' ? 'Uncommitted changes present' : release.dirty === 'false' ? 'Clean at deployment' : 'Unknown'}</dd></>}
    {release.deployed_at && <><dt>Deployed</dt><dd>{release.deployed_at}</dd></>}
  </dl>{release.commit_source === 'checkout-at-deploy' && <p className="hint">This commit was observed in the checkout when deploying. It does not prove which commit built the artifact.</p>}</div>
}

function DeploymentView({ data, repo, busy, setBusy }) {
  const [live, setLive] = useState(null)
  const [checking, setChecking] = useState(false)
  const [releasePath, setReleasePath] = useState('')
  const [service, setService] = useState('')
  const [deploying, setDeploying] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const [target, setTarget] = useState(data.remoteConnection)
  const [connection, setConnection] = useState(data.remoteConnection?.legacy ? '' : data.remoteConnection?.host || '')
  const [sshUser, setSshUser] = useState(data.remoteConnection?.user || '')
  const [sshPort, setSshPort] = useState(data.remoteConnection?.port?.toString() || '')
  const [identityFile, setIdentityFile] = useState(data.remoteConnection?.identityFile || '')
  const [targetChanged, setTargetChanged] = useState(false)
  const [targetError, setTargetError] = useState(data.remoteError || '')
  const [targetNotice, setTargetNotice] = useState('')
  async function saveTarget(event) {
    event.preventDefault()
    setBusy(true)
    setTargetError('')
    setTargetNotice('')
    try {
      const saved = await api(`/api/repos/${encodeURIComponent(repo.name)}/target`, {
        connection,
        ...(sshUser ? { user: sshUser } : {}),
        ...(sshPort ? { port: Number(sshPort) } : {}),
        ...(identityFile ? { identityFile } : {}),
      })
      setTarget(saved.target)
      setConnection(saved.target.host)
      setSshUser(saved.target.user)
      setSshPort(String(saved.target.port))
      setIdentityFile(saved.target.identityFile || '')
      setTargetChanged(false)
      setTargetNotice('Target saved. No host connection was made.')
      setLive(null)
      setResult(null)
      setError('')
    } catch (failure) { setTargetError(failure.message) }
    finally { setBusy(false) }
  }
  async function checkHost() {
    setChecking(true)
    setLive(null)
    try {
      setLive(await api(`/api/repos/${encodeURIComponent(repo.name)}/releases`))
    } catch (error) {
      setLive({ error: error.message, services: [], checkedAt: new Date().toISOString() })
    } finally { setChecking(false) }
  }
  async function deploy(event) {
    event.preventDefault()
    if (busy || checking) return
    setBusy(true)
    setDeploying(true)
    setResult(null)
    setError('')
    setLive(null)
    try {
      setResult(await api(`/api/repos/${encodeURIComponent(repo.name)}/deployments`, { releasePath, ...(service ? { service } : {}) }))
    } catch (failure) {
      setError(failure.message)
    } finally {
      setDeploying(false)
      await checkHost()
      setBusy(false)
    }
  }
  return <DevScope id="r9t3y7u" state={{ repo: repo.name, checking, deploying, live: live?.error ? 'error' : live ? 'checked' : 'idle' }}><section className="panel">
    <div className="panel-heading"><div><h2>Deployments</h2><p>Running services, release identities, and local packages</p></div><button onClick={checkHost} disabled={busy || checking || !target || targetChanged}>{checking ? 'Checking host…' : 'Check host via SSH'}</button></div>
    <div className="deployment-summary"><div><span className="eyebrow">REMOTE TARGET</span><p>{target ? `${target.user ? `${target.user}@` : ''}${target.host}${target.port ? ` · port ${target.port}` : ''}` : 'No registered target'}</p></div><div><span className="eyebrow">LIVE STATUS</span><p>{checking ? 'Checking…' : live?.error ? 'Check failed' : live ? 'Checked' : 'Not checked'}</p></div></div>
    <form className="deploy-form" onSubmit={saveTarget} onChange={() => { setTargetChanged(true); setTargetNotice('') }} aria-label="Deployment target">
      <h3>Deployment target</h3>
      {target?.legacy && <p className="notice">This target uses a legacy SSH alias. Save an IP address, DNS hostname or connection string to replace it.</p>}
      <fieldset disabled={busy || checking}>
        <label>Host or SSH connection<input required value={connection} onChange={event => { setConnection(event.target.value); setSshUser(''); setSshPort('') }} placeholder="192.168.1.50 or ssh://deploy@example.com:2222" /><span className="hint">Accepts an IP address, DNS hostname, user@host or ssh://user@host:port.</span></label>
        <label>SSH user<input value={sshUser} onChange={event => setSshUser(event.target.value)} placeholder="deploy" /><span className="hint">Required for a bare host. If supplied here, overrides the connection string’s user.</span></label>
        <label>SSH port<input type="number" min="1" max="65535" step="1" value={sshPort} onChange={event => setSshPort(event.target.value)} placeholder="22" /><span className="hint">Optional override; defaults to the connection string’s port or 22.</span></label>
        <label>SSH key path<input value={identityFile} onChange={event => setIdentityFile(event.target.value)} placeholder="/home/you/.ssh/id_ed25519" pattern="/.*" /><span className="hint">Optional absolute path on the API machine. Otherwise uses default SSH keys or the agent.</span></label>
        <button type="submit">Save target</button>
      </fieldset>
      <p className="hint">Connection settings are saved locally as JSON. No SSH config entry is needed. The host needs SSH access, s6 and noninteractive sudo for deployment.</p>
      {targetChanged && <p className="hint">Save target changes before checking or deploying.</p>}
      {targetError && <p className="form-error" role="alert">{targetError}</p>}
      {targetNotice && <p className="success" role="status">{targetNotice}</p>}
    </form>
    <form className="deploy-form" onSubmit={deploy} aria-label="Deploy release">
      <fieldset disabled={busy || checking || !target || targetChanged}>
        <label>Service<select value={service} onChange={event => { setService(event.target.value); setReleasePath('') }}><option value="">All services</option>{data.services.map(name => <option key={name} value={name}>{name}</option>)}</select></label>
        <label>Release directory<input required value={releasePath} onChange={event => setReleasePath(event.target.value)} list="release-paths" placeholder={service ? `/absolute/path/to/release/${service}` : '/absolute/path/to/release'} pattern="/.*" /><span className="hint">{service ? 'Choose the prepared service directory containing an executable run file.' : 'Choose a prepared bundle containing a directory with an executable run file for every service.'}</span></label>
        <datalist id="release-paths">{data.releases.map(release => <option key={release.path} value={service ? `${release.path}/${service}` : release.path} />)}</datalist>
        <p className="hint">Deploys to {target?.host || 'the registered SSH target'}, selects the release and requests service restarts. Services marked down stay down. Build and package artifacts before deploying.</p>
        <button className="primary" type="submit">{deploying ? 'Deploying…' : `Deploy ${service || 'all services'}`}</button>
      </fieldset>
      {!target && <p className="hint">Save a deployment target above, then prepare it with <code>remote setup all {repo.name}</code>.</p>}
      {deploying && <p role="status">Uploading and deploying the release…</p>}
      {error && <p className="form-error" role="alert">{error}</p>}
      {result && <div role="status"><p className="success">Deployment command completed. Host status below reports what is running; application health is not checked.</p>{result.output && <pre className="deploy-output">{result.output}</pre>}</div>}
    </form>
    {live && <section className="live-releases" aria-live="polite"><p className="hint">Checked {new Date(live.checkedAt).toLocaleString()}</p>
      {live.error ? <p className="form-error" role="alert">{live.error}</p> : live.services.map(service => <article className="live-service" key={service.name}>
        <div className="panel-heading"><h3>{service.name}</h3><span className="badge">{service.runtime.state}{service.runtime.state === 'up' ? ` · PID ${service.runtime.pid}` : ''}</span></div>
        {service.runtime.identity === 'verified' ? <ReleaseIdentity title="Running · process verified" release={service.running} /> : <p className="notice">{service.runtime.identity === 'not-running' ? 'The service is down. No release is currently running.' : 'Running release unknown. This process has no matching startup record; older or custom runners may not record one.'}</p>}
        <ReleaseIdentity title="Selected for next start" release={service.selected} />
      </article>)}
    </section>}
    <div className="deployment-files"><h3>Configuration</h3>{data.files.length ? <ul>{data.files.map(file => <li key={file}><code>{file}</code></li>)}</ul> : <p className="hint">No deployment configuration found in this repository.</p>}</div>
    <div className="panel-heading"><h3>Local releases <span className="count">{data.releases.length}</span></h3></div>
    {data.releases.length ? <ul className="resources">{data.releases.map(release => <li key={release.name}><div><strong>{release.name}</strong><span className="path">{release.path}</span></div><time dateTime={release.modifiedAt} title="Directory modified time">{new Date(release.modifiedAt).toLocaleString()}</time></li>)}</ul> : <p className="empty">No packaged releases in .release/ yet.</p>}
    <p className="notice">Local packages do not indicate what is running. Check host via SSH reads release metadata and s6 process state without deploying or restarting services.</p>
  </section></DevScope>
}

export default function App() {
  const [repos, setRepos] = useState([])
  const [selected, setSelected] = useState('')
  const [parentPath, setParentPath] = useState('')
  const [detail, setDetail] = useState(null)
  const [deployment, setDeployment] = useState(null)
  const [view, setView] = useState('resources')
  const [form, setForm] = useState(null)
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [revision, setRevision] = useState(0)

  async function refresh(preferred) {
    setError('')
    setLoading(true)
    try {
      const data = await api('/api/repos')
      setRepos(data.repos)
      setSelected(current => preferred || (data.repos.some(repo => repo.name === current) ? current : data.repos.find(repo => repo.current)?.name || data.repos[0]?.name || ''))
      setRevision(value => value + 1)
    } catch (failure) { setError(failure.message) }
    finally { setLoading(false) }
  }

  useEffect(() => {
    refresh()
    api('/api/config').then(data => setParentPath(data.parentPath)).catch(failure => setError(failure.message))
  }, [])

  useEffect(() => {
    setDetail(null)
    setDeployment(null)
    if (!selected) return
    const controller = new AbortController()
    const base = `/api/repos/${encodeURIComponent(selected)}`
    const endpoint = view === 'deployments' ? `${base}/deployments` : base
    api(endpoint, undefined, controller.signal).then(data => {
      if (view === 'deployments') setDeployment(data)
      else setDetail(data)
    }).catch(failure => { if (!controller.signal.aborted) setError(failure.message) })
    return () => controller.abort()
  }, [selected, revision, view])

  async function completed(resultPath, kind) {
    setForm(null)
    setNotice(`${kind === 'import' ? 'Imported' : 'Created'} ${resultPath}`)
    const preferred = ['create', 'import'].includes(kind) ? resultPath.split('/').pop() : selected
    await refresh(preferred)
  }

  async function selectCurrent() {
    setBusy(true)
    setError('')
    try {
      await api(`/api/repos/${encodeURIComponent(selected)}/select`, {})
      setNotice(`Selected ${selected} in bootstrap.`)
      await refresh(selected)
    } catch (failure) { setError(failure.message) }
    finally { setBusy(false) }
  }

  const repo = repos.find(repo => repo.name === selected)
  return <DevTools><DevScope id="k7m3p9w" state={{ selected, view, form: form || undefined, busy, loading }}><main>
    <DevScope id="q2n8r4t"><header><a className="brand" href="/dashboard/">tk<span>toolkit</span></a><span className="local">Local workspace</span></header></DevScope>
    <DevScope id="h6c1v5b"><section className="intro"><div><p className="eyebrow">WORKSPACE</p><h1>Build from here.</h1><p>Scaffold your next service. Keep every repository in view.</p></div></section></DevScope>
    {notice && <DevScope id="j9w4e8y"><p className="success" role="status">{notice}</p></DevScope>}
    {error && <DevScope id="u3i7o1a"><p className="error" role="alert">{error}</p></DevScope>}
    {form && <CreateForm key={`${form}-${selected}`} kind={form} repo={repo} parentPath={parentPath} busy={busy} setBusy={setBusy} onComplete={completed} onClose={() => setForm(null)} />}
    <div className="workspace">
      <DevScope id="z8x3c7v" state={{ count: repos.length, selected }}><aside className="panel repo-list" aria-label="Repositories"><div className="panel-heading"><h2>Repositories <span className="count">{repos.length}</span></h2><button disabled={busy || loading} onClick={() => refresh()} aria-label="Refresh repositories">↻</button></div><div className="repo-actions"><button disabled={busy || loading} onClick={() => setForm('import')}>Import repo</button><button className="primary" disabled={busy || loading} onClick={() => setForm('create')}>+ New repo</button></div>
        {loading && <p className="empty">Refreshing…</p>}
        {!loading && !repos.length && <p className="empty">Create or import your first repository.</p>}
        {repos.map(item => <button key={item.name} className={`repo-choice ${selected === item.name ? 'active' : ''}`} aria-pressed={selected === item.name} disabled={busy} onClick={() => { setSelected(item.name); setForm(null); setError(''); setNotice('') }}><span>{item.name}</span>{item.current && <span className="selection-dot" title="Current bootstrap selection" aria-label="Current bootstrap selection" />}</button>)}
      </aside></DevScope>
      <DevScope id="l2k6z5x" state={{ repo: repo?.name, view }}><div className="repo-content">
        {repo ? <>
          <DevScope id="p8a3s7d" state={{ name: repo.name, current: Boolean(repo.current) }}><div className="repo-heading"><div><h2>{repo.name}</h2><p className="path">{repo.path}</p></div>{repo.current ? <span className="badge">Current in bootstrap</span> : <button disabled={busy} onClick={selectCurrent}>Set current</button>}</div></DevScope>
          <DevScope id="f1g5h9j" state={{ view }}><nav className="tabs" aria-label="Repository view"><button disabled={busy} className={view === 'resources' ? 'active' : ''} aria-pressed={view === 'resources'} onClick={() => { setView('resources'); setError('') }}>Services & UIs</button><button disabled={busy} className={view === 'deployments' ? 'active' : ''} aria-pressed={view === 'deployments'} onClick={() => { setView('deployments'); setForm(null); setError('') }}>Deployments</button></nav></DevScope>
          {view === 'resources' ? detail ? <div className="resource-stack"><ResourceList devId="t4y8u2i" title="Services" kind="services" items={detail.services} onAdd={setForm} busy={busy} /><ResourceList devId="n4p7q2w" title="UIs" kind="uis" items={detail.uis} onAdd={setForm} busy={busy} /><ResourceList devId="h8j3k6m" title="Databases" kind="databases" items={detail.databases} onAdd={setForm} busy={busy} /></div> : <p className="empty">{error ? 'Could not load this repository.' : 'Loading repository…'}</p> : deployment ? <DeploymentView key={selected} data={deployment} repo={repo} busy={busy} setBusy={setBusy} /> : <p className="empty">{error ? 'Could not load deployment details.' : 'Loading deployments…'}</p>}
        </> : <section className="panel empty">Select a repository to view its services, UIs, and deployments.</section>}
      </div></DevScope>
    </div>
    <DevScope id="e3r7t1y"><footer>Toolkit dashboard <span>Powered by the toolkit CLI</span></footer></DevScope>
  </main></DevScope></DevTools>
}
