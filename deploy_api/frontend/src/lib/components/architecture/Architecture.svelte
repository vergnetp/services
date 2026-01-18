<script>
  import { onMount, onDestroy } from 'svelte'
  import { projects } from '../../stores/app.js'
  import { getDoToken } from '../../stores/auth.js'
  import { toasts } from '../../stores/toast.js'
  import { api } from '../../api/client.js'
  import { Card } from '@myorg/ui'
  import { Button } from '@myorg/ui'
  import { Badge } from '@myorg/ui'
  
  let projectFilter = ''
  let envFilter = ''
  
  let loading = false
  let nodes = []
  let servers = []
  let infrastructure = []
  let lastUpdated = null
  let error = null
  
  // Track if initial load done (for hidden tab support)
  let initialLoadDone = false
  let refreshTimer = null
  
  function formatTime(date) {
    if (!date) return ''
    return date.toLocaleTimeString()
  }
  
  onMount(() => {
    if (!initialLoadDone) {
      loadArchitecture()
      // Auto-refresh every 60s
      refreshTimer = setInterval(loadArchitecture, 60000)
    }
  })
  
  onDestroy(() => {
    if (refreshTimer) {
      clearInterval(refreshTimer)
    }
  })
  
  async function loadArchitecture() {
    // Only show loading spinner on first load
    if (!initialLoadDone) {
      loading = true
    }
    error = null
    
    try {
      // Get DO token from auth store
      const doTokenValue = getDoToken()
      if (!doTokenValue) {
        throw new Error('DigitalOcean token required')
      }
      
      const data = await api('POST', '/infra/architecture', {
        project: projectFilter || null,
        environment: envFilter || null,
        do_token: doTokenValue
      })
      
      nodes = data.nodes || []
      servers = data.servers || []
      infrastructure = data.infrastructure || []
      lastUpdated = new Date()
      initialLoadDone = true
    } catch (err) {
      error = err.message
      if (!initialLoadDone) {
        toasts.error('Failed to load architecture: ' + err.message)
      }
    } finally {
      loading = false
    }
  }
  
  function getNodeIcon(node) {
    switch (node.type) {
      case 'stateful': return '🗄️'
      case 'frontend': return '🌐'
      case 'api': return '⚡'
      case 'worker': return '⚙️'
      default: return '📦'
    }
  }
  
  function getNginxStatus(server) {
    return server.nginx_status === 'running'
  }
  
  $: nginxCount = servers.filter(s => s.nginx_status === 'running').length
  $: totalServers = servers.length
  $: nginxOk = nginxCount === totalServers
  
  async function fixMissingNginx() {
    const missingServers = servers
      .filter(s => s.nginx_status !== 'running')
      .map(s => s.ip)
    
    if (missingServers.length === 0) {
      toasts.info('All servers already have nginx running')
      return
    }
    
    toasts.info(`Fixing ${missingServers.length} server(s)...`)
    
    try {
      await api('POST', '/infra/nginx/ensure', {
        server_ips: missingServers
      })
      toasts.success('Nginx sidecar installed')
      architectureStore.refresh()
    } catch (err) {
      toasts.error(err.message)
    }
  }
  
  function handleFilterChange() {
    loadArchitecture()
  }
  
  export function refresh() {
    loadArchitecture()
  }
</script>

