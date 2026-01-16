import { writable, derived } from 'svelte/store'

// Cookie helpers
function setCookie(name, value, days = 7) {
  const expires = new Date(Date.now() + days * 864e5).toUTCString()
  document.cookie = `${name}=${encodeURIComponent(value)}; expires=${expires}; path=/; SameSite=Strict`
}

function getCookie(name) {
  const match = document.cookie.match(new RegExp('(^| )' + name + '=([^;]+)'))
  return match ? decodeURIComponent(match[2]) : null
}

function deleteCookie(name) {
  document.cookie = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/; SameSite=Strict`
}

// Auth state
function createAuthStore() {
  const storedToken = getCookie('jwt_token')
  
  const { subscribe, set, update } = writable({
    token: storedToken,
    user: null,
    loading: false,
    error: null
  })

  return {
    subscribe,
    
    setToken(token) {
      setCookie('jwt_token', token, 7)
      update(s => ({ ...s, token, error: null }))
    },
    
    setUser(user) {
      update(s => ({ ...s, user }))
    },
    
    setError(error) {
      update(s => ({ ...s, error, loading: false }))
    },
    
    setLoading(loading) {
      update(s => ({ ...s, loading }))
    },
    
    logout() {
      deleteCookie('jwt_token')
      deleteCookie('do_token_local')
      set({ token: null, user: null, loading: false, error: null })
    },
    
    clearError() {
      update(s => ({ ...s, error: null }))
    }
  }
}

export const auth = createAuthStore()

// Derived store for checking if authenticated
export const isAuthenticated = derived(auth, $auth => !!$auth.token && !!$auth.user)

// Admin emails (must match backend ADMIN_EMAILS)
const ADMIN_EMAILS = ['vergnetp@yahoo.fr']

// Derived store for checking if user is admin
export const isAdmin = derived(auth, $auth => {
  if (!$auth.user?.email) return false
  return ADMIN_EMAILS.includes($auth.user.email.toLowerCase())
})

// DO Token (stored in cookie, not in auth store)
export function getDoToken() {
  return getCookie('do_token_local')
}

export function setDoToken(token) {
  setCookie('do_token_local', token, 30)
}

export function getCfToken() {
  return getCookie('cf_token_local')
}

export function setCfToken(token) {
  setCookie('cf_token_local', token, 30)
}
