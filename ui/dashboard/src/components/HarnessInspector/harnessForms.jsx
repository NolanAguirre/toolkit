import { useEffect, useRef, useState } from 'react'
import { useFormReady } from 'component-library'

export const BASE = import.meta.env.VITE_HARNESS_API_BASE || '/dashboard/harness-api'

export const harnessRequest = async (path, body, method = 'POST') => {
  const response = await fetch(`${BASE}${path}`, body === undefined ? {} : {
    method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  })
  if (!response.ok) {
    const detail = await response.json().catch(() => null)
    throw new Error(detail?.error || `Harness unavailable (${response.status})`)
  }
  return response.json()
}

const toolkitWorkspace = workspaces => workspaces.find(workspace => workspace.name?.toLowerCase() === 'toolkit')
  || workspaces.find(workspace => /\/toolkit\/?$/.test(workspace.cwd || ''))
  || workspaces.find(workspace => /\/dashboard\/?$/.test(workspace.cwd || ''))

export const HarnessFields = ({ form, inspector }) => {
  const [providers, setProviders] = useState([])
  const [workspaces, setWorkspaces] = useState([])
  const setValue = form.setValue
  const provider = providers.find(item => item.id === form.values.provider)
  const models = provider?.models || []
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState(null)
  const [attempt, setAttempt] = useState(0)
  const promptPrefix = inspector?.descriptor?.leaf ? `For ${inspector.descriptor.leaf} ` : ''
  const previousPrefix = useRef('')
  const prompt = form.values.prompt
  const promptDirty = form.dirty?.prompt
  useEffect(() => {
    if (((!promptDirty && prompt === '') || (previousPrefix.current !== promptPrefix && prompt === previousPrefix.current))
      && prompt !== promptPrefix) {
      setValue('prompt', promptPrefix)
    }
    previousPrefix.current = promptPrefix
  }, [promptPrefix, prompt, promptDirty, setValue])
  useFormReady(form, 'component', loaded && Boolean(provider?.implemented && !provider.error))
  useEffect(() => {
    let cancelled = false
    Promise.all([harnessRequest('/providers'), harnessRequest('/workspaces')])
      .then(([result, { workspaces }]) => {
        if (cancelled) return
        setProviders(result.providers)
        setWorkspaces(workspaces)
        const toolkit = toolkitWorkspace(workspaces)
        setValue('workspaceId', toolkit?.id || '')
        const available = result.providers.filter(item => item.implemented && !item.error)
        const initial = available.find(item => item.id === 'cursor') || available[0]
        setValue('provider', initial?.id || '')
        setValue('model', initial?.models?.[0]?.id || '')
        setLoaded(true)
      })
      .catch(err => { if (!cancelled) setError(err.message) })
    return () => { cancelled = true }
  }, [attempt, setValue])

  return <>
    {error && <p role="alert">{error}. Check that the harness service is running.</p>}
    {!loaded && !error && <p role="status">Loading workspaces and providers…</p>}
    {loaded && !form.values.workspaceId && <p>Choose a workspace. If toolkit is missing, create it in the harness and refresh.</p>}
    {loaded && !provider && <p>No available provider. Check the harness provider configuration and refresh.</p>}
    {provider?.error && <p role="alert">{provider.error}</p>}
    <button type="button" disabled={form.isSubmitting} onClick={() => {
      form.setReady('component', false)
      form.setValue('provider', '')
      form.setValue('model', '')
      setLoaded(false); setError(null); setAttempt(value => value + 1)
    }}>Refresh options</button>
    <label className="form__label" htmlFor="harness-workspace">Workspace</label>
    <select id="harness-workspace" className="form__select" value={form.values.workspaceId}
      disabled={!loaded || form.isSubmitting} onChange={event => {
        const id = event.target.value
        form.setValue('workspaceId', id)
      }}>
      <option value="">Choose a workspace</option>
      {workspaces.map(workspace => <option key={workspace.id} value={workspace.id}>{workspace.name}</option>)}
    </select>
    <label className="form__label" htmlFor="harness-provider">Provider</label>
    <select id="harness-provider" className="form__select" value={form.values.provider}
      disabled={!loaded || form.isSubmitting} onChange={event => {
        const next = providers.find(item => item.id === event.target.value)
        form.setValue('provider', next?.id || '')
        form.setValue('model', next?.models?.[0]?.id || '')
      }}>
      <option value="">Choose a provider</option>
      {providers.map(item => <option key={item.id} value={item.id} disabled={!item.implemented || Boolean(item.error)}>
        {item.id}{!item.implemented || item.error ? ' (unavailable)' : ''}
      </option>)}
    </select>
    <label className="form__label" htmlFor="harness-model">Model</label>
    <select id="harness-model" className="form__select" value={form.values.model}
      disabled={!loaded || !provider || form.isSubmitting}
      onChange={event => form.setValue('model', event.target.value)}>
      <option value="">Provider default</option>
      {models.map(model => <option key={model.id} value={model.id}>{model.displayName || model.id}</option>)}
    </select>
    <p>Each submission creates a new session in the selected workspace.</p>
    <label className="form__label" htmlFor="harness-action">Action</label>
    <select id="harness-action" className="form__select" value={form.values.action}
      disabled={form.isSubmitting} onChange={event => form.setValue('action', event.target.value)}>
      <option value="plan">Plan</option><option value="run">Run</option><option value="decompose">Decompose</option>
    </select>
    <label className="form__label" htmlFor="harness-prompt">Prompt</label>
    <textarea id="harness-prompt" className="form__textarea" rows={5} value={form.values.prompt}
      disabled={form.isSubmitting} onChange={event => form.setValue('prompt', event.target.value)} />
    {Object.entries(form.errors).map(([name, error]) => form.touched[name] && error
      ? <p key={name} role="alert">{error}</p> : null)}
  </>
}

const harnessForms = [{
  id: 'harness', title: 'Harness',
  icon: <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
    <rect x="3" y="4" width="18" height="16" rx="2" /><path d="m7 9 3 3-3 3m6 0h4" />
  </svg>,
  component: HarnessFields,
  submitLabel: 'Send to harness',
  config: { fields: {
    workspaceId: { type: 'select', defaultValue: '', required: true, requiredMessage: 'Choose a workspace' },
    provider: { type: 'select', defaultValue: '', required: true, requiredMessage: 'Choose a provider' },
    model: { type: 'select', defaultValue: '' },
    action: { type: 'select', defaultValue: 'run', required: true },
    prompt: { type: 'textarea', defaultValue: '', required: true, requiredMessage: 'Enter a prompt' },
  } },
  onSubmit: async ({ workspaceId, provider, model, action, prompt }) => {
    const { session } = await harnessRequest(`/workspaces/${encodeURIComponent(workspaceId)}/sessions`, {
      provider, model: model || null,
    })
    try {
      const response = await harnessRequest(`/sessions/${encodeURIComponent(session.id)}/${action}`,
        action === 'run' ? { prompt, mode: 'agent' } : { prompt })
      return { session, ...response }
    } catch (error) {
      throw new Error(`Session ${session.id} was created, but ${action} failed: ${error.message}. Submitting again will create another session.`)
    }
  },
}]

export default harnessForms
