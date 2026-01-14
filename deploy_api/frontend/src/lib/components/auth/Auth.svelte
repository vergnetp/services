<!--
  Auth.svelte - Reusable authentication component
  
  Usage:
  <Auth 
    title="My App"
    subtitle="Sign in to continue"
    apiBase="/api/v1"
    on:success={(e) => handleLogin(e.detail.user)}
    on:error={(e) => console.error(e.detail.error)}
  />
  
  Props:
  - title: string - App title (default: "Welcome")
  - subtitle: string - Subtitle text (default: "Sign in to your account")
  - apiBase: string - API base URL (default: "/api/v1")
  - showLogo: boolean - Show brand dot (default: true)
  - allowSignup: boolean - Allow new registrations (default: true)
  
  Events:
  - success: { user, token } - Fired on successful auth
  - error: { error, type } - Fired on auth error
  
  CSS Variables (override in parent):
  - All theme variables from theme.css
-->
<script>
  import { createEventDispatcher } from 'svelte'
  import { api } from '../../api/client.js'
  
  // Props
  export let title = 'Welcome'
  export let subtitle = 'Sign in to your account'
  export let apiBase = '/api/v1'
  export let showLogo = true
  export let allowSignup = true
  
  const dispatch = createEventDispatcher()
  
  // Local state
  let activeTab = 'login'
  let loading = false
  let error = null
  
  // Form fields
  let loginEmail = ''
  let loginPassword = ''
  let signupEmail = ''
  let signupPassword = ''
  let signupConfirm = ''
  
  function switchTab(tab) {
    activeTab = tab
    error = null
  }
  
  // NOTE: We route all auth through the shared API client so it works in
  // both real backend mode and mock mode.
  async function apiCall(method, path, data) {
    // Keep prop for compatibility, but ignore apiBase here.
    return await api(method, path, data, { skipDoToken: true })
  }
  
  async function handleLogin(e) {
    e.preventDefault()
    loading = true
    error = null
    
    try {
      const res = await apiCall('POST', '/auth/login', {
        username: loginEmail,
        password: loginPassword
      })

      // Support both shapes:
      // - { access_token, token_type }
      // - { token, user }
      const token = res?.access_token || res?.token

      // If API returns the user already (mock could), use it; otherwise fetch /auth/me
      const user = res?.user || await apiCall('GET', '/auth/me')

      if (!token || !user) throw new Error('Login failed')
      dispatch('success', { user, token })
    } catch (err) {
      error = err.message
      dispatch('error', { error: err.message, type: 'login' })
    } finally {
      loading = false
    }
  }
  
  async function handleSignup(e) {
    e.preventDefault()
    
    if (signupPassword !== signupConfirm) {
      error = 'Passwords do not match'
      return
    }
    
    loading = true
    error = null
    
    try {
      await apiCall('POST', '/auth/register', { 
        username: signupEmail, 
        email: signupEmail, 
        password: signupPassword 
      })
      
      // Auto-login after signup
      const res = await apiCall('POST', '/auth/login', { 
        username: signupEmail, 
        password: signupPassword 
      })
      
      const token = res?.access_token || res?.token
      const user = res?.user || await apiCall('GET', '/auth/me')

      if (!token || !user) throw new Error('Signup failed')
      dispatch('success', { user, token })
    } catch (err) {
      error = err.message
      dispatch('error', { error: err.message, type: 'signup' })
    } finally {
      loading = false
    }
  }
</script>

