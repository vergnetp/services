import { writable, derived } from 'svelte/store'
import { createApiStore, createParamStore } from './fetchStore.js'
import { getDoToken } from './auth.js'

// Current tab
export const currentTab = writable('infra')

// DO Token store (reactive wrapper around cookie)
function createDoTokenStore() {
  const { subscribe, set } = writable(null)
  
  // Initialize from cookie on client
  if (typeof window !== 'undefined') {
    set(getDoToken())
  }
  
  return {
    subscribe,
    refresh() {
      set(getDoToken())
    },
    set(value) {
      set(value)
    }
  }
}

export const doToken = createDoTokenStore()

// Scope bar state (shared across tabs)
export const scope = writable({
  project: '',
  env: '',
  server: '',
  container: '',
  range: '30d',
  tail: false
})

// Tabs that show scope bar
export const SCOPE_BAR_TABS = ['infra', 'metrics', 'logs', 'deployments']

// ============ SWR STORES ============

// Servers list
export const serversStore = createApiStore('/infra/servers', {
  transform: (data) => data?.servers || data || [],
  refreshInterval: 60000,
  revalidateOnFocus: true,
  initialData: [],
})

// Projects list
export const projectsStore = createApiStore('/infra/projects', {
  transform: (data) => data?.projects || [],
  refreshInterval: 120000,
  initialData: [],
})

// Snapshots list
export const snapshotsStore = createApiStore('/infra/snapshots', {
  transform: (data) => data?.snapshots || [],
  refreshInterval: 60000,
  initialData: [],
})

// Deployment history
export const deploymentsStore = createApiStore('/infra/deployments/history', {
  transform: (data) => data?.deployments || [],
  refreshInterval: 30000,
  initialData: [],
})

// Containers for selected server (parameterized)
export const containersStore = createParamStore(
  (params) => params?.server ? `/infra/agent/${params.server}/containers` : null,
  {
    transform: (data) => {
      // Docker ps returns containers with Names field
      const containers = data?.containers || data || []
      return (Array.isArray(containers) ? containers : []).map(c => ({
        id: c.ID || c.Id || c.id,
        name: c.Names || c.Name || c.name || 'unknown',
        image: c.Image || c.image,
        status: c.Status || c.State || c.status,
        state: c.State || c.state,
      }))
    },
  }
)

// VPCs cache
export const vpcs = writable({})

// ============ DERIVED STORES (for easy component access) ============

export const servers = derived(serversStore, $s => $s?.data || [])
export const projects = derived(projectsStore, $s => $s?.data || [])
export const snapshots = derived(snapshotsStore, $s => $s?.data || [])
export const deploymentHistory = derived(deploymentsStore, $s => $s?.data || [])
export const containers = derived(containersStore, $s => $s?.data || [])

// Agent version (keep in sync with agent_code.py)
export const EXPECTED_AGENT_VERSION = '1.9.7'

// Theme
function createThemeStore() {
  const stored = typeof localStorage !== 'undefined' 
    ? localStorage.getItem('theme') || 'dark'
    : 'dark'
  
  const { subscribe, set } = writable(stored)
  
  if (typeof document !== 'undefined') {
    document.documentElement.setAttribute('data-theme', stored)
  }
  
  return {
    subscribe,
    set(theme) {
      if (typeof localStorage !== 'undefined') {
        localStorage.setItem('theme', theme)
      }
      if (typeof document !== 'undefined') {
        document.documentElement.setAttribute('data-theme', theme)
      }
      set(theme)
    }
  }
}

export const theme = createThemeStore()
