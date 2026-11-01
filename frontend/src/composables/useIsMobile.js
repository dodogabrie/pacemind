import { ref, onMounted, onBeforeUnmount } from 'vue'

/**
 * Reactive mobile detection via matchMedia.
 * @param {number} breakpoint - Max width in px (default 640, matching Tailwind's `sm`)
 * @returns {{ isMobile: import('vue').Ref<boolean> }}
 */
export function useIsMobile(breakpoint = 640) {
  const isMobile = ref(false)
  let mql = null
  let handler = null

  onMounted(() => {
    if (typeof window === 'undefined') return

    mql = window.matchMedia(`(max-width: ${breakpoint}px)`)
    handler = (event) => {
      isMobile.value = event?.matches ?? mql.matches
    }
    handler() // set initial value

    if (mql.addEventListener) {
      mql.addEventListener('change', handler)
    } else if (mql.addListener) {
      mql.addListener(handler)
    }
  })

  onBeforeUnmount(() => {
    if (!mql || !handler) return
    if (mql.removeEventListener) {
      mql.removeEventListener('change', handler)
    } else if (mql.removeListener) {
      mql.removeListener(handler)
    }
  })

  return { isMobile }
}
