<template>
  <!-- Inline prominent mode (default on prediction page) -->
  <div v-if="prominent" class="agent-prominent">
    <!-- Collapsed bar -->
    <button v-if="!isOpen" @click="isOpen = true" class="agent-collapsed-bar">
      <div class="agent-collapsed-left">
        <div class="agent-avatar-lg">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 2L14.5 9.5L22 12L14.5 14.5L12 22L9.5 14.5L2 12L9.5 9.5L12 2Z"/>
          </svg>
        </div>
        <div class="agent-collapsed-text">
          <span class="agent-collapsed-title">
            <span class="agent-ai-badge">{{ $t('agentChat.badge') }}</span>
            {{ $t('agentChat.title') }}
          </span>
          <span class="agent-collapsed-hint">{{ $t('agentChat.collapsed_hint') }}</span>
        </div>
      </div>
      <span class="agent-collapsed-cta">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="display:inline;vertical-align:-2px;margin-right:4px"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
        {{ $t('agentChat.ask') }}
      </span>
    </button>

    <!-- Expanded panel -->
    <div v-else class="agent-panel-prominent">
      <div class="agent-header-prominent">
        <div class="agent-header-left">
          <div class="agent-avatar-lg">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
              <path d="M12 2L14.5 9.5L22 12L14.5 14.5L12 22L9.5 14.5L2 12L9.5 9.5L12 2Z"/>
            </svg>
          </div>
          <div>
            <h3 class="agent-header-title"><span class="agent-ai-badge">{{ $t('agentChat.badge') }}</span> {{ $t('agentChat.title') }}</h3>
            <p class="agent-header-sub">{{ $t('agentChat.header_sub') }}</p>
          </div>
        </div>
        <div class="flex items-center gap-1 agent-header-actions">
          <button
            v-if="historyEnabled"
            @click="toggleHistory"
            class="agent-header-btn"
            :class="{ 'agent-header-btn--active': historyOpen }"
            :title="$t('agentChat.history')"
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l3 2"/>
            </svg>
          </button>
          <button @click="resetChat" class="agent-header-btn" :title="$t('agentChat.new_chat')">
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M12 5v14M5 12h14"/>
            </svg>
          </button>
          <div v-if="historyOpen && historyEnabled" class="agent-history-pop">
            <div class="agent-history-head">
              <span>{{ $t('agentChat.past_chats') }}</span>
              <button class="agent-history-close" @click="historyOpen = false" :title="$t('common.buttons.close')">×</button>
            </div>
            <div v-if="historyLoading" class="agent-history-empty">{{ $t('common.loading') }}</div>
            <div v-else-if="!historyItems.length" class="agent-history-empty">{{ $t('agentChat.no_chats') }}</div>
            <ul v-else class="agent-history-list">
              <li
                v-for="c in historyItems"
                :key="c.conversation_id"
                class="agent-history-item"
                :class="{ 'agent-history-item--current': c.conversation_id === conversationId }"
              >
                <button class="agent-history-row" @click="resumeConversation(c.conversation_id)">
                  <span class="agent-history-title">{{ c.title || $t('agentChat.untitled') }}</span>
                  <span class="agent-history-meta">
                    {{ formatHistoryDate(c.last_active_at) }} · {{ $t('agentChat.msg_count', { n: c.user_message_count }) }}
                  </span>
                </button>
                <button class="agent-history-del" @click.stop="deleteConversation(c.conversation_id)" :title="$t('agentChat.delete')">
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/></svg>
                </button>
              </li>
            </ul>
          </div>
          <button @click="isOpen = false" class="agent-header-btn" :title="$t('agentChat.minimize')">
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="18 15 12 9 6 15"/>
            </svg>
          </button>
        </div>
      </div>

      <!-- Quick action chips (only when no user messages yet) -->
      <div v-if="messages.length <= 1" class="agent-quick-actions">
        <button v-for="q in quickActions" :key="q.label" @click="quickSend(q.prompt)" class="agent-chip">
          {{ q.label }}
        </button>
      </div>

      <div ref="messagesContainer" class="agent-messages-prominent">
        <template v-for="(msg, i) in messages" :key="i">
          <div v-if="msg.role === 'assistant'" class="agent-msg agent-msg-assistant">
            <div class="agent-msg-avatar">AI</div>
            <div class="agent-msg-body">
              <div class="assistant-content" v-html="renderMarkdown(msg.content)"></div>
              <div v-if="msg.toolCalls && msg.toolCalls.length" class="agent-tools">
                <details>
                  <summary class="text-xs text-slate-400 cursor-pointer hover:text-slate-600 transition-colors">
                    {{ $t('agentChat.tools_used', msg.toolCalls.length) }}
                  </summary>
                  <ul class="text-xs text-slate-400 mt-1 ml-3 list-disc">
                    <li v-for="(tc, j) in msg.toolCalls" :key="j">
                      <code class="text-xs">{{ tc.tool }}</code> &mdash; {{ tc.result_summary }}
                    </li>
                  </ul>
                </details>
              </div>
              <div v-if="msg.suggestions && msg.suggestions.length" class="suggestion-cards">
                <div class="suggestion-header">
                  <span class="text-xs font-semibold text-slate-600">{{ $t('agentChat.suggested_waypoints') }}</span>
                  <div v-if="hasPendingSuggestions(msg)" class="suggestion-actions">
                    <button @click="acceptAllSuggestions(msg)" class="suggestion-btn suggestion-btn-accept-all">{{ $t('agentChat.accept_all') }}</button>
                    <button @click="dismissAllSuggestions(msg)" class="suggestion-btn suggestion-btn-dismiss-all">{{ $t('agentChat.dismiss_all') }}</button>
                  </div>
                </div>
                <div v-for="(s, si) in msg.suggestions" :key="si"
                  class="suggestion-card"
                  :class="{
                    'suggestion-card--accepted': s.status === 'accepted',
                    'suggestion-card--dismissed': s.status === 'dismissed'
                  }"
                >
                  <div class="suggestion-card-top">
                    <span class="suggestion-badge" :style="{ background: WAYPOINT_COLORS[s.type] || '#8b5cf6' }">
                      {{ WAYPOINT_LABELS[s.type] ? $t(WAYPOINT_LABELS[s.type]) : s.type }}
                    </span>
                    <span class="suggestion-distance">km {{ s.distance_km }}</span>
                  </div>
                  <div class="suggestion-label">{{ s.label }}</div>
                  <div v-if="s.reason" class="suggestion-reason">{{ s.reason }}</div>
                  <div v-if="s.stop_time_seconds" class="suggestion-stop">{{ $t('agentChat.stop', { s: s.stop_time_seconds }) }}</div>
                  <div v-if="s.status === 'pending'" class="suggestion-card-actions">
                    <button @click="acceptSuggestion(msg, si)" class="suggestion-btn suggestion-btn-accept">{{ $t('agentChat.accept') }}</button>
                    <button @click="dismissSuggestion(msg, si)" class="suggestion-btn suggestion-btn-dismiss">{{ $t('agentChat.dismiss') }}</button>
                  </div>
                  <div v-else-if="s.status === 'accepted'" class="suggestion-status-text suggestion-status-accepted">{{ $t('agentChat.added') }}</div>
                  <div v-else class="suggestion-status-text suggestion-status-dismissed">{{ $t('agentChat.dismissed') }}</div>
                </div>
              </div>
            </div>
          </div>
          <div v-else class="agent-msg agent-msg-user">
            <div class="agent-msg-body">
              <p>{{ msg.content }}</p>
            </div>
          </div>
        </template>
        <div v-if="loading" class="agent-msg agent-msg-assistant">
          <div class="agent-msg-avatar">AI</div>
          <div class="agent-msg-body">
            <div class="tool-progress">
              <div v-for="t in displayedCompletedTools" :key="'done-'+t.tool" class="tool-status tool-done">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
                <span>{{ t.label }}</span>
              </div>
              <div v-for="t in activeTools" :key="'active-'+t.tool" class="tool-status tool-active">
                <span class="tool-dots"><span></span><span></span><span></span></span>
                <span>{{ t.label }}</span>
              </div>
              <div v-if="!activeTools.length" class="tool-status tool-active">
                <span class="tool-dots"><span></span><span></span><span></span></span>
                <span>{{ completedTools.length ? $t('agentChat.composing') : $t('agentChat.thinking') }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="agent-input-area-prominent">
        <form @submit.prevent="sendMessage" class="agent-input-row">
          <textarea
            ref="textareaRef"
            v-model="input"
            :placeholder="$t('agentChat.placeholder_race')"
            :disabled="loading"
            class="agent-input"
            maxlength="2000"
            rows="1"
            @input="resizeTextarea"
            @keydown="handleKeydown"
          ></textarea>
          <button
            type="submit"
            :disabled="loading || !input.trim()"
            class="agent-send"
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
              <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/>
            </svg>
          </button>
        </form>
        <div v-if="subscriptionStore.messagesRemaining !== null && subscriptionStore.messagesRemaining !== undefined" class="agent-remaining">
          {{ $t('agentChat.remaining', subscriptionStore.messagesRemaining) }}
        </div>
      </div>
    </div>
  </div>

  <!-- Floating bubble mode (other pages, embedded) -->
  <div v-else class="agent-chat" :class="{ 'agent-chat--embedded': embedded }">
    <button
      v-if="!embedded"
      @click="isOpen = !isOpen"
      class="agent-toggle"
      :class="{ 'agent-toggle-open': isOpen }"
    >
      <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
      </svg>
      <span>{{ $t('agentChat.title') }}</span>
    </button>

    <div v-if="isOpen || embedded" class="agent-panel" :class="{ 'agent-panel--embedded': embedded }">
      <div class="agent-header">
        <div class="flex items-center gap-2">
          <div class="agent-avatar">AI</div>
          <h3>{{ $t('agentChat.title') }}</h3>
        </div>
        <div class="flex items-center gap-1 agent-header-actions">
          <button
            v-if="historyEnabled"
            @click="toggleHistory"
            class="agent-header-btn"
            :class="{ 'agent-header-btn--active': historyOpen }"
            :title="$t('agentChat.history')"
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l3 2"/>
            </svg>
          </button>
          <button @click="resetChat" class="agent-header-btn" :title="$t('agentChat.new_chat')">
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M12 5v14M5 12h14"/>
            </svg>
          </button>
          <div v-if="historyOpen && historyEnabled" class="agent-history-pop">
            <div class="agent-history-head">
              <span>{{ $t('agentChat.past_chats') }}</span>
              <button class="agent-history-close" @click="historyOpen = false" :title="$t('common.buttons.close')">×</button>
            </div>
            <div v-if="historyLoading" class="agent-history-empty">{{ $t('common.loading') }}</div>
            <div v-else-if="!historyItems.length" class="agent-history-empty">{{ $t('agentChat.no_chats') }}</div>
            <ul v-else class="agent-history-list">
              <li
                v-for="c in historyItems"
                :key="c.conversation_id"
                class="agent-history-item"
                :class="{ 'agent-history-item--current': c.conversation_id === conversationId }"
              >
                <button class="agent-history-row" @click="resumeConversation(c.conversation_id)">
                  <span class="agent-history-title">{{ c.title || $t('agentChat.untitled') }}</span>
                  <span class="agent-history-meta">
                    {{ formatHistoryDate(c.last_active_at) }} · {{ $t('agentChat.msg_count', { n: c.user_message_count }) }}
                  </span>
                </button>
                <button class="agent-history-del" @click.stop="deleteConversation(c.conversation_id)" :title="$t('agentChat.delete')">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/></svg>
                </button>
              </li>
            </ul>
          </div>
          <button v-if="!embedded" @click="isOpen = false" class="agent-header-btn" :title="$t('common.buttons.close')">
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M18 6L6 18M6 6l12 12"/>
            </svg>
          </button>
        </div>
      </div>

      <div ref="messagesContainer" class="agent-messages">
        <template v-for="(msg, i) in messages" :key="i">
          <div v-if="msg.role === 'assistant'" class="agent-msg agent-msg-assistant">
            <div class="agent-msg-avatar">AI</div>
            <div class="agent-msg-body">
              <div class="assistant-content" v-html="renderMarkdown(msg.content)"></div>
              <div v-if="msg.toolCalls && msg.toolCalls.length" class="agent-tools">
                <details>
                  <summary class="text-xs text-slate-400 cursor-pointer hover:text-slate-600 transition-colors">
                    {{ $t('agentChat.tools_used', msg.toolCalls.length) }}
                  </summary>
                  <ul class="text-xs text-slate-400 mt-1 ml-3 list-disc">
                    <li v-for="(tc, j) in msg.toolCalls" :key="j">
                      <code class="text-xs">{{ tc.tool }}</code> &mdash; {{ tc.result_summary }}
                    </li>
                  </ul>
                </details>
              </div>
              <div v-if="msg.suggestions && msg.suggestions.length" class="suggestion-cards">
                <div class="suggestion-header">
                  <span class="text-xs font-semibold text-slate-600">{{ $t('agentChat.suggested_waypoints') }}</span>
                  <div v-if="hasPendingSuggestions(msg)" class="suggestion-actions">
                    <button @click="acceptAllSuggestions(msg)" class="suggestion-btn suggestion-btn-accept-all">{{ $t('agentChat.accept_all') }}</button>
                    <button @click="dismissAllSuggestions(msg)" class="suggestion-btn suggestion-btn-dismiss-all">{{ $t('agentChat.dismiss_all') }}</button>
                  </div>
                </div>
                <div v-for="(s, si) in msg.suggestions" :key="si"
                  class="suggestion-card"
                  :class="{
                    'suggestion-card--accepted': s.status === 'accepted',
                    'suggestion-card--dismissed': s.status === 'dismissed'
                  }"
                >
                  <div class="suggestion-card-top">
                    <span class="suggestion-badge" :style="{ background: WAYPOINT_COLORS[s.type] || '#8b5cf6' }">
                      {{ WAYPOINT_LABELS[s.type] ? $t(WAYPOINT_LABELS[s.type]) : s.type }}
                    </span>
                    <span class="suggestion-distance">km {{ s.distance_km }}</span>
                  </div>
                  <div class="suggestion-label">{{ s.label }}</div>
                  <div v-if="s.reason" class="suggestion-reason">{{ s.reason }}</div>
                  <div v-if="s.stop_time_seconds" class="suggestion-stop">{{ $t('agentChat.stop', { s: s.stop_time_seconds }) }}</div>
                  <div v-if="s.status === 'pending'" class="suggestion-card-actions">
                    <button @click="acceptSuggestion(msg, si)" class="suggestion-btn suggestion-btn-accept">{{ $t('agentChat.accept') }}</button>
                    <button @click="dismissSuggestion(msg, si)" class="suggestion-btn suggestion-btn-dismiss">{{ $t('agentChat.dismiss') }}</button>
                  </div>
                  <div v-else-if="s.status === 'accepted'" class="suggestion-status-text suggestion-status-accepted">{{ $t('agentChat.added') }}</div>
                  <div v-else class="suggestion-status-text suggestion-status-dismissed">{{ $t('agentChat.dismissed') }}</div>
                </div>
              </div>
            </div>
          </div>
          <div v-else class="agent-msg agent-msg-user">
            <div class="agent-msg-body">
              <p>{{ msg.content }}</p>
            </div>
          </div>
        </template>
        <div v-if="loading" class="agent-msg agent-msg-assistant">
          <div class="agent-msg-avatar">AI</div>
          <div class="agent-msg-body">
            <div class="tool-progress">
              <div v-for="t in displayedCompletedTools" :key="'done-'+t.tool" class="tool-status tool-done">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
                <span>{{ t.label }}</span>
              </div>
              <div v-for="t in activeTools" :key="'active-'+t.tool" class="tool-status tool-active">
                <span class="tool-dots"><span></span><span></span><span></span></span>
                <span>{{ t.label }}</span>
              </div>
              <div v-if="!activeTools.length" class="tool-status tool-active">
                <span class="tool-dots"><span></span><span></span><span></span></span>
                <span>{{ completedTools.length ? $t('agentChat.composing') : $t('agentChat.thinking') }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="agent-input-area">
        <form @submit.prevent="sendMessage" class="agent-input-row">
          <textarea
            ref="textareaRef"
            v-model="input"
            :placeholder="$t('agentChat.placeholder')"
            :disabled="loading"
            class="agent-input"
            maxlength="2000"
            rows="1"
            @input="resizeTextarea"
            @keydown="handleKeydown"
          ></textarea>
          <button
            type="submit"
            :disabled="loading || !input.trim()"
            class="agent-send"
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
              <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/>
            </svg>
          </button>
        </form>
        <div v-if="subscriptionStore.messagesRemaining !== null && subscriptionStore.messagesRemaining !== undefined" class="agent-remaining">
          {{ $t('agentChat.remaining', subscriptionStore.messagesRemaining) }}
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, nextTick, onMounted, onBeforeUnmount, watch } from 'vue'
import api from '../services/api'
import { useSubscriptionStore } from '../stores/subscription'
import { usePredictionStore } from '../stores/prediction'
import { useAuthStore } from '../stores/auth'
import { renderMarkdown } from '../utils/markdown'
import { parseSSEEvents } from '../utils/sse'
import { useI18n } from 'vue-i18n'

