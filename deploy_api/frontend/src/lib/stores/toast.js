import { writable } from 'svelte/store'

function createToastStore() {
  const { subscribe, update } = writable([])
  
  let id = 0
  
  function add(message, type = 'info', duration = 3000) {
    const toast = { id: ++id, message, type }
    update(toasts => [...toasts, toast])
    
    if (duration > 0) {
      setTimeout(() => remove(toast.id), duration)
    }
    
    return toast.id
  }
  
  function remove(id) {
    update(toasts => toasts.filter(t => t.id !== id))
  }
  
  return {
    subscribe,
    success: (msg, duration) => add(msg, 'success', duration),
    error: (msg, duration) => add(msg, 'error', duration),
    warning: (msg, duration) => add(msg, 'warning', duration),
    info: (msg, duration) => add(msg, 'info', duration),
    remove
  }
}

export const toasts = createToastStore()
