<script>
  import { onMount } from 'svelte'
  import { servers } from '../../stores/app.js'
  import { toasts } from '../../stores/toast.js'
  import { api } from '../../api/client.js'
  import Card from '../ui/Card.svelte'
  import Button from '../ui/Button.svelte'
  
  let serviceType = ''
  let project = ''
  let environment = 'prod'
  let targetServer = ''
  
  let deploying = false
  let result = null
  
  const serviceTypes = [
    { value: 'postgres', label: '🐘 PostgreSQL', port: 5432 },
    { value: 'redis', label: '⚡ Redis', port: 6379 },
    { value: 'mysql', label: '🐬 MySQL', port: 3306 },
    { value: 'mongo', label: '🍃 MongoDB', port: 27017 }
  ]
  
  const environments = ['prod', 'staging', 'dev']
  
  onMount(() => {
    loadServers()
  })
  
  async function loadServers() {
    try {
      const data = await api('GET', '/infra/servers')
      servers.set(data.servers || data || [])
    } catch (err) {
      console.error('Failed to load servers:', err)
    }
  }
  
  async function deployService(e) {
    e.preventDefault()
    
    if (!serviceType || !project || !targetServer) {
      toasts.error('Please fill in all required fields')
      return
    }
    
    deploying = true
    result = null
    
    try {
      // TODO: Add /infra/services/deploy endpoint to backend
      // For now, use the general deploy endpoint
      toasts.error('Service deployment not yet implemented. Use Deploy tab instead.')
      return
      
      // const data = await api('POST', '/infra/services/deploy', {
      //   service_type: serviceType,
      //   project,
      //   environment,
      //   server_ip: targetServer
      // })
      // 
      // result = data
      // toasts.success(`${serviceType} deployed successfully!`)
    } catch (err) {
      toasts.error('Deployment failed: ' + err.message)
    } finally {
      deploying = false
    }
  }
  
  function copyToClipboard(text) {
    navigator.clipboard.writeText(text)
    toasts.success('Copied to clipboard')
  }
</script>