const props = defineProps({
  gpxId: { type: Number, default: null },
  predictionId: { type: Number, default: null },
  planId: { type: Number, default: null },
  embedded: { type: Boolean, default: false },
  prominent: { type: Boolean, default: false },
  welcomeText: { type: String, default: null },
  contextType: { type: String, default: null },
})

const emit = defineEmits(['plan-saved', 'week-generated', 'plan-adjusted', 'tool-result'])

const { t, locale } = useI18n()
const subscriptionStore = useSubscriptionStore()
const predictionStore = usePredictionStore()
const authStore = useAuthStore()
const isOpen = ref(props.prominent)

// Persist the current conversation_id per (user, contextType) so a page
// reload resumes the same chat instead of orphaning history. Only enabled
// when a contextType is provided — surfaces without one stay ephemeral.
const historyEnabled = computed(() => !!props.contextType)
const lastConvStorageKey = computed(() => {
  if (!historyEnabled.value) return null
  const uid = authStore.user?.id ?? 'anon'
  return `agentChat:lastConv:${uid}:${props.contextType}`
})

const historyOpen = ref(false)
const historyItems = ref([])
const historyLoading = ref(false)

const quickActions = computed(() => ['briefing', 'pacing', 'waypoints', 'nutrition', 'ready'].map((k) => ({
  label: t(`agentChat.quick.${k}.label`),
  prompt: t(`agentChat.quick.${k}.prompt`),
})))

