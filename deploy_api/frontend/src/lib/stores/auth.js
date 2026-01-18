/**
 * auth.js - App-specific auth extensions
 * 
 * Re-exports shared auth and adds deploy_api-specific token handling
 * (DigitalOcean token, Cloudflare token)
 */

// Re-export everything from shared auth
export { 
  authStore, 
  authStore as auth,  // Alias for backward compatibility
  isAuthenticated, 
  currentUser, 
  isAdmin,
  getAuthToken,
  setAuthToken,
  clearAuth,
  setAdminEmails,
  getCustomToken,
  setCustomToken,
  clearCustomToken,
} from '@myorg/ui'

// Import for internal use
import { setAdminEmails, getCustomToken, setCustomToken, clearCustomToken } from '@myorg/ui'

// =============================================================================
// App-specific: Admin emails
// =============================================================================
setAdminEmails(['vergnetp@yahoo.fr'])

// =============================================================================
// App-specific: DigitalOcean Token
// =============================================================================

export function getDoToken() {
  return getCustomToken('do_token_local')
}

export function setDoToken(token) {
  setCustomToken('do_token_local', token, 30)
}

export function clearDoToken() {
  clearCustomToken('do_token_local')
}

// =============================================================================
// App-specific: Cloudflare Token
// =============================================================================

export function getCfToken() {
  return getCustomToken('cf_token_local')
}

export function setCfToken(token) {
  setCustomToken('cf_token_local', token, 30)
}

export function clearCfToken() {
  clearCustomToken('cf_token_local')
}
