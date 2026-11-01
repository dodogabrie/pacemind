// Fails the build if any emoji ships in src/ — literal, HTML entity (&#x1F3C3;)
// or JS escape ('\u{1F45F}', '\uD83C'). Icons go through components/Icon.vue.
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'

// Emoji / pictograph ranges, plus U+FE0F (emoji presentation selector).
// Arrows (U+2190–21FF) and typographic symbols are allowed.
const isEmoji = (cp) =>
  (cp >= 0x1f000 && cp <= 0x1faff) || (cp >= 0x2600 && cp <= 0x27bf) ||
  (cp >= 0x2300 && cp <= 0x23ff) || (cp >= 0x2b00 && cp <= 0x2bff) || cp === 0xfe0f

const ESCAPES = [
  [/&#x([0-9a-f]+);/gi, 16], [/&#(\d+);/g, 10],
  [/\\u\{([0-9a-f]+)\}/gi, 16], [/\\u([0-9a-f]{4})/gi, 16], [/\\U([0-9a-f]{8})/g, 16],
]

export const findEmoji = (text) => {
  const hits = []
  for (const ch of text) if (isEmoji(ch.codePointAt(0))) hits.push(ch)
  for (const [re, base] of ESCAPES) for (const m of text.matchAll(re)) {
    const cp = parseInt(m[1], base)
    if (isEmoji(cp) || (cp >= 0xd83c && cp <= 0xd83e)) hits.push(m[0])
  }
  return hits
}

const walk = (dir) => readdirSync(dir).flatMap((f) => {
  const p = join(dir, f)
  return statSync(p).isDirectory() ? walk(p) : /\.(vue|js|json|html)$/.test(p) ? [p] : []
})

if (import.meta.url === `file://${process.argv[1]}`) {
  // self-check
  console.assert(findEmoji('ok → ©').length === 0, 'arrows/© allowed')
  console.assert(findEmoji("a \u{1F3C3} &#x1F512; '\\u{1F45F}' &#9728; '\\u2602'").length === 5, 'all forms caught')
  const bad = [...walk('src'), 'index.html'].flatMap((f) =>
    readFileSync(f, 'utf8').split('\n').flatMap((l, i) => findEmoji(l).map((e) => `${f}:${i + 1}: ${e}`)))
  if (bad.length) { console.error('Emoji are not allowed (use components/Icon.vue):\n' + bad.join('\n')); process.exit(1) }
}