const quickSend = (prompt) => {
  input.value = prompt
  sendMessage()
}
const input = ref('')
const loading = ref(false)
const textareaRef = ref(null)

const activeTools = ref([])
const completedTools = ref([])

// Collapse completed tools to max 6, showing count for overflow
const displayedCompletedTools = computed(() => {
  const all = completedTools.value
  if (all.length <= 6) return all
  const shown = all.slice(0, 5)
  const hidden = all.length - 5
  return [...shown, { tool: '_overflow', label: t('agentChat.more_steps', { n: hidden }) }]
})

const defaultWelcome = t('agentChat.welcome')

const welcomeMessage = {
  role: 'assistant',
  content: props.welcomeText || defaultWelcome,
  toolCalls: []
}

const messages = ref([{ ...welcomeMessage }])
const messagesContainer = ref(null)
const conversationId = ref(`chat-${Date.now()}`)

const scrollToBottom = async () => {
  await nextTick()
  if (messagesContainer.value) {
    messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
  }
}

watch(messages, scrollToBottom, { deep: true })

const resizeTextarea = () => {
  const el = textareaRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 120) + 'px'
}

const handleKeydown = (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    sendMessage()
  }
}

const persistCurrentConvId = () => {
  const key = lastConvStorageKey.value
  if (!key) return
  try { localStorage.setItem(key, conversationId.value) } catch (_) {}
}

const clearPersistedConvId = (id) => {
  const key = lastConvStorageKey.value
  if (!key) return
  try {
    if (!id || localStorage.getItem(key) === id) {
      localStorage.removeItem(key)
    }
  } catch (_) {}
}