<div class="services-page">
  <div class="services-grid">
    <!-- Deploy Form -->
    <Card title="🗄️ Deploy Database/Cache">
      <p class="description">
        Deploy stateful services with automatic configuration, persistence, and service mesh.
      </p>
      
      <form on:submit={deployService}>
        <div class="form-group">
          <label for="svc-type">Service Type *</label>
          <select id="svc-type" bind:value={serviceType} required>
            <option value="">Select service...</option>
            {#each serviceTypes as svc}
              <option value={svc.value}>{svc.label}</option>
            {/each}
          </select>
        </div>
        
        <div class="form-group">
          <label for="svc-project">Project *</label>
          <input 
            id="svc-project"
            type="text"
            bind:value={project}
            placeholder="myapp"
            required
          >
        </div>
        
        <div class="form-group">
          <label for="svc-env">Environment</label>
          <select id="svc-env" bind:value={environment}>
            {#each environments as env}
              <option value={env}>{env.charAt(0).toUpperCase() + env.slice(1)}</option>
            {/each}
          </select>
        </div>
        
        <div class="form-group">
          <label for="svc-server">Target Server *</label>
          <select id="svc-server" bind:value={targetServer} required>
            <option value="">Select server...</option>
            {#each $servers as server}
              {@const ip = server.ip || server.networks?.v4?.[0]?.ip_address}
              {#if ip}
                <option value={ip}>{server.name || 'unnamed'} ({ip})</option>
              {/if}
            {/each}
          </select>
          <small>Servers from Infrastructure tab</small>
        </div>
        
        <Button variant="primary" type="submit" disabled={deploying}>
          {#if deploying}
            Deploying...
          {:else}
            🚀 Deploy Service
          {/if}
        </Button>
      </form>
    </Card>
    
    <!-- Result -->
    <Card title="📋 Deployment Result">
      {#if result}
        <div class="result-content">
          <div class="result-header">
            <span class="result-icon">✅</span>
            <span class="result-title">{result.service_type} deployed</span>
          </div>
          
          <div class="connection-info">
            <div class="info-row">
              <span class="label">Host:</span>
              <code class="value clickable" on:click={() => copyToClipboard(result.host || 'localhost')}>
                {result.host || 'localhost'}
              </code>
            </div>
            <div class="info-row">
              <span class="label">Port:</span>
              <code class="value clickable" on:click={() => copyToClipboard(String(result.port))}>
                {result.port}
              </code>
            </div>
            {#if result.database}
              <div class="info-row">
                <span class="label">Database:</span>
                <code class="value clickable" on:click={() => copyToClipboard(result.database)}>
                  {result.database}
                </code>
              </div>
            {/if}
            {#if result.username}
              <div class="info-row">
                <span class="label">Username:</span>
                <code class="value clickable" on:click={() => copyToClipboard(result.username)}>
                  {result.username}
                </code>
              </div>
            {/if}
            {#if result.password}
              <div class="info-row">
                <span class="label">Password:</span>
                <code class="value clickable" on:click={() => copyToClipboard(result.password)}>
                  {result.password}
                </code>
              </div>
            {/if}
            {#if result.connection_url}
              <div class="info-row full-width">
                <span class="label">Connection URL:</span>
                <code class="value url clickable" on:click={() => copyToClipboard(result.connection_url)}>
                  {result.connection_url}
                </code>
              </div>
            {/if}
          </div>
          
          <small class="copy-hint">Click any value to copy</small>
        </div>
      {:else}
        <div class="empty-result">
          <div class="empty-icon">🗄️</div>
          <div>Deploy a service to see connection details</div>
        </div>
      {/if}
    </Card>
  </div>
  
  <!-- How It Works -->
  <Card title="ℹ️ How It Works">
    <div class="features-grid">
      <div class="feature">
        <strong>🔐 Auto Credentials</strong>
        <p>Deterministic passwords generated from project/env. Same inputs = same password.</p>
      </div>
      <div class="feature">
        <strong>💾 Persistent Storage</strong>
        <p>Data volumes mounted at /data. Survives container restarts and redeploys.</p>
      </div>
      <div class="feature">
        <strong>🔀 Service Mesh</strong>
        <p>Nginx proxy on internal ports. Apps connect to localhost:PORT.</p>
      </div>
      <div class="feature">
        <strong>🔧 Auto-Inject</strong>
        <p>Enable "Auto-inject" in Deploy tab to get DATABASE_URL automatically.</p>
      </div>
    </div>
  </Card>
</div>

<style>
  .services-page {
    padding: 0;
  }
  
  .services-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
    margin-bottom: 16px;
  }
  
  .description {
    color: var(--text-muted);
    font-size: 0.875rem;
    margin-bottom: 16px;
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
  
  .form-group small {
    font-size: 0.75rem;
    color: var(--text-muted2);
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
  
  .result-content {
    display: flex;
    flex-direction: column;
    gap: 16px;
  }
  
  .result-header {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  
  .result-icon {
    font-size: 1.5rem;
  }
  
  .result-title {
    font-weight: 600;
    font-size: 1.1rem;
  }
  
  .connection-info {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 12px;
    background: var(--bg-input);
    border-radius: 8px;
  }
  
  .info-row {
    display: flex;
    gap: 8px;
    align-items: center;
  }
  
  .info-row.full-width {
    flex-direction: column;
    align-items: flex-start;
  }
  
  .info-row .label {
    color: var(--text-muted);
    font-size: 0.85rem;
    min-width: 80px;
  }
  
  .info-row .value {
    font-family: monospace;
    padding: 4px 8px;
    background: var(--bg-card);
    border-radius: 4px;
    font-size: 0.85rem;
  }
  
  .info-row .value.url {
    word-break: break-all;
    width: 100%;
  }
  
  .info-row .value.clickable {
    cursor: pointer;
    transition: background 0.15s;
  }
  
  .info-row .value.clickable:hover {
    background: var(--primary);
    color: white;
  }
  
  .copy-hint {
    color: var(--text-muted2);
    font-size: 0.75rem;
  }
  
  .empty-result {
    text-align: center;
    padding: 40px;
    color: var(--text-muted);
  }
  
  .empty-icon {
    font-size: 2rem;
    margin-bottom: 8px;
  }
  
  .features-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 16px;
  }
  
  .feature {
    padding: 12px;
    background: var(--bg-input);
    border-radius: 8px;
  }
  
  .feature strong {
    display: block;
    margin-bottom: 4px;
  }
  
  .feature p {
    font-size: 0.85rem;
    color: var(--text-muted);
    margin: 0;
  }
  
  @media (max-width: 768px) {
    .services-grid {
      grid-template-columns: 1fr;
    }
  }
</style>
