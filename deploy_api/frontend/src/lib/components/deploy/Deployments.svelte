<script>
  import { onMount } from 'svelte'
  import { deploymentsStore, scope } from '../../stores/app.js'
  import { toasts } from '../../stores/toast.js'
  import { api, apiStream, getDoToken } from '../../api/client.js'
  import { Card } from '@myorg/ui'
  import { Button } from '@myorg/ui'
  import { Badge } from '@myorg/ui'
  import { Modal } from '@myorg/ui'
  
  let loading = false
  let rollbackModalOpen = false
  let rollbackTarget = null
  let previousDeployments = []
  let selectedRollbackId = null
  
  // Rollback progress
  let rollbackInProgress = false
  let rollbackLogs = []
  
  // Rollback confirmation state (cleanup or missing servers)
  let showRollbackConfirm = false
  let rollbackConfirmType = ''  // 'cleanup' or 'missing'
  let rollbackCleanupServers = []  // Servers that will have containers stopped
  let rollbackMissingServers = []  // Servers that are unavailable
  let rollbackAvailableServers = []  // Servers that are available for rollback
  let pendingRollbackTarget = null
  
  // Config snapshot modal
  let configModalOpen = false
  let configDeployment = null
  
  // Deployment logs modal
  let logsModalOpen = false
  let logsDeployment = null
  let deploymentLogs = []
  let logsLoading = false
  
  // Processed deployments (local)
  let allDeployments = []
  let deployments = []
  
  // Subscribe to store loading state
  $: storeState = $deploymentsStore || { loading: false }
  $: loading = storeState.loading
  $: lastUpdated = storeState.lastFetched
  
  function formatTime(date) {
    if (!date) return ''
    return date.toLocaleTimeString()
  }
  
  // Process deployments when data changes
  $: if (storeState.data) {
    allDeployments = processDeployments(storeState.data)
  }
  
  // Filter deployments based on scope
  $: deployments = filterDeployments(allDeployments, $scope)
  
  function filterDeployments(data, scopeFilter) {
    if (!data) return []
    return data.filter(d => {
      // Filter by project
      if (scopeFilter.project && d.project !== scopeFilter.project) {
        return false
      }
      // Filter by environment
      if (scopeFilter.env && d.environment !== scopeFilter.env) {
        return false
      }
      return true
    })
  }
  
  function processDeployments(data) {
    // Mark which deployment is "current active" for each project/service/env
    // The first successful deployment (deploy OR rollback) is what's currently running
    const result = [...data]
    const seen = new Set()
    for (const d of result) {
      const key = `${d.project}/${d.service || d.name}/${d.environment}`
      // First successful deployment per key is the current live version
      if (d.status === 'success' && d.can_rollback && !seen.has(key)) {
        d.is_current_active = true
        seen.add(key)
      } else {
        d.is_current_active = false
      }
    }
    return result
  }
  
  function formatDate(dateStr) {
    if (!dateStr) return '-'
    const date = new Date(dateStr)
    return date.toLocaleString()
  }
  
  function getStatusBadge(status) {
    switch (status) {
      case 'success':
      case 'active':
        return 'success'
      case 'failed':
      case 'error':
        return 'danger'
      case 'pending':
      case 'deploying':
        return 'warning'
      case 'superseded':
        return 'secondary'
      default:
        return 'info'
    }
  }
  
  function getDisplayStatus(deployment) {
    // Normalize status for display
    const status = deployment.status || 'unknown'
    
    if (status === 'rolled_back') {
      // "rolled_back" only makes sense for regular deploys that were superseded
      // For rollback operations with this status, it's a data inconsistency → show as failed
      if (deployment.is_rollback) {
        return 'failed'
      }
      return 'superseded'
    }
    
    return status
  }
  
  function showConfigSnapshot(deployment) {
    configDeployment = deployment
    configModalOpen = true
  }
  
  function redeployFromConfig() {
    if (!configDeployment?.config_snapshot) return
    // Dispatch event to switch to deploy tab with config
    const event = new CustomEvent('redeploy', { 
      detail: { 
        deployment: configDeployment,
        config: configDeployment.config_snapshot 
      },
      bubbles: true 
    })
    document.dispatchEvent(event)
    configModalOpen = false
    toasts.info('Config loaded - switch to Deploy tab')
  }
  
  async function showDeploymentLogs(deployment) {
    logsDeployment = deployment
    logsModalOpen = true
    logsLoading = true
    deploymentLogs = []
    
    try {
      const data = await api('GET', `/infra/deployments/history/${deployment.id}/logs`)
      deploymentLogs = data.logs || []
    } catch (err) {
      toasts.error('Failed to load logs: ' + (err.message || err))
    } finally {
      logsLoading = false
    }
  }
  
  async function initiateRollback(deployment) {
    rollbackTarget = deployment
    
    // Load previous deployments for this service using correct endpoint
    try {
      const params = new URLSearchParams({
        project: deployment.project || '',
        environment: deployment.environment || '',
        service_name: deployment.service_name || deployment.service || ''
      })
      const data = await api('GET', `/infra/deployments/rollback/preview?${params}`)
      previousDeployments = (data.recent_deployments || []).filter(d => d.id !== deployment.id && d.status === 'success')
    } catch (err) {
      previousDeployments = []
    }
    
    rollbackModalOpen = true
  }
  
  async function executeRollback() {
    if (!rollbackTarget || !selectedRollbackId) {
      toasts.error('Select a deployment to rollback to')
      return
    }
    
    // Find the target deployment from previousDeployments
    const targetDeployment = previousDeployments.find(d => d.id === selectedRollbackId)
    if (!targetDeployment) {
      toasts.error('Target deployment not found')
      return
    }
    
    const project = rollbackTarget.project || ''
    const environment = rollbackTarget.environment || ''
    const serviceName = rollbackTarget.service_name || rollbackTarget.service || ''
    
    // Check current service state and target servers
    try {
      // Get current service servers
      const stateParams = new URLSearchParams({ project, environment, service_name: serviceName })
      const currentState = await api('GET', `/infra/services/state?${stateParams}`)
      
      // Get target deployment servers
      const targetServerIps = targetDeployment.server_ips || []
      const currentServerIps = currentState.server_ips || []
      
      // Find orphan servers (currently running but not in target)
      const orphanIps = currentServerIps.filter(ip => !targetServerIps.includes(ip))
      const orphanServers = (currentState.servers || []).filter(s => orphanIps.includes(s.ip))
      
      // Check if target servers are available
      if (targetServerIps.length > 0) {
        const checkResult = await api('POST', `/infra/services/check-servers?do_token=${getDoToken()}&server_ips=${targetServerIps.join(',')}`, null)
        
        rollbackMissingServers = checkResult.unavailable || []
        rollbackAvailableServers = checkResult.available || []
        
        // If some servers are missing, show confirmation
        if (rollbackMissingServers.length > 0) {
          rollbackConfirmType = 'missing'
          pendingRollbackTarget = targetDeployment
          showRollbackConfirm = true
          return
        }
      }
      
      // If there are orphan servers, show cleanup confirmation
      if (orphanServers.length > 0) {
        rollbackCleanupServers = orphanServers
        rollbackConfirmType = 'cleanup'
        pendingRollbackTarget = targetDeployment
        showRollbackConfirm = true
        return
      }
      
    } catch (err) {
      console.log('Rollback pre-check:', err.message || err)
      // Continue with rollback if checks fail
    }
    
    // No issues - proceed with rollback
    await performRollback()
  }
  
  async function confirmRollbackAndProceed() {
    showRollbackConfirm = false
    
    if (rollbackConfirmType === 'cleanup' && rollbackCleanupServers.length > 0) {
      // Cleanup orphan containers
      const containerName = `${rollbackTarget.project}_${rollbackTarget.service || rollbackTarget.service_name}_${rollbackTarget.environment}`.replace(/[^a-zA-Z0-9_]/g, '_')
      const orphanIps = rollbackCleanupServers.map(s => s.ip)
      
      try {
        const result = await api('POST', `/infra/services/cleanup?do_token=${getDoToken()}`, {
          server_ips: orphanIps,
          container_name: containerName
        })
        rollbackLogs = [...rollbackLogs, { message: `Cleanup: ${result.cleaned} stopped`, type: 'info', time: new Date() }]
      } catch (err) {
        rollbackLogs = [...rollbackLogs, { message: `Cleanup warning: ${err.message}`, type: 'warning', time: new Date() }]
      }
    }
    
    rollbackCleanupServers = []
    rollbackMissingServers = []
    pendingRollbackTarget = null
    
    await performRollback()
  }
  
  // Store servers to use for partial rollback
  let useOnlyAvailableServers = false
  let availableServersForRollback = []
  
  async function rollbackWithAvailableOnly() {
    showRollbackConfirm = false
    
    // Save available servers for partial rollback
    useOnlyAvailableServers = true
    availableServersForRollback = rollbackAvailableServers.map(s => s.ip)
    
    rollbackMissingServers = []
    pendingRollbackTarget = null
    
    // Proceed with available servers only
    await performRollback()
  }
  
  async function performRollback() {
    
    // Reset and start
    rollbackLogs = []
    rollbackInProgress = true
    
    const addLog = (msg, type = 'info') => {
      rollbackLogs = [...rollbackLogs, { message: msg, type, time: new Date() }]
    }
    
    try {
      const queryParams = new URLSearchParams({
        project: rollbackTarget.project || '',
        environment: rollbackTarget.environment || '',
        service_name: rollbackTarget.service_name || rollbackTarget.service || ''
      }).toString()
      
      addLog('Starting rollback...')
      
      let success = false
      let errorMsg = ''
      
      // Build request body - include server_ips for partial rollback
      const requestBody = { deployment_id: selectedRollbackId }
      if (useOnlyAvailableServers && availableServersForRollback.length > 0) {
        requestBody.server_ips = availableServersForRollback
        addLog(`Partial rollback to ${availableServersForRollback.length} available server(s)`)
      }
      
      await apiStream('POST', `/infra/deployments/rollback?${queryParams}`, 
        requestBody,
        (msg) => {
          if (msg.type === 'progress' || msg.type === 'start') {
            addLog(msg.message, 'info')
          } else if (msg.type === 'server_complete') {
            addLog(`✅ ${msg.ip}: Success`, 'success')
          } else if (msg.type === 'error') {
            addLog(`❌ ${msg.message || msg.error}`, 'error')
            errorMsg = msg.message || msg.error || 'Unknown error'
          } else if (msg.type === 'complete') {
            success = msg.success
            if (!success) {
              errorMsg = msg.message || 'Rollback failed'
              addLog(`❌ ${errorMsg}`, 'error')
            } else {
              addLog(`✅ ${msg.message}`, 'success')
            }
          }
        }
      )
      
      if (success) {
        toasts.success('Rollback completed successfully')
        await loadDeploymentHistory()
      } else {
        throw new Error(errorMsg || 'Rollback failed')
      }
    } catch (err) {
      addLog(`❌ Error: ${err.message || String(err)}`, 'error')
      toasts.error('Rollback failed: ' + (err.message || String(err)))
    } finally {
      rollbackInProgress = false
      // Reset partial rollback flags
      useOnlyAvailableServers = false
      availableServersForRollback = []
    }
  }
  
  function loadDeploymentHistory() {
    deploymentsStore.refresh()
  }
  
  export function refresh() {
    deploymentsStore.refresh()
  }
