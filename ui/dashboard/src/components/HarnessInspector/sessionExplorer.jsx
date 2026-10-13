import { useEffect, useRef, useState } from 'react'
import { Badge, ScrollingText } from 'component-library'
import { BASE, harnessRequest } from './harnessForms'
import './styles.css'

const JOB_LIST_LIMIT = 20

const STATUS_VARIANT = {
  idle: 'neutral',
  running: 'info',
  awaiting_input: 'warning',
  paused: 'warning',
  stopped: 'neutral',
  finished: 'success',
  error: 'danger',
}

const isActiveJob = job => job.status === 'running' || job.status === 'awaiting_input'

const jobLabel = job => job.name || (job.model ? `${job.provider} · ${job.model}` : job.provider)

const sessionsQuery = (active, limit) =>
  `/sessions?includeArchived=false&orderBy=createdAt&order=desc&active=${active}&limit=${limit}`

const JobRow = ({ job, workspaceName, active, onSelect }) => {
  const label = jobLabel(job)
  return (
    <button
      type="button"
      className={`harness-explorer__job${active ? ' harness-explorer__job--active' : ''}`}
      aria-pressed={active}
      onClick={() => onSelect(job)}
    >
      <span className="harness-explorer__job-info">
        {isActiveJob(job) && <span className="harness-explorer__pulse" aria-hidden="true" />}
        <ScrollingText className="harness-explorer__job-label" title={label}>{label}</ScrollingText>
        {workspaceName && <span className="harness-explorer__ws">{workspaceName}</span>}
      </span>
      <Badge size="small" variant={STATUS_VARIANT[job.status] || 'neutral'}>{job.status}</Badge>
    </button>
  )
}

export const SessionStream = ({ sessionId }) => {
  const [events, setEvents] = useState([])
  const [session, setSession] = useState(null)
  const [runs, setRuns] = useState([])
  const [questions, setQuestions] = useState([])
  const [status, setStatus] = useState('Connecting…')
  const [log, setLog] = useState('')
  const [logError, setLogError] = useState(null)
  const [follow, setFollow] = useState(true)
  const transcript = useRef(null)

  useEffect(() => {
    const source = new EventSource(`${BASE}/sessions/${encodeURIComponent(sessionId)}/events`)
    // The server replays its complete log on reconnect (it has no Last-Event-ID cursor).
    source.onopen = () => { setEvents([]); setStatus('Replaying…') }
    const read = handler => event => {
      try { handler(JSON.parse(event.data)) } catch { setStatus('Invalid stream data') }
    }
    source.addEventListener('event', read(event => setEvents(previous => [...previous, event].slice(-500))))
    source.addEventListener('session', read(setSession))
    source.addEventListener('runs', read(setRuns))
    source.addEventListener('questions', read(setQuestions))
    source.addEventListener('ready', () => setStatus('Live'))
    source.onerror = event => {
      if (event.data) {
        try { setStatus(JSON.parse(event.data).message) } catch { setStatus('Stream error') }
        source.close()
      } else setStatus('Disconnected — reconnecting…')
    }
    return () => source.close()
  }, [sessionId])

  useEffect(() => {
    const controller = new AbortController()
    let timer
    const load = async () => {
      try {
        const response = await fetch(`${BASE}/sessions/${encodeURIComponent(sessionId)}/log`, { signal: controller.signal })
        if (!response.ok) throw new Error(`Log unavailable (${response.status})`)
        const text = await response.text()
        if (!controller.signal.aborted) { setLog(text.slice(-50000)); setLogError(null) }
      } catch (error) {
        if (!controller.signal.aborted) setLogError(error.message)
      } finally {
        if (!controller.signal.aborted) timer = setTimeout(load, 3000)
      }
    }
    load()
    return () => { controller.abort(); clearTimeout(timer) }
  }, [sessionId])

  useEffect(() => {
    if (follow && transcript.current) transcript.current.scrollTop = transcript.current.scrollHeight
  }, [events, follow])

  return <section>
    <p role="status">{status}{session ? ` · ${session.status} · ${session.provider} · ${session.model || 'default model'}` : ''}</p>
    <label><input type="checkbox" checked={follow} onChange={event => setFollow(event.target.checked)} /> Follow latest events</label>
    <p>Latest 500 events</p>
    <div className="harness-explorer__events" ref={transcript} tabIndex={0} aria-label="Session events">
      {!events.length && <p>No events yet.</p>}
      {events.map((event, index) => <details key={index} open={event.type === 'text' || event.type === 'error'}>
        <summary>{event.type || 'event'}{event.status ? ` · ${event.status}` : ''}</summary>
        <pre>{typeof event.text === 'string' ? event.text : JSON.stringify(event, null, 2)}</pre>
      </details>)}
    </div>
    <details><summary>Runs ({runs.length})</summary><pre>{JSON.stringify(runs, null, 2)}</pre></details>
    <details><summary>Pending questions ({questions.filter(question => question.status === 'pending').length})</summary>
      <pre>{JSON.stringify(questions.filter(question => question.status === 'pending'), null, 2)}</pre>
    </details>
    <details><summary>Process log · refreshes every 3 seconds</summary>
      {logError && <p role="alert">{logError}</p>}<pre>{log || 'No process output yet.'}</pre>
    </details>
  </section>
}

