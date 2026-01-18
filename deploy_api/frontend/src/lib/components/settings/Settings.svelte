<script>
  import { onMount } from 'svelte'
  import { theme, serversStore, projectsStore, snapshotsStore, deploymentsStore } from '../../stores/app.js'
  import { toasts } from '../../stores/toast.js'
  import { api } from '../../api/client.js'
  import { setDoToken, getDoToken, setCfToken, getCfToken } from '../../stores/auth.js'
  import { Card } from '@myorg/ui'
  import { Button } from '@myorg/ui'
  import { Badge } from '@myorg/ui'
  
  let doToken = ''
  let doTokenStatus = null
  let cfToken = ''
  let cfTokenStatus = null
  
  // Domain setup
  let domainName = ''
  let domainIp = ''
  let domainProxied = true
  let domainResult = null
  
  // DNS Round-robin
  let lbDomain = ''
  let lbIps = ''
  let lbProxied = true
  let lbResult = null
  
  // Scheduled tasks
  let scheduledTasks = []
  let tasksLoading = false
  
  onMount(() => {
    checkDoToken()
    checkCfToken()
    loadScheduledTasks()
  })
  
  async function checkDoToken() {
    const token = getDoToken()
    if (token) {
      doToken = token.substring(0, 10) + '...'
      try {
        // Use snapshots endpoint to validate DO token
        await api('GET', '/infra/snapshots')
        doTokenStatus = { valid: true }
      } catch {
        doTokenStatus = { valid: false }
      }
    } else {
      doTokenStatus = { valid: false, missing: true }
    }
  }
  
  async function checkCfToken() {
    const token = getCfToken()
    if (token) {
      cfToken = token.substring(0, 10) + '...'
      cfTokenStatus = { valid: true }
    } else {
      cfTokenStatus = { valid: false, missing: true }
    }
  }
  
  async function saveDoToken(e) {
    e.preventDefault()
    const input = e.target.querySelector('input')
    const token = input.value
    
    if (!token) {
      toasts.error('Token is required')
      return
    }
    
    setDoToken(token)
    input.value = ''
    toasts.success('DigitalOcean token saved')
    await checkDoToken()
    
    // Refresh all stores now that DO token is available
    serversStore.refresh()
    projectsStore.refresh()
    snapshotsStore.refresh()
    deploymentsStore.refresh()
  }
  
  async function saveCfToken(e) {
    e.preventDefault()
    const input = e.target.querySelector('input')
    const token = input.value
    
    if (!token) {
      toasts.error('Token is required')
      return
    }
    
    setCfToken(token)
    input.value = ''
    toasts.success('Cloudflare token saved')
    await checkCfToken()
  }
  
  async function setupDomain(e) {
    e.preventDefault()
    
    try {
      const result = await api('POST', '/infra/cloudflare/domain', {
        domain: domainName,
        ip: domainIp,
        proxied: domainProxied
      })
      domainResult = { success: true, message: 'Domain configured successfully' }
      toasts.success('Domain setup complete')
    } catch (err) {
      domainResult = { success: false, message: err.message }
      toasts.error(err.message)
    }
  }
  
  async function setupLoadBalancer(e) {
    e.preventDefault()
    
    try {
      const ips = lbIps.split(',').map(ip => ip.trim()).filter(Boolean)
      const result = await api('POST', '/infra/cloudflare/lb', {
        domain: lbDomain,
        server_ips: ips,
        proxied: lbProxied
      })
      lbResult = { success: true, message: `Created load balancer with ${ips.length} servers` }
      toasts.success('Load balancer configured')
    } catch (err) {
      lbResult = { success: false, message: err.message }
      toasts.error(err.message)
    }
  }
  
  async function loadScheduledTasks() {
    tasksLoading = true
    try {
      const data = await api('GET', '/infra/scheduler/tasks')
      scheduledTasks = data.tasks || data || []
    } catch (err) {
      scheduledTasks = []
    } finally {
      tasksLoading = false
    }
  }
  
  async function deleteTask(id) {
    if (!confirm('Delete this scheduled task?')) return
    
    try {
      await api('DELETE', `/infra/scheduler/tasks/${id}`)
      toasts.success('Task deleted')
      await loadScheduledTasks()
    } catch (err) {
      toasts.error(err.message)
    }
  }
