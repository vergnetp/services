<script>
  import { auth } from '../../stores/auth.js'
  import Button from './Button.svelte'
  
  export let title = 'Deploy Dashboard'
  
  function logout() {
    auth.logout()
  }
</script>

<header class="header glass">
  <h1>
    <span class="brand-dot"></span>
    {title}
  </h1>
  <div class="header-actions">
    {#if $auth.user}
      <span class="user-email">{$auth.user.email}</span>
    {/if}
    <Button variant="ghost" size="sm" on:click={logout}>Logout</Button>
  </div>
</header>

<style>
  .header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 16px 24px;
    margin-bottom: 16px;
    gap: 16px;
  }
  
  h1 {
    margin: 0;
    font-size: 1.25rem;
    font-weight: 800;
    display: flex;
    align-items: center;
    gap: 10px;
    white-space: nowrap;
  }
  
  .brand-dot {
    width: 10px;
    height: 10px;
    border-radius: 999px;
    background: linear-gradient(180deg, var(--primary), var(--primary2));
    box-shadow: 0 0 0 4px rgba(109,92,255,.18);
    flex-shrink: 0;
  }
  
  .header-actions {
    display: flex;
    gap: 12px;
    align-items: center;
  }
  
  .user-email {
    color: var(--text-muted);
    font-size: 0.875rem;
  }
  
  @media (max-width: 640px) {
    .header {
      flex-direction: column;
      padding: 12px 16px;
      gap: 12px;
    }
    
    h1 {
      font-size: 1.1rem;
    }
    
    .user-email {
      display: none;
    }
  }
</style>