const SessionExplorer = () => {
  const [workspaces, setWorkspaces] = useState([])
  const [jobs, setJobs] = useState([])
  const [sessionId, setSessionId] = useState('')
  const [filterActiveOnly, setFilterActiveOnly] = useState(false)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const [refresh, setRefresh] = useState(0)
  const [archiveBusy, setArchiveBusy] = useState(false)
  const [archiveError, setArchiveError] = useState(null)

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        const [workspaceData, activeData] = await Promise.all([
          harnessRequest('/workspaces'),
          harnessRequest(sessionsQuery(true, JOB_LIST_LIMIT)),
        ])
        if (cancelled) return
        const activeJobs = activeData.sessions
        let nextJobs = activeJobs
        if (activeJobs.length < JOB_LIST_LIMIT) {
          const recentData = await harnessRequest(sessionsQuery(false, JOB_LIST_LIMIT - activeJobs.length))
          if (cancelled) return
          const activeIds = new Set(activeJobs.map(job => job.id))
          const byRecent = (a, b) => (b.createdAt || 0) - (a.createdAt || 0) || a.id.localeCompare(b.id)
          nextJobs = [...activeJobs, ...recentData.sessions.filter(job => !activeIds.has(job.id))].sort(byRecent)
        }
        setWorkspaces(workspaceData.workspaces)
        setJobs(nextJobs)
        setError(null)
      } catch (loadError) {
        if (!cancelled) setError(loadError.message)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    const timer = setInterval(load, 3000)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [refresh])

  const nameById = Object.fromEntries(workspaces.map(workspace => [workspace.id, workspace.name]))
  const activeJobs = jobs.filter(isActiveJob)
  const displayedJobs = filterActiveOnly ? activeJobs : jobs
  const selected = jobs.find(job => job.id === sessionId)
  const toggleArchive = async () => {
    if (!selected || archiveBusy) return
    setArchiveBusy(true)
    setArchiveError(null)
    try {
      const { session } = await harnessRequest(`/sessions/${encodeURIComponent(selected.id)}`, { archived: !selected.archived }, 'PATCH')
      setJobs(current => current.filter(job => job.id !== session.id))
      setSessionId('')
      setRefresh(value => value + 1)
    } catch (archiveFailure) {
      setArchiveError(archiveFailure.message)
    } finally {
      setArchiveBusy(false)
    }
  }
  return <div className="harness-explorer">
    <div className="harness-explorer__jobs-header">
      <h3>Jobs</h3>
      <Badge size="small" variant={activeJobs.length ? 'info' : 'neutral'} count={activeJobs.length} />
      <button type="button" onClick={() => setRefresh(value => value + 1)}>Refresh</button>
    </div>
    {loading && <p role="status">Loading jobs…</p>}
    {error && <p role="alert">{error}</p>}
    <div className="harness-explorer__filters" role="tablist" aria-label="Job filters">
      <button type="button" role="tab" aria-selected={!filterActiveOnly}
        className={`harness-explorer__filter${!filterActiveOnly ? ' harness-explorer__filter--active' : ''}`}
        onClick={() => setFilterActiveOnly(false)}>
        All ({jobs.length})
      </button>
      <button type="button" role="tab" aria-selected={filterActiveOnly}
        className={`harness-explorer__filter${filterActiveOnly ? ' harness-explorer__filter--active' : ''}`}
        onClick={() => setFilterActiveOnly(true)}>
        Active ({activeJobs.length})
      </button>
    </div>
    <div className="harness-explorer__jobs" aria-label="Jobs">
      {!loading && !error && !displayedJobs.length && (
        <p className="harness-explorer__empty">{filterActiveOnly ? 'No active background jobs.' : 'No recent jobs.'}</p>
      )}
      {displayedJobs.map(job => (
        <JobRow
          key={job.id}
          job={job}
          workspaceName={nameById[job.workspaceId] || job.cwd}
          active={job.id === sessionId}
          onSelect={item => setSessionId(item.id)}
        />
      ))}
    </div>
    {archiveError && <p role="alert">{archiveError}</p>}
    {selected && <button type="button" disabled={archiveBusy} onClick={toggleArchive}>Archive session</button>}
    {selected && <SessionStream key={selected.id} sessionId={selected.id} />}
  </div>
}

export default SessionExplorer