<div class="architecture-page">
  <Card title="🏗️ Architecture View">
    <div slot="header" class="filters">
      <select bind:value={projectFilter} on:change={handleFilterChange}>
        <option value="">All Projects</option>
        {#each $projects || [] as project}
          <option value={project}>{project}</option>
        {/each}
      </select>
      <select bind:value={envFilter} on:change={handleFilterChange}>
        <option value="">All Envs</option>
        <option value="prod">prod</option>
        <option value="staging">staging</option>
        <option value="dev">dev</option>
      </select>
      {#if lastUpdated}
        <span class="last-updated">Updated {formatTime(lastUpdated)}</span>
      {/if}
      <Button variant="ghost" size="sm" on:click={refresh}>↻ Refresh</Button>
    </div>
    
    {#if loading && !initialLoadDone}
      <div class="empty-state">Loading architecture...</div>
    {:else if error}
      <div class="empty-state">
        <p>Failed to load: {error}</p>
        <p class="hint">Check your connection and try refreshing</p>
      </div>
    {:else if nodes.length === 0 && servers.length === 0}
      <div class="empty-state">
        <p>No services deployed yet</p>
        <p class="hint">Deploy your first service to see the architecture</p>
      </div>
    {:else}
      <!-- Infrastructure Summary -->
      <div class="summary-grid">
        <div class="summary-card" class:ok={nginxOk} class:warn={!nginxOk}>
          <div class="summary-header">
            <span class="summary-icon">🔀</span>
            <span>Nginx Sidecar</span>
          </div>
          <div class="summary-value">{nginxCount}/{totalServers}</div>
          <div class="summary-label">servers with nginx</div>
          {#if !nginxOk}
            <Button variant="warning" size="sm" on:click={fixMissingNginx}>
              🔧 Fix {totalServers - nginxCount} server(s)
            </Button>
          {:else}
            <div class="summary-ok">✅ All servers OK</div>
          {/if}
        </div>
        
        <div class="summary-card info">
          <div class="summary-header">
            <span class="summary-icon">🤖</span>
            <span>Node Agents</span>
          </div>
          <div class="summary-value">{servers.length}</div>
          <div class="summary-label">servers monitored</div>
        </div>
        
        <div class="summary-card info">
          <div class="summary-header">
            <span class="summary-icon">📦</span>
            <span>Services</span>
          </div>
          <div class="summary-value">{nodes.length}</div>
          <div class="summary-label">deployed services</div>
        </div>
      </div>
    {/if}
  </Card>
  
  <div class="panels-grid">
    <!-- Services List -->
    <Card title="📦 Services" padding={false}>
      {#if nodes.length === 0}
        <div class="empty-panel">No services found</div>
      {:else}
        <div class="list">
          {#each nodes as node}
            <div class="list-item">
              <div class="item-icon">{getNodeIcon(node)}</div>
              <div class="item-info">
                <div class="item-name">{node.service}</div>
                <div class="item-meta">{node.project} / {node.env}</div>
              </div>
              <div class="item-stats">
                <div>{node.servers?.length || 0} server(s)</div>
                <div class="ports">{node.ports?.join(', ') || '-'}</div>
              </div>
              <Badge variant={node.type === 'stateful' ? 'warning' : 'info'}>
                {node.type}
              </Badge>
            </div>
          {/each}
        </div>
      {/if}
    </Card>
    
    <!-- Servers List -->
    <Card title="🖥️ Servers" padding={false}>
      {#if servers.length === 0}
        <div class="empty-panel">No servers found</div>
      {:else}
        <div class="list">
          {#each servers as server}
            <div class="list-item">
              <div class="item-icon">{server.status === 'online' ? '🟢' : '🔴'}</div>
              <div class="item-info">
                <code class="server-ip">{server.ip}</code>
                <div class="item-meta">{server.containers || 0} container(s)</div>
              </div>
              <div class="item-badges">
                <Badge variant={getNginxStatus(server) ? 'success' : 'warning'}>
                  {getNginxStatus(server) ? '🔀 nginx' : '⚠️ no nginx'}
                </Badge>
                <Badge variant="info">🤖 v{server.agent_version || '?'}</Badge>
              </div>
            </div>
          {/each}
        </div>
      {/if}
    </Card>
  </div>
  
  <!-- Traffic Flow -->
  <Card title="🚦 Traffic Flow">
    <span slot="header" class="subtitle">Request path from client to container</span>
    
    {#if nodes.length === 0}
      <div class="empty-panel">Deploy services to see traffic flow</div>
    {:else}
      <div class="traffic-flow">
        {#each nodes as node}
          {@const nodeServers = servers.filter(s => node.servers?.includes(s.ip))}
          {@const hasDomain = node.domain}
          {@const hasMultipleServers = nodeServers.length > 1}
          
          <div class="flow-card">
            <div class="flow-header">
              <span class="flow-icon">{getNodeIcon(node)}</span>
              <span class="flow-name">{node.service}</span>
              <Badge variant={node.env === 'prod' ? 'danger' : 'info'}>{node.env}</Badge>
            </div>
            
            <div class="flow-path">
              {#if hasDomain}
                <div class="flow-node cloudflare">
                  <span>☁️</span>
                  <span class="node-label">Cloudflare</span>
                  <span class="node-detail">{node.domain}</span>
                </div>
                <div class="flow-arrow">→</div>
              {/if}
              
              <div class="flow-node server">
                <span>🖥️</span>
                <span class="node-label">
                  {#if hasMultipleServers}
                    ⚖️ Load Balanced ({nodeServers.length})
                  {:else}
                    Server
                  {/if}
                </span>
              </div>
              
              <div class="flow-arrow">→</div>
              
              <div class="flow-node nginx">
                <span>🔀</span>
                <span class="node-label">nginx</span>
                <span class="node-detail">:443</span>
              </div>
              
              <div class="flow-arrow">→</div>
              
              <div class="flow-node container">
                <span>🐳</span>
                <span class="node-label">Container</span>
                <span class="node-detail">:{node.host_port || '8000'}</span>
              </div>
            </div>
            
            <div class="flow-details">
              {#if hasDomain}
                <span>
                  Domain: <a href="https://{node.domain}" target="_blank">{node.domain}</a>
                </span>
              {/if}
              <span>Container: <code>{node.container_name || node.id}</code></span>
            </div>
          </div>
        {/each}
      </div>
    {/if}
  </Card>
</div>

<style>
  .architecture-page {
    display: flex;
    flex-direction: column;
    gap: 16px;
  }
  
  .filters {
    display: flex;
    gap: 8px;
    align-items: center;
  }
  
  .filters select {
    padding: 6px 10px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--bg-input);
    color: var(--text);
    font-size: 0.85rem;
  }
  
  .last-updated {
    font-size: 0.75rem;
    color: var(--text-muted2);
    margin-left: auto;
  }
  
  .empty-state {
    text-align: center;
    padding: 40px;
    color: var(--text-muted);
  }
  
  .hint {
    font-size: 0.85rem;
    color: var(--text-muted2);
    margin-top: 8px;
  }
  
  .summary-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 16px;
    margin-top: 16px;
  }
  
  .summary-card {
    padding: 16px;
    border-radius: 8px;
    border: 1px solid var(--border);
  }
  
  .summary-card.ok {
    background: rgba(16, 185, 129, 0.1);
    border-color: rgba(16, 185, 129, 0.3);
  }
  
  .summary-card.warn {
    background: rgba(245, 158, 11, 0.1);
    border-color: rgba(245, 158, 11, 0.3);
  }
  
  .summary-card.info {
    background: rgba(59, 130, 246, 0.1);
    border-color: rgba(59, 130, 246, 0.3);
  }
  
  .summary-header {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 8px;
    font-weight: 600;
  }
  
  .summary-icon {
    font-size: 1.25rem;
  }
  
  .summary-value {
    font-size: 1.5rem;
    font-weight: 700;
  }
  
  .summary-label {
    font-size: 0.8rem;
    color: var(--text-muted);
    margin-bottom: 8px;
  }
  
  .summary-ok {
    font-size: 0.75rem;
    color: var(--success);
  }
  
  .panels-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
  }
  
  .empty-panel {
    padding: 20px;
    text-align: center;
    color: var(--text-muted);
  }
  
  .list {
    max-height: 300px;
    overflow-y: auto;
  }
  
  .list-item {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px 16px;
    border-bottom: 1px solid var(--border);
  }
  
  .list-item:last-child {
    border-bottom: none;
  }
  
  .item-icon {
    font-size: 1.25rem;
  }
  
  .item-info {
    flex: 1;
  }
  
  .item-name {
    font-weight: 600;
  }
  
  .item-meta {
    font-size: 0.8rem;
    color: var(--text-muted);
  }
  
  .item-stats {
    text-align: right;
    font-size: 0.85rem;
  }
  
  .ports {
    font-size: 0.75rem;
    color: var(--text-muted);
  }
  
  .item-badges {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
  }
  
  .server-ip {
    font-family: monospace;
    font-size: 0.9rem;
  }
  
  .subtitle {
    font-size: 0.8rem;
    color: var(--text-muted);
  }
  
  .traffic-flow {
    display: flex;
    flex-direction: column;
    gap: 16px;
  }
  
  .flow-card {
    padding: 16px;
    background: var(--bg-input);
    border-radius: 12px;
  }
  
  .flow-header {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 12px;
  }
  
  .flow-icon {
    font-size: 1.25rem;
  }
  
  .flow-name {
    font-weight: 600;
    flex: 1;
  }
  
  .flow-path {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
    justify-content: center;
    margin-bottom: 12px;
  }
  
  .flow-node {
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 12px 16px;
    background: var(--bg-card);
    border-radius: 12px;
    min-width: 80px;
  }
  
  .flow-node span:first-child {
    font-size: 1.5rem;
  }
  
  .node-label {
    font-size: 0.75rem;
    color: var(--text-muted);
    margin-top: 4px;
  }
  
  .node-detail {
    font-size: 0.7rem;
    color: var(--primary);
    font-family: monospace;
  }
  
  .flow-arrow {
    color: var(--text-muted);
    font-weight: bold;
  }
  
  .flow-details {
    display: flex;
    gap: 16px;
    font-size: 0.8rem;
    color: var(--text-muted);
    flex-wrap: wrap;
  }
  
  .flow-details a {
    color: var(--primary);
  }
  
  .flow-details code {
    font-size: 0.75rem;
  }
  
  @media (max-width: 768px) {
    .panels-grid {
      grid-template-columns: 1fr;
    }
    
    .flow-path {
      flex-direction: column;
    }
    
    .flow-arrow {
      transform: rotate(90deg);
    }
  }
</style>