</script>

<div class="settings-page">
  <!-- Theme -->
  <Card title="🎨 Appearance">
    <div class="form-group">
      <label for="theme-select">Theme</label>
      <select id="theme-select" bind:value={$theme} on:change={() => theme.set($theme)}>
        <option value="dark">🌙 Dark (Space)</option>
        <option value="light">☀️ Light</option>
      </select>
    </div>
    <p class="hint">Theme preference is saved to your browser.</p>
  </Card>
  
  <!-- DigitalOcean Token -->
  <Card title="⚙️ DigitalOcean Credentials">
    <p class="description">
      Get your token from 
      <a href="https://cloud.digitalocean.com/account/api/tokens" target="_blank">DO Control Panel</a>.
    </p>
    
    <div class="info-box">
      <div class="info-title">🔒 Browser Storage</div>
      <div class="info-text">Token stored in browser cookie. Passed with each API request. Never stored on server.</div>
    </div>
    
    <form on:submit={saveDoToken}>
      <div class="form-group">
        <label for="do-token">DigitalOcean API Token</label>
        <input 
          id="do-token"
          type="password" 
          placeholder="dop_v1_xxxxx"
        >
      </div>
      <Button variant="primary" type="submit">Save Token</Button>
    </form>
    
    <div class="token-status">
      {#if doTokenStatus?.valid}
        <Badge variant="success">✓ Connected</Badge>
        <span class="token-preview">{doToken}</span>
      {:else if doTokenStatus?.missing}
        <Badge variant="warning">Not configured</Badge>
      {:else}
        <Badge variant="danger">Invalid token</Badge>
      {/if}
    </div>
  </Card>
  
  <!-- Cloudflare Token -->
  <Card title="☁️ Cloudflare Credentials">
    <p class="description">
      Get your token from 
      <a href="https://dash.cloudflare.com/profile/api-tokens" target="_blank">Cloudflare Dashboard</a>.
    </p>
    
    <form on:submit={saveCfToken}>
      <div class="form-group">
        <label for="cf-token">Cloudflare API Token</label>
        <input 
          id="cf-token"
          type="password" 
          placeholder="xxxxx"
        >
      </div>
      <Button variant="primary" type="submit">Save Token</Button>
    </form>
    
    <div class="token-status">
      {#if cfTokenStatus?.valid}
        <Badge variant="success">✓ Connected</Badge>
        <span class="token-preview">{cfToken}</span>
      {:else}
        <Badge variant="warning">Not configured</Badge>
      {/if}
    </div>
  </Card>
  
  <!-- Domain Setup -->
  <Card title="🌐 Domain Setup">
    <p class="description">
      Point a domain to your server. With "Proxied" enabled, HTTPS works automatically.
    </p>
    
    <form on:submit={setupDomain}>
      <div class="form-group">
        <label for="domain-name">Domain</label>
        <input 
          id="domain-name"
          type="text"
          bind:value={domainName}
          placeholder="api.example.com"
          required
        >
      </div>
      <div class="form-group">
        <label for="domain-ip">Server IP</label>
        <input 
          id="domain-ip"
          type="text"
          bind:value={domainIp}
          placeholder="1.2.3.4"
          required
        >
      </div>
      <label class="checkbox-label">
        <input type="checkbox" bind:checked={domainProxied}>
        Proxied (Cloudflare handles SSL)
      </label>
      <div class="form-actions">
        <Button variant="primary" type="submit">Setup Domain</Button>
      </div>
    </form>
    
    {#if domainResult}
      <div class="result" class:success={domainResult.success} class:error={!domainResult.success}>
        {domainResult.message}
      </div>
    {/if}
  </Card>
  
  <!-- DNS Round-Robin -->
  <Card title="🌐 DNS Round-Robin (Cloudflare)">
    <p class="description">
      Simple load distribution via multiple A records. Cloudflare rotates between IPs at DNS level.
      <strong>FREE</strong>, but no health checks.
    </p>
    
    <form on:submit={setupLoadBalancer}>
      <div class="form-group">
        <label for="lb-domain">Domain</label>
        <input 
          id="lb-domain"
          type="text"
          bind:value={lbDomain}
          placeholder="api.example.com"
          required
        >
      </div>
      <div class="form-group">
        <label for="lb-ips">Server IPs (comma-separated)</label>
        <input 
          id="lb-ips"
          type="text"
          bind:value={lbIps}
          placeholder="1.2.3.4, 5.6.7.8"
          required
        >
      </div>
      <label class="checkbox-label">
        <input type="checkbox" bind:checked={lbProxied}>
        Proxied (SSL + CDN)
      </label>
      <div class="form-actions">
        <Button variant="primary" type="submit">Setup DNS Round-Robin</Button>
      </div>
    </form>
    
    {#if lbResult}
      <div class="result" class:success={lbResult.success} class:error={!lbResult.success}>
        {lbResult.message}
      </div>
    {/if}
  </Card>
  
  <!-- Scheduled Tasks -->
  <Card title="⏰ Task Scheduler">
    <Button slot="header" variant="ghost" size="sm" on:click={loadScheduledTasks}>
      ↻ Refresh
    </Button>
    
    <p class="description">
      Schedule recurring tasks like health checks, auto-restart, and backups.
    </p>
    
    {#if tasksLoading}
      <div class="empty-state">Loading tasks...</div>
    {:else if scheduledTasks.length === 0}
      <div class="empty-state">No scheduled tasks</div>
    {:else}
      <div class="task-list">
        {#each scheduledTasks as task}
          <div class="task-item">
            <div class="task-info">
              <div class="task-name">{task.name}</div>
              <div class="task-meta">
                <Badge variant="info">{task.type}</Badge>
                <span>Every {task.interval} min</span>
              </div>
            </div>
            <Button variant="danger" size="sm" on:click={() => deleteTask(task.id)}>
              🗑️
            </Button>
          </div>
        {/each}
      </div>
    {/if}
  </Card>
</div>

<style>
  .settings-page {
    display: flex;
    flex-direction: column;
    gap: 16px;
    max-width: 700px;
  }
  
  .description {
    color: var(--text-muted);
    font-size: 0.875rem;
    margin-bottom: 16px;
  }
  
  .description a {
    color: var(--primary);
  }
  
  .hint {
    font-size: 0.8rem;
    color: var(--text-muted2);
    margin-top: 8px;
  }
  
  .info-box {
    background: var(--bg-input);
    border-radius: 8px;
    padding: 12px;
    margin-bottom: 16px;
  }
  
  .info-title {
    font-weight: 500;
    margin-bottom: 4px;
  }
  
  .info-text {
    font-size: 0.8rem;
    color: var(--text-muted);
  }
  
  .form-group {
    margin-bottom: 16px;
  }
  
  .form-group label {
    display: block;
    font-size: 0.875rem;
    color: var(--text-muted);
    margin-bottom: 6px;
  }
  
  .form-group input,
  .form-group select {
    width: 100%;
    max-width: 300px;
    padding: 10px 12px;
    background: var(--bg-input);
    border: 1px solid var(--border);
    border-radius: 12px;
    color: var(--text);
    font-size: 0.875rem;
  }
  
  .checkbox-label {
    display: flex;
    align-items: center;
    gap: 8px;
    cursor: pointer;
    margin-bottom: 16px;
  }
  
  .checkbox-label input {
    width: auto;
  }
  
  .form-actions {
    margin-top: 16px;
  }
  
  .token-status {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 16px;
    padding-top: 16px;
    border-top: 1px solid var(--border);
  }
  
  .token-preview {
    font-family: monospace;
    font-size: 0.8rem;
    color: var(--text-muted);
  }
  
  .result {
    margin-top: 12px;
    padding: 10px 12px;
    border-radius: 8px;
    font-size: 0.875rem;
  }
  
  .result.success {
    background: rgba(54,211,124,.15);
    color: var(--success);
  }
  
  .result.error {
    background: rgba(255,77,94,.15);
    color: var(--danger);
  }
  
  .empty-state {
    text-align: center;
    padding: 24px;
    color: var(--text-muted);
  }
  
  .task-list {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  
  .task-item {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 12px;
    background: var(--bg-input);
    border-radius: 8px;
  }
  
  .task-name {
    font-weight: 500;
    margin-bottom: 4px;
  }
  
  .task-meta {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 0.8rem;
    color: var(--text-muted);
  }
</style>
