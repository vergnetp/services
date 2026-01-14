<script>
  import { createEventDispatcher } from 'svelte'
  import Badge from '../ui/Badge.svelte'
  import Button from '../ui/Button.svelte'
  import { EXPECTED_AGENT_VERSION, doToken } from '../../stores/app.js'
  import { toasts } from '../../stores/toast.js'
  import { api } from '../../api/client.js'
  
  export let server
  export let showProject = false
  
  const dispatch = createEventDispatcher()
  
  $: ip = server.ip || server.networks?.v4?.[0]?.ip_address || 'N/A'
  $: status = server.status || 'unknown'
  $: isOnline = status === 'active' || status === 'online'
  $: agentVersion = server.agent_version
  $: agentOutdated = agentVersion && agentVersion !== EXPECTED_AGENT_VERSION
  
  // Health warning - any metric > 80%
  $: hasHealthWarning = metrics && (metrics.cpu > 80 || metrics.mem > 80 || metrics.disk > 80)
  
  // Container state
  let containers = []
  let loadingContainers = false
  let containersLoaded = false
  let actionInProgress = {}
  
  // Metrics state
  let metrics = null
  let loadingMetrics = false
  
  // Estimate monthly cost from size
  $: monthlyCost = estimateCost(server.size_slug || server.size || '')
  
  function estimateCost(size) {
    if (size.includes('4gb')) return 24
    if (size.includes('2gb')) return 12
    if (size.includes('1gb')) return 6
    if (size.includes('512mb')) return 4
    return 6
  }
  
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
  
  function getContainerStatusColor(state) {
    if (!state) return 'gray'
    const s = state.toLowerCase()
    if (s === 'running') return 'green'
    if (s === 'exited' || s === 'stopped') return 'yellow'
    if (s === 'restarting') return 'blue'
    return 'red'
  }
  
  function getUsageClass(pct) {
    if (pct >= 90) return 'danger'
    if (pct >= 70) return 'warning'
    return 'ok'
  }
  
  function getContainerName(container) {
    if (container.Names && typeof container.Names === 'string') {
      return container.Names.replace(/^\//, '')
    }
    if (Array.isArray(container.Names) && container.Names.length > 0) {
      return container.Names[0].replace(/^\//, '')
    }
    if (container.Name) return container.Name.replace(/^\//, '')
    if (container.name) return container.name
    if (container.ID) return container.ID.substring(0, 12)
    if (container.Id) return container.Id.substring(0, 12)
    return 'unknown'
  }
  
  function getContainerState(container) {
    return container.State || container.state || container.Status || 'unknown'
  }
  
  function getShortName(fullName) {
    if (!fullName) return 'unknown'
    const parts = fullName.split('-')
    if (parts.length >= 3 && parts[0].length <= 10) {
      return parts.slice(2).join('-')
    }
    return fullName
  }
  
  function handleAction(action) {
    dispatch(action, { server })
  }
  
  async function loadContainers() {
    if (!isOnline || !$doToken) return
    
    loadingContainers = true
    try {
      const res = await api('GET', `/infra/agent/${ip}/containers?do_token=${$doToken}`)
      containers = res.containers || []
      containersLoaded = true
    } catch (e) {
      console.error('Failed to load containers:', e)
      containers = []
    } finally {
      loadingContainers = false
    }
  }
  
  async function loadMetrics() {
    if (!isOnline || !$doToken) return
    
    loadingMetrics = true
    try {
      const res = await api('GET', `/infra/agent/${ip}/metrics?do_token=${$doToken}`)
      metrics = {
        cpu: res.system?.load_1m || 0,
        mem: res.system?.mem_percent || 0,
        disk: res.system?.disk_percent || 0,
        netIn: res.system?.net_in_bytes || 0,
        netOut: res.system?.net_out_bytes || 0
      }
    } catch (e) {
      console.error('Failed to load metrics:', e)
    } finally {
      loadingMetrics = false
    }
  }
  
  function formatNetBytes(bytes) {
    if (!bytes) return '0'
    if (bytes < 1024) return `${bytes}B`
    if (bytes < 1048576) return `${(bytes / 1024).toFixed(0)}K`
    if (bytes < 1073741824) return `${(bytes / 1048576).toFixed(1)}M`
    return `${(bytes / 1073741824).toFixed(1)}G`
  }
  
  async function restartContainer(name) {
    if (!$doToken) return
    actionInProgress[name] = 'restart'
    try {
      await api('POST', `/infra/agent/${ip}/containers/${name}/restart?do_token=${$doToken}`)
      toasts.success(`Restarted ${getShortName(name)}`)
      await loadContainers()
    } catch (e) {
      toasts.error(`Failed: ${e.message}`)
    } finally {
      actionInProgress[name] = null
    }
  }
  
  async function removeContainer(name) {
    if (!$doToken) return
    if (!confirm(`Remove "${getShortName(name)}"?`)) return
    
    actionInProgress[name] = 'remove'
    try {
      await api('POST', `/infra/agent/${ip}/containers/${name}/stop?do_token=${$doToken}`).catch(() => {})
      await api('POST', `/infra/agent/${ip}/containers/${name}/remove?do_token=${$doToken}`)
      toasts.success(`Removed ${getShortName(name)}`)
      await loadContainers()
    } catch (e) {
      toasts.error(`Failed: ${e.message}`)
    } finally {
      actionInProgress[name] = null
    }
  }
  
  function viewLogs(name) {
    dispatch('viewLogs', { server, containerName: name })
  }
  
  async function refresh() {
    await Promise.all([loadContainers(), loadMetrics()])
  }
  
  // Auto-load when online
  $: if (isOnline && !containersLoaded && $doToken) {
    loadContainers()
    loadMetrics()
  }
</script>

<div class="server-card">
  <div class="server-header">
    <div class="server-info">
      <span class="status-dot {getStatusColor(status)}"></span>
      <span class="server-name">{server.name || 'Unnamed'}</span>
      {#if hasHealthWarning}
        <span class="health-warn" title="High resource usage">⚠</span>
      {/if}
      <code class="server-ip">{ip}</code>
      <span class="server-meta">{server.region?.slug || server.region || ''}</span>
      {#if agentOutdated}
        <span class="agent-warn" title="Agent outdated">⚠️</span>
      {/if}
    </div>
    <div class="server-metrics-inline">
      {#if isOnline && metrics}
        <span class="metric-inline {getUsageClass(metrics.cpu)}">CPU {metrics.cpu.toFixed(0)}%</span>
        <span class="metric-inline {getUsageClass(metrics.mem)}">MEM {metrics.mem.toFixed(0)}%</span>
        <span class="metric-inline {getUsageClass(metrics.disk)}">DISK {metrics.disk.toFixed(0)}%</span>
        {#if metrics.netIn || metrics.netOut}
          <span class="metric-inline net">↓{formatNetBytes(metrics.netIn)} ↑{formatNetBytes(metrics.netOut)}</span>
        {/if}
      {:else if isOnline && loadingMetrics}
        <span class="metric-skeleton"></span>
        <span class="metric-skeleton"></span>
        <span class="metric-skeleton"></span>
      {:else if !isOnline}
        <span class="metric-inline offline">offline</span>
      {/if}
      <span class="metric-inline cost">£{monthlyCost}/mo</span>
    </div>
    <div class="server-actions">
      {#if showProject && server.project}
        <Badge variant="info">{server.project}</Badge>
      {/if}
      <button class="icon-btn" title="Refresh" on:click={refresh} disabled={loadingContainers || loadingMetrics}>
        {loadingContainers || loadingMetrics ? '...' : '↻'}
      </button>
      <button class="icon-btn danger" title="Destroy" on:click={() => handleAction('destroy')}>
        🗑️
      </button>
    </div>
  </div>
  
  <div class="containers">
    {#if loadingContainers && containers.length === 0}
      <span class="loading-text">Loading...</span>
    {:else if containers.length === 0 && containersLoaded}
      <span class="empty-text">No containers</span>
    {:else}
      {#each containers as container}
        {@const name = getContainerName(container)}
        {@const displayName = getShortName(name)}
        {@const state = getContainerState(container)}
        {@const busy = actionInProgress[name]}
        <div class="container-pill" class:busy title={name}>
          <span class="container-status {getContainerStatusColor(state)}"></span>
          <span class="container-name">{displayName}</span>
          <div class="container-actions">
            <button class="pill-btn" title="Restart" on:click={() => restartContainer(name)} disabled={busy}>
              {busy === 'restart' ? '...' : '↻'}
            </button>
            <button class="pill-btn" title="Logs" on:click={() => viewLogs(name)}>
              📋
            </button>
            <button class="pill-btn danger" title="Remove" on:click={() => removeContainer(name)} disabled={busy}>
              ×
            </button>
          </div>
        </div>
      {/each}
    {/if}
  </div>
</div>

<style>
  .server-card {
    background: var(--table-row-hover);
    border: 1px solid var(--border);
    border-radius: var(--r2);
    padding: 10px 12px;
    margin-bottom: 8px;
  }
  
  .server-card:hover {
    border-color: var(--border2);
  }
  
  .server-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 8px;
    margin-bottom: 6px;
  }
  
  .server-info {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }
  
  .status-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
  }
  
  .status-dot.green { background: var(--success); }
  .status-dot.blue { background: var(--primary2); }
  .status-dot.yellow { background: var(--warning); }
  .status-dot.red { background: var(--danger); }
  
  .server-name {
    font-weight: 600;
    font-size: 0.9rem;
  }
  
  .server-ip {
    font-family: monospace;
    font-size: 0.8rem;
    color: var(--text-muted);
  }
  
  .server-meta {
    font-size: 0.75rem;
    color: var(--text-muted);
  }
  
  .agent-warn {
    font-size: 0.75rem;
  }
  
  .server-metrics-inline {
    display: flex;
    align-items: center;
    gap: 10px;
    font-size: 0.7rem;
    font-family: monospace;
  }
  
  .metric-inline {
    padding: 2px 6px;
    border-radius: 4px;
    background: rgba(255,255,255,.05);
  }
  
  .metric-inline.ok {
    color: var(--success);
  }
  
  .metric-inline.warning {
    color: var(--warning);
  }
  
  .metric-inline.danger {
    color: var(--danger);
  }
  
  .metric-inline.loading {
    color: var(--text-muted2);
  }
  
  .metric-inline.cost {
    color: var(--text-muted);
  }
  
  .metric-inline.net {
    color: var(--text-muted);
    font-size: 0.65rem;
  }
  
  .metric-inline.offline {
    color: var(--text-muted2);
    font-style: italic;
  }
  
  .metric-skeleton {
    width: 50px;
    height: 18px;
    background: linear-gradient(90deg, rgba(255,255,255,.03) 25%, rgba(255,255,255,.06) 50%, rgba(255,255,255,.03) 75%);
    background-size: 200% 100%;
    animation: skeleton-shimmer 1.5s infinite;
    border-radius: 4px;
  }
  
  @keyframes skeleton-shimmer {
    0% { background-position: 200% 0; }
    100% { background-position: -200% 0; }
  }
  
  .health-warn {
    color: var(--warning);
    font-size: 0.85rem;
  }
  
  .server-actions {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  
  .icon-btn {
    background: transparent;
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 3px 6px;
    cursor: pointer;
    font-size: 0.7rem;
    color: var(--text-muted);
    transition: all 0.15s;
  }
  
  .icon-btn:hover {
    background: rgba(255,255,255,.1);
    border-color: var(--border2);
    color: var(--text);
  }
  
  .icon-btn.danger:hover {
    background: rgba(255,77,94,.15);
    border-color: var(--danger);
  }
  
  .icon-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  
  /* Containers */
  .containers {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  
  .loading-text, .empty-text {
    font-size: 0.7rem;
    color: var(--text-muted2);
  }
  
  .container-pill {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 4px 8px;
    background: rgba(29, 99, 237, 0.08);
    border: 1px solid rgba(29, 99, 237, 0.2);
    border-radius: 6px;
    font-size: 0.75rem;
  }
  
  .container-pill:hover {
    background: rgba(29, 99, 237, 0.15);
    border-color: rgba(29, 99, 237, 0.35);
  }
  
  .container-pill.busy {
    opacity: 0.6;
  }
  
  .container-status {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    flex-shrink: 0;
  }
  
  .container-status.green { background: var(--success); }
  .container-status.yellow { background: var(--warning); }
  .container-status.blue { background: var(--primary2); }
  .container-status.red { background: var(--danger); }
  .container-status.gray { background: var(--text-muted); }
  
  .container-name {
    font-family: monospace;
    color: var(--text);
    max-width: 120px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  
  .container-actions {
    display: flex;
    gap: 2px;
    opacity: 0;
    transition: opacity 0.15s;
  }
  
  .container-pill:hover .container-actions {
    opacity: 1;
  }
  
  .pill-btn {
    background: transparent;
    border: none;
    padding: 0 3px;
    cursor: pointer;
    font-size: 0.65rem;
    color: var(--text-muted);
    transition: color 0.15s;
  }
  
  .pill-btn:hover {
    color: var(--text);
  }
  
  .pill-btn.danger:hover {
    color: var(--danger);
  }
  
  .pill-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  
  @media (max-width: 640px) {
    .server-header {
      flex-direction: column;
      align-items: flex-start;
    }
    
    .server-actions {
      width: 100%;
      justify-content: flex-end;
    }
  }
</style>
