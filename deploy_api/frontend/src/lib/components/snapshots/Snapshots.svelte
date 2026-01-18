<script>
  import { onMount } from 'svelte'
  import { snapshots, snapshotsStore } from '../../stores/app.js'
  import { toasts } from '../../stores/toast.js'
  import { api, apiStream } from '../../api/client.js'
  import { Card } from '@myorg/ui'
  import { Button } from '@myorg/ui'
  import { Badge } from '@myorg/ui'
  import { Modal } from '@myorg/ui'
  
  let loading = false
  let baseSnapshotStatus = null
  let registryStatus = null
  let buildModalOpen = false
  let buildProgress = 0
  let buildLogs = []
  let building = false
  
  // Subscribe to store loading state
  $: storeState = $snapshotsStore || { loading: false }
  $: loading = storeState.loading
  
  // Build form
  let snapshotName = ''
  let baseImage = 'ubuntu-22-04-x64'
  let installDocker = true
  let installNginx = true
  let installCertbot = true
  
  const baseImages = [
    { value: 'ubuntu-22-04-x64', label: 'Ubuntu 22.04 LTS' },
    { value: 'ubuntu-20-04-x64', label: 'Ubuntu 20.04 LTS' },
    { value: 'debian-11-x64', label: 'Debian 11' },
    { value: 'debian-12-x64', label: 'Debian 12' }
  ]
  
  onMount(() => {
    // SWR store handles initial fetch
    checkBaseSnapshot()
    checkRegistry()
  })
  
  function loadSnapshots() {
    snapshotsStore.refresh()
  }
  
  async function checkBaseSnapshot() {
    try {
      const data = await api('GET', '/infra/setup/status')
      baseSnapshotStatus = data
    } catch (err) {
      baseSnapshotStatus = { exists: false, error: err.message }
    }
  }
  
  async function checkRegistry() {
    try {
      const data = await api('GET', '/infra/registry')
      registryStatus = data
    } catch (err) {
      registryStatus = { exists: false, error: err.message }
    }
  }
  
  async function createBaseSnapshot() {
    building = true
    buildProgress = 0
    buildLogs = []
    
    try {
      buildLogs.push({ message: '🚀 Creating base snapshot...', type: 'info' })
      buildProgress = 5
      
      await apiStream('POST', '/infra/setup/init/stream', {}, (msg) => {
        if (msg.message) {
          buildLogs.push({ message: msg.message, type: msg.type || 'info' })
          buildLogs = buildLogs // trigger reactivity
        }
        if (msg.progress) {
          buildProgress = msg.progress
        }
        if (msg.type === 'done' || msg.type === 'complete') {
          buildProgress = 100
        }
      })
      
      buildLogs.push({ message: '✅ Base snapshot created successfully', type: 'success' })
      toasts.success('Base snapshot created!')
      await checkBaseSnapshot()
      await loadSnapshots()
      
    } catch (err) {
      buildLogs.push({ message: `❌ Error: ${err.message}`, type: 'error' })
      toasts.error('Failed to create base snapshot: ' + err.message)
    } finally {
      building = false
    }
  }
  
  async function buildCustomSnapshot() {
    if (!snapshotName) {
      toasts.error('Snapshot name is required')
      return
    }
    
    building = true
    buildProgress = 0
    buildLogs = []
    
    try {
      buildLogs.push({ message: `Building snapshot: ${snapshotName}`, type: 'info' })
      buildProgress = 10
      
      const result = await api('POST', '/infra/snapshots/build', {
        name: snapshotName,
        base_image: baseImage,
        install_docker: installDocker,
        install_nginx: installNginx,
        install_certbot: installCertbot
      })
      
      buildProgress = 100
      buildLogs.push({ message: '✅ Snapshot created successfully', type: 'success' })
      toasts.success('Snapshot created!')
      
      await loadSnapshots()
      buildModalOpen = false
    } catch (err) {
      buildLogs.push({ message: `❌ Error: ${err.message}`, type: 'error' })
      toasts.error(err.message)
    } finally {
      building = false
    }
  }
  
  async function deleteSnapshot(id, name) {
    if (!confirm(`Delete snapshot "${name}"? This cannot be undone.`)) return
    
    try {
      await api('DELETE', `/infra/snapshots/${id}`)
      toasts.success('Snapshot deleted')
      await loadSnapshots()
    } catch (err) {
      toasts.error('Failed to delete snapshot: ' + err.message)
    }
  }
  
  function formatDate(dateStr) {
    if (!dateStr) return '-'
    return new Date(dateStr).toLocaleDateString()
  }
  
  function formatSize(sizeGb) {
    if (!sizeGb) return '-'
    return `${sizeGb} GB`
  }
</script>

