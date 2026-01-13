<script>
  import { onMount } from 'svelte'
  import { auth } from './lib/stores/auth.js'
  import { 
    currentTab, scope, 
    serversStore, projectsStore, snapshotsStore, deploymentsStore,
    SCOPE_BAR_TABS 
  } from './lib/stores/app.js'
  import { toasts } from './lib/stores/toast.js'
  import { api, initAuth } from './lib/api/client.js'
  
  // Components
  import Auth from './lib/components/auth/Auth.svelte'
  import ToastContainer from './lib/components/ui/ToastContainer.svelte'
  import Header from './lib/components/ui/Header.svelte'
  import Tabs from './lib/components/ui/Tabs.svelte'
  import ScopeBar from './lib/components/ui/ScopeBar.svelte'
  
  // Page components
  import Infrastructure from './lib/components/infra/Infrastructure.svelte'
  import Deploy from './lib/components/deploy/Deploy.svelte'
  import Deployments from './lib/components/deploy/Deployments.svelte'
  import Logs from './lib/components/logs/Logs.svelte'
  import Metrics from './lib/components/metrics/Metrics.svelte'
  import Snapshots from './lib/components/snapshots/Snapshots.svelte'
  import Services from './lib/components/services/Services.svelte'
  import Settings from './lib/components/settings/Settings.svelte'
  import Architecture from './lib/components/architecture/Architecture.svelte'
  
  let initialized = false
  let infraRef
  let deploymentsRef
  let logsRef
  let metricsRef
  let architectureRef
  
  const tabs = [
    { id: 'infra', label: 'Infrastructure' },
    { id: 'deploy', label: 'Deploy' },
    { id: 'deployments', label: 'Deployments' },
    { id: 'architecture', label: 'Architecture' },
    { id: 'logs', label: 'Logs' },
    { id: 'metrics', label: 'Metrics' },
    { id: 'snapshots', label: 'Snapshots' },
    { id: 'services', label: 'Services' },
    { id: 'settings', label: 'Settings' }
  ]
  
  $: showScopeBar = SCOPE_BAR_TABS.includes($currentTab)
  $: showTail = $currentTab === 'logs'
  $: showContainer = $currentTab === 'logs'
  
  onMount(async () => {
    const authenticated = await initAuth()
    initialized = true
    
    if (authenticated) {
      preloadStores()
    }
  })
  
  // Preload all core data immediately on auth
  function preloadStores() {
    // These trigger fetch immediately
    serversStore.refresh()
    projectsStore.refresh()
    snapshotsStore.refresh()
    deploymentsStore.refresh()
  }
  
  async function handleAuthSuccess(event) {
    const { user, token } = event.detail
    auth.setToken(token)
    auth.setUser(user)
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
      case 'logs':
        logsRef?.refresh()
        break
      case 'metrics':
        metricsRef?.refresh()
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
{:else if !$auth.token || !$auth.user}
  <Auth 
    title="Deploy Dashboard"
    subtitle="Sign in to manage your infrastructure"
    on:success={handleAuthSuccess}
  />
{:else}
  <div class="app">
    <div class="container">
      <Header />
      
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
        <div class:hidden={$currentTab !== 'metrics'}>
          <Metrics bind:this={metricsRef} />
        </div>
        
        <!-- These can remount since they're less frequently used -->
        {#if $currentTab === 'logs'}
          <Logs bind:this={logsRef} />
        {:else if $currentTab === 'snapshots'}
          <Snapshots />
        {:else if $currentTab === 'services'}
          <Services />
        {:else if $currentTab === 'settings'}
          <Settings />
        {/if}
      </main>
    </div>
  </div>
{/if}

<style>
  .loading-screen {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 100vh;
  }
  
  .spinner {
    width: 40px;
    height: 40px;
    border: 3px solid var(--border);
    border-top-color: var(--primary);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }
  
  @keyframes spin {
    to { transform: rotate(360deg); }
  }
  
  .app {
    min-height: 100vh;
  }
  
  .container {
    max-width: 1280px;
    margin: 0 auto;
    padding: 24px 28px 60px;
  }
  
  .content {
    padding: 22px;
  }
  
  @media (max-width: 768px) {
    .container {
      padding: 16px 12px 40px;
    }
    
    .content {
      padding: 16px;
      border-radius: var(--r2);
    }
  }
  
  .hidden {
    display: none !important;
  }
</style>
