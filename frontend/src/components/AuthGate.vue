<template>
  <div class="auth-gate" :class="overlay ? 'auth-gate--overlay' : 'auth-gate--block'">
    <div class="auth-gate-card">
      <div class="auth-gate-icon">
        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.75" stroke="currentColor" class="w-6 h-6">
          <path stroke-linecap="round" stroke-linejoin="round" d="M16.5 10.5V7.875a4.125 4.125 0 10-8.25 0V10.5m-.75 0h9a2.25 2.25 0 012.25 2.25v5.25A2.25 2.25 0 0116.5 20.25h-9a2.25 2.25 0 01-2.25-2.25v-5.25A2.25 2.25 0 017.5 10.5z" />
        </svg>
      </div>

      <!-- "check your inbox" confirmation -->
      <template v-if="sent">
        <h2 class="auth-gate-title">{{ $t('auth.signin.sent_title') }}</h2>
        <p class="auth-gate-text">{{ $t('auth.signin.sent_text', { email }) }}</p>
        <button type="button" class="auth-gate-link" @click="reset">
          {{ $t('auth.signin.resend') }}
        </button>
      </template>

      <template v-else>
        <h2 class="auth-gate-title">{{ title || $t('auth.gate.title') }}</h2>
        <p class="auth-gate-text">{{ text || $t('auth.gate.text') }}</p>

        <!-- Primary: email magic link -->
        <form class="auth-gate-form" novalidate @submit.prevent="submitEmail">
          <label class="auth-gate-label" :for="emailId">{{ $t('auth.signin.email_label') }}</label>
          <input
            :id="emailId"
            ref="emailInput"
            v-model.trim="email"
            type="email"
            name="email"
            autocomplete="email"
            required
            :placeholder="$t('auth.signin.email_placeholder')"
            :aria-invalid="error ? 'true' : 'false'"
            :aria-describedby="error ? errorId : undefined"
            class="auth-gate-input"
          />
          <button type="submit" class="auth-gate-btn" :disabled="sending">
            {{ sending ? $t('auth.signin.sending') : $t('auth.signin.submit') }}
          </button>
        </form>

        <div class="auth-gate-sep"><span>{{ $t('auth.signin.or') }}</span></div>

        <!-- Secondary: Strava OAuth (also the "link a connection" entry point) -->
        <button type="button" class="auth-gate-btn-secondary" :disabled="connecting" @click="connect">
          {{ connecting ? $t('common.loading') : $t('auth.signin.strava') }}
        </button>
      </template>

      <p v-if="error" :id="errorId" class="auth-gate-error" role="alert">{{ error }}</p>
    </div>
  </div>
</template>

<script setup>
import { ref, useId } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '../stores/auth'
import { useToastStore } from '../stores/toast'

defineProps({
  /** Headline; falls back to the generic auth.gate copy. */
  title: { type: String, default: '' },
  /** Body copy explaining what this particular screen needs the login for. */
  text: { type: String, default: '' },
  /** Absolutely-position over the parent (parent must be `relative`). */
  overlay: { type: Boolean, default: false }
})

const { t } = useI18n()
const authStore = useAuthStore()
const toastStore = useToastStore()
const emailId = useId()
const errorId = useId()

const email = ref('')
const emailInput = ref(null)
const sending = ref(false)
const sent = ref(false)
const connecting = ref(false)
const error = ref('')

// ponytail: same shape the browser's type=email uses; swap for a server-side
// check if we ever need stricter validation than "looks like an address".
const looksLikeEmail = (value) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)

const submitEmail = async () => {
  error.value = ''
  if (!looksLikeEmail(email.value)) {
    error.value = t('auth.signin.invalid_email')
    emailInput.value?.focus()
    return
  }
  sending.value = true
  try {
    await authStore.requestMagicLink(email.value)
    sent.value = true
    toastStore.push({ key: 'magic-link', message: t('auth.signin.sent_toast') })
  } catch (err) {
    error.value = t('auth.signin.error')
  } finally {
    sending.value = false
  }
}

const reset = () => {
  sent.value = false
  error.value = ''
}

const connect = async () => {
  connecting.value = true
  error.value = ''
  try {
    window.location.href = await authStore.getStravaAuthUrl()
  } catch (err) {
    connecting.value = false
    error.value = t('auth.gate.error')
  }
}
</script>

<style scoped>
.auth-gate--overlay {
  position: absolute;
  inset: 0;
  z-index: 20;
  background: rgb(255 255 255 / .82);
  backdrop-filter: blur(4px);
}
.auth-gate--block {
  min-height: 60vh;
}
.auth-gate {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 2rem 1.5rem;
  text-align: center;
}
.auth-gate-card { max-width: 26rem; width: 100%; }
.auth-gate-icon {
  width: 3rem;
  height: 3rem;
  margin: 0 auto 1rem;
  border-radius: 9999px;
  background: #d1fae5;
  color: #047857;
  display: flex;
  align-items: center;
  justify-content: center;
}
.auth-gate-icon svg { width: 1.5rem; height: 1.5rem; }
.auth-gate-title {
  margin: 0 0 .5rem;
  font-size: 1.125rem;
  font-weight: 700;
  color: #064e3b;
}
.auth-gate-text {
  margin: 0 0 1.25rem;
  font-size: .875rem;
  line-height: 1.5;
  color: #334155;
}
.auth-gate-form {
  display: flex;
  flex-direction: column;
  gap: .5rem;
  text-align: left;
}
.auth-gate-label {
  font-size: .75rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .05em;
  color: #64748b;
}
.auth-gate-input {
  width: 100%;
  padding: .6rem .75rem;
  border: 1px solid #cbd5e1;
  border-radius: .5rem;
  font-size: 1rem; /* <16px makes iOS Safari zoom the page on focus */
  color: #0f172a;
}
.auth-gate-input:focus {
  outline: 2px solid #047857;
  outline-offset: 1px;
  border-color: #047857;
}
.auth-gate-btn {
  width: 100%;
  padding: .7rem 1rem;
  border: none;
  border-radius: .5rem;
  background: #047857;
  color: #fff;
  font-weight: 700;
  font-size: .875rem;
  cursor: pointer;
  transition: background-color .15s ease;
}
.auth-gate-btn:hover:not(:disabled) { background: #065f46; }
.auth-gate-btn:disabled { opacity: .6; cursor: default; }
.auth-gate-sep {
  display: flex;
  align-items: center;
  gap: .75rem;
  margin: 1rem 0;
  font-size: .75rem;
  text-transform: uppercase;
  letter-spacing: .08em;
  color: #94a3b8;
}
.auth-gate-sep::before,
.auth-gate-sep::after {
  content: '';
  flex: 1;
  height: 1px;
  background: #e2e8f0;
}
.auth-gate-btn-secondary {
  width: 100%;
  padding: .7rem 1rem;
  border: 1px solid #cbd5e1;
  border-radius: .5rem;
  background: #fff;
  color: #334155;
  font-weight: 600;
  font-size: .875rem;
  cursor: pointer;
  transition: border-color .15s ease, color .15s ease;
}
.auth-gate-btn-secondary:hover:not(:disabled) { border-color: #FC4C02; color: #FC4C02; }
.auth-gate-btn-secondary:disabled { opacity: .6; cursor: default; }
.auth-gate-link {
  margin-top: .25rem;
  border: none;
  background: none;
  padding: 0;
  font-size: .8125rem;
  font-weight: 600;
  color: #047857;
  cursor: pointer;
  text-decoration: underline;
}
.auth-gate-error {
  margin: .75rem 0 0;
  font-size: .8125rem;
  color: #be123c;
}
</style>