</script>

<div class="deployments-page">
  <div class="page-header">
    <h1>Deployment History</h1>
    <div class="header-actions">
      {#if lastUpdated}
        <span class="last-updated">Updated {formatTime(lastUpdated)}</span>
      {/if}
      <Button variant="ghost" on:click={() => deploymentsStore.refresh()}>↻ Refresh</Button>
    </div>
  </div>
  
  <Card padding={false}>
    <div class="table-container">
      <table class="table">
        <thead>
          <tr>
            <th>Project</th>
            <th>Service</th>
            <th>Environment</th>
            <th class="version-col">v</th>
            <th>Deployed</th>
            <th>By</th>
            <th>Type</th>
            <th>Status</th>
            <th>Comment</th>
            <th class="config-col"></th>
            <th class="logs-col"></th>
            <th class="rollback-col"></th>
          </tr>
        </thead>
        <tbody>
          {#if loading && deployments.length === 0}
            <tr>
              <td colspan="12" class="loading-cell">Loading deployment history...</td>
            </tr>
          {:else if deployments.length === 0}
            <tr>
              <td colspan="12" class="empty-cell">No deployments found</td>
            </tr>
          {:else}
            {#each deployments as deployment}
              {@const displayStatus = getDisplayStatus(deployment)}
              <tr>
                <td>
                  <span class="project-name">{deployment.project || '-'}</span>
                </td>
                <td>
                  <span class="service-name">{deployment.service || deployment.name}</span>
                </td>
                <td>
                  <Badge variant={deployment.environment === 'prod' ? 'purple' : deployment.environment === 'staging' ? 'warning' : 'info'}>
                    {deployment.environment || '-'}
                  </Badge>
                </td>
                <td class="version-cell">
                  {#if deployment.version}
                    <span class="version-badge">v{deployment.version}</span>
                  {:else}
                    <span class="version-none">-</span>
                  {/if}
                </td>
                <td class="date-cell">{formatDate(deployment.deployed_at || deployment.created_at)}</td>
                <td class="by-cell" title={deployment.deployed_by || deployment.user || '-'}>{deployment.deployed_by || deployment.user || '-'}</td>
                <td>
                  <Badge variant={deployment.is_rollback ? 'warning' : 'info'}>
                    {deployment.is_rollback ? 'rollback' : 'deploy'}
                  </Badge>
                </td>
                <td>
                  <Badge variant={getStatusBadge(displayStatus)}>
                    {displayStatus}
                  </Badge>
                </td>
                <td class="comment-cell">{deployment.comment || '-'}</td>
                <td class="config-cell">
                  {#if deployment.config_snapshot}
                    <button class="icon-btn" on:click={() => showConfigSnapshot(deployment)} title="View config">
                      ⚙️
                    </button>
                  {/if}
                </td>
                <td class="logs-cell">
                  {#if deployment.has_logs}
                    <button class="icon-btn" on:click={() => showDeploymentLogs(deployment)} title="View logs">
                      📋
                    </button>
                  {/if}
                </td>
                <td class="rollback-cell">
                  {#if deployment.is_current_active}
                    <button class="icon-btn rollback-icon-btn" on:click={() => initiateRollback(deployment)} title="Rollback">
                      ⏪
                    </button>
                  {/if}
                </td>
              </tr>
            {/each}
          {/if}
        </tbody>
      </table>
    </div>
  </Card>
</div>

<!-- Rollback Modal -->
<Modal 
  bind:open={rollbackModalOpen}
  title="⏪ Rollback"
  width="600px"
  on:close={() => rollbackModalOpen = false}
>
  {#if rollbackTarget}
    <div class="rollback-content">
      <div class="service-info">
        <div class="service-name">{rollbackTarget.service || rollbackTarget.name}</div>
        <div class="service-coords">{rollbackTarget.project} / {rollbackTarget.environment}</div>
      </div>
      
      <div class="section">
        <label>📍 Current Deployment</label>
        <div class="deployment-card current">
          <div class="deploy-date">{formatDate(rollbackTarget.deployed_at || rollbackTarget.created_at)}</div>
          <div class="deploy-by">by {rollbackTarget.deployed_by || rollbackTarget.user || 'unknown'}</div>
          {#if rollbackTarget.comment}
            <div class="deploy-comment">{rollbackTarget.comment}</div>
          {/if}
        </div>
      </div>
      
      <div class="section">
        <label>🎯 Rollback to</label>
        {#if previousDeployments.length === 0}
          <div class="no-deployments">No previous deployments found</div>
        {:else}
          <div class="deployment-list">
            {#each previousDeployments as dep}
              <label class="deployment-option" class:selected={selectedRollbackId === dep.id}>
                <input 
                  type="radio" 
                  bind:group={selectedRollbackId} 
                  value={dep.id}
                  disabled={rollbackInProgress}
                >
                <div class="deploy-version">
                  {#if dep.version}
                    <span class="version-badge">v{dep.version}</span>
                  {:else}
                    <span class="version-badge muted">{dep.id.substring(0, 8)}</span>
                  {/if}
                </div>
                <div class="deploy-info">
                  <div class="deploy-date">{formatDate(dep.deployed_at || dep.created_at)}</div>
                  <div class="deploy-by">by {dep.deployed_by || dep.user || 'unknown'}</div>
                </div>
                <Badge variant={getStatusBadge(getDisplayStatus(dep))}>{getDisplayStatus(dep)}</Badge>
              </label>
            {/each}
          </div>
        {/if}
      </div>
      
      <!-- Rollback Logs -->
      {#if rollbackLogs.length > 0}
        <div class="section rollback-logs-section">
          <label>📋 Progress</label>
          <div class="rollback-logs">
            {#each rollbackLogs as log}
              <div class="log-entry log-{log.type}">
                {log.message}
              </div>
            {/each}
            {#if rollbackInProgress}
              <div class="log-entry log-info">
                <span class="spinner">⏳</span> Working...
              </div>
            {/if}
          </div>
        </div>
      {/if}
    </div>
  {/if}
  
  <div slot="footer">
    <Button variant="ghost" on:click={() => { rollbackModalOpen = false; rollbackLogs = []; }}>
      {rollbackLogs.length > 0 ? 'Close' : 'Cancel'}
    </Button>
    <Button variant="warning" on:click={executeRollback} disabled={!selectedRollbackId || rollbackInProgress}>
      {#if rollbackInProgress}
        ⏳ Rolling back...
      {:else}
        ⏪ Execute Rollback
      {/if}
    </Button>
  </div>
</Modal>

<!-- Config Snapshot Modal -->
<Modal 
  bind:open={configModalOpen}
  title="⚙️ Deployment Config"
  width="500px"
  on:close={() => configModalOpen = false}
>
  {#if configDeployment}
    <div class="config-content">
      <div class="config-header-info">
        <span class="service-name">{configDeployment.service_name || configDeployment.service}</span>
        <span class="meta">{configDeployment.environment} • {formatDate(configDeployment.deployed_at)}</span>
      </div>
      
      {#if configDeployment.config_snapshot}
        {@const config = configDeployment.config_snapshot}
        <table class="config-table">
          <tbody>
            <tr><td class="label">Source Type</td><td><strong>{config.source_type || '-'}</strong></td></tr>
            {#if config.git_url}<tr><td class="label">Git URL</td><td>{config.git_url}</td></tr>{/if}
            {#if config.git_branch}<tr><td class="label">Git Branch</td><td>{config.git_branch}</td></tr>{/if}
            {#if config.image}<tr><td class="label">Image</td><td>{config.image}</td></tr>{/if}
            <tr><td class="label">Port</td><td>{config.port || '-'}</td></tr>
            {#if config.container_port}<tr><td class="label">Container Port</td><td>{config.container_port}</td></tr>{/if}
            {#if config.host_port}<tr><td class="label">Host Port</td><td>{config.host_port}</td></tr>{/if}
            {#if config.snapshot_id}<tr><td class="label">Snapshot ID</td><td>{config.snapshot_id}</td></tr>{/if}
            {#if config.region}<tr><td class="label">Region</td><td>{config.region}</td></tr>{/if}
            {#if config.size}<tr><td class="label">Size</td><td>{config.size}</td></tr>{/if}
            {#if config.server_ips?.length}<tr><td class="label">Servers</td><td>{config.server_ips.join(', ')}</td></tr>{/if}
            {#if config.setup_domain}<tr><td class="label">Setup Domain</td><td>Yes</td></tr>{/if}
            {#if config.base_domain}<tr><td class="label">Base Domain</td><td>{config.base_domain}</td></tr>{/if}
          </tbody>
        </table>
        
        {#if config.env_vars && Object.keys(config.env_vars).length > 0}
          <div class="env-section">
            <div class="section-title">Environment Variables</div>
            <div class="env-list">
              {#each Object.entries(config.env_vars) as [key, value]}
                <div class="env-item">{key}={value.length > 20 ? value.substring(0, 20) + '...' : value}</div>
              {/each}
            </div>
          </div>
        {/if}
        
        {#if config.tags?.length}
          <div class="tags-section">
            <div class="section-title">Tags</div>
            <div class="tags-list">
              {#each config.tags as tag}
                <Badge>{tag}</Badge>
              {/each}
            </div>
          </div>
        {/if}
      {:else}
        <div class="no-config">No config snapshot available</div>
      {/if}
    </div>
  {/if}
  
  <div slot="footer">
    <Button variant="primary" on:click={redeployFromConfig}>🚀 Redeploy with this config</Button>
    <Button variant="ghost" on:click={() => configModalOpen = false}>Close</Button>
  </div>
</Modal>

<!-- Deployment Logs Modal -->
<Modal 
  bind:open={logsModalOpen}
  title="📋 Deployment Logs"
  width="700px"
  on:close={() => logsModalOpen = false}
>
  {#if logsDeployment}
    <div class="logs-modal-content">
      <div class="logs-header-info">
        <span class="service-name">{logsDeployment.service || logsDeployment.name}</span>
        <span class="meta">{logsDeployment.environment} • {formatDate(logsDeployment.deployed_at)}</span>
        {#if logsDeployment.version}
          <Badge variant="purple">v{logsDeployment.version}</Badge>
        {/if}
        <Badge variant={getStatusBadge(getDisplayStatus(logsDeployment))}>{getDisplayStatus(logsDeployment)}</Badge>
      </div>
      
      {#if logsLoading}
        <div class="logs-loading">Loading logs...</div>
      {:else if deploymentLogs.length === 0}
        <div class="no-logs">No logs available for this deployment</div>
      {:else}
        <div class="logs-container">
          {#each deploymentLogs as log}
            <div class="log-line">
              <span class="log-time">{log.timestamp ? new Date(log.timestamp).toLocaleTimeString() : ''}</span>
              <span class="log-message">{log.message}</span>
            </div>
          {/each}
        </div>
      {/if}
    </div>
  {/if}
  
  <div slot="footer">
    <Button variant="ghost" on:click={() => logsModalOpen = false}>Close</Button>
  </div>
</Modal>

<!-- Rollback Confirmation Modal -->
<Modal 
  bind:open={showRollbackConfirm}
  title={rollbackConfirmType === 'cleanup' ? '⚠️ Stop Orphan Containers' : '⚠️ Servers Unavailable'}
  width="500px"
  on:close={() => { showRollbackConfirm = false; pendingRollbackTarget = null }}
>
  {#if rollbackConfirmType === 'cleanup'}
    <div class="rollback-confirm-content">
      <p>
        Rolling back will restore to <strong>{rollbackAvailableServers.length}</strong> servers.
        Service currently runs on <strong>{rollbackAvailableServers.length + rollbackCleanupServers.length}</strong> servers.
      </p>
      
      <p>Stop containers on the following servers?</p>
      
      <div class="confirm-server-list">
        {#each rollbackCleanupServers as server}
          <div class="confirm-server-item">
            <span class="server-name">{server.name || server.ip}</span>
            <span class="server-ip">{server.ip}</span>
          </div>
        {/each}
      </div>
    </div>
  {:else if rollbackConfirmType === 'missing'}
    <div class="rollback-confirm-content">
      <p>
        <strong>{rollbackMissingServers.length}</strong> server(s) from the original deployment are unavailable:
      </p>
      
      <div class="confirm-server-list unavailable">
        {#each rollbackMissingServers as server}
          <div class="confirm-server-item">
            <span class="server-name">{server.name || server.ip}</span>
            <span class="server-ip">{server.ip}</span>
            <Badge variant="error">offline</Badge>
          </div>
        {/each}
      </div>
      
      {#if rollbackAvailableServers.length > 0}
        <p>Available servers ({rollbackAvailableServers.length}):</p>
        <div class="confirm-server-list available">
          {#each rollbackAvailableServers as server}
            <div class="confirm-server-item">
              <span class="server-name">{server.name || server.ip}</span>
              <span class="server-ip">{server.ip}</span>
              <Badge variant="success">online</Badge>
            </div>
          {/each}
        </div>
      {/if}
    </div>
  {/if}
  
  <div slot="footer">
    {#if rollbackConfirmType === 'cleanup'}
      <Button variant="primary" on:click={confirmRollbackAndProceed}>Proceed</Button>
    {:else if rollbackConfirmType === 'missing' && rollbackAvailableServers.length > 0}
      <Button variant="primary" on:click={rollbackWithAvailableOnly}>Proceed with available only</Button>
    {/if}
    <Button variant="ghost" on:click={() => { showRollbackConfirm = false; pendingRollbackTarget = null }}>Cancel</Button>
  </div>
</Modal>

<style>
  .deployments-page {
    padding: 0;
  }
  
  .page-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 16px;
  }
  
  .page-header h1 {
    margin: 0;
    font-size: 1.5rem;
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
    font-size: 0.85rem;
    color: var(--text-muted);
    background: var(--table-header-bg);
    border-bottom: 1px solid var(--border);
    white-space: nowrap;
  }
  
  .table td {
    padding: 10px 12px;
    border-bottom: 1px solid var(--border);
    font-size: 0.85rem;
  }
  
  .table tbody tr:last-child td {
    border-bottom: none;
  }
  
  .table tr:hover {
    background: var(--table-row-hover);
  }
  
  .version-col {
    width: 40px;
    text-align: center;
  }
  
  .version-cell {
    text-align: center;
  }
  
  .version-badge {
    font-family: var(--font-mono, monospace);
    font-size: 0.75rem;
    font-weight: 600;
    color: var(--primary2);
    background: rgba(45, 125, 255, 0.1);
    padding: 2px 6px;
    border-radius: 4px;
  }
  
  .version-none {
    color: var(--text-muted2);
  }
  
  .config-col {
    width: 36px;
    text-align: center;
    padding: 10px 4px !important;
  }
  
  .logs-col {
    width: 36px;
    text-align: center;
    padding: 10px 4px !important;
  }
  
  .rollback-col {
    width: 36px;
    text-align: center;
    padding: 10px 8px 10px 4px !important;
  }
  
  .config-cell,
  .logs-cell,
  .rollback-cell {
    text-align: center;
    padding: 10px 4px !important;
  }
  
  .service-cell {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  
  .service-name {
    font-weight: 600;
  }
  
  .project-name {
    font-size: 0.75rem;
    color: var(--text-muted);
  }
  
  .date-cell {
    white-space: nowrap;
    font-size: 0.8rem;
  }
  
  .by-cell {
    max-width: 100px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  
  .comment-cell {
    max-width: 120px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--text-muted);
  }
  
  .loading-cell, .empty-cell {
    text-align: center;
    padding: 40px !important;
    color: var(--text-muted);
  }
  
  /* Rollback modal styles */
  .rollback-content {
    display: flex;
    flex-direction: column;
    gap: 16px;
  }
  
  .service-info {
    padding: 12px;
    background: var(--bg-input);
    border-radius: 8px;
  }
  
  .service-info .service-name {
    font-weight: 600;
    margin-bottom: 4px;
  }
  
  .service-coords {
    font-size: 0.85rem;
    color: var(--text-muted);
  }
  
  .section {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  
  .section label {
    font-weight: 500;
    color: var(--text-muted);
  }
  
  .deployment-card {
    padding: 12px;
    background: var(--bg-input);
    border-radius: 8px;
  }
  
  .deployment-card.current {
    border-left: 3px solid var(--primary);
  }
  
  .deploy-date {
    font-weight: 500;
  }
  
  .deploy-by {
    font-size: 0.8rem;
    color: var(--text-muted);
  }
  
  .deploy-comment {
    margin-top: 4px;
    font-size: 0.85rem;
    color: var(--text-muted2);
  }
  
  .no-deployments {
    padding: 20px;
    text-align: center;
    color: var(--text-muted);
    background: var(--bg-input);
    border-radius: 8px;
  }
  
  .deployment-list {
    display: flex;
    flex-direction: column;
    gap: 8px;
    max-height: 250px;
    overflow-y: auto;
  }
  
  .deployment-option {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 10px 12px;
    background: var(--bg-input);
    border: 2px solid transparent;
    border-radius: 8px;
    cursor: pointer;
    transition: all 0.15s;
  }
  
  .deployment-option:hover {
    border-color: var(--border2);
  }
  
  .deployment-option.selected {
    border-color: var(--warning);
    background: rgba(245,158,11,.1);
  }
  
  .deployment-option input {
    width: auto;
  }
  
  .deploy-version {
    min-width: 50px;
  }
  
  .version-badge {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.85rem;
    font-weight: 600;
    color: var(--purple);
  }
  
  .version-badge.muted {
    color: var(--text-muted);
    font-size: 0.75rem;
  }
  
  .deploy-info {
    flex: 1;
  }
  
  /* Rollback logs */
  .rollback-logs-section {
    margin-top: 8px;
  }
  
  .rollback-logs {
    max-height: 200px;
    overflow-y: auto;
    background: var(--bg-dark, #1a1b26);
    border-radius: 8px;
    padding: 12px;
    font-family: 'Monaco', 'Menlo', monospace;
    font-size: 0.85rem;
  }
  
  .log-entry {
    padding: 2px 0;
    color: #a9b1d6;
  }
  
  .log-entry.log-info {
    color: #7aa2f7;
  }
  
  .log-entry.log-success {
    color: #9ece6a;
  }
  
  .log-entry.log-error {
    color: #f7768e;
  }
  
  .spinner {
    display: inline-block;
    animation: pulse 1s ease-in-out infinite;
  }
  
  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.5; }
  }
  
  /* Config modal styles */
  .config-content {
    display: flex;
    flex-direction: column;
    gap: 16px;
  }
  
  .config-header-info {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 8px 12px;
    background: var(--bg-input);
    border-radius: 8px;
  }
  
  .config-header-info .service-name {
    font-weight: 600;
  }
  
  .config-header-info .meta {
    font-size: 0.8rem;
    color: var(--text-muted);
  }
  
  .config-table {
    width: 100%;
    font-size: 0.85rem;
  }
  
  .config-table td {
    padding: 4px 8px;
  }
  
  .config-table td.label {
    color: var(--text-muted);
    width: 120px;
  }
  
  .env-section, .tags-section {
    margin-top: 8px;
  }
  
  .section-title {
    font-weight: 500;
    margin-bottom: 8px;
  }
  
  .env-list {
    background: var(--bg-secondary);
    padding: 8px;
    border-radius: 4px;
    font-family: monospace;
    font-size: 0.8rem;
    max-height: 120px;
    overflow-y: auto;
  }
  
  .env-item {
    margin-bottom: 4px;
  }
  
  .tags-list {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  
  .no-config {
    padding: 20px;
    text-align: center;
    color: var(--text-muted);
  }
  
  @media (max-width: 768px) {
    .table th:nth-child(4),
    .table td:nth-child(4),
    .table th:nth-child(6),
    .table td:nth-child(6) {
      display: none;
    }
  }
  
  /* Action buttons */
  .icon-btn {
    padding: 6px 8px;
    background: transparent;
    border: none;
    border-radius: 6px;
    cursor: pointer;
    font-size: 14px;
    transition: background 0.15s;
    display: inline-flex;
    align-items: center;
    justify-content: center;
  }
  
  .icon-btn:hover {
    background: var(--btn-bg-hover);
  }
  
  .rollback-icon-btn {
    color: #a78bfa !important;
  }
  
  .rollback-icon-btn:hover {
    background: rgba(139, 92, 246, 0.15) !important;
  }

  /* Logs Modal */
  .logs-modal-content {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  
  .logs-header-info {
    display: flex;
    align-items: center;
    gap: 8px;
    padding-bottom: 8px;
    border-bottom: 1px solid var(--border);
  }
  
  .logs-header-info .service-name {
    font-weight: 600;
  }
  
  .logs-header-info .meta {
    color: var(--text-muted);
    font-size: 0.85rem;
  }
  
  .logs-loading,
  .no-logs {
    padding: 24px;
    text-align: center;
    color: var(--text-muted);
  }
  
  .logs-container {
    max-height: 400px;
    overflow-y: auto;
    background: var(--bg-dark, #1a1b26);
    border-radius: 8px;
    padding: 12px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.8rem;
  }
  
  .log-line {
    display: flex;
    gap: 12px;
    padding: 4px 0;
    line-height: 1.4;
  }
  
  .log-time {
    color: var(--text-muted);
    flex-shrink: 0;
    width: 80px;
  }
  
  .log-message {
    color: var(--text);
    white-space: pre-wrap;
    word-break: break-word;
  }
  
  /* Rollback Confirmation Modal */
  .rollback-confirm-content {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  
  .rollback-confirm-content p {
    margin: 0;
    line-height: 1.5;
  }
  
  .confirm-server-list {
    display: flex;
    flex-direction: column;
    gap: 8px;
    background: var(--bg-input);
    border-radius: 8px;
    padding: 12px;
    max-height: 180px;
    overflow-y: auto;
  }
  
  .confirm-server-list.unavailable {
    border: 1px solid var(--error);
    background: rgba(239, 68, 68, 0.05);
  }
  
  .confirm-server-list.available {
    border: 1px solid var(--success);
    background: rgba(34, 197, 94, 0.05);
  }
  
  .confirm-server-item {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 8px 12px;
    background: var(--bg-secondary);
    border-radius: 6px;
    gap: 12px;
  }
  
  .confirm-server-item .server-name {
    font-weight: 500;
    flex: 1;
  }
  
  .confirm-server-item .server-ip {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.85rem;
    color: var(--text-muted);
  }
</style>