const resetChat = () => {
  messages.value = [{ ...welcomeMessage }]
  conversationId.value = `chat-${Date.now()}`
  input.value = ''
  if (textareaRef.value) {
    textareaRef.value.style.height = 'auto'
  }
  // New chat: drop the persisted pointer so the next reload starts fresh
  // until this conversation has at least one round-trip.
  clearPersistedConvId()
  historyOpen.value = false
}

const loadHistory = async () => {
  if (!historyEnabled.value) return
  historyLoading.value = true
  try {
    const res = await api.get('/agent/conversations', {
      params: { context: props.contextType, limit: 50 },
    })
    historyItems.value = res.data?.conversations || []
  } catch (err) {
    console.error('Failed to load chat history', err)
    historyItems.value = []
  } finally {
    historyLoading.value = false
  }
}

const toggleHistory = async () => {
  historyOpen.value = !historyOpen.value
  if (historyOpen.value) await loadHistory()
}

const resumeConversation = async (id) => {
  if (!id || loading.value) return
  try {
    const res = await api.get(`/agent/conversations/${encodeURIComponent(id)}`)
    const restored = (res.data?.messages || []).map(m => ({
      role: m.role,
      content: m.content || '',
      toolCalls: m.toolCalls || [],
    }))
    messages.value = restored.length
      ? [{ ...welcomeMessage }, ...restored]
      : [{ ...welcomeMessage }]
    conversationId.value = id
    persistCurrentConvId()
    historyOpen.value = false
    await scrollToBottom()
  } catch (err) {
    console.error('Failed to resume conversation', err)
  }
}

const deleteConversation = async (id) => {
  if (!id) return
  try {
    await api.delete(`/agent/conversations/${encodeURIComponent(id)}`)
    historyItems.value = historyItems.value.filter(c => c.conversation_id !== id)
    // If the user just deleted the chat they're currently viewing, start fresh.
    if (id === conversationId.value) {
      messages.value = [{ ...welcomeMessage }]
      conversationId.value = `chat-${Date.now()}`
    }
    clearPersistedConvId(id)
  } catch (err) {
    console.error('Failed to delete conversation', err)
  }
}

const formatHistoryDate = (iso) => {
  if (!iso) return ''
  try {
    const d = new Date(iso)
    const now = new Date()
    const sameDay = d.toDateString() === now.toDateString()
    if (sameDay) {
      return d.toLocaleTimeString(locale.value, { hour: '2-digit', minute: '2-digit' })
    }
    return d.toLocaleDateString(locale.value, { day: 'numeric', month: 'short' })
  } catch (_) {
    return ''
  }
}

// Mobile keyboard: expose the *visual* viewport as CSS vars so full-screen chat
// sheets (here and in Calendar.vue) shrink above the on-screen keyboard instead
// of hiding the input behind it (iOS doesn't resize the layout viewport).
const syncViewport = () => {
  const vv = window.visualViewport
  if (!vv) return
  const st = document.documentElement.style
  st.setProperty('--vvh', `${vv.height}px`)
  st.setProperty('--vvt', `${vv.offsetTop}px`)
}
onMounted(() => {
  syncViewport()
  window.visualViewport?.addEventListener('resize', syncViewport)
  window.visualViewport?.addEventListener('scroll', syncViewport)
})
onBeforeUnmount(() => {
  window.visualViewport?.removeEventListener('resize', syncViewport)
  window.visualViewport?.removeEventListener('scroll', syncViewport)
})

onMounted(async () => {
  if (!historyEnabled.value) return
  const key = lastConvStorageKey.value
  let savedId = null
  try { savedId = key ? localStorage.getItem(key) : null } catch (_) {}
  if (!savedId) return
  try {
    const res = await api.get(`/agent/conversations/${encodeURIComponent(savedId)}`)
    const restored = (res.data?.messages || []).map(m => ({
      role: m.role,
      content: m.content || '',
      toolCalls: m.toolCalls || [],
    }))
    if (restored.length) {
      messages.value = [{ ...welcomeMessage }, ...restored]
      conversationId.value = savedId
      await scrollToBottom()
    } else {
      clearPersistedConvId(savedId)
    }
  } catch (_) {
    // Conversation gone (deleted from another device, etc.) — clean up
    clearPersistedConvId(savedId)
  }
})

const WAYPOINT_COLORS = {
  aid_station: '#10b981',
  water: '#3b82f6',
  checkpoint: '#f59e0b',
  caution: '#ef4444',
  generic: '#8b5cf6',
}

const WAYPOINT_LABELS = {
  aid_station: 'agentChat.wp.aid_station',
  water: 'agentChat.wp.water',
  checkpoint: 'agentChat.wp.checkpoint',
  caution: 'agentChat.wp.caution',
  generic: 'agentChat.wp.generic',
}

const acceptSuggestion = (msg, index) => {
  if (!msg.suggestions || !msg.suggestions[index]) return
  msg.suggestions[index].status = 'accepted'
  predictionStore.acceptSuggestion(index)
  autoSaveAnnotations()
}

const dismissSuggestion = (msg, index) => {
  if (!msg.suggestions || !msg.suggestions[index]) return
  msg.suggestions[index].status = 'dismissed'
  predictionStore.dismissSuggestion(index)
}

const acceptAllSuggestions = (msg) => {
  if (!msg.suggestions) return
  msg.suggestions.forEach((s, i) => {
    if (s.status === 'pending') {
      s.status = 'accepted'
    }
  })
  predictionStore.acceptAllSuggestions()
  autoSaveAnnotations()
}

const dismissAllSuggestions = (msg) => {
  if (!msg.suggestions) return
  msg.suggestions.forEach(s => {
    if (s.status === 'pending') s.status = 'dismissed'
  })
  predictionStore.dismissAllSuggestions()
}

const hasPendingSuggestions = (msg) => {
  return msg.suggestions?.some(s => s.status === 'pending') ?? false
}

const autoSaveAnnotations = async () => {
  if (props.predictionId && predictionStore.annotationsDirty) {
    try {
      await predictionStore.saveAnnotations(props.predictionId)
    } catch (e) {
      console.error('Auto-save annotations failed:', e)
    }
  }
}

