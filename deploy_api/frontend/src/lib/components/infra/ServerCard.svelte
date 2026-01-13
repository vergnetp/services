<script>
  import { createEventDispatcher } from 'svelte'
  import Badge from '../ui/Badge.svelte'
  import Button from '../ui/Button.svelte'
  import { EXPECTED_AGENT_VERSION } from '../../stores/app.js'
  
  export let server
  
  const dispatch = createEventDispatcher()
  
  $: ip = server.ip || server.networks?.v4?.[0]?.ip_address || 'N/A'
  $: status = server.status || 'unknown'
  $: isOnline = status === 'active' || status === 'online'
  $: containers = server.containers || []
  $: agentVersion = server.agent_version
  $: agentOutdated = agentVersion && agentVersion !== EXPECTED_AGENT_VERSION
  
  function getStatusColor(status) {
    switch (status) {
      case 'active':
      case 'online':
        return 'green'
      case 'new':
      case 'starting':
        return 'blue'
      case 'off':
      case 'stopped':
        return 'yellow'
      default:
        return 'red'
    }
  }
  
  function handleAction(action) {
    dispatch(action, { server })
  }
</script>

<div class="server-item">
  <div class="server-header">
    <div class="server-name">
      <span class="status-dot {getStatusColor(status)}"></span>
      <span>{server.name || 'Unnamed'}</span>
    </div>
    <div class="server-badges">
      {#if server.project}
        <Badge variant="info">{server.project}</Badge>
      {/if}
      {#if server.env}
        <Badge variant={server.env === 'prod' ? 'danger' : 'warning'}>{server.env}</Badge>
      {/if}
    </div>
  </div>
  
  <div class="server-details">
    <div class="detail">
      <span class="label">IP</span>
      <code class="server-ip">{ip}</code>
    </div>
    <div class="detail">
      <span class="label">Size</span>
      <span>{server.size_slug || server.size || 'N/A'}</span>
    </div>
    <div class="detail">
      <span class="label">Region</span>
      <span>{server.region?.slug || server.region || 'N/A'}</span>
    </div>
    {#if containers.length > 0}
      <div class="detail">
        <span class="label">Containers</span>
        <span>{containers.length}</span>
      </div>
    {/if}
    {#if agentVersion}
      <div class="detail">
        <span class="label">Agent</span>
        <span class:outdated={agentOutdated}>v{agentVersion}</span>
      </div>
    {/if}
  </div>
  
  {#if containers.length > 0}
    <div class="containers">
      {#each containers.slice(0, 5) as container}
        <span class="container-tag">{container.name || container}</span>
      {/each}
      {#if containers.length > 5}
        <span class="container-tag more">+{containers.length - 5}</span>
      {/if}
    </div>
  {/if}
  
  <div class="server-actions">
    <Button variant="ghost" size="sm" on:click={() => handleAction('ssh')}>
      Terminal
    </Button>
    <Button variant="ghost" size="sm" on:click={() => handleAction('details')}>
      Details
    </Button>
    {#if !isOnline}
      <Button variant="success" size="sm" on:click={() => handleAction('start')}>
        Start
      </Button>
    {:else}
      <Button variant="warning" size="sm" on:click={() => handleAction('stop')}>
        Stop
      </Button>
    {/if}
    <Button variant="danger" size="sm" on:click={() => handleAction('destroy')}>
      Destroy
    </Button>
  </div>
</div>

<style>
  .server-item {
    background: var(--table-row-hover);
    border: 1px solid var(--border);
    border-radius: var(--r2);
    padding: 16px;
    margin-bottom: 12px;
    transition: all 0.15s;
  }
  
  .server-item:hover {
    background: rgba(255,255,255,.06);
    border-color: var(--border2);
  }
  
  .server-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 12px;
    flex-wrap: wrap;
    gap: 8px;
  }
  
  .server-name {
    font-weight: 750;
    display: flex;
    align-items: center;
    gap: 10px;
    font-size: 1rem;
  }
  
  .status-dot {
    width: 10px;
    height: 10px;
    border-radius: 999px;
    flex-shrink: 0;
  }
  
  .status-dot.green {
    background: var(--success);
    box-shadow: 0 0 0 4px rgba(54,211,124,.16);
  }
  
  .status-dot.blue {
    background: var(--primary2);
    box-shadow: 0 0 0 4px rgba(45,125,255,.18);
  }
  
  .status-dot.yellow {
    background: var(--warning);
    box-shadow: 0 0 0 4px rgba(245,158,11,.16);
  }
  
  .status-dot.red {
    background: var(--danger);
    box-shadow: 0 0 0 4px rgba(255,77,94,.16);
  }
  
  .server-badges {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
  }
  
  .server-details {
    display: flex;
    gap: 16px;
    font-size: 0.8rem;
    color: var(--text-muted);
    flex-wrap: wrap;
    margin-bottom: 12px;
  }
  
  .detail {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  
  .detail .label {
    color: var(--text-muted2);
  }
  
  .server-ip {
    font-family: monospace;
    background: rgba(255,255,255,.06);
    padding: 2px 8px;
    border-radius: 6px;
    border: 1px solid var(--border);
    font-size: 0.75rem;
  }
  
  .outdated {
    color: var(--warning);
  }
  
  .containers {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
    margin-bottom: 12px;
  }
  
  .container-tag {
    font-size: 0.7rem;
    padding: 3px 8px;
    background: rgba(45,125,255,.1);
    border: 1px solid rgba(45,125,255,.2);
    border-radius: 6px;
    color: var(--primary2);
  }
  
  .container-tag.more {
    background: var(--btn-ghost-bg);
    border-color: var(--border);
    color: var(--text-muted);
  }
  
  .server-actions {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
  }
  
  @media (max-width: 640px) {
    .server-item {
      padding: 12px;
    }
    
    .server-details {
      flex-direction: column;
      gap: 8px;
    }
    
    .server-actions {
      flex-wrap: wrap;
    }
  }
</style>
