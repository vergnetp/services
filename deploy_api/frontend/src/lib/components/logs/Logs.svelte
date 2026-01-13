<script>
  import { onMount, onDestroy } from 'svelte'
  import { scope, servers } from '../../stores/app.js'
  import { toasts } from '../../stores/toast.js'
  import { api } from '../../api/client.js'
  import Card from '../ui/Card.svelte'
  import Button from '../ui/Button.svelte'
  
  let logs = ''
  let filteredLogs = ''
  let loading = false
  let searchQuery = ''
  let levelFilter = ''
  let tailInterval = null
  
  $: context = $scope.server 
    ? ($scope.container ? `${$scope.server} / ${$scope.container}` : $scope.server)
    : 'Select a server'
  
  $: {
    // Filter logs when search or level changes
    filterLogs()
  }
  
  onMount(() => {
    if ($scope.server) {
      loadLogs()
    }
  })
  
  onDestroy(() => {
    stopTail()
  })
  
  async function loadLogs() {
    if (!$scope.server) {
      logs = 'Select a server and container from the scope bar above to view logs.'
      filteredLogs = logs
      return
    }
    
    loading = true
    try {
      const serverIp = $scope.server
      const container = $scope.container
      
      if (!serverIp) {
        logs = 'Select a server to view logs'
        filteredLogs = logs
        return
      }
      
      // Container must be selected for logs
      if (!container || container === 'all') {
        logs = 'Select a specific container from the scope bar above to view logs.\n\nTip: Use the Server dropdown to pick a server, then select a container.'
        filteredLogs = logs
        loading = false
        return
      }
      
      // Use the agent logs endpoint for specific container
      const params = new URLSearchParams()
      params.set('lines', '500')
      
      const endpoint = `/infra/agent/${serverIp}/containers/${container}/logs?${params}`
      
      const response = await api('GET', endpoint)
      // Handle AgentResponse format: {success, data: {logs: "..."}, error}
      // Or direct format: {logs: "..."}
      if (response.data && response.data.logs !== undefined) {
        logs = response.data.logs
      } else if (response.logs !== undefined) {
        logs = response.logs
      } else if (typeof response === 'string') {
        logs = response
      } else {
        logs = JSON.stringify(response, null, 2)
      }
      filterLogs()
    } catch (err) {
      logs = `Error loading logs: ${err.message}`
      filteredLogs = logs
      toasts.error('Failed to load logs: ' + err.message)
    } finally {
      loading = false
    }
  }
  
  function filterLogs() {
    let result = logs
    
    if (searchQuery) {
      const lines = result.split('\n')
      result = lines.filter(line => 
        line.toLowerCase().includes(searchQuery.toLowerCase())
      ).join('\n')
    }
    
    if (levelFilter) {
      const lines = result.split('\n')
      result = lines.filter(line => 
        line.toUpperCase().includes(levelFilter)
      ).join('\n')
    }
    
    filteredLogs = result
  }
  
  function startTail() {
    if (tailInterval) return
    tailInterval = setInterval(loadLogs, 5000)
    toasts.info('Tailing logs...')
  }
  
  function stopTail() {
    if (tailInterval) {
      clearInterval(tailInterval)
      tailInterval = null
    }
  }
  
  function copyLogs() {
    navigator.clipboard.writeText(filteredLogs)
    toasts.success('Logs copied to clipboard')
  }
  
  function downloadLogs() {
    const blob = new Blob([filteredLogs], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `logs-${$scope.server || 'unknown'}-${new Date().toISOString()}.txt`
    a.click()
    URL.revokeObjectURL(url)
  }
  
  // Watch for scope changes
  $: if ($scope.server || $scope.container || $scope.range) {
    loadLogs()
  }
  
  // Watch for tail toggle
  $: if ($scope.tail) {
    startTail()
  } else {
    stopTail()
  }
  
  export function refresh() {
    loadLogs()
  }
</script>

<div class="logs-page">
  <h2 class="page-title">
    Logs · <span class="context">{context}</span>
  </h2>
  
  <Card padding={false}>
    <!-- Toolbar -->
    <div class="toolbar">
      <div class="search-box">
        <span class="search-icon">🔍</span>
        <input 
          type="text" 
          placeholder="Search logs..."
          bind:value={searchQuery}
          on:input={filterLogs}
        >
      </div>
      
      <select bind:value={levelFilter} on:change={filterLogs}>
        <option value="">All Levels</option>
        <option value="ERROR">ERROR</option>
        <option value="WARN">WARN</option>
        <option value="INFO">INFO</option>
        <option value="DEBUG">DEBUG</option>
      </select>
      
      <Button variant="ghost" size="sm" on:click={copyLogs}>📋 Copy</Button>
      <Button variant="ghost" size="sm" on:click={downloadLogs}>⬇ Download</Button>
    </div>
    
    <!-- Log viewer -->
    <div class="log-viewer">
      {#if loading}
        <div class="loading-overlay">Loading logs...</div>
      {/if}
      <pre class="log-content">{#if filteredLogs}{filteredLogs}{:else}<span class="placeholder">Select a server and container from the scope bar above to view logs.</span>{/if}</pre>
    </div>
  </Card>
</div>

<style>
  .logs-page {
    padding: 0;
  }
  
  .page-title {
    margin: 0 0 16px 0;
    font-size: 1.25rem;
  }
  
  .context {
    font-weight: normal;
    color: var(--text-muted);
  }
  
  .toolbar {
    display: flex;
    gap: 12px;
    align-items: center;
    padding: 12px 16px;
    border-bottom: 1px solid var(--border);
    flex-wrap: wrap;
  }
  
  .search-box {
    display: flex;
    align-items: center;
    gap: 8px;
    flex: 1;
    min-width: 200px;
  }
  
  .search-icon {
    color: var(--text-muted);
  }
  
  .search-box input {
    flex: 1;
    padding: 8px 12px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--bg-input);
    color: var(--text);
    font-size: 0.875rem;
  }
  
  .search-box input:focus {
    outline: none;
    border-color: var(--primary);
  }
  
  .toolbar select {
    padding: 8px 12px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--bg-input);
    color: var(--text);
    font-size: 0.875rem;
  }
  
  .log-viewer {
    position: relative;
  }
  
  .loading-overlay {
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    background: var(--bg-card);
    padding: 12px 24px;
    border-radius: 8px;
    box-shadow: var(--shadow2);
    z-index: 10;
  }
  
  .log-content {
    background: var(--bg-input);
    padding: 16px;
    margin: 0;
    min-height: 400px;
    max-height: 600px;
    overflow: auto;
    font-size: 12px;
    white-space: pre-wrap;
    word-break: break-word;
    font-family: 'Monaco', 'Menlo', 'Consolas', monospace;
    line-height: 1.5;
  }
  
  .placeholder {
    color: var(--text-muted);
  }
  
  @media (max-width: 640px) {
    .toolbar {
      flex-direction: column;
      align-items: stretch;
    }
    
    .search-box {
      min-width: 100%;
    }
  }
</style>
