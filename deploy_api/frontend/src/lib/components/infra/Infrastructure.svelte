<script>
  import { onMount } from 'svelte'
  import { servers, serversStore, scope } from '../../stores/app.js'
  import { toasts } from '../../stores/toast.js'
  import { api } from '../../api/client.js'
  import Card from '../ui/Card.svelte'
  import Button from '../ui/Button.svelte'
  import Modal from '../ui/Modal.svelte'
  import ServerCard from './ServerCard.svelte'
  
  let loading = false
  let provisionModalOpen = false
  
  // Subscribe to store loading state
  $: storeState = $serversStore || { loading: false }
  $: loading = storeState.loading
  
  // Provision form
  let provisionForm = {
    name: '',
    project: '',
    env: 'prod',
    region: 'nyc1',
    size: 's-1vcpu-1gb',
    count: 1
  }
  
  const regions = [
    { value: 'nyc1', label: 'New York 1' },
    { value: 'nyc3', label: 'New York 3' },
    { value: 'sfo3', label: 'San Francisco 3' },
    { value: 'ams3', label: 'Amsterdam 3' },
    { value: 'sgp1', label: 'Singapore 1' },
    { value: 'lon1', label: 'London 1' },
    { value: 'fra1', label: 'Frankfurt 1' },
    { value: 'tor1', label: 'Toronto 1' },
    { value: 'blr1', label: 'Bangalore 1' }
  ]
  
  const sizes = [
    { value: 's-1vcpu-512mb-10gb', label: '$4/mo - 1 vCPU, 512MB RAM' },
    { value: 's-1vcpu-1gb', label: '$6/mo - 1 vCPU, 1GB RAM' },
    { value: 's-1vcpu-2gb', label: '$12/mo - 1 vCPU, 2GB RAM' },
    { value: 's-2vcpu-2gb', label: '$18/mo - 2 vCPU, 2GB RAM' },
    { value: 's-2vcpu-4gb', label: '$24/mo - 2 vCPU, 4GB RAM' },
    { value: 's-4vcpu-8gb', label: '$48/mo - 4 vCPU, 8GB RAM' }
  ]
  
  // SWR store handles initial fetch automatically
  
  async function provision() {
    try {
      const result = await api('POST', '/infra/servers/provision', {
        name: provisionForm.name,
        project: provisionForm.project,
        env: provisionForm.env,
        region: provisionForm.region,
        size: provisionForm.size,
        count: provisionForm.count
      })
      toasts.success(`Provisioned ${result.created || 1} server(s)`)
      provisionModalOpen = false
      // Refresh store to get new server
      serversStore.refresh()
    } catch (err) {
      toasts.error('Failed to provision: ' + err.message)
    }
  }
  
  async function handleServerAction(event) {
    const { server } = event.detail
    const action = event.type
    
    try {
      switch (action) {
        case 'start':
          // Power actions not yet implemented - show message
          toasts.info(`Power actions not yet implemented. Use DigitalOcean console.`)
          break
        case 'stop':
          toasts.info(`Power actions not yet implemented. Use DigitalOcean console.`)
          break
        case 'destroy':
          if (confirm(`Are you sure you want to destroy ${server.name}? This cannot be undone.`)) {
            await api('DELETE', `/infra/servers/${server.id}`)
            toasts.success(`Destroyed ${server.name}`)
          }
          break
        case 'ssh':
          // TODO: Open terminal modal
          toasts.info('Terminal feature coming soon')
          break
        case 'details':
          // TODO: Open details modal
          toasts.info('Details modal coming soon')
          break
      }
      serversStore.refresh()
    } catch (err) {
      toasts.error(`Failed to ${action}: ${err.message}`)
    }
  }
  
  export function refresh() {
    serversStore.refresh()
  }
</script>

