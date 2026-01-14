<script>
  import { createEventDispatcher } from 'svelte'
  import { scope, projects, servers, containers, containersStore } from '../../stores/app.js'

  export let showTail = false
  export let showContainer = false

  const dispatch = createEventDispatcher()

  function setScope(key, value) {
    scope.update(s => ({ ...s, [key]: value }))
    dispatch('change')
  }

  function handleServerChange(value) {
    // Reset container when server changes
    scope.update(s => ({ ...s, server: value, container: '' }))
    dispatch('change')
  }

  function toggleTail(checked) {
    scope.update(s => ({ ...s, tail: checked }))
    dispatch('change')
  }

  // Fetch containers when server changes
  $: if ($scope.server) {
    containersStore.fetch({ server: $scope.server })
  } else {
    containersStore.clear()
    // ensure container reset via store update (do NOT mutate $scope)
    if ($scope.container) scope.update(s => ({ ...s, container: '' }))
  }

  function refresh() {
    dispatch('refresh')
  }
</script>


<div class="scope-bar glass">
  <div class="scope-bar-inner">
    <div class="scope-brand">
      <span class="brand-dot"></span>
      <span>cc</span>
    </div>
    
    <div class="scope-field">
      <label>Project:</label>
      <select value={$scope.project} on:change={(e)=>setScope("project", e.target.value)}>
        <option value="">All</option>
        {#each $projects || [] as project}
          <option value={project}>{project}</option>
        {/each}
      </select>
    </div>
    
    <div class="scope-field">
      <label>Env:</label>
      <select value={$scope.env} on:change={(e)=>setScope("env", e.target.value)}>
        <option value="">All</option>
        <option value="prod">prod</option>
        <option value="staging">staging</option>
        <option value="dev">dev</option>
      </select>
    </div>
    
    <div class="scope-field">
      <label>Server:</label>
      <select value={$scope.server} on:change={(e)=>handleServerChange(e.target.value)}>
        <option value="">(Fleet)</option>
        {#each $servers || [] as server}
          {@const ip = server.ip || server.networks?.v4?.[0]?.ip_address}
          {#if ip}
            <option value={ip}>{server.name || 'unnamed'} ({ip})</option>
          {/if}
        {/each}
      </select>
    </div>
    
    {#if showContainer && $scope.server}
      <div class="scope-field">
        <label>Container:</label>
        <select value={$scope.container} on:change={(e)=>setScope("container", e.target.value)}>
          <option value="">(All)</option>
          {#each $containers || [] as container}
            <option value={container.name}>{container.name}</option>
          {/each}
        </select>
      </div>
    {/if}
    
    <div class="scope-field">
      <label>Last</label>
      <select value={$scope.range} on:change={(e)=>setScope("range", e.target.value)}>
        <option value="15m">15m</option>
        <option value="1h">1h</option>
        <option value="6h">6h</option>
        <option value="24h">24h</option>
        <option value="7d">7d</option>
        <option value="30d">30d</option>
      </select>
    </div>
    
    <button class="iconbtn" on:click={refresh} title="Refresh">
      <svg viewBox="0 0 24 24" fill="none">
        <path d="M20 12a8 8 0 1 1-2.34-5.66" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
        <path d="M20 4v6h-6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
    </button>
  </div>
  
  {#if showTail}
    <label class="tail-toggle">
      <input type="checkbox" checked={$scope.tail} on:change={(e)=>toggleTail(e.target.checked)}>
      Tail
    </label>
  {/if}
</div>

<style>
  .scope-bar {
    padding: 12px 16px;
    margin-bottom: 16px;
    display: flex;
    gap: 16px;
    align-items: center;
    flex-wrap: wrap;
    position: sticky;
    top: 10px;
    z-index: 100;
  }
  
  .scope-bar-inner {
    display: flex;
    align-items: center;
    gap: 8px;
    background: var(--scope-bg);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 8px 12px;
    flex-wrap: wrap;
    flex: 1;
  }
  
  .scope-brand {
    display: flex;
    align-items: center;
    gap: 8px;
    color: var(--primary);
    font-weight: 800;
    letter-spacing: .2px;
    padding: 0 6px 0 2px;
  }
  
  .brand-dot {
    width: 8px;
    height: 8px;
    border-radius: 999px;
    background: linear-gradient(180deg, var(--primary), var(--primary2));
    box-shadow: 0 0 0 3px rgba(109,92,255,.18);
  }
  
  .scope-field {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 6px 10px;
    border-radius: 12px;
    background: var(--field-bg);
    border: 1px solid var(--field-border);
  }
  
  .scope-field label {
    font-size: 12px;
    color: var(--text-muted2);
    white-space: nowrap;
  }
  
  .scope-field select {
    min-width: 70px;
    border: none;
    background: transparent;
    font-weight: 650;
    font-size: 13px;
    color: var(--text);
    cursor: pointer;
    padding: 2px 0;
  }
  
  .scope-field select:focus {
    outline: none;
  }
  
  .iconbtn {
    height: 36px;
    width: 36px;
    border-radius: 10px;
    border: 1px solid var(--border);
    background: var(--iconbtn-bg);
    color: var(--iconbtn-text);
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    transition: all 0.15s;
  }
  
  .iconbtn:hover {
    background: var(--btn-bg-hover);
    border-color: var(--border2);
  }
  
  .iconbtn svg {
    width: 16px;
    height: 16px;
  }
  
  .tail-toggle {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 0.85rem;
    color: var(--text-muted);
    cursor: pointer;
    margin-left: auto;
  }
  
  .tail-toggle input {
    width: auto;
  }
  
  @media (max-width: 768px) {
    .scope-bar {
      padding: 10px 12px;
    }
    
    .scope-bar-inner {
      padding: 6px 10px;
      gap: 6px;
    }
    
    .scope-brand {
      display: none;
    }
    
    .scope-field {
      padding: 4px 8px;
    }
    
    .scope-field label {
      display: none;
    }
    
    .scope-field select {
      font-size: 12px;
      min-width: 60px;
    }
  }
</style>