<script>
  import { onMount, onDestroy } from 'svelte'
  import { scope, servers } from '../../stores/app.js'
  import { toasts } from '../../stores/toast.js'
  import { api } from '../../api/client.js'
  import Card from '../ui/Card.svelte'
  import Button from '../ui/Button.svelte'
  import Badge from '../ui/Badge.svelte'
  
  let loading = false
  let lastUpdated = null
  let error = null
  let initialLoadDone = false
  let refreshTimer = null
  
  // Fleet data
  let fleetData = null
  
  // Server data
  let serverData = null
  
  $: isFleetView = !$scope.server
  
  function formatTime(date) {
    if (!date) return ''
    return date.toLocaleTimeString()
  }
  
  $: selectedServer = $servers.find(s => 
    (s.ip || s.networks?.v4?.[0]?.ip_address) === $scope.server
  )
  
  // Fleet metrics (derived)
  $: fleetMetrics = fleetData ? {
    serverCount: fleetData.summary?.total || $servers.length,
    containerCount: fleetData.servers?.reduce((sum, s) => sum + (s.containers?.length || 0), 0) || 0,
    monthlyCost: (fleetData.summary?.total || 0) * 12,
    health: fleetData.summary?.healthy === fleetData.summary?.total ? 'healthy' : 'degraded'
  } : { serverCount: $servers.length, containerCount: 0, monthlyCost: 0, health: 'unknown' }
  
  // Server info from fleet health (shows container health, not CPU)
  $: serverHealth = (fleetData?.servers || []).map(s => ({
    name: s.name || s.ip || 'Unknown',
    ip: s.ip,
    status: s.status || 'unknown',
    containers: s.containers ?? 0,
    healthy: s.healthy ?? 0,
    unhealthy: s.unhealthy ?? 0,
    healthStatus: s.health_status || 'unknown'
  }))
  
  // Server metrics (derived)
  $: serverMetrics = serverData ? {
    cpu: serverData.system?.load_1m || 0,
    memory: serverData.system?.mem_percent || 0,
    memoryUsed: serverData.system?.mem_used || 0,
    memoryTotal: serverData.system?.mem_total || 0,
    disk: serverData.system?.disk_percent || 0,
    diskUsed: serverData.system?.disk_used || 0,
    diskTotal: serverData.system?.disk_total || 0,
    network: { in: 0, out: 0 }
  } : null
  
  $: containers = (serverData?.containers || []).map(c => {
    const cpuStr = c.cpu || '0%'
    const memStr = c.memory || '0B / 0B'
    const memPercStr = c.mem_perc || '0%'
    const memParts = memStr.split('/')
    return {
      name: c.name || 'unknown',
      cpu: parseFloat(cpuStr.replace('%', '')) || 0,
      memory_percent: parseFloat(memPercStr.replace('%', '')) || 0,
      memory_used: parseMemory(memParts[0]?.trim()),
      memory_total: memParts[1] ? parseMemory(memParts[1].trim()) : 0,
      net_in: c.net_in || 0,
      net_out: c.net_out || 0,
      status: c.state || 'running'
    }
  })
  
  onMount(() => {
    loadMetrics()
    refreshTimer = setInterval(loadMetrics, isFleetView ? 30000 : 15000)
  })
  
  onDestroy(() => {
    if (refreshTimer) clearInterval(refreshTimer)
  })
  
  // Watch for scope changes
  let prevServer = null
  $: {
    const newServer = $scope.server
    if (newServer !== prevServer && prevServer !== null) {
      // Server changed - reload and reset timer
      if (refreshTimer) clearInterval(refreshTimer)
      initialLoadDone = false
      loadMetrics()
      refreshTimer = setInterval(loadMetrics, newServer ? 15000 : 30000)
    }
    prevServer = newServer
  }
  
  async function loadMetrics() {
    if (!initialLoadDone) loading = true
    error = null
    
    try {
      if (isFleetView) {
        fleetData = await api('GET', '/infra/fleet/health')
      } else {
        serverData = await api('GET', `/infra/agent/${$scope.server}/metrics`)
      }
      lastUpdated = new Date()
      initialLoadDone = true
    } catch (err) {
      error = err.message
    } finally {
      loading = false
    }
  }
  
  function parseMemory(str) {
    if (!str) return 0
    const match = str.match(/([\d.]+)\s*(B|KB|KiB|MB|MiB|GB|GiB|TB|TiB)?/i)
    if (!match) return 0
    const val = parseFloat(match[1])
    const unit = (match[2] || 'B').toLowerCase()
    const multipliers = { b: 1, kb: 1024, kib: 1024, mb: 1024**2, mib: 1024**2, gb: 1024**3, gib: 1024**3, tb: 1024**4, tib: 1024**4 }
    return val * (multipliers[unit] || 1)
  }
  
  function formatBytes(bytes) {
    if (!bytes) return '0 B'
    const units = ['B', 'KB', 'MB', 'GB', 'TB']
    let i = 0
    while (bytes >= 1024 && i < units.length - 1) {
      bytes /= 1024
      i++
    }
    return `${bytes.toFixed(1)} ${units[i]}`
  }
  
  function formatCost(cost) {
    return `$${(cost || 0).toFixed(2)}`
  }
  
  function getHealthColor(health) {
    switch (health) {
      case 'healthy': return 'success'
      case 'degraded': return 'warning'
      case 'unhealthy': return 'danger'
      default: return 'info'
    }
  }
  
  function getUsageColor(percent) {
    if (percent >= 90) return 'var(--danger)'
    if (percent >= 70) return 'var(--warning)'
    return 'var(--success)'
  }
  
  export function refresh() {
    loadMetrics()
  }
