const form = document.querySelector('form')
const fieldset = form.querySelector('fieldset')
const password = document.querySelector('#password')
const status = document.querySelector('#status')
const signup = form.dataset.mode === 'signup'

const safeReturnPath = () => {
  const value = new URLSearchParams(window.location.search).get('returnTo')
  if (!value || !value.startsWith('/') || value.startsWith('//')) return '/'
  try {
    const target = new URL(value, window.location.origin)
    if (target.origin !== window.location.origin || target.pathname.startsWith('//')) return '/'
    return target.pathname + target.search + target.hash
  } catch {
    return '/'
  }
}

const returnPath = safeReturnPath()
const signinPath = '/auth/signin?returnTo=' + encodeURIComponent(returnPath)
document.querySelectorAll('[data-auth-link]').forEach((link) => {
  link.href += '?returnTo=' + encodeURIComponent(returnPath)
})

const showStatus = (message, error = false) => {
  status.textContent = message
  status.dataset.error = String(error)
  if (error) status.focus()
}

const postCredentials = async (url, credentials) => {
  const response = await fetch(url, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify(credentials),
  })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(typeof body?.error === 'string' ? body.error : 'The request failed. Please try again.')
  }
}

document.querySelector('#show-password').addEventListener('change', (event) => {
  password.type = event.target.checked ? 'text' : 'password'
})

password.addEventListener('input', () => password.setCustomValidity(''))

form.addEventListener('submit', async (event) => {
  event.preventDefault()
  if (fieldset.disabled) return
  if (signup && ([...password.value].length < 8 || new TextEncoder().encode(password.value).length > 72)) {
    password.setCustomValidity('Use at least 8 characters and no more than 72 bytes.')
    password.reportValidity()
    return
  }
  const credentials = {
    email: document.querySelector('#email').value.trim(),
    password: password.value,
  }
  let accountCreated = false
  fieldset.disabled = true
  form.setAttribute('aria-busy', 'true')
  showStatus(signup ? 'Creating your account…' : 'Signing in…')
  try {
    if (signup) {
      await postCredentials('/auth/register', credentials)
      accountCreated = true
      showStatus('Account created. Signing in…')
    }
    // The public endpoint creates the cookie session through OpenResty.
    await postCredentials('/auth/login', credentials)
    const session = await fetch('/auth/session', { credentials: 'same-origin', cache: 'no-store' })
    if (!session.ok) throw new Error('Your session could not be confirmed. Allow cookies and try signing in again.')
    showStatus('Signed in. Redirecting…')
    window.location.assign(returnPath)
  } catch (error) {
    if (accountCreated) {
      form.hidden = true
      showStatus('Your account was created, but sign-in did not finish. ', true)
      const link = document.createElement('a')
      link.href = signinPath
      link.textContent = 'Sign in to your account.'
      status.append(link)
    } else {
      showStatus(error instanceof TypeError
        ? 'Could not reach the server. Please try again. If you already created an account, use Sign in.'
        : error.message, true)
    }
  } finally {
    password.value = ''
    credentials.password = ''
    fieldset.disabled = false
    form.removeAttribute('aria-busy')
  }
})

fieldset.disabled = false
