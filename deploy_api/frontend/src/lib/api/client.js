import { get } from 'svelte/store'
import { authStore as auth, getDoToken, getCfToken } from '../stores/auth.js'
import { toasts } from '../stores/toast.js'

// Re-export for convenience
export { getDoToken, getCfToken }

const API_BASE = '/api/v1'

// Infra endpoints that require DO token (call DigitalOcean/Cloudflare APIs)
const INFRA_NEEDS_DO_TOKEN = [
  '/infra/servers',
  '/infra/snapshots',
  '/infra/setup',
  '/infra/deploy',
  '/infra/registry',
  '/infra/agent',
  '/infra/architecture',
  '/infra/fleet',
  '/infra/projects',
  '/infra/containers',
  '/infra/services',
  '/infra/deployments',
]

/**
 * Validate JWT format (must have 3 dot-separated parts)
 * @private
 */
function isValidJwtFormat(token) {
  if (!token || typeof token !== 'string') return false
  const parts = token.split('.')
  return parts.length === 3
}

/**
 * Build headers and URL for API request (internal helper)
 * @private
 */
function buildRequest(path, options = {}) {
  const authState = get(auth)
  
  const headers = { 'Content-Type': 'application/json' }
  
  // Don't add auth header for auth endpoints (login, register) or if skipAuth option
  const isAuthEndpoint = path.startsWith('/auth/login') || path.startsWith('/auth/register')
  
  if (authState.token && authState.token.trim() !== '' && !isAuthEndpoint && !options.skipAuth) {
    // Validate token format before sending
    if (!isValidJwtFormat(authState.token)) {
      console.error('Invalid JWT format detected - token may be corrupted')
      // Force logout to clear corrupted token
      auth.logout()
      return { error: 'Session corrupted - please login again', url: null, headers: null }
    }
    headers['Authorization'] = `Bearer ${authState.token}`
  }
  
  // Add DO token for endpoints that need it
  let url = API_BASE + path
  
  // Check if this endpoint needs DO token - more permissive matching
  const needsDoToken = !options.skipDoToken && (
    path.startsWith('/infra/') || 
    INFRA_NEEDS_DO_TOKEN.some(p => path.startsWith(p))
  )
  
  if (needsDoToken) {
    const doToken = getDoToken()
    if (!doToken) {
      return { error: 'DO token not set', url: null, headers: null }
    }
    const sep = url.includes('?') ? '&' : '?'
    url += `${sep}do_token=${encodeURIComponent(doToken)}`
  }
  
  return { url, headers, error: null }
}

/**
 * Handle error responses (internal helper)
 * @private
 */
async function handleErrorResponse(res) {
  if (res.status === 401) {
    let errorMsg = 'Authentication failed'
    try {
      const errBody = await res.json()
      errorMsg = errBody.detail || errBody.error || errBody.message || errorMsg
    } catch {}
    
    const authState = get(auth)
    if (authState.token) {
      auth.logout()
      errorMsg = 'Session expired - please login again'
    }
    
    throw new Error(errorMsg)
  }
  
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Request failed' }))
    throw new Error(err.detail || err.error || err.message || 'Request failed')
  }
}

/**
 * Make an API request (JSON response)
 * @param {string} method - HTTP method
 * @param {string} path - API path (e.g., '/auth/login')
 * @param {object} data - Request body (for POST/PUT)
 * @param {object} options - Additional options
 * @returns {Promise<any>}
 */
export async function api(method, path, data = null, options = {}) {
  const { url, headers, error } = buildRequest(path, options)
  
  if (error) {
    console.debug(`Skipping ${path} - ${error}`)
    return null
  }
  
  const opts = { method, headers }
  if (data) opts.body = JSON.stringify(data)
  
  const res = await fetch(url, opts)
  
  await handleErrorResponse(res)
  
  if (res.status === 204) return null
  
  const result = await res.json()
  
  // Unwrap proxy response format: { success: true, data: {...} }
  if (result && result.success === true && result.data !== undefined) {
    return result.data
  }
  
  return result
}