</script>

<div class="metrics-page">
  {#if isFleetView}
    <!-- Fleet View -->
    <div class="page-header">
      <h2 class="page-title">Metrics · Fleet</h2>
      <div class="header-actions">
        {#if lastUpdated}
          <span class="last-updated">Updated {formatTime(lastUpdated)}</span>
        {/if}
        <Button variant="ghost" size="sm" on:click={refresh}>↻ Refresh</Button>
      </div>
    </div>
    
    {#if error}
      <div class="empty-state">
        <p>Failed to load: {error}</p>
      </div>
    {:else}
    <!-- Summary Cards -->
    <div class="metrics-grid">
      <Card>
        <div class="metric-card">
          <div class="metric-label">Servers</div>
          <div class="metric-value">{fleetMetrics.serverCount}</div>
        </div>
      </Card>
      <Card>
        <div class="metric-card">
          <div class="metric-label">Containers</div>
          <div class="metric-value">{fleetMetrics.containerCount}</div>
        </div>
      </Card>
      <Card>
        <div class="metric-card">
          <div class="metric-label">Monthly Cost</div>
          <div class="metric-value">{formatCost(fleetMetrics.monthlyCost)}</div>
        </div>
      </Card>
      <Card>
        <div class="metric-card">
          <div class="metric-label">Health</div>
          <div class="metric-value">
            <Badge variant={getHealthColor(fleetMetrics.health)}>
              {fleetMetrics.health}
            </Badge>
          </div>
        </div>
      </Card>
    </div>
    
    <!-- Server Health Overview -->
    <Card title="Server Health">
      {#if loading && !fleetData}
        <div class="empty-state">Loading fleet health...</div>
      {:else if !fleetData}
        <div class="empty-state">Unable to load fleet health. Check your DO token.</div>
      {:else if serverHealth.length === 0}
        <div class="empty-state">No servers found</div>
      {:else}
        <div class="usage-list">
          {#each serverHealth as server}
            {@const isOnline = server.status === 'online'}
            {@const healthPercent = server.containers > 0 ? Math.round((server.healthy / server.containers) * 100) : 100}
            <div class="usage-item">
              <div class="usage-header">
                <span class="usage-name">
                  <span class="status-dot" class:online={isOnline} class:offline={!isOnline}></span>
                  {server.name}
                </span>
                {#if isOnline}
                  <span class="usage-value" style="color: {server.unhealthy > 0 ? 'var(--danger)' : 'var(--success)'}">
                    {server.healthy}/{server.containers}
                  </span>
                {:else}
                  <span class="usage-value" style="color: var(--text-muted)">{server.status}</span>
                {/if}
              </div>
              {#if isOnline}
                <div class="usage-bar">
                  <div class="usage-fill" style="width: {healthPercent}%; background: {server.unhealthy > 0 ? 'var(--warning)' : 'var(--success)'}"></div>
                </div>
                <div class="usage-details">
                  <span>Containers: {server.containers}</span>
                  <span>Healthy: {server.healthy}</span>
                  {#if server.unhealthy > 0}
                    <span style="color: var(--danger)">Unhealthy: {server.unhealthy}</span>
                  {/if}
                </div>
              {/if}
            </div>
          {/each}
        </div>
      {/if}
    </Card>
    {/if}
  {:else}
    <!-- Server View -->
    <div class="page-header">
      <h2 class="page-title">
        Metrics · <span class="server-name">{selectedServer?.name || $scope.server}</span>
      </h2>
      <div class="header-actions">
        {#if lastUpdated}
          <span class="last-updated">Updated {formatTime(lastUpdated)}</span>
        {/if}
        <Button variant="ghost" size="sm" on:click={refresh}>↻ Refresh</Button>
      </div>
    </div>
    
    {#if error}
      <div class="empty-state">
        <p>Failed to load: {error}</p>
      </div>
    {:else}
    <!-- Server Metrics Cards -->
    <div class="metrics-grid">
      <Card>
        <div class="metric-card">
          <div class="metric-label">CPU</div>
          <div class="metric-value" style="color: {getUsageColor(serverMetrics?.cpu || 0)}">
            {serverMetrics?.cpu || 0}%
          </div>
        </div>
      </Card>
      <Card>
        <div class="metric-card">
          <div class="metric-label">Memory</div>
          <div class="metric-value" style="color: {getUsageColor(serverMetrics?.memory || 0)}">
            {serverMetrics?.memory || 0}%
          </div>
          <div class="metric-detail">
            {formatBytes(serverMetrics?.memoryUsed)} / {formatBytes(serverMetrics?.memoryTotal)}
          </div>
        </div>
      </Card>
      <Card>
        <div class="metric-card">
          <div class="metric-label">Disk</div>
          <div class="metric-value" style="color: {getUsageColor(serverMetrics?.disk || 0)}">
            {serverMetrics?.disk || 0}%
          </div>
          <div class="metric-detail">
            {formatBytes(serverMetrics?.diskUsed)} / {formatBytes(serverMetrics?.diskTotal)}
          </div>
        </div>
      </Card>
      <Card>
        <div class="metric-card">
          <div class="metric-label">Network</div>
          <div class="metric-value small">
            ↓ {formatBytes(serverMetrics?.network?.in || 0)}/s
          </div>
          <div class="metric-detail">
            ↑ {formatBytes(serverMetrics?.network?.out || 0)}/s
          </div>
        </div>
      </Card>
    </div>
    
    <!-- Containers Table -->
    <Card title="🐳 Containers">
      {#if loading}
        <div class="empty-state">Loading containers...</div>
      {:else if containers.length === 0}
        <div class="empty-state">No containers found</div>
      {:else}
        <div class="table-container">
          <table class="table">
            <thead>
              <tr>
                <th>Container</th>
                <th>Status</th>
                <th>CPU</th>
                <th>Memory</th>
                <th>Network I/O</th>
              </tr>
            </thead>
            <tbody>
              {#each containers as container}
                <tr>
                  <td class="container-name">{container.name}</td>
                  <td>
                    <Badge variant={container.status === 'running' ? 'success' : 'warning'}>
                      {container.status}
                    </Badge>
                  </td>
                  <td style="color: {getUsageColor(container.cpu)}">{container.cpu.toFixed(2)}%</td>
                  <td>
                    <span style="color: {getUsageColor(container.memory_percent)}">{container.memory_percent.toFixed(2)}%</span>
                    <span class="detail">({formatBytes(container.memory_used)})</span>
                  </td>
                  <td class="network-io">
                    ↓{formatBytes(container.net_in)} / ↑{formatBytes(container.net_out)}
                  </td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      {/if}
    </Card>
    {/if}
  {/if}
</div>

<style>
  .metrics-page {
    padding: 0;
  }
  
  .page-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 16px;
  }
  
  .header-actions {
    display: flex;
    align-items: center;
    gap: 12px;
  }
  
  .last-updated {
    font-size: 0.75rem;
    color: var(--text-muted2);
  }
  
  .page-title {
    margin: 0;
    font-size: 1.25rem;
  }
  
  .server-name {
    color: var(--primary);
  }
  
  .metrics-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 16px;
    margin-bottom: 16px;
  }
  
  .metric-card {
    text-align: center;
    padding: 8px 0;
  }
  
  .metric-label {
    font-size: 0.85rem;
    color: var(--text-muted);
    margin-bottom: 4px;
  }
  
  .metric-value {
    font-size: 1.75rem;
    font-weight: 600;
  }
  
  .metric-value.small {
    font-size: 1rem;
  }
  
  .metric-detail {
    font-size: 0.75rem;
    color: var(--text-muted);
    margin-top: 4px;
  }
  
  .empty-state {
    text-align: center;
    padding: 40px;
    color: var(--text-muted);
  }
  
  .usage-list {
    display: flex;
    flex-direction: column;
    gap: 16px;
  }
  
  .usage-item {
    padding: 12px;
    background: var(--bg-input);
    border-radius: 8px;
  }
  
  .usage-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 8px;
  }
  
  .usage-name {
    font-weight: 500;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  
  .status-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
  }
  
  .status-dot.online {
    background: var(--success);
  }
  
  .status-dot.offline {
    background: var(--text-muted);
  }
  
  .usage-value {
    font-weight: 600;
  }
  
  .usage-bar {
    height: 6px;
    background: var(--border);
    border-radius: 3px;
    overflow: hidden;
    margin-bottom: 8px;
  }
  
  .usage-fill {
    height: 100%;
    transition: width 0.3s;
  }
  
  .usage-details {
    display: flex;
    gap: 16px;
    font-size: 0.75rem;
    color: var(--text-muted);
  }
  
  .table-container {
    overflow-x: auto;
  }
  
  .table {
    width: 100%;
    border-collapse: collapse;
  }
  
  .table th {
    text-align: left;
    padding: 10px 12px;
    font-weight: 500;
    font-size: 0.8rem;
    color: var(--text-muted);
    border-bottom: 1px solid var(--border);
  }
  
  .table td {
    padding: 10px 12px;
    border-bottom: 1px solid var(--border);
    font-size: 0.85rem;
  }
  
  .container-name {
    font-family: monospace;
    font-weight: 500;
  }
  
  .detail {
    font-size: 0.75rem;
    color: var(--text-muted);
    margin-left: 4px;
  }
  
  .network-io {
    font-size: 0.8rem;
    font-family: monospace;
  }
  
  @media (max-width: 900px) {
    .metrics-grid {
      grid-template-columns: repeat(2, 1fr);
    }
  }
  
  @media (max-width: 480px) {
    .metrics-grid {
      grid-template-columns: 1fr;
    }
  }
</style>
