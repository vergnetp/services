<script>
  import { onMount } from 'svelte'
  
  // Shared components and stores from @myorg/ui
  import { 
    Auth, Header, Tabs, ToastContainer,
    authStore, isAuthenticated, isAdmin, setAuthToken,
    toasts, api,
    presets
  } from '@myorg/ui'
  import '@myorg/ui/styles/base.css'
  import './app.css'
  
  // App-specific stores
  import { 
    currentTab, scope, doToken,
    serversStore, projectsStore, snapshotsStore, deploymentsStore
  } from './lib/stores/app.js'
  
  // App-specific components
  import ScopeBar from './lib/components/ui/ScopeBar.svelte'
  import Infrastructure from './lib/components/infra/Infrastructure.svelte'
  import Deploy from './lib/components/deploy/Deploy.svelte'
  import Deployments from './lib/components/deploy/Deployments.svelte'
  import Services from './lib/components/services/Services.svelte'
  import Settings from './lib/components/settings/Settings.svelte'
  import Architecture from './lib/components/architecture/Architecture.svelte'
  import Telemetry from './lib/components/telemetry/Telemetry.svelte'
  
  // ==========================================================================
  // BUILD VERSION - Embedded at build time by Claude
  // ==========================================================================
  const BUILD_VERSION = '2026-01-25 08:45 UTC'
  // ==========================================================================
  
  let initialized = false
  let infraRef
  let deploymentsRef
  let architectureRef
  let lastDoToken = null
  
  // Base tabs available to all users
  const baseTabs = [
    { id: 'infra', label: 'Infrastructure' },
    { id: 'deploy', label: 'Deploy' },
    { id: 'deployments', label: 'Deployments' },
    { id: 'architecture', label: 'Architecture' },
    { id: 'services', label: 'Services' },
    { id: 'settings', label: 'Settings' }
  ]
  
  // Admin-only tabs
  const adminTabs = [
    { id: 'telemetry', label: '⚙️ Admin', admin: true }
  ]
  
  // Combined tabs (reactive based on isAdmin)
  $: tabs = $isAdmin ? [...baseTabs, ...adminTabs] : baseTabs
  
  $: showScopeBar = $currentTab === 'deployments'
  $: showTail = false
  $: showContainer = false
  
  // Reactive: reload stores when DO token changes (after initial auth)
  $: if (initialized && $authStore.user && $doToken && $doToken !== lastDoToken) {
    lastDoToken = $doToken
    preloadStores()
  }
  
  onMount(async () => {
    const authenticated = await initAuth()
    initialized = true
    
    if (authenticated) {
      // Initialize lastDoToken to prevent double-fetch on mount
      lastDoToken = $doToken
      preloadStores()
    }
  })
  
  // Initialize auth - check existing token
  async function initAuth() {
    const authState = $authStore
    
    if (!authState.token || authState.token.trim() === '') {
      return false
    }
    
    try {
      const user = await api('GET', '/auth/me')
      authStore.setUser(user)
      return true
    } catch (err) {
      authStore.logout()
      return false
    }
  }
  
  // Preload all core data immediately on auth
  function preloadStores() {
    serversStore.refresh()
    projectsStore.refresh()
    snapshotsStore.refresh()
    deploymentsStore.refresh()
  }
  
  async function handleAuthSuccess(event) {
    const { user, token } = event.detail
    setAuthToken(token)
    authStore.setUser(user)
    lastDoToken = $doToken
    preloadStores()
  }
  
  function handleTabChange(event) {
    currentTab.set(event.detail)
  }
  
  function handleScopeChange() {
    refreshCurrentTab()
  }
  
  function refreshCurrentTab() {
    switch ($currentTab) {
      case 'infra':
        infraRef?.refresh()
        serversStore.refresh()
        break
      case 'deployments':
        deploymentsRef?.refresh()
        break
      case 'architecture':
        architectureRef?.refresh()
        break
    }
  }
</script>

<ToastContainer />

{#if !initialized}
  <div class="loading-screen">
    <div class="spinner"></div>
  </div>
{:else if !$authStore.token || !$authStore.user}
  <Auth 
    title="Deploy Dashboard"
    subtitle="Sign in to manage your infrastructure"
    {...presets.internal}
    allowSignup={true}
    on:success={handleAuthSuccess}
  />
{:else}
  <div class="app">
    <div class="container">
      <Header title="Deploy Dashboard" />
      
      <!-- Version badge -->
      <div class="version-badge" title="Build timestamp">{BUILD_VERSION}</div>
      
      <Tabs 
        {tabs} 
        active={$currentTab} 
        on:change={handleTabChange}
        scrollable={true}
      />
      
      {#if showScopeBar}
        <ScopeBar 
          {showTail}
          {showContainer}
          on:change={handleScopeChange}
          on:refresh={refreshCurrentTab}
        />
      {/if}
      
      <main class="content glass">
        <!-- Keep key components mounted but hidden for instant tab switching -->
        <div class:hidden={$currentTab !== 'infra'}>
          <Infrastructure bind:this={infraRef} />
        </div>
        <div class:hidden={$currentTab !== 'deploy'}>
          <Deploy />
        </div>
        <div class:hidden={$currentTab !== 'deployments'}>
          <Deployments bind:this={deploymentsRef} />
        </div>
        <div class:hidden={$currentTab !== 'architecture'}>
          <Architecture bind:this={architectureRef} />
        </div>
        
        <!-- These can remount since they're less frequently used -->
        {#if $currentTab === 'services'}
          <Services />
        {:else if $currentTab === 'settings'}
          <Settings />
        {:else if $currentTab === 'telemetry' && $isAdmin}
          <Telemetry />
        {/if}
      </main>
    </div>
  </div>
{/if}

<style>
  .version-badge {
    position: fixed;
    bottom: 10px;
    right: 10px;
    background: var(--bg-tertiary, #333);
    color: var(--text-secondary, #888);
    padding: 4px 10px;
    border-radius: 4px;
    font-size: 11px;
    font-family: monospace;
    opacity: 0.7;
    z-index: 1000;
    cursor: default;
  }
  
  .version-badge:hover {
    opacity: 1;
  }
</style>