const handleDoneEvent = (data) => {
  if (data.error && !data.response) {
    messages.value.push({
      role: 'assistant',
      content: t('agentChat.error', { msg: data.error }),
      toolCalls: [],
    })
  } else {
    const msg = {
      role: 'assistant',
      content: data.response || t('agentChat.no_response'),
      toolCalls: data.tool_calls || [],
      suggestions: null,
    }

    if (data.suggested_annotations && data.suggested_annotations.length > 0) {
      msg.suggestions = data.suggested_annotations.map(s => ({ ...s, status: 'pending' }))
      predictionStore.setSuggestedAnnotations(data.suggested_annotations)
    }

    if (data.annotations_updated) {
      predictionStore.syncAnnotations(data.annotations_updated)
    }

    if (data.training_plan_saved) {
      emit('plan-saved', data.training_plan_saved)
    }
    if (data.generated_weeks && data.generated_weeks.length > 0) {
      emit('week-generated', data.generated_weeks)
    }
    if (data.plan_adjusted) {
      emit('plan-adjusted')
    }
    // Surface wizard-style tool results to the parent so it can mount the
    // onboarding modal inline. Backend may report this either via a
    // top-level field (data.wizard_payload) or via a tool_call entry.
    if (data.wizard_payload) {
      emit('tool-result', data.wizard_payload)
    } else if (Array.isArray(data.tool_calls)) {
      const wizardCall = data.tool_calls.find(
        tc => tc?.tool === 'start_onboarding_questionnaire',
      )
      if (wizardCall) {
        emit('tool-result', { wizard_id: 'training_preferences_v1' })
      }
    }

    messages.value.push(msg)
  }
  if (data.agent_messages_remaining !== undefined) {
    subscriptionStore.updateMessagesRemaining(data.agent_messages_remaining)
  }
}

