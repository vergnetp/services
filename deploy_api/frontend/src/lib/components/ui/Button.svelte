<script>
  export let variant = 'default' // default, primary, success, danger, warning, ghost
  export let size = 'md' // sm, md, lg
  export let disabled = false
  export let loading = false
  export let type = 'button'
  export let href = null
</script>

{#if href}
  <a 
    {href}
    class="btn btn-{variant} btn-{size}"
    class:disabled
    on:click
  >
    {#if loading}
      <span class="spinner"></span>
    {/if}
    <slot />
  </a>
{:else}
  <button
    {type}
    class="btn btn-{variant} btn-{size}"
    {disabled}
    on:click
  >
    {#if loading}
      <span class="spinner"></span>
    {/if}
    <slot />
  </button>
{/if}

<style>
  .btn {
    padding: 10px 16px;
    border: 1px solid var(--border);
    border-radius: 14px;
    font-size: 0.875rem;
    font-weight: 650;
    cursor: pointer;
    transition: all 0.2s;
    background: var(--btn-bg);
    color: var(--text);
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    text-decoration: none;
    white-space: nowrap;
  }
  
  .btn:hover:not(:disabled) {
    background: var(--btn-bg-hover);
    border-color: var(--border2);
  }
  
  .btn-primary {
    background: linear-gradient(135deg, var(--primary), var(--primary2));
    border-color: rgba(109,92,255,.35);
    color: white;
    box-shadow: 0 8px 24px rgba(99,102,241,.25);
  }
  .btn-primary:hover:not(:disabled) {
    filter: brightness(1.05);
    background: linear-gradient(135deg, var(--primary), var(--primary2));
  }
  
  .btn-success {
    background: rgba(54,211,124,.15);
    border-color: rgba(54,211,124,.35);
    color: var(--success);
  }
  .btn-success:hover:not(:disabled) {
    background: rgba(54,211,124,.25);
  }
  
  .btn-danger {
    background: rgba(255,77,94,.12);
    border-color: rgba(255,77,94,.35);
    color: var(--btn-danger-text);
  }
  .btn-danger:hover:not(:disabled) {
    background: rgba(255,77,94,.18);
  }
  
  .btn-warning {
    background: rgba(245,158,11,.15);
    border-color: rgba(245,158,11,.35);
    color: var(--warning);
  }
  .btn-warning:hover:not(:disabled) {
    background: rgba(245,158,11,.25);
  }
  
  .btn-ghost {
    background: var(--btn-ghost-bg);
    border: 1px solid var(--border);
    color: var(--text-muted);
  }
  .btn-ghost:hover:not(:disabled) {
    background: var(--bg-input);
    border-color: var(--border2);
  }
  
  .btn-sm {
    padding: 6px 14px;
    font-size: 0.75rem;
    height: 36px;
  }
  
  .btn-lg {
    padding: 14px 24px;
    font-size: 1rem;
  }
  
  .btn:disabled, .btn.disabled {
    opacity: 0.5;
    cursor: not-allowed;
    pointer-events: none;
  }
  
  .spinner {
    width: 16px;
    height: 16px;
    border: 2px solid currentColor;
    border-top-color: transparent;
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }
  
  @keyframes spin {
    to { transform: rotate(360deg); }
  }
</style>