<div class="auth-container">
  <div class="auth-card glass">
    <div class="auth-title">
      <h1>
        {#if showLogo}
          <span class="brand-dot"></span>
        {/if}
        {title}
      </h1>
      <p>{subtitle}</p>
    </div>
    
    {#if allowSignup}
      <div class="tabs">
        <button 
          class="tab" 
          class:active={activeTab === 'login'}
          on:click={() => switchTab('login')}
        >
          Sign In
        </button>
        <button 
          class="tab" 
          class:active={activeTab === 'signup'}
          on:click={() => switchTab('signup')}
        >
          Sign Up
        </button>
      </div>
    {/if}
    
    {#if activeTab === 'login'}
      <form on:submit={handleLogin}>
        <div class="form-group">
          <label for="login-email">Email</label>
          <input 
            type="email" 
            id="login-email"
            bind:value={loginEmail}
            placeholder="you@example.com" 
            required
            disabled={loading}
          >
        </div>
        <div class="form-group">
          <label for="login-password">Password</label>
          <input 
            type="password" 
            id="login-password"
            bind:value={loginPassword}
            placeholder="••••••••" 
            required
            disabled={loading}
          >
        </div>
        <button type="submit" class="btn btn-primary btn-full" disabled={loading}>
          {#if loading}
            <span class="spinner"></span>
          {:else}
            Sign In
          {/if}
        </button>
      </form>
    {:else}
      <form on:submit={handleSignup}>
        <div class="form-group">
          <label for="signup-email">Email</label>
          <input 
            type="email" 
            id="signup-email"
            bind:value={signupEmail}
            placeholder="you@example.com" 
            required
            disabled={loading}
          >
        </div>
        <div class="form-group">
          <label for="signup-password">Password</label>
          <input 
            type="password" 
            id="signup-password"
            bind:value={signupPassword}
            placeholder="••••••••" 
            required
            disabled={loading}
          >
        </div>
        <div class="form-group">
          <label for="signup-confirm">Confirm Password</label>
          <input 
            type="password" 
            id="signup-confirm"
            bind:value={signupConfirm}
            placeholder="••••••••" 
            required
            disabled={loading}
          >
        </div>
        <button type="submit" class="btn btn-primary btn-full" disabled={loading}>
          {#if loading}
            <span class="spinner"></span>
          {:else}
            Create Account
          {/if}
        </button>
      </form>
    {/if}
    
    {#if error}
      <p class="error-message">{error}</p>
    {/if}
  </div>
</div>

<style>
  .auth-container {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 100vh;
    padding: 20px;
  }
  
  .auth-card {
    width: 100%;
    max-width: 420px;
    padding: 32px;
  }
  
  .auth-title {
    text-align: center;
    margin-bottom: 24px;
  }
  
  .auth-title h1 {
    font-size: 1.75rem;
    margin-bottom: 8px;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 12px;
  }
  
  .auth-title p {
    color: var(--text-muted);
  }
  
  .brand-dot {
    width: 12px;
    height: 12px;
    border-radius: 999px;
    background: linear-gradient(180deg, var(--primary), var(--primary2));
    box-shadow: 0 0 0 4px rgba(109,92,255,.18);
  }
  
  .tabs {
    display: flex;
    gap: 4px;
    margin-bottom: 20px;
    padding: 6px;
    background: var(--tabs-bg);
    border: 1px solid var(--border);
    border-radius: 14px;
    justify-content: center;
  }
  
  .tab {
    flex: 1;
    padding: 10px 18px;
    background: transparent;
    border: none;
    border-radius: 10px;
    color: var(--text-muted);
    cursor: pointer;
    font-size: 0.875rem;
    font-weight: 600;
    transition: all 0.2s;
  }
  
  .tab.active {
    background: var(--tab-active-bg);
    color: var(--tab-active-text);
  }
  
  .tab:hover:not(.active) {
    background: var(--tab-hover-bg);
    color: var(--text);
  }
  
  .form-group {
    margin-bottom: 16px;
  }
  
  .form-group label {
    display: block;
    font-size: 0.875rem;
    color: var(--text-muted);
    margin-bottom: 6px;
  }
  
  input {
    width: 100%;
    padding: 12px 14px;
    background: var(--bg-input);
    border: 1px solid var(--border);
    border-radius: 14px;
    color: var(--text);
    font-size: 0.9rem;
    transition: all 0.2s;
  }
  
  input:focus {
    outline: none;
    border-color: var(--primary);
    background: var(--input-focus-bg);
  }
  
  input:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }
  
  .btn {
    padding: 12px 18px;
    border: 1px solid var(--border);
    border-radius: 14px;
    font-size: 0.9rem;
    font-weight: 650;
    cursor: pointer;
    transition: all 0.2s;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
  }
  
  .btn-primary {
    background: linear-gradient(135deg, var(--primary), var(--primary2));
    border-color: rgba(109,92,255,.35);
    color: white;
    box-shadow: 0 8px 24px rgba(99,102,241,.25);
  }
  
  .btn-primary:hover:not(:disabled) {
    filter: brightness(1.05);
  }
  
  .btn-full {
    width: 100%;
  }
  
  .btn:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }
  
  .error-message {
    color: var(--danger);
    margin-top: 16px;
    text-align: center;
    font-size: 0.875rem;
  }
  
  .spinner {
    width: 18px;
    height: 18px;
    border: 2px solid rgba(255,255,255,.3);
    border-top-color: white;
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }
  
  @keyframes spin {
    to { transform: rotate(360deg); }
  }
  
  /* Mobile */
  @media (max-width: 480px) {
    .auth-card {
      padding: 24px 20px;
    }
    
    .auth-title h1 {
      font-size: 1.5rem;
    }
  }
</style>