<div class="snapshots-page">
  <div class="snapshots-grid">
    <!-- Your Snapshots -->
    <Card title="📸 Your Snapshots">
      <Button slot="header" variant="success" size="sm" on:click={() => buildModalOpen = true}>
        + Custom
      </Button>
      
      {#if loading}
        <div class="empty-state">Loading...</div>
      {:else if !$snapshots || $snapshots.length === 0}
        <div class="empty-state">No snapshots found</div>
      {:else}
        <div class="snapshot-list">
          {#each $snapshots as snapshot}
            <div class="snapshot-item">
              <div class="snapshot-info">
                <div class="snapshot-name">{snapshot.name}</div>
                <div class="snapshot-meta">
                  <span>{formatDate(snapshot.created_at)}</span>
                  <span>•</span>
                  <span>{formatSize(snapshot.size_gigabytes)}</span>
                  <span>•</span>
                  <span>{snapshot.regions?.join(', ') || '-'}</span>
                </div>
              </div>
              <div class="snapshot-actions">
                <Button variant="danger" size="sm" on:click={() => deleteSnapshot(snapshot.id, snapshot.name)}>
                  🗑️
                </Button>
              </div>
            </div>
          {/each}
        </div>
      {/if}
      
      <div class="card-footer">
        <Button variant="ghost" size="sm" on:click={loadSnapshots}>↻ Refresh</Button>
      </div>
    </Card>
    
    <div class="right-column">
      <!-- Base Snapshot Status -->
      <Card title="🏗️ Base Snapshot">
        {#if baseSnapshotStatus === null}
          <div class="status-checking">Checking...</div>
        {:else if baseSnapshotStatus.exists}
          <div class="status-ok">
            <Badge variant="success">✓ Ready</Badge>
            <div class="status-details">
              <div>Name: {baseSnapshotStatus.name}</div>
              <div>Created: {formatDate(baseSnapshotStatus.created_at)}</div>
            </div>
          </div>
        {:else}
          <div class="status-missing">
            <Badge variant="warning">Not found</Badge>
            <p>Base snapshot is required for provisioning new servers.</p>
            <Button variant="primary" on:click={createBaseSnapshot}>Create Base Snapshot</Button>
          </div>
        {/if}
      </Card>
      
      <!-- Registry Status -->
      <Card title="📦 App Registry (DO)">
        {#if registryStatus === null}
          <div class="status-checking">Checking...</div>
        {:else if registryStatus.exists}
          <div class="status-ok">
            <Badge variant="success">✓ Connected</Badge>
            <div class="status-details">
              <div>Name: {registryStatus.name}</div>
              <div>Region: {registryStatus.region}</div>
            </div>
          </div>
        {:else}
          <div class="status-missing">
            <Badge variant="info">Not configured</Badge>
            <p>Optional: Use DO Container Registry for private images.</p>
          </div>
        {/if}
      </Card>
      
      <!-- Build Progress -->
      {#if buildLogs.length > 0}
        <Card title="📋 Progress">
          <div class="progress-bar">
            <div class="progress-fill" style="width: {buildProgress}%"></div>
          </div>
          <div class="log-container">
            {#each buildLogs as log}
              <div class="log-line {log.type}">{log.message}</div>
            {/each}
          </div>
        </Card>
      {/if}
    </div>
  </div>
</div>

<!-- Build Modal -->
<Modal 
  bind:open={buildModalOpen}
  title="Build Custom Snapshot"
  width="500px"
  on:close={() => buildModalOpen = false}
>
  <form on:submit|preventDefault={buildCustomSnapshot}>
    <div class="form-group">
      <label for="snap-name">Snapshot Name *</label>
      <input 
        id="snap-name"
        type="text" 
        bind:value={snapshotName}
        placeholder="my-base-snapshot"
        required
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
          <input type="checkbox" bind:checked={installDocker}>
          Docker
        </label>
        <label class="checkbox-item">
          <input type="checkbox" bind:checked={installNginx}>
          Nginx
        </label>
        <label class="checkbox-item">
          <input type="checkbox" bind:checked={installCertbot}>
          Certbot (SSL)
        </label>
      </div>
    </div>
  </form>
  
  <div slot="footer">
    <Button variant="ghost" on:click={() => buildModalOpen = false}>Cancel</Button>
    <Button variant="primary" on:click={buildCustomSnapshot} disabled={building}>
      {#if building}Building...{:else}🔨 Build Snapshot{/if}
    </Button>
  </div>
</Modal>

<style>
  .snapshots-page {
    padding: 0;
  }
  
  .snapshots-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
  }
  
  .right-column {
    display: flex;
    flex-direction: column;
    gap: 16px;
  }
  
  .empty-state {
    text-align: center;
    padding: 40px;
    color: var(--text-muted);
  }
  
  .snapshot-list {
    display: flex;
    flex-direction: column;
  }
  
  .snapshot-item {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 12px 0;
    border-bottom: 1px solid var(--border);
  }
  
  .snapshot-item:last-child {
    border-bottom: none;
  }
  
  .snapshot-name {
    font-weight: 600;
    margin-bottom: 4px;
  }
  
  .snapshot-meta {
    font-size: 0.75rem;
    color: var(--text-muted);
    display: flex;
    gap: 8px;
  }
  
  .card-footer {
    margin-top: 12px;
  }
  
  .status-checking {
    color: var(--text-muted);
    padding: 8px 0;
  }
  
  .status-ok {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  
  .status-details {
    font-size: 0.85rem;
    color: var(--text-muted);
  }
  
  .status-missing {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  
  .status-missing p {
    color: var(--text-muted);
    font-size: 0.875rem;
    margin: 0;
  }
  
  .progress-bar {
    height: 6px;
    background: var(--border);
    border-radius: 3px;
    overflow: hidden;
    margin-bottom: 12px;
  }
  
  .progress-fill {
    height: 100%;
    background: linear-gradient(90deg, var(--primary), var(--primary2));
    transition: width 0.3s;
  }
  
  .log-container {
    background: rgba(0,0,0,.3);
    border-radius: 8px;
    padding: 12px;
    max-height: 200px;
    overflow-y: auto;
    font-family: monospace;
    font-size: 0.8rem;
  }
  
  .log-line {
    margin-bottom: 4px;
  }
  
  .log-line.success { color: var(--success); }
  .log-line.error { color: var(--danger); }
  
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
    padding: 10px 12px;
    background: var(--bg-input);
    border: 1px solid var(--border);
    border-radius: 12px;
    color: var(--text);
    font-size: 0.875rem;
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
  
  @media (max-width: 768px) {
    .snapshots-grid {
      grid-template-columns: 1fr;
    }
  }
</style>