<div class="infrastructure">
  <div class="page-header">
    <div>
      <h1>Infrastructure</h1>
      <p class="subtitle">Inventory & lifecycle actions</p>
    </div>
    <Button variant="primary" on:click={() => provisionModalOpen = true}>
      <span class="plus-icon">+</span>
      Provision
    </Button>
  </div>
  
  <Card title="Servers" padding={false}>
    <Button slot="header" variant="ghost" size="sm" on:click={() => serversStore.refresh()}>
      ↻ Refresh
    </Button>
    
    <div class="server-list">
      {#if loading}
        <div class="empty-state">
          <p>Loading...</p>
        </div>
      {:else if $servers.length === 0}
        <div class="empty-state">
          <p>No servers found. Provision one to get started.</p>
        </div>
      {:else}
        {#each $servers as server (server.id)}
          <ServerCard 
            {server}
            on:start={handleServerAction}
            on:stop={handleServerAction}
            on:destroy={handleServerAction}
            on:ssh={handleServerAction}
            on:details={handleServerAction}
          />
        {/each}
      {/if}
    </div>
  </Card>
</div>

<Modal 
  bind:open={provisionModalOpen} 
  title="Provision Server"
  width="500px"
  on:close={() => provisionModalOpen = false}
>
  <form on:submit|preventDefault={provision}>
    <div class="form-row">
      <div class="form-group">
        <label for="prov-name">Name *</label>
        <input 
          id="prov-name"
          type="text" 
          bind:value={provisionForm.name}
          placeholder="web-server-01"
          required
        >
      </div>
    </div>
    
    <div class="form-row two-col">
      <div class="form-group">
        <label for="prov-project">Project</label>
        <input 
          id="prov-project"
          type="text" 
          bind:value={provisionForm.project}
          placeholder="myapp"
        >
      </div>
      <div class="form-group">
        <label for="prov-env">Environment</label>
        <select id="prov-env" bind:value={provisionForm.env}>
          <option value="prod">Production</option>
          <option value="staging">Staging</option>
          <option value="dev">Development</option>
        </select>
      </div>
    </div>
    
    <div class="form-row two-col">
      <div class="form-group">
        <label for="prov-region">Region</label>
        <select id="prov-region" bind:value={provisionForm.region}>
          {#each regions as region}
            <option value={region.value}>{region.label}</option>
          {/each}
        </select>
      </div>
      <div class="form-group">
        <label for="prov-count">Count</label>
        <input 
          id="prov-count"
          type="number" 
          bind:value={provisionForm.count}
          min="1"
          max="10"
        >
      </div>
    </div>
    
    <div class="form-group">
      <label for="prov-size">Size</label>
      <select id="prov-size" bind:value={provisionForm.size}>
        {#each sizes as size}
          <option value={size.value}>{size.label}</option>
        {/each}
      </select>
    </div>
  </form>
  
  <div slot="footer">
    <Button variant="ghost" on:click={() => provisionModalOpen = false}>
      Cancel
    </Button>
    <Button variant="primary" on:click={provision}>
      🚀 Provision
    </Button>
  </div>
</Modal>

<style>
  .infrastructure {
    padding: 0;
  }
  
  .page-header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 16px;
    margin-bottom: 20px;
    flex-wrap: wrap;
  }
  
  .page-header h1 {
    margin: 0;
    font-size: 2rem;
    letter-spacing: 0.2px;
  }
  
  .subtitle {
    margin-top: 6px;
    color: var(--text-muted);
    font-size: 0.875rem;
  }
  
  .plus-icon {
    width: 18px;
    height: 18px;
    border-radius: 6px;
    background: rgba(255,255,255,.18);
    display: grid;
    place-items: center;
    box-shadow: inset 0 0 0 1px rgba(255,255,255,.18);
    font-weight: 900;
  }
  
  .server-list {
    padding: 16px;
  }
  
  .empty-state {
    text-align: center;
    padding: 40px;
    color: var(--text-muted);
  }
  
  .form-row {
    margin-bottom: 16px;
  }
  
  .form-row.two-col {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
  }
  
  .form-group {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  
  .form-group label {
    font-size: 0.875rem;
    color: var(--text-muted);
  }
  
  .form-group input,
  .form-group select {
    width: 100%;
    padding: 10px 12px;
    background: var(--bg-input);
    border: 1px solid var(--border);
    border-radius: 12px;
    color: var(--text);
    font-size: 0.875rem;
  }
  
  .form-group input:focus,
  .form-group select:focus {
    outline: none;
    border-color: var(--primary);
    background: var(--input-focus-bg);
  }
  
  @media (max-width: 640px) {
    .page-header {
      flex-direction: column;
      align-items: stretch;
    }
    
    .page-header h1 {
      font-size: 1.5rem;
    }
    
    .form-row.two-col {
      grid-template-columns: 1fr;
    }
  }
</style>
