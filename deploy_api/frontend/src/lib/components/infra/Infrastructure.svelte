<script>
  import { onMount } from 'svelte'
  import { servers, serversStore, snapshotsStore, doToken, projects, deploymentHistory } from '../../stores/app.js'
  import { toasts } from '../../stores/toast.js'
  import { api } from '../../api/client.js'
  import Button from '../ui/Button.svelte'
  import Badge from '../ui/Badge.svelte'
  import Modal from '../ui/Modal.svelte'
  import ServerCard from './ServerCard.svelte'
  
  // Filtering state
  let filterProject = ''
  let filterEnv = ''
  let lastUpdated = null
  
  // Compute unique projects/envs from servers
  $: allProjects = [...new Set([
    ...($servers || []).map(s => s.project).filter(Boolean),
    ...($projects || []),
    ...($deploymentHistory || []).map(d => d.project).filter(Boolean)
  ])].sort()
  
  $: allEnvs = [...new Set([
    ...($servers || []).map(s => s.env || s.environment).filter(Boolean),
    'prod', 'staging', 'dev'
  ])].sort()
  
  // Filtered servers (client-side)
  $: filteredServers = ($servers || []).filter(s => {
    if (filterProject && s.project !== filterProject) return false
    if (filterEnv && (s.env || s.environment) !== filterEnv) return false
    return true
  })
  
  // Section collapse state
  let serversExpanded = true
  let snapshotsExpanded = false
  
  // Snapshots
  let snapshots = []
  let snapshotsLoading = false
  let buildModalOpen = false
  let building = false
  let snapshotType = 'custom' // 'base' or 'custom'
  let snapshotName = ''
  let baseImage = 'ubuntu-22-04-x64'
  let installDocker = true
  let installNginx = true
  let installCertbot = true
  let baseSnapshotStatus = null
  
  const baseImages = [
    { value: 'ubuntu-22-04-x64', label: 'Ubuntu 22.04 LTS' },
    { value: 'ubuntu-20-04-x64', label: 'Ubuntu 20.04 LTS' },
    { value: 'debian-11-x64', label: 'Debian 11' },
    { value: 'debian-12-x64', label: 'Debian 12' }
  ]
  
  $: if (snapshotsExpanded && snapshots.length === 0 && !snapshotsLoading) loadSnapshots()
  
  // Auto-select base type if base snapshot missing
  function openBuildModal() {
    snapshotType = baseSnapshotStatus?.exists ? 'custom' : 'base'
    buildModalOpen = true
  }
  
  // Metrics - from fleet health API (summary only, per-server metrics now in ServerCard)
  let metricsLoading = false
  let fleetHealth = null
  
  $: fleetMetrics = fleetHealth ? {
    serverCount: fleetHealth.summary?.total || $servers?.length || 0,
    containerCount: fleetHealth.servers?.reduce((sum, s) => sum + (s.containers || 0), 0) || 0,
    healthyContainers: fleetHealth.servers?.reduce((sum, s) => sum + (s.healthy || 0), 0) || 0,
    unhealthyContainers: fleetHealth.servers?.reduce((sum, s) => sum + (s.unhealthy || 0), 0) || 0,
    monthlyCost: estimateCost($servers),
    health: fleetHealth.summary?.healthy === fleetHealth.summary?.total ? 'healthy' : 'degraded'
  } : {
    serverCount: $servers?.length || 0,
    containerCount: 0,
    healthyContainers: 0,
    unhealthyContainers: 0,
    monthlyCost: estimateCost($servers),
    health: 'unknown'
  }
  
  // Estimate monthly cost
  function estimateCost(servers) {
    if (!servers?.length) return 0
    return servers.reduce((sum, s) => {
      const size = s.size_slug || s.size || ''
      if (size.includes('4gb')) return sum + 24
      if (size.includes('2gb')) return sum + 12
      if (size.includes('1gb')) return sum + 6
      if (size.includes('512mb')) return sum + 4
      return sum + 6
    }, 0)
  }
  
  async function loadFleetHealth() {
    if (!$doToken) return
    metricsLoading = true
    try {
      fleetHealth = await api('GET', `/infra/fleet/health?do_token=${$doToken}`)
    } catch (e) {
      console.error('Failed to load fleet health:', e)
    } finally {
      metricsLoading = false
    }
  }
  
  // Auto-load fleet health when doToken available
  $: if (!fleetHealth && $doToken) loadFleetHealth()
  
  // Logs modal - enhanced with search and tail
  let logsModalOpen = false
  let logsTitle = ''
  let logsContent = ''
  let logsLoading = false
  let currentLogServer = null
  let currentLogContainer = null
  let logSearch = ''
  let logTail = 200
  let logAutoRefresh = false
  let logRefreshInterval = null
  
  // Filtered logs (client-side search)
  $: filteredLogs = logSearch 
    ? logsContent.split('\n').filter(line => line.toLowerCase().includes(logSearch.toLowerCase())).join('\n')
    : logsContent
  
  // Pluralize helper
  function plural(count, singular, pluralForm = null) {
    return count === 1 ? `${count} ${singular}` : `${count} ${pluralForm || singular + 's'}`
  }
  
  // Provision modal
  let provisionModalOpen = false
  let provisionForm = {
    name: '',
    project: '',
    env: 'prod',
    region: 'lon1',
    size: 's-1vcpu-1gb',
    count: 1
  }
  
  const regions = [
    { value: 'lon1', label: 'London' },
    { value: 'fra1', label: 'Frankfurt' },
    { value: 'ams3', label: 'Amsterdam' },
    { value: 'nyc1', label: 'New York' },
    { value: 'sfo3', label: 'San Francisco' },
    { value: 'sgp1', label: 'Singapore' },
  ]
  
  const sizes = [
    { value: 's-1vcpu-512mb-10gb', label: '$4 - 512MB' },
    { value: 's-1vcpu-1gb', label: '$6 - 1GB' },
    { value: 's-1vcpu-2gb', label: '$12 - 2GB' },
    { value: 's-2vcpu-2gb', label: '$18 - 2vCPU/2GB' },
    { value: 's-2vcpu-4gb', label: '$24 - 2vCPU/4GB' },
  ]
  
  // Subscribe to store
  $: storeState = $serversStore || { loading: false }
  $: loading = storeState.loading
  
  async function loadSnapshots() {
    snapshotsLoading = true
    try {
      const res = await api('GET', `/infra/snapshots?do_token=${$doToken}`)
      snapshots = res.snapshots || []
      // Check for base snapshot after loading
      checkBaseSnapshot()
    } catch (e) {
      console.error('Failed to load snapshots:', e)
    } finally {
      snapshotsLoading = false
    }
  }
  
  function checkBaseSnapshot() {
    // Check if any snapshot starts with "base-"
    const baseSnap = snapshots.find(s => s.name?.toLowerCase().startsWith('base-'))
    if (baseSnap) {
      baseSnapshotStatus = { exists: true, name: baseSnap.name, created_at: baseSnap.created_at }
    } else {
      baseSnapshotStatus = { exists: false }
    }
  }
  
  async function createBaseSnapshot() {
    building = true
    try {
      toasts.info('Creating base snapshot... This takes ~5 minutes')
      await api('POST', `/infra/setup/init?do_token=${$doToken}`)
      toasts.success('Base snapshot created!')
      await checkBaseSnapshot()
      await loadSnapshots()
    } catch (e) {
      toasts.error(`Failed: ${e.message}`)
    } finally {
      building = false
    }
  }
  
  async function deleteSnapshot(id, name) {
    if (!confirm(`Delete snapshot "${name}"?`)) return
    try {
      await api('DELETE', `/infra/snapshots/${id}?do_token=${$doToken}`)
      toasts.success(`Deleted ${name}`)
      snapshots = snapshots.filter(s => s.id !== id)
    } catch (e) {
      toasts.error(`Failed: ${e.message}`)
    }
  }
  
  async function buildSnapshot() {
    building = true
    try {
      if (snapshotType === 'base') {
        toasts.info('Creating base snapshot... This takes ~5 minutes')
        await api('POST', `/infra/setup/init?do_token=${$doToken}`)
        toasts.success('Base snapshot created!')
        await checkBaseSnapshot()
      } else {
        if (!snapshotName) {
          toasts.error('Snapshot name required')
          building = false
          return
        }
        if (snapshotName.toLowerCase().startsWith('base-')) {
          toasts.error('Custom snapshots cannot start with "base-"')
          building = false
          return
        }
        await api('POST', `/infra/snapshots/build?do_token=${$doToken}`, {
          name: snapshotName,
          base_image: baseImage,
          install_docker: installDocker,
          install_nginx: installNginx,
          install_certbot: installCertbot
        })
        toasts.success('Snapshot build started! Takes 5-10 min.')
      }
      buildModalOpen = false
      snapshotName = ''
      setTimeout(() => loadSnapshots(), 5000)
    } catch (err) {
      toasts.error(err.message)
    } finally {
      building = false
    }
  }
  
  async function provision() {
    try {
      const result = await api('POST', '/infra/servers/provision', {
        ...provisionForm,
        do_token: $doToken
      })
      toasts.success(`Provisioned ${result.created || 1} server(s)`)
      provisionModalOpen = false
      serversStore.refresh()
    } catch (e) {
      toasts.error('Failed: ' + e.message)
    }
  }
  
  async function handleServerAction(event) {
    const { server } = event.detail
    const action = event.type
    
    if (action === 'destroy') {
      if (confirm(`Destroy ${server.name}? This cannot be undone.`)) {
        try {
          await api('DELETE', `/infra/servers/${server.id}?do_token=${$doToken}`)
          toasts.success(`Destroyed ${server.name}`)
          serversStore.refresh()
        } catch (e) {
          toasts.error(`Failed: ${e.message}`)
        }
      }
    }
  }
  
  async function handleViewLogs(event) {
    const { server, containerName } = event.detail
    const ip = server.ip || server.networks?.v4?.[0]?.ip_address
    
    currentLogServer = ip
    currentLogContainer = containerName
    logsTitle = `📋 ${containerName} @ ${ip}`
    logsContent = ''
    logSearch = ''
    logsModalOpen = true
    logsLoading = true
    
    try {
      const res = await api('GET', `/infra/agent/${ip}/containers/${containerName}/logs?do_token=${$doToken}&tail=${logTail}`)
      logsContent = res.logs || 'No logs available'
    } catch (e) {
      logsContent = `Error: ${e.message}`
    } finally {
      logsLoading = false
    }
  }
  
  async function refreshLogs() {
    if (!currentLogServer || !currentLogContainer) return
    logsLoading = true
    try {
      const res = await api('GET', `/infra/agent/${currentLogServer}/containers/${currentLogContainer}/logs?do_token=${$doToken}&tail=${logTail}`)
      logsContent = res.logs || 'No logs available'
    } catch (e) {
      logsContent = `Error: ${e.message}`
    } finally {
      logsLoading = false
    }
  }
  
  function toggleAutoRefresh() {
    if (logAutoRefresh) {
      logRefreshInterval = setInterval(refreshLogs, 3000)
    } else {
      stopAutoRefresh()
    }
  }
  
  function stopAutoRefresh() {
    if (logRefreshInterval) {
      clearInterval(logRefreshInterval)
      logRefreshInterval = null
    }
    logAutoRefresh = false
  }
  
  function formatBytes(bytes) {
    if (!bytes) return '0 B'
    const k = 1024
    const sizes = ['B', 'KB', 'MB', 'GB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i]
  }
  
  function formatDate(dateStr) {
    if (!dateStr) return ''
    return new Date(dateStr).toLocaleDateString('en-GB', { day: '2-digit', month: 'short' })
  }
  
  export function refresh() {
    serversStore.refresh()
    lastUpdated = new Date()
  }
  
  // Track updates
  $: if ($servers) {
    lastUpdated = new Date()
  }
  
  function formatLastUpdated(date) {
    if (!date) return 'never'
    const now = new Date()
    const diff = Math.floor((now - date) / 1000)
    if (diff < 5) return 'just now'
    if (diff < 60) return `${diff}s ago`
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
    return date.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
  }
</script>

<div class="infrastructure">
  <!-- FILTER BAR -->
  <div class="filter-bar">
    <div class="filter-group">
      <label>Project</label>
      <select bind:value={filterProject}>
        <option value="">All</option>
        {#each allProjects as p}<option value={p}>{p}</option>{/each}
      </select>
    </div>
    <div class="filter-group">
      <label>Env</label>
      <select bind:value={filterEnv}>
        <option value="">All</option>
        {#each allEnvs as e}<option value={e}>{e}</option>{/each}
      </select>
    </div>
    <div class="filter-spacer"></div>
    <span class="last-updated">Updated {formatLastUpdated(lastUpdated)}</span>
    <button class="filter-refresh" on:click={refresh} title="Refresh">↻</button>
  </div>

  <!-- SUMMARY BANNER -->
  <div class="summary-banner">
    <div class="banner-metric">
      <span class="banner-value">{filteredServers.length}</span>
      <span class="banner-label">{filteredServers.length === 1 ? 'SERVER' : 'SERVERS'}</span>
    </div>
    <div class="banner-metric">
      <span class="banner-value">{fleetMetrics.containerCount}</span>
      <span class="banner-label">{fleetMetrics.containerCount === 1 ? 'CONTAINER' : 'CONTAINERS'}</span>
    </div>
    <div class="banner-metric">
      <span class="banner-value">£{fleetMetrics.monthlyCost}</span>
      <span class="banner-label">/MONTH</span>
    </div>
    <div class="banner-metric">
      <span class="banner-value {fleetMetrics.unhealthyContainers > 0 ? 'warning' : 'success'}">
        {fleetMetrics.healthyContainers}/{fleetMetrics.containerCount}
      </span>
      <span class="banner-label">HEALTHY</span>
    </div>
  </div>

  <!-- SERVERS SECTION -->
  <div class="section" class:expanded={serversExpanded}>
    <div class="section-header" on:click={() => serversExpanded = !serversExpanded}>
      <div class="section-title">
        <span class="expand-icon">{serversExpanded ? '▼' : '▶'}</span>
        <span>{plural(filteredServers.length, 'Server')}</span>
      </div>
      <div class="section-actions" on:click|stopPropagation>
        <button class="section-btn" on:click={refresh}>↻</button>
        <button class="section-btn primary" on:click={() => provisionModalOpen = true}>+ Add</button>
      </div>
    </div>
    
    {#if serversExpanded}
      <div class="section-content">
        {#if loading}
          <div class="loading-skeleton">
            <div class="skeleton-card"></div>
            <div class="skeleton-card"></div>
          </div>
        {:else if !filteredServers.length}
          <div class="empty-msg">
            {#if filterProject || filterEnv}
              No servers match filters
            {:else}
              No servers. Click "+ Add" to provision.
            {/if}
          </div>
        {:else}
          {#each filteredServers as server (server.id)}
            <ServerCard 
              {server}
              on:destroy={handleServerAction}
              on:viewLogs={handleViewLogs}
            />
          {/each}
        {/if}
      </div>
    {/if}
  </div>
  
  <!-- SNAPSHOTS SECTION -->
  <div class="section" class:expanded={snapshotsExpanded}>
    <div class="section-header" on:click={() => snapshotsExpanded = !snapshotsExpanded}>
      <div class="section-title">
        <span class="expand-icon">{snapshotsExpanded ? '▼' : '▶'}</span>
        <span>{plural(snapshots.length, 'Snapshot')}</span>
      </div>
      <div class="section-actions" on:click|stopPropagation>
        <button class="section-btn" on:click={loadSnapshots}>↻</button>
        <button class="section-btn primary" on:click={openBuildModal}>+ Build</button>
      </div>
    </div>
    
    {#if snapshotsExpanded}
      <div class="section-content">
        <!-- Base Snapshot Status -->
        <div class="base-snapshot-row">
          <span class="base-label">Base Snapshot:</span>
          {#if baseSnapshotStatus === null}
            <span class="base-status checking">checking...</span>
          {:else if baseSnapshotStatus.exists}
            <Badge variant="success">✓ {baseSnapshotStatus.name}</Badge>
          {:else}
            <Badge variant="warning">Not found</Badge>
            <span class="base-hint">Use "+ Build" to create</span>
          {/if}
        </div>
        
        {#if snapshotsLoading}
          <div class="empty-msg">Loading...</div>
        {:else if !snapshots.length}
          <div class="empty-msg">No custom snapshots</div>
        {:else}
          <div class="snapshots-grid">
            {#each snapshots as snap}
              <div class="snapshot-pill">
                <span class="snap-name">{snap.name}</span>
                <span class="snap-meta">{formatBytes(snap.size_gigabytes * 1024 * 1024 * 1024)} • {formatDate(snap.created_at)}</span>
                <button class="pill-del" title="Delete" on:click={() => deleteSnapshot(snap.id, snap.name)}>×</button>
              </div>
            {/each}
          </div>
        {/if}
      </div>
    {/if}
  </div>
</div>

<!-- Provision Modal -->
<Modal bind:open={provisionModalOpen} title="Provision Server" width="400px">
  <div class="form-grid">
    <div class="form-group full">
      <label>Name</label>
      <input type="text" bind:value={provisionForm.name} placeholder="web-01">
    </div>
    <div class="form-group">
      <label>Project</label>
      <input type="text" bind:value={provisionForm.project} placeholder="myapp">
    </div>
    <div class="form-group">
      <label>Env</label>
      <select bind:value={provisionForm.env}>
        <option value="prod">prod</option>
        <option value="staging">staging</option>
        <option value="dev">dev</option>
      </select>
    </div>
    <div class="form-group">
      <label>Region</label>
      <select bind:value={provisionForm.region}>
        {#each regions as r}<option value={r.value}>{r.label}</option>{/each}
      </select>
    </div>
    <div class="form-group">
      <label>Size</label>
      <select bind:value={provisionForm.size}>
        {#each sizes as s}<option value={s.value}>{s.label}</option>{/each}
      </select>
    </div>
  </div>
  <div slot="footer">
    <Button variant="ghost" on:click={() => provisionModalOpen = false}>Cancel</Button>
    <Button variant="primary" on:click={provision}>🚀 Provision</Button>
  </div>
</Modal>

<!-- Logs Modal - Enhanced -->
<Modal bind:open={logsModalOpen} title={logsTitle} width="1000px">
  <div class="logs-toolbar">
    <div class="logs-search">
      <input 
        type="text" 
        placeholder="Search logs..." 
        bind:value={logSearch}
      />
    </div>
    <div class="logs-tail">
      <label>Lines:</label>
      <select bind:value={logTail} on:change={refreshLogs}>
        <option value={100}>100</option>
        <option value={200}>200</option>
        <option value={500}>500</option>
        <option value={1000}>1000</option>
      </select>
    </div>
    <label class="logs-auto">
      <input type="checkbox" bind:checked={logAutoRefresh} on:change={toggleAutoRefresh} />
      Auto-refresh
    </label>
    <Button variant="ghost" size="sm" on:click={refreshLogs} disabled={logsLoading}>
      {logsLoading ? '...' : '↻'}
    </Button>
  </div>
  <pre class="logs-content large">{filteredLogs || 'No logs'}</pre>
  <div slot="footer">
    <span class="logs-count">{filteredLogs?.split('\n').length || 0} lines</span>
    <Button variant="ghost" on:click={() => { logsModalOpen = false; stopAutoRefresh() }}>Close</Button>
  </div>
</Modal>

<!-- Build Snapshot Modal -->
<Modal 
  bind:open={buildModalOpen}
  title="Build Snapshot"
  width="500px"
  on:close={() => buildModalOpen = false}
>
  <div class="snap-type-selector">
    <button 
      class="snap-type-btn" 
      class:active={snapshotType === 'base'}
      on:click={() => snapshotType = 'base'}
    >
      🏗️ Base Snapshot
    </button>
    <button 
      class="snap-type-btn" 
      class:active={snapshotType === 'custom'}
      on:click={() => snapshotType = 'custom'}
    >
      📸 Custom Snapshot
    </button>
  </div>
  
  {#if snapshotType === 'base'}
    <div class="snap-type-info">
      <p>Creates the default base snapshot with Docker, Nginx, Certbot pre-installed. Required for provisioning new servers.</p>
      {#if baseSnapshotStatus?.exists}
        <Badge variant="warning">⚠️ Base snapshot already exists: {baseSnapshotStatus.name}</Badge>
      {/if}
    </div>
  {:else}
    <form on:submit|preventDefault={buildSnapshot}>
      <div class="form-group">
        <label for="snap-name">Snapshot Name *</label>
        <input 
          id="snap-name"
          type="text" 
          bind:value={snapshotName}
          placeholder="my-custom-snapshot"
        >
      </div>
      
      <div class="form-group">
        <label for="base-image">Base Image</label>
        <select id="base-image" bind:value={baseImage}>
          {#each baseImages as image}
            <option value={image.value}>{image.label}</option>
          {/each}
        </select>
      </div>
      
      <div class="form-group">
        <label>Pre-install</label>
        <div class="checkbox-list">
          <label class="checkbox-item">
            <input type="checkbox" bind:checked={installDocker}> Docker
          </label>
          <label class="checkbox-item">
            <input type="checkbox" bind:checked={installNginx}> Nginx
          </label>
          <label class="checkbox-item">
            <input type="checkbox" bind:checked={installCertbot}> Certbot
          </label>
        </div>
      </div>
    </form>
  {/if}
  
  <div slot="footer">
    <Button variant="ghost" on:click={() => buildModalOpen = false}>Cancel</Button>
    <Button variant="primary" on:click={buildSnapshot} disabled={building}>
      {#if building}Building...{:else}🔨 Build{/if}
    </Button>
  </div>
</Modal>

<style>
  .infrastructure {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  
  /* Filter Bar */
  .filter-bar {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 8px 12px;
    background: rgba(255,255,255,.02);
    border: 1px solid var(--border);
    border-radius: var(--r2);
  }
  
  .filter-group {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  
  .filter-group label {
    font-size: 0.75rem;
    color: var(--text-muted);
  }
  
  .filter-group select {
    background: var(--bg-input);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 4px 8px;
    color: var(--text);
    font-size: 0.8rem;
    min-width: 80px;
  }
  
  .filter-spacer {
    flex: 1;
  }
  
  .last-updated {
    font-size: 0.75rem;
    color: var(--text-muted2);
  }
  
  .filter-refresh {
    background: transparent;
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 4px 8px;
    cursor: pointer;
    color: var(--text-muted);
    font-size: 0.8rem;
  }
  
  .filter-refresh:hover {
    background: rgba(255,255,255,.08);
    color: var(--text);
  }
  
  /* Loading Skeleton */
  .loading-skeleton {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  
  .skeleton-card {
    height: 80px;
    background: linear-gradient(90deg, rgba(255,255,255,.03) 25%, rgba(255,255,255,.06) 50%, rgba(255,255,255,.03) 75%);
    background-size: 200% 100%;
    animation: skeleton-shimmer 1.5s infinite;
    border-radius: 8px;
  }
  
  @keyframes skeleton-shimmer {
    0% { background-position: 200% 0; }
    100% { background-position: -200% 0; }
  }
  
  /* Summary Banner */
  .summary-banner {
    display: flex;
    align-items: center;
    gap: 24px;
    padding: 12px 16px;
    background: rgba(255,255,255,.03);
    border: 1px solid var(--border);
    border-radius: var(--r2);
  }
  
  .banner-metric {
    display: flex;
    flex-direction: column;
    align-items: center;
    min-width: 60px;
  }
  
  .banner-value {
    font-size: 1.4rem;
    font-weight: 700;
    color: var(--text);
  }
  
  .banner-value.success { color: var(--success); }
  .banner-value.warning { color: var(--warning); }
  
  .banner-label {
    font-size: 0.65rem;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }
  
  .banner-refresh {
    margin-left: auto;
    background: transparent;
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 4px 8px;
    cursor: pointer;
    color: var(--text-muted);
    font-size: 0.8rem;
  }
  
  .banner-refresh:hover {
    background: rgba(255,255,255,.08);
    border-color: var(--border2);
    color: var(--text);
  }
  
  /* Sections */
  .section {
    background: var(--card-bg);
    border: 1px solid var(--border);
    border-radius: var(--r2);
    overflow: hidden;
  }
  
  .section.expanded {
    border-color: var(--border2);
  }
  
  .section-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 10px 14px;
    cursor: pointer;
    user-select: none;
  }
  
  .section-header:hover {
    background: rgba(255,255,255,.03);
  }
  
  .section-title {
    display: flex;
    align-items: center;
    gap: 8px;
    font-weight: 600;
    font-size: 0.9rem;
  }
  
  .expand-icon {
    font-size: 0.65rem;
    color: var(--text-muted);
    width: 10px;
  }
  
  .section-actions {
    display: flex;
    gap: 6px;
  }
  
  .section-btn {
    background: transparent;
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 4px 10px;
    font-size: 0.75rem;
    color: var(--text-muted);
    cursor: pointer;
    transition: all 0.15s;
  }
  
  .section-btn:hover {
    background: rgba(255,255,255,.08);
    color: var(--text);
  }
  
  .section-btn.primary {
    background: var(--primary);
    border-color: var(--primary);
    color: white;
  }
  
  .section-btn.primary:hover {
    background: var(--primary2);
  }
  
  .section-content {
    padding: 8px 12px 12px;
    border-top: 1px solid var(--border);
  }
  
  .empty-msg {
    color: var(--text-muted);
    font-size: 0.8rem;
    padding: 12px 0;
    text-align: center;
  }
  
  /* Snapshots */
  .base-snapshot-row {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 10px;
    background: rgba(255,255,255,.03);
    border-radius: 6px;
    margin-bottom: 10px;
    font-size: 0.8rem;
  }
  
  .base-label {
    color: var(--text-muted);
  }
  
  .base-status.checking {
    color: var(--text-muted2);
    font-style: italic;
  }
  
  .base-hint {
    font-size: 0.75rem;
    color: var(--text-muted2);
    font-style: italic;
  }
  
  .snap-type-selector {
    display: flex;
    gap: 8px;
    margin-bottom: 16px;
  }
  
  .snap-type-btn {
    flex: 1;
    padding: 10px;
    background: rgba(255,255,255,.04);
    border: 1px solid var(--border);
    border-radius: 8px;
    color: var(--text-muted);
    cursor: pointer;
    font-size: 0.85rem;
    transition: all 0.15s;
  }
  
  .snap-type-btn:hover {
    background: rgba(255,255,255,.08);
  }
  
  .snap-type-btn.active {
    background: rgba(99, 102, 241, 0.15);
    border-color: var(--primary);
    color: var(--text);
  }
  
  .snap-type-info {
    padding: 12px;
    background: rgba(255,255,255,.03);
    border-radius: 8px;
    font-size: 0.85rem;
    color: var(--text-muted);
  }
  
  .snap-type-info p {
    margin: 0 0 10px 0;
  }

  .snapshots-grid {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  
  .snapshot-pill {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 6px 10px;
    background: rgba(255,255,255,.04);
    border: 1px solid var(--border);
    border-radius: 6px;
    font-size: 0.75rem;
  }
  
  .snapshot-pill:hover {
    background: rgba(255,255,255,.08);
  }
  
  .snap-name {
    font-family: monospace;
    color: var(--text);
  }
  
  .snap-meta {
    color: var(--text-muted);
  }
  
  .pill-del {
    background: transparent;
    border: none;
    color: var(--text-muted);
    cursor: pointer;
    padding: 0 2px;
    font-size: 0.9rem;
  }
  
  .pill-del:hover {
    color: var(--danger);
  }
  
  /* Form */
  .form-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
  }
  
  .form-group {
    display: flex;
    flex-direction: column;
    gap: 4px;
    margin-bottom: 16px;
  }
  
  .form-group:last-child {
    margin-bottom: 0;
  }
  
  .form-group.full {
    grid-column: span 2;
  }
  
  .form-group label {
    font-size: 0.75rem;
    color: var(--text-muted);
  }
  
  .form-group input,
  .form-group select {
    width: 100%;
    padding: 10px 12px;
    background: var(--bg-input);
    border: 1px solid var(--border);
    border-radius: 8px;
    color: var(--text);
    font-size: 0.875rem;
  }
  
  .form-group input:focus,
  .form-group select:focus {
    outline: none;
    border-color: var(--primary);
  }
  
  .checkbox-label {
    display: flex;
    align-items: center;
    gap: 6px;
    cursor: pointer;
    font-size: 0.85rem;
  }
  
  .checkbox-label input {
    width: auto;
    padding: 0;
  }
  
  .checkbox-list {
    display: flex;
    gap: 16px;
    flex-wrap: wrap;
  }
  
  .checkbox-item {
    display: flex;
    align-items: center;
    gap: 6px;
    cursor: pointer;
  }
  
  .checkbox-item input {
    width: auto;
  }
  
  /* Server Health List */
  .server-health-list {
    display: flex;
    flex-direction: column;
    gap: 12px;
    margin-top: 16px;
  }
  
  .health-item {
    padding: 10px;
    background: var(--bg-input);
    border-radius: 8px;
  }
  
  .health-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 6px;
  }
  
  .health-name {
    font-weight: 500;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  
  .health-value {
    font-weight: 600;
  }
  
  .health-bar {
    height: 6px;
    background: var(--border);
    border-radius: 3px;
    overflow: hidden;
  }
  
  .health-fill {
    height: 100%;
    transition: width 0.3s;
  }
  
  .health-fill.success {
    background: var(--success);
  }
  
  .health-fill.warning {
    background: var(--warning);
  }
  
  .status-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
  }
  
  .status-dot.green {
    background: var(--success);
  }
  
  .status-dot.gray {
    background: var(--text-muted);
  }
  
  .metric-value.success {
    color: var(--success);
  }
  
  .metric-value.warning {
    color: var(--warning);
  }
  
  /* Logs Modal Enhanced */
  .logs-toolbar {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 12px;
    padding: 8px;
    background: rgba(255,255,255,.02);
    border-radius: 6px;
  }
  
  .logs-search {
    flex: 1;
  }
  
  .logs-search input {
    width: 100%;
    padding: 6px 10px;
    background: var(--bg-input);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text);
    font-size: 0.8rem;
  }
  
  .logs-search input::placeholder {
    color: var(--text-muted2);
  }
  
  .logs-tail {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  
  .logs-tail label {
    font-size: 0.75rem;
    color: var(--text-muted);
  }
  
  .logs-tail select {
    background: var(--bg-input);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 4px 6px;
    color: var(--text);
    font-size: 0.8rem;
  }
  
  .logs-auto {
    display: flex;
    align-items: center;
    gap: 4px;
    font-size: 0.75rem;
    color: var(--text-muted);
    cursor: pointer;
  }
  
  .logs-auto input {
    width: auto;
  }
  
  .logs-content {
    background: rgba(0,0,0,.4);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 10px;
    font-family: monospace;
    font-size: 0.7rem;
    line-height: 1.4;
    max-height: 400px;
    overflow: auto;
    white-space: pre-wrap;
    word-break: break-all;
    color: var(--text-muted);
  }
  
  .logs-content.large {
    max-height: 500px;
    font-size: 0.75rem;
  }
  
  .logs-count {
    font-size: 0.75rem;
    color: var(--text-muted2);
    margin-right: auto;
  }
</style>