const sendMessage = async () => {
  const text = input.value.trim()
  if (!text || loading.value) return

  messages.value.push({ role: 'user', content: text, toolCalls: [] })
  input.value = ''
  if (textareaRef.value) {
    textareaRef.value.style.height = 'auto'
  }
  loading.value = true
  activeTools.value = []
  completedTools.value = []

  const payload = {
    message: text,
    conversation_id: conversationId.value,
  }
  if (props.gpxId) payload.gpx_id = props.gpxId
  if (props.predictionId) payload.prediction_id = props.predictionId
  if (props.planId) payload.plan_id = props.planId
  if (props.contextType) payload.context_type = props.contextType

  try {
    const baseURL = api.defaults.baseURL
    const response = await fetch(`${baseURL}/agent/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(payload),
    })

    if (!response.ok) {
      if (response.status === 429) {
        messages.value.push({
          role: 'assistant',
          content: 'You\'ve hit today\'s message limit. Upgrade to Premium for 15 advisor chats/day plus 5 plan generations/month, with terrain, weather and pacing intelligence.',
          toolCalls: [],
        })
        subscriptionStore.openUpgradeModal()
        return
      }
      const errData = await response.json().catch(() => ({}))
      throw new Error(errData.error || `HTTP ${response.status}`)
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const { events, remaining } = parseSSEEvents(buffer)
      buffer = remaining

      for (const ev of events) {
        if (ev.event === 'tool_start') {
          activeTools.value.push({ tool: ev.data.tool, label: ev.data.label })
        } else if (ev.event === 'tool_end') {
          const finished = activeTools.value.find(t => t.tool === ev.data.tool)
          activeTools.value = activeTools.value.filter(t => t.tool !== ev.data.tool)
          completedTools.value.push({
            tool: ev.data.tool,
            label: finished?.label || ev.data.tool.replace(/_/g, ' '),
          })
          // Fast-path: refresh the calendar as soon as a plan-mutating tool
          // finishes, without waiting for the agent to write its final
          // assistant text. Backend emits these hints on tool_end for
          // save_training_plan / adjust_training_week.
          if (ev.data.plan_saved) {
            emit('plan-saved', ev.data.plan_saved)
          }
          if (ev.data.plan_adjusted) {
            emit('plan-adjusted')
          }
        } else if (ev.event === 'week') {
          // Single week streamed in real-time — render on calendar immediately
          if (ev.data.week) {
            emit('week-generated', [ev.data.week])
          }
        } else if (ev.event === 'done') {
          handleDoneEvent(ev.data)
          // Conversation now exists server-side — pin it for resume on reload.
          persistCurrentConvId()
        } else if (ev.event === 'error') {
          messages.value.push({
            role: 'assistant',
            content: t('agentChat.error', { msg: ev.data.error || t('agentChat.generic_error') }),
            toolCalls: [],
          })
        }
      }
    }
  } catch (err) {
    const errorMsg = err.message || t('agentChat.generic_error')
    messages.value.push({
      role: 'assistant',
      content: t('agentChat.error', { msg: errorMsg }),
      toolCalls: [],
    })
  } finally {
    loading.value = false
    activeTools.value = []
    completedTools.value = []
  }
}

defineExpose({
  sendMessage(text) {
    if (text) {
      input.value = text
    }
    sendMessage()
  },
  prefillInput(text) {
    input.value = text || ''
    // Focus the textarea on the next tick so the user can keep typing
    requestAnimationFrame(() => {
      const el = document.querySelector('.agent-input-row textarea, .agent-input-row input')
      if (el) {
        el.focus()
        try { el.setSelectionRange(el.value.length, el.value.length) } catch (_) {}
      }
    })
  },
})
</script>

<style scoped>
.agent-chat {
  position: fixed;
  bottom: 1.5rem;
  right: 1.5rem;
  z-index: 1000;
  font-family: var(--font-sans);
}
.agent-chat--embedded {
  position: static;
  width: 100%;
  height: 100%;
}

.agent-toggle {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.625rem 1rem;
  background: #047857;
  color: white;
  border: none;
  border-radius: 2rem;
  font-size: 0.875rem;
  font-weight: 500;
  cursor: pointer;
  box-shadow: 0 4px 12px rgba(4, 120, 87, 0.3);
  transition: all 0.2s;
}
.agent-toggle:hover {
  background: #065f46;
  transform: translateY(-1px);
}
.agent-toggle-open {
  display: none;
}

.agent-panel {
  position: fixed;
  bottom: 1.5rem;
  right: 1.5rem;
  width: 440px;
  max-width: calc(100vw - 2rem);
  height: 600px;
  max-height: calc(100vh - 4rem);
  background: white;
  border-radius: 1rem;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.12), 0 0 0 1px rgba(0, 0, 0, 0.05);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.agent-panel--embedded {
  position: static;
  width: 100%;
  height: 100%;
  max-width: none;
  max-height: none;
  border-radius: 0.75rem;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
  border: 1px solid #e2e8f0;
}

.agent-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem 1rem;
  border-bottom: 1px solid #e2e8f0;
}
.agent-header h3 {
  font-size: 0.8125rem;
  font-weight: 600;
  color: #334155;
  margin: 0;
  font-family: var(--font-sans);
  text-transform: none;
  letter-spacing: 0;
}
.agent-header-btn {
  background: none;
  border: none;
  color: #94a3b8;
  cursor: pointer;
  padding: 0.375rem;
  border-radius: 0.375rem;
  line-height: 1;
  transition: all 0.15s;
}
.agent-header-btn:hover {
  color: #475569;
  background: #f1f5f9;
}

.agent-avatar {
  width: 24px;
  height: 24px;
  border-radius: 0.375rem;
  background: #047857;
  color: white;
  font-size: 0.625rem;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.agent-messages {
  flex: 1;
  overflow-y: auto;
  padding: 1rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.agent-msg {
  display: flex;
  gap: 0.625rem;
  font-size: 0.8125rem;
  line-height: 1.6;
}

.agent-msg-avatar {
  width: 24px;
  height: 24px;
  border-radius: 0.375rem;
  background: #047857;
  color: white;
  font-size: 0.5625rem;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  margin-top: 2px;
}

.agent-msg-body {
  min-width: 0;
  flex: 1;
}

.agent-msg-user {
  justify-content: flex-end;
}
.agent-msg-user .agent-msg-body {
  background: #f1f5f9;
  border-radius: 0.75rem;
  padding: 0.5rem 0.75rem;
  max-width: 85%;
  color: #1e293b;
}
.agent-msg-user .agent-msg-body p {
  margin: 0;
  white-space: pre-wrap;
}

/* Markdown prose styles for assistant messages */
.agent-msg-assistant .assistant-content :deep(h1),
.agent-msg-assistant .assistant-content :deep(h2),
.agent-msg-assistant .assistant-content :deep(h3),
.agent-msg-assistant .assistant-content :deep(h4),
.agent-msg-assistant .assistant-content :deep(h5),
.agent-msg-assistant .assistant-content :deep(h6) {
  font-family: var(--font-sans);
  text-transform: none;
  letter-spacing: 0;
  margin: 0.75em 0 0.25em;
  line-height: 1.3;
}
.agent-msg-assistant .assistant-content :deep(h1) { font-size: 1.125rem; font-weight: 700; }
.agent-msg-assistant .assistant-content :deep(h2) { font-size: 1rem; font-weight: 700; }
.agent-msg-assistant .assistant-content :deep(h3) { font-size: 0.875rem; font-weight: 600; }
.agent-msg-assistant .assistant-content :deep(h4),
.agent-msg-assistant .assistant-content :deep(h5),
.agent-msg-assistant .assistant-content :deep(h6) { font-size: 0.8125rem; font-weight: 600; }

.agent-msg-assistant .assistant-content :deep(h1:first-child),
.agent-msg-assistant .assistant-content :deep(h2:first-child),
.agent-msg-assistant .assistant-content :deep(h3:first-child) {
  margin-top: 0;
}

.agent-msg-assistant .assistant-content :deep(p) {
  margin: 0.375em 0;
}
.agent-msg-assistant .assistant-content :deep(p:first-child) {
  margin-top: 0;
}
.agent-msg-assistant .assistant-content :deep(p:last-child) {
  margin-bottom: 0;
}

.agent-msg-assistant .assistant-content :deep(ul),
.agent-msg-assistant .assistant-content :deep(ol) {
  margin: 0.375em 0;
  padding-left: 1.25em;
}
.agent-msg-assistant .assistant-content :deep(ul) {
  list-style-type: disc;
}
.agent-msg-assistant .assistant-content :deep(ol) {
  list-style-type: decimal;
}
.agent-msg-assistant .assistant-content :deep(li) {
  margin: 0.125em 0;
}
.agent-msg-assistant .assistant-content :deep(li > ul),
.agent-msg-assistant .assistant-content :deep(li > ol) {
  margin: 0;
}

.agent-msg-assistant .assistant-content :deep(code) {
  background: #f1f5f9;
  padding: 0.125em 0.35em;
  border-radius: 0.25em;
  font-size: 0.8em;
  font-family: var(--font-mono);
}

.agent-msg-assistant .assistant-content :deep(pre) {
  background: #1e293b;
  color: #e2e8f0;
  border-radius: 0.5rem;
  padding: 0.75rem 1rem;
  margin: 0.5em 0;
  overflow-x: auto;
  font-size: 0.75rem;
  line-height: 1.5;
}
.agent-msg-assistant .assistant-content :deep(pre code) {
  background: none;
  padding: 0;
  border-radius: 0;
  color: inherit;
  font-size: inherit;
}

.agent-msg-assistant .assistant-content :deep(blockquote) {
  border-left: 3px solid #047857;
  margin: 0.5em 0;
  padding: 0.25em 0.75em;
  color: #475569;
}

.agent-msg-assistant .assistant-content :deep(table) {
  border-collapse: collapse;
  width: 100%;
  margin: 0.5em 0;
  font-size: 0.75rem;
}
.agent-msg-assistant .assistant-content :deep(th),
.agent-msg-assistant .assistant-content :deep(td) {
  border: 1px solid #e2e8f0;
  padding: 0.375rem 0.5rem;
  text-align: left;
}
.agent-msg-assistant .assistant-content :deep(th) {
  background: #f8fafc;
  font-weight: 600;
}

.agent-msg-assistant .assistant-content :deep(hr) {
  border: none;
  border-top: 1px solid #e2e8f0;
  margin: 0.75em 0;
}

.agent-msg-assistant .assistant-content :deep(a) {
  color: #047857;
  text-decoration: underline;
  text-underline-offset: 2px;
}
.agent-msg-assistant .assistant-content :deep(a:hover) {
  color: #065f46;
}

.agent-msg-assistant .assistant-content :deep(strong) {
  font-weight: 600;
}

/* Glossary term hints */
.agent-msg-assistant .assistant-content :deep(.agent-term) {
  text-decoration: none;
  border-bottom: 1px dashed #94a3b8;
  cursor: help;
  position: relative;
  font-style: normal;
  color: inherit;
  transition: border-color 0.15s;
}
.agent-msg-assistant .assistant-content :deep(.agent-term:hover),
.agent-msg-assistant .assistant-content :deep(.agent-term:focus) {
  border-bottom-color: #047857;
  outline: none;
}
.agent-msg-assistant .assistant-content :deep(.agent-term:hover::after),
.agent-msg-assistant .assistant-content :deep(.agent-term:focus::after) {
  content: attr(title);
  position: absolute;
  bottom: calc(100% + 6px);
  left: 50%;
  transform: translateX(-50%);
  background: #1e293b;
  color: #f1f5f9;
  font-size: 0.6875rem;
  font-weight: 400;
  line-height: 1.5;
  padding: 0.5rem 0.75rem;
  border-radius: 0.375rem;
  white-space: normal;
  width: max-content;
  max-width: 280px;
  z-index: 50;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  pointer-events: none;
}
.agent-msg-assistant .assistant-content :deep(.agent-term:hover::before),
.agent-msg-assistant .assistant-content :deep(.agent-term:focus::before) {
  content: '';
  position: absolute;
  bottom: calc(100% + 2px);
  left: 50%;
  transform: translateX(-50%);
  border: 4px solid transparent;
  border-top-color: #1e293b;
  z-index: 50;
  pointer-events: none;
}

.agent-tools {
  margin-top: 0.5rem;
  padding-top: 0.5rem;
  border-top: 1px solid #e2e8f0;
}

.agent-input-area {
  border-top: 1px solid #e2e8f0;
  padding: 0.625rem;
}

.agent-input-row {
  display: flex;
  gap: 0.5rem;
  align-items: flex-end;
}
.agent-input {
  flex: 1;
  padding: 0.5rem 0.75rem;
  border: 1px solid #e2e8f0;
  border-radius: 0.625rem;
  font-size: 0.8125rem;
  font-family: var(--font-sans);
  outline: none;
  transition: border-color 0.2s;
  resize: none;
  max-height: 120px;
  line-height: 1.5;
}
.agent-input:focus {
  border-color: #047857;
  box-shadow: 0 0 0 2px rgba(4, 120, 87, 0.1);
}
.agent-send {
  padding: 0.5rem;
  background: #047857;
  color: white;
  border: none;
  border-radius: 0.5rem;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.2s;
  flex-shrink: 0;
}
.agent-send:hover:not(:disabled) {
  background: #065f46;
}
.agent-send:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.agent-remaining {
  text-align: center;
  font-size: 0.6875rem;
  color: #94a3b8;
  margin-top: 0.375rem;
}

.agent-typing {
  display: flex;
  gap: 0.25rem;
  padding: 0.25rem 0;
}
.agent-typing span {
  width: 6px;
  height: 6px;
  background: #94a3b8;
  border-radius: 50%;
  animation: typing 1.4s infinite;
}
.agent-typing span:nth-child(2) { animation-delay: 0.2s; }
.agent-typing span:nth-child(3) { animation-delay: 0.4s; }

@keyframes typing {
  0%, 60%, 100% { transform: translateY(0); opacity: 0.4; }
  30% { transform: translateY(-4px); opacity: 1; }
}

/* Tool progress indicators */
.tool-progress {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  padding: 0.25rem 0;
}
.tool-status {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.75rem;
  color: #64748b;
  line-height: 1.4;
}
.tool-done {
  opacity: 0.55;
}
.tool-done span {
  color: #64748b;
}
.tool-active {
  margin-top: 0.125rem;
}
.tool-active span {
  color: #334155;
  font-weight: 500;
}
.tool-dots {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  min-width: 20px;
}
.tool-dots span {
  width: 4px;
  height: 4px;
  background: #047857;
  border-radius: 50%;
  animation: typing 1.4s infinite;
}
.tool-dots span:nth-child(2) { animation-delay: 0.2s; }
.tool-dots span:nth-child(3) { animation-delay: 0.4s; }

/* Suggestion Cards */
.suggestion-cards {
  margin-top: 0.625rem;
  padding-top: 0.5rem;
  border-top: 1px solid #e2e8f0;
}
.suggestion-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.5rem;
}
.suggestion-actions {
  display: flex;
  gap: 0.375rem;
}
.suggestion-card {
  border: 1px solid #e2e8f0;
  border-radius: 0.5rem;
  padding: 0.5rem 0.625rem;
  margin-bottom: 0.375rem;
  background: #f8fafc;
  transition: opacity 0.2s, background 0.2s;
}
.suggestion-card--accepted {
  background: #f0fdf4;
  border-color: #bbf7d0;
  opacity: 0.7;
}
.suggestion-card--dismissed {
  opacity: 0.4;
  background: #f1f5f9;
}
.suggestion-card-top {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.25rem;
}
.suggestion-badge {
  display: inline-block;
  padding: 1px 6px;
  border-radius: 9999px;
  font-size: 0.625rem;
  font-weight: 700;
  color: white;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}
.suggestion-distance {
  font-size: 0.6875rem;
  font-weight: 600;
  color: #64748b;
  font-family: var(--font-mono, monospace);
}
.suggestion-label {
  font-size: 0.75rem;
  font-weight: 600;
  color: #334155;
}
.suggestion-reason {
  font-size: 0.6875rem;
  color: #64748b;
  margin-top: 0.125rem;
}
.suggestion-stop {
  font-size: 0.625rem;
  color: #94a3b8;
  margin-top: 0.125rem;
}
.suggestion-card-actions {
  display: flex;
  gap: 0.375rem;
  margin-top: 0.375rem;
}
.suggestion-btn {
  padding: 0.2rem 0.5rem;
  border-radius: 0.375rem;
  font-size: 0.6875rem;
  font-weight: 600;
  border: 1px solid transparent;
  cursor: pointer;
  transition: all 0.15s;
}
.suggestion-btn-accept {
  background: #047857;
  color: white;
}
.suggestion-btn-accept:hover {
  background: #065f46;
}
.suggestion-btn-dismiss {
  background: white;
  color: #64748b;
  border-color: #e2e8f0;
}
.suggestion-btn-dismiss:hover {
  background: #f1f5f9;
}
.suggestion-btn-accept-all {
  background: #047857;
  color: white;
  font-size: 0.625rem;
}
.suggestion-btn-accept-all:hover {
  background: #065f46;
}
.suggestion-btn-dismiss-all {
  background: white;
  color: #64748b;
  border-color: #e2e8f0;
  font-size: 0.625rem;
}
.suggestion-btn-dismiss-all:hover {
  background: #f1f5f9;
}
.suggestion-status-text {
  font-size: 0.625rem;
  font-weight: 600;
  margin-top: 0.25rem;
}
.suggestion-status-accepted {
  color: #047857;
}
.suggestion-status-dismissed {
  color: #94a3b8;
}

/* ── Prominent inline mode ── */
.agent-prominent {
  width: 100%;
}

.agent-collapsed-bar {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1rem 1.5rem;
  background: white;
  border: 1px solid #d1d5db;
  border-left: 4px solid #047857;
  border-radius: 0.5rem;
  cursor: pointer;
  transition: all 0.2s;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
}
.agent-collapsed-bar:hover {
  border-color: #047857;
  box-shadow: 0 4px 12px rgba(4, 120, 87, 0.12);
  transform: translateY(-1px);
}
.agent-collapsed-left {
  display: flex;
  align-items: center;
  gap: 0.875rem;
}
.agent-collapsed-text {
  text-align: left;
}
.agent-collapsed-title {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-family: var(--font-display, "Barlow Condensed", sans-serif);
  font-size: 1.0625rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.02em;
  color: var(--text-primary, #1e293b);
  line-height: 1.3;
}
.agent-collapsed-hint {
  display: block;
  font-size: 0.75rem;
  color: var(--text-muted, #94a3b8);
  margin-top: 0.125rem;
}
.agent-collapsed-cta {
  font-size: 0.75rem;
  font-weight: 600;
  color: white;
  padding: 0.375rem 0.875rem;
  background: #047857;
  border: none;
  border-radius: 2rem;
  transition: all 0.2s;
  white-space: nowrap;
}
.agent-collapsed-bar:hover .agent-collapsed-cta {
  background: #065f46;
}

.agent-ai-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0.125rem 0.375rem;
  font-family: var(--font-sans, "Inter", sans-serif);
  font-size: 0.5625rem;
  font-weight: 800;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: white;
  background: #047857;
  border-radius: 0.25rem;
  line-height: 1.4;
}

.agent-avatar-lg {
  width: 40px;
  height: 40px;
  border-radius: 0.5rem;
  background: #047857;
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.agent-panel-prominent {
  background: white;
  border-radius: 0.5rem;
  border: 1px solid #d1d5db;
  border-left: 4px solid #047857;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.agent-header-prominent {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1rem 1.25rem;
  background: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
}
.agent-header-left {
  display: flex;
  align-items: center;
  gap: 0.875rem;
}
.agent-header-title {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-family: var(--font-display, "Barlow Condensed", sans-serif);
  font-size: 1.0625rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.02em;
  color: var(--text-primary, #1e293b);
  margin: 0;
  line-height: 1.3;
}
.agent-header-sub {
  font-size: 0.6875rem;
  color: var(--text-muted, #94a3b8);
  margin: 0.125rem 0 0;
  line-height: 1.4;
}
.agent-header-prominent .agent-header-btn {
  color: #94a3b8;
}
.agent-header-prominent .agent-header-btn:hover {
  color: #475569;
  background: #f1f5f9;
}

.agent-quick-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  padding: 0.875rem 1.25rem;
  border-bottom: 1px solid #e2e8f0;
  background: #f8fafc;
}
.agent-chip {
  padding: 0.375rem 0.75rem;
  border: 1px solid #d1d5db;
  border-radius: 2rem;
  background: white;
  font-size: 0.75rem;
  font-weight: 500;
  color: #475569;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}
.agent-chip:hover {
  border-color: #047857;
  color: #047857;
  background: #ecfdf5;
}

.agent-messages-prominent {
  flex: 1;
  overflow-y: auto;
  padding: 0.75rem 1.25rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
  max-height: 500px;
}

.agent-input-area-prominent {
  border-top: 1px solid #e2e8f0;
  padding: 0.875rem 1.25rem;
  background: #f8fafc;
}
.agent-input-area-prominent .agent-input {
  background: white;
}

/* ── Chat history popover ── */
.agent-header-actions {
  position: relative;
}
.agent-header-btn--active {
  color: #047857;
  background: #ecfdf5;
}
.agent-history-pop {
  position: absolute;
  top: calc(100% + 6px);
  right: 0;
  width: 280px;
  max-height: 360px;
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 0.5rem;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12);
  z-index: 50;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.agent-history-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.5rem 0.75rem;
  border-bottom: 1px solid #e2e8f0;
  font-size: 0.75rem;
  font-weight: 600;
  color: #475569;
  background: #f8fafc;
}
.agent-history-close {
  background: none;
  border: none;
  font-size: 1rem;
  line-height: 1;
  color: #94a3b8;
  cursor: pointer;
  padding: 0 0.25rem;
}
.agent-history-close:hover { color: #475569; }
.agent-history-empty {
  padding: 1rem;
  font-size: 0.75rem;
  color: #94a3b8;
  text-align: center;
}
.agent-history-list {
  list-style: none;
  margin: 0;
  padding: 0.25rem;
  overflow-y: auto;
}
.agent-history-item {
  display: flex;
  align-items: stretch;
  gap: 2px;
  border-radius: 0.375rem;
}
.agent-history-item:hover {
  background: #f1f5f9;
}
.agent-history-item--current {
  background: #ecfdf5;
}
.agent-history-row {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  padding: 0.5rem 0.625rem;
  background: none;
  border: none;
  text-align: left;
  cursor: pointer;
  min-width: 0;
}
.agent-history-title {
  font-size: 0.75rem;
  font-weight: 500;
  color: #1e293b;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}
.agent-history-meta {
  font-size: 0.625rem;
  color: #94a3b8;
}
.agent-history-del {
  background: none;
  border: none;
  color: #cbd5e1;
  cursor: pointer;
  padding: 0 0.5rem;
  border-radius: 0.375rem;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: color 0.15s, background 0.15s;
}
.agent-history-del:hover {
  color: #ef4444;
  background: #fef2f2;
}

/* Long unbroken tokens (URLs, ids) must wrap instead of widening the bubble. */
.assistant-content,
.agent-msg-user .agent-msg-body p {
  overflow-wrap: anywhere;
}
/* Wide markdown tables scroll inside the bubble, never the page. */
.agent-msg-assistant .assistant-content :deep(table) {
  display: block;
  max-width: 100%;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}
.agent-msg-assistant .assistant-content :deep(th),
.agent-msg-assistant .assistant-content :deep(td) {
  overflow-wrap: normal;
  min-width: 4.5rem;
}
.agent-messages,
.agent-messages-prominent {
  overscroll-behavior: contain;
}

@media (max-width: 640px) {
  /* Floating mode: the panel becomes a full-screen sheet sized to the visual
     viewport, so the input stays above the keyboard. */
  .agent-chat:not(.agent-chat--embedded) {
    bottom: calc(1rem + env(safe-area-inset-bottom));
    right: 1rem;
  }
  .agent-panel:not(.agent-panel--embedded) {
    top: var(--vvt, 0px);
    left: 0;
    right: 0;
    bottom: auto;
    width: 100%;
    max-width: none;
    height: var(--vvh, 100dvh);
    max-height: none;
    border-radius: 0;
    padding-top: env(safe-area-inset-top);
  }
  .agent-input-area,
  .agent-input-area-prominent {
    padding: 0.5rem 0.75rem calc(0.5rem + env(safe-area-inset-bottom));
  }
  /* 16px stops iOS from zooming the page when the textarea gets focus. */
  .agent-input {
    font-size: 16px;
    min-height: 44px;
    padding: 0.625rem 0.875rem;
  }
  .agent-input::placeholder { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .agent-send {
    width: 44px;
    height: 44px;
    border-radius: 0.75rem;
  }
  .agent-header-btn {
    min-width: 40px;
    min-height: 40px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
  }
  .agent-header { padding: 0.375rem 0.5rem 0.375rem 1rem; }
  .agent-messages { padding: 0.875rem 0.75rem; }
  .agent-msg { font-size: 0.875rem; }
  .agent-history-pop { width: min(280px, calc(100vw - 2rem)); }
  .agent-history-row { min-height: 44px; }
  .agent-history-del { min-width: 44px; }
  .suggestion-btn { min-height: 36px; padding: 0.25rem 0.75rem; }
  .agent-chip { min-height: 40px; white-space: normal; text-align: left; }

  /* Prominent (Prediction page) mode */
  .agent-collapsed-bar { padding: 0.875rem 1rem; gap: 0.75rem; }
  .agent-header-prominent { padding: 0.625rem 0.5rem 0.625rem 0.875rem; }
  .agent-header-sub { display: none; }
  .agent-quick-actions { padding: 0.75rem; }
  .agent-messages-prominent { padding: 0.75rem; max-height: 65dvh; }
}
</style>
