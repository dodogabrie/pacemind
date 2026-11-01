<template>
  <Teleport to="body">
    <div class="toast-host" role="region" aria-live="polite">
      <TransitionGroup name="toast">
        <div
          v-for="toast in toastStore.toasts"
          :key="toast.id"
          class="toast"
          :class="`toast--${toast.type}`"
          role="status"
        >
          <div class="toast-body">
            <p v-if="toast.title" class="toast-title">{{ toast.title }}</p>
            <p class="toast-message">{{ toast.message }}</p>
            <button
              v-if="toast.action"
              class="toast-action"
              @click="runAction(toast)"
            >{{ toast.action.label }}</button>
          </div>
          <button
            class="toast-close"
            :aria-label="$t('common.buttons.close')"
            @click="toastStore.dismiss(toast.id)"
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12"/></svg>
          </button>
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>

<script setup>
import { useToastStore } from '../stores/toast'

const toastStore = useToastStore()

const runAction = (toast) => {
  try {
    toast.action.handler()
  } finally {
    toastStore.dismiss(toast.id)
  }
}
</script>

<style scoped>
.toast-host {
  position: fixed;
  bottom: calc(1.25rem + env(safe-area-inset-bottom));
  right: 1.25rem;
  z-index: 200;
  display: flex;
  flex-direction: column;
  gap: .5rem;
  max-width: min(24rem, calc(100vw - 2.5rem));
  pointer-events: none;
}
.toast {
  pointer-events: auto;
  display: flex;
  align-items: flex-start;
  gap: .75rem;
  padding: .75rem .875rem;
  border-radius: .625rem;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-left: 3px solid #64748b;
  box-shadow: 0 10px 25px -5px rgb(15 23 42 / .18);
}
.toast--warning { border-left-color: #f59e0b; }
.toast--error { border-left-color: #e11d48; }
.toast--info { border-left-color: #059669; }
.toast-body { flex: 1; min-width: 0; }
.toast-title {
  margin: 0 0 .125rem;
  font-size: .8125rem;
  font-weight: 700;
  color: #0f172a;
}
.toast-message {
  margin: 0;
  font-size: .8125rem;
  line-height: 1.35;
  color: #475569;
}
.toast-action {
  margin-top: .5rem;
  font-size: .75rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .04em;
  color: #047857;
  background: none;
  border: none;
  padding: 0;
  cursor: pointer;
}
@media (max-width: 639px) {
  /* Full-width bottom sheet style on phones: never under the sticky nav. */
  .toast-host { left: .75rem; right: .75rem; bottom: calc(.75rem + env(safe-area-inset-bottom)); max-width: none; }
}
.toast-action { padding: .375rem 0; }
.toast-action:hover { color: #065f46; text-decoration: underline; }
.toast-close {
  flex-shrink: 0;
  margin: -.5rem -.5rem -.5rem 0; /* 30px+ hit area without growing the toast */
  background: none;
  border: none;
  color: #94a3b8;
  cursor: pointer;
  padding: .5rem;
  line-height: 0;
}
.toast-close:hover { color: #475569; }

.toast-enter-active, .toast-leave-active { transition: all .22s ease; }
.toast-enter-from, .toast-leave-to { opacity: 0; transform: translateY(8px); }
.toast-leave-active { position: absolute; }
</style>