/**
 * Make an SSE streaming API request
 * All SSE calls go through here - no direct fetch() in components!
 * 
 * @param {string} method - HTTP method
 * @param {string} path - API path
 * @param {object} data - Request body
 * @param {function} onMessage - Callback for each SSE message: (msg) => void
 * @param {object} options - Additional options
 * @returns {Promise<void>}
 */
export async function apiStream(method, path, data = null, onMessage, options = {}) {
  const { url, headers, error } = buildRequest(path, options)
  
  if (error) {
    throw new Error(error)
  }
  
  const opts = { method, headers }
  if (data) opts.body = JSON.stringify(data)
  
  const res = await fetch(url, opts)
  
  await handleErrorResponse(res)
  
  // Read SSE stream
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''
    
    for (const line of lines) {
      if (line.startsWith('data: ')) {
        try {
          const msg = JSON.parse(line.slice(6))
          onMessage(msg)
        } catch (e) {
          // Ignore parse errors for malformed lines
        }
      }
    }
  }
}

/**
 * Make an SSE streaming API request with multipart/form-data (for file uploads)
 * 
 * @param {string} path - API path
 * @param {FormData} formData - Form data with files
 * @param {function} onMessage - Callback for each SSE message
 * @param {object} options - Additional options
 * @returns {Promise<void>}
 */
export async function apiStreamMultipart(path, formData, onMessage, options = {}) {
  const authState = get(auth)
  
  // Validate token format before sending
  if (authState.token && !isValidJwtFormat(authState.token)) {
    console.error('Invalid JWT format detected - token may be corrupted')
    auth.logout()
    throw new Error('Session corrupted - please login again')
  }
  
  // Build URL with DO token if needed
  let url = API_BASE + path
  const needsDoToken = !options.skipDoToken && INFRA_NEEDS_DO_TOKEN.some(p => path.startsWith(p))
  
  if (needsDoToken) {
    const doToken = getDoToken()
    if (!doToken) {
      throw new Error('DO token not set')
    }
    const sep = url.includes('?') ? '&' : '?'
    url += `${sep}do_token=${encodeURIComponent(doToken)}`
  }
  
  // Headers - NO Content-Type (browser sets it with boundary for multipart)
  const headers = {}
  if (authState.token) {
    headers['Authorization'] = `Bearer ${authState.token}`
  }
  
  const res = await fetch(url, {
    method: 'POST',
    headers,
    body: formData
  })
  
  await handleErrorResponse(res)
  
  // Read SSE stream
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''
    
    for (const line of lines) {
      if (line.startsWith('data: ')) {
        try {
          const msg = JSON.parse(line.slice(6))
          onMessage(msg)
        } catch (e) {
          // Ignore parse errors
        }
      }
    }
  }
}

// Convenience methods
export const get_ = (path, options) => api('GET', path, null, options)
export const post = (path, data, options) => api('POST', path, data, options)
export const put = (path, data, options) => api('PUT', path, data, options)
export const del = (path, options) => api('DELETE', path, null, options)

/**
 * Login user
 */
export async function login(email, password) {
  auth.setLoading(true)
  auth.clearError()
  
  try {
    const res = await api('POST', '/auth/login', { username: email, password })
    auth.setToken(res.access_token)
    
    // Fetch user info
    const user = await api('GET', '/auth/me')
    auth.setUser(user)
    auth.setLoading(false)
    
    return user
  } catch (err) {
    auth.setError(err.message)
    throw err
  }
}

/**
 * Register new user
 */
export async function register(email, password) {
  auth.setLoading(true)
  auth.clearError()
  
  try {
    await api('POST', '/auth/register', { username: email, email, password })
    // Auto-login after registration
    return await login(email, password)
  } catch (err) {
    auth.setError(err.message)
    throw err
  }
}

/**
 * Initialize app - check auth and load user
 */
export async function initAuth() {
  const authState = get(auth)
  
  // Check for valid token (not null, not empty)
  if (!authState.token || authState.token.trim() === '') {
    return false
  }
  
  try {
    const user = await api('GET', '/auth/me')
    auth.setUser(user)
    return true
  } catch (err) {
    auth.logout()
    return false
  }
}
