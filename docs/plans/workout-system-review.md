# Piano — Revisione sistema di creazione allenamenti + integrazione LiteLLM

> Branch: `claude/review-workout-system-zkxWz`
> Stato: **completo** (3/3) — Contesto, Punto 1 (linguaggio coach), Punto 2 (LiteLLM proxy), Punto 3 (engine), Punto 4 (test), verifica end-to-end, rollout.

---

## Contesto

PaceMind genera piani di allenamento trail tramite un **engine deterministico** (`backend/services/plan_engine.py`, ~1500 righe) orchestrato da un **agente LLM** (Claude tool-use loop in `backend/services/agent/`). Questa revisione affronta tre ambiti:

1. **Linguaggio dell'agente** — il chatbot fa riferimento a "libri", "sezioni" (es. "sezione 4.3"), "manuali". L'utente lo percepisce come scollegato dal prodotto e poco professionale. La causa è una combinazione di istruzioni esplicite all'LLM (`'Reference coaching knowledge from expert trail running books'`) e di un knowledge file `.md` strutturato in `## Heading` che il modello cita come "sezioni".
2. **Provider LLM bloccato su Anthropic** — l'app usa direttamente `anthropic.Anthropic(...)`. Vogliamo poter switchare modello/provider mantenendo invariato il codice agente, idealmente passando per un proxy compatibile.
3. **Incoerenze interne dell'engine** — il `SYSTEM_PROMPT` annuncia all'LLM dei tipi di workout (`tempo`, `back_to_back`, `race_simulation` in Peak) che l'engine non produce mai; `tempo` esiste solo in fase di compliance/route-matching come classificazione runtime, non come output. Risultato: piani generati che non corrispondono a quanto promesso al modello, e potenziali allucinazioni quando l'LLM cerca di "spiegarli".

**Risultato atteso complessivo:**
- Chat che parla in prima persona da coach, senza citare libri/sezioni/capitoli.
- Backend agnostic-by-default: `AGENT_MODEL` può essere un modello Anthropic, OpenAI, Gemini, Bedrock — nessuna riga del loop tool-use cambia.
- Engine i cui workout sono allineati con quanto il prompt dichiara, e test che inchiodano questa coerenza.

**Branch + push.** Tutti i commit vanno su `claude/review-workout-system-zkxWz`. Il push finale (`git push -u origin claude/review-workout-system-zkxWz`) avviene a fine implementazione, NON in plan mode. Il file `.md` di questo piano viene anche copiato in repo come `docs/plans/workout-system-review.md` durante l'esecuzione, così resta tracciato sul branch.

**Non-obiettivi (esplicitamente fuori scope):**
- Rifattorizzazione del knowledge base markdown.
- Cambio di provider di default (resta Claude finché `LITELLM_BASE_URL` non è settato).
- Cambio di schema DB.
- Modifiche al frontend (Vue) — i fix sono tutti backend.

---

## Punto 1 — Linguaggio coach: rimuovere riferimenti a libri / sezioni / capitoli

### Cosa risolve

Eliminare frasi come *"come spiegato nella sezione 4.3"*, *"secondo i manuali"*, *"riferimenti ai libri"* dalle risposte dell'agente. L'LLM è già abbastanza bravo: il problema è che **gli stiamo esplicitamente dicendo di citare libri**.

### Diagnosi precisa (file e righe)

| File | Riga | Problema |
|---|---|---|
| `backend/services/agent/tool_handlers/knowledge.py` | 116 | Tool result include `'note': 'Reference coaching knowledge from expert trail running books. Cite specific protocols when advising.'` — istruzione esplicita di citare libri. |
| `backend/services/agent/tool_handlers/knowledge.py` | 121 | Docstring di `_handle_assess_training_readiness` recita *"book-sourced criteria"*. |
| `backend/services/agent/tool_handlers/validation.py` | 45 | Commento `# Minimum weeks by race distance (book-sourced absolute minimums)` — interno, OK lasciarlo. |
| `backend/services/agent/tool_handlers/validation.py` | 592–600, 674, 695, 705, 722, 726 | Variabile locale `book_min_weeks` usata in **stringhe di warning user-facing**. La variabile in sé non viene esposta, ma il fatto che il warning dica *"a full preparation plan is typically N weeks"* va bene; il problema è altrove. |
| `backend/services/agent/tool_handlers/validation.py` | 742 | Docstring di `_assess_coaching_knowledge_warnings`: *"Apply book-sourced coaching rules"*. Internal-only, ma in chiaro nel codice. |
| `backend/services/agent/tool_handlers/validation.py` | 776 | Warning user-facing: *"Based on the 10% progression rule from training methodology, limit weekly volume increases to ~10%"* — ridondante e suggerisce all'LLM di citare la "metodologia". |
| `backend/services/agent/prompts.py` | (nuova sezione) | Manca una "Communication discipline" che vieti esplicitamente riferimenti a libri/sezioni. |
| `backend/data/coaching_knowledge/*.md` | tutti | Strutturati in `## Section`. **Lasciare invariati**: il modello li legge ma non deve citarli, e il fix è nel prompt, non nel materiale. |

### Modifiche puntuali

#### a) `backend/services/agent/tool_handlers/knowledge.py`

**Riga 116** — sostituire la `note` del tool result:
```python
# PRIMA
'note': 'Reference coaching knowledge from expert trail running books. Cite specific protocols when advising.',

# DOPO
'note': (
    'Internal coaching reference. Apply these protocols as your own coaching '
    'judgement — speak in first person. Never tell the user the advice comes '
    'from a book, manual, chapter, section, or external source. The user '
    'should perceive you as the coach, not as a citation engine.'
),
```

**Riga 121** — docstring di `_handle_assess_training_readiness`:
```python
# PRIMA
"""Assess training readiness using book-sourced criteria."""

# DOPO
"""Assess training readiness using endurance-training criteria."""
```

#### b) `backend/services/agent/prompts.py`

Aggiungere una nuova sezione **prima** di `## Communication Style` (riga ~404):

```markdown
## Coaching Voice (HARD RULE)

Speak as the coach. The runner is talking to you, not to a textbook.

- NEVER reference "books", "manuals", "chapters", "sections" (numbered or otherwise),
  "the literature", "studies say", or any external source — including the internal
  coaching knowledge base. The user must perceive your advice as your own.
- NEVER write phrases like "according to section 4.3", "as discussed in the
  periodization chapter", "the manual recommends", "research suggests",
  "secondo la sezione X", "come spiega il libro".
- If the knowledge base says X, internalize X and tell the runner X directly,
  in your own voice. Example:
    - WRONG: "Section on aerobic base says you need 80% Z1-Z2 volume"
    - RIGHT: "I want 80% of your weekly volume in Z1-Z2 — that's the easy
      pace where you can hold a conversation"
- The only allowed external reference is the user's own data ("your last 8
  weeks averaged 45 km", "your Strava shows…").
```

Inoltre, riga 408 (`Reference specific numbers — "the rocky section from km 15-18 will cost you ~3 min vs road pace"`) **lasciare invariata**: lì "section" si riferisce al tratto del percorso, non a una sezione del libro — semantica diversa e legittima.

#### c) `backend/services/agent/tool_handlers/validation.py`

**Riga 776** — riformulare il warning del 10% rule:
```python
# PRIMA
warnings.append(
    f"Week {curr_wn}: volume increases {increase_pct:.0f}% over previous week "
    f"({prev_km:.0f}km -> {curr_km:.0f}km). Based on the 10% progression rule "
    f"from training methodology, limit weekly volume increases to ~10% to reduce "
    f"injury risk."
)

# DOPO
warnings.append(
    f"Week {curr_wn}: volume jumps {increase_pct:.0f}% over the previous week "
    f"({prev_km:.0f}km -> {curr_km:.0f}km). Keep weekly increases at ~10% or "
    f"less to reduce injury risk."
)
```

**Riga 742** — docstring (interna, ma ripulisce il codice):
```python
# PRIMA
"""Apply book-sourced coaching rules to validated weeks."""

# DOPO
"""Apply cross-week coaching rules to validated weeks.

Includes 10% progression check, ADS gating, recovery-week volume,
elevation specificity vs race ratio, and back-to-back validation.
"""
```

**Righe 798–803** — il warning ADS attualmente dice *"Athletes new to structured training may have Aerobic Deficiency Syndrome (ADS)"*. È OK così — non cita libri. Lasciare invariato.

**`book_min_weeks` (variabile locale)** — lasciare il nome invariato per minimizzare il diff e perché non è user-facing. Il valore appare nei warning come numero (`{book_min_weeks}`), non come variabile.

### Effetti collaterali

- **Cache prompt Anthropic invalidato una volta.** Il `SYSTEM_PROMPT` è marcato `cache_control: ephemeral` e cambia → la prima chat dopo il deploy paga il prezzo pieno (~6k token). Trascurabile a regime.
- **Test esistenti.** Cercare nel codice agent test stringhe che fanno asserzioni sulla `note` o sui warning testuali:
  - `backend/tests/test_agent/` — verificare `test_agent_service.py`, `test_persistence.py`, `test_safety.py`. Se uno asserisce `'expert trail running books'` o `'10% progression rule from training methodology'`, va aggiornato.

### Verifica end-to-end

1. **Unit**: aggiornare/aggiungere `backend/tests/test_agent/test_coaching_voice.py`:
   - Assert che `_handle_lookup_coaching_knowledge(...)['note']` non contenga `'book'` né `'books'` né `'manual'`.
   - Assert che `_handle_assess_training_readiness.__doc__` non contenga `'book'`.
   - Assert che `SYSTEM_PROMPT` contenga la sezione `## Coaching Voice`.
2. **Integration manuale**: avviare backend dev, fare una chat simulata via `POST /api/agent/chat` con messaggio *"Crea un piano per una 50K"*. Controllare che la risposta non contenga `'book'`, `'chapter'`, `'section [0-9]'`, `'libro'`, `'capitolo'`, `'sezione [0-9]'`. Esempio comando:
   ```bash
   curl -s -X POST localhost:5000/api/agent/chat -H 'Content-Type: application/json' \
     -d '{"message": "Spiega come strutturi un piano 50K", "context_type": "training-plan"}' \
     | jq -r .response | grep -iE 'book|chapter|libro|sezione [0-9]'  # deve essere vuoto
   ```
3. **Regression**: `pytest backend/tests/test_agent/ -v` deve essere verde.

### Stima

- ~30 righe di codice modificate (tutte in 3 file).
- 1 nuovo test file (~40 righe).
- Rischio: **basso**. Solo stringhe + docstring + un blocco prompt aggiuntivo. Nessuna logica modificata.

---

---

## Punto 2 — Integrazione LiteLLM Proxy (provider-agnostic, retro-compatibile)

### Cosa risolve

Sganciare il codice agente dalla SDK Anthropic come unico backend, mantenendo:
- la **stessa SDK** (`anthropic.Anthropic`) lato applicazione → zero refactor del tool-use loop;
- la **stessa cache prompt** (`cache_control: ephemeral`) quando si instrada su Claude;
- compatibilità con i test esistenti che mockano `_get_client()`;
- possibilità di switchare a OpenAI / Gemini / Bedrock / Groq cambiando una env var.

L'approccio è **LiteLLM in modalità proxy server**: un sidecar che espone un endpoint `/v1/messages` Anthropic-compatibile e instrada verso il provider scelto. La SDK Anthropic supporta `base_url` override → basta puntarci.

### Architettura

```
┌──────────────┐      x-api-key: $LITELLM_KEY        ┌──────────────────┐
│  Flask app   │  POST /v1/messages (Anthropic API)  │  LiteLLM Proxy   │──→  Anthropic
│  agent loop  ├────────────────────────────────────►│  (Docker sidecar)│──→  OpenAI
│              │  Risposta Anthropic-compat          │  config.yaml     │──→  Gemini
└──────────────┘                                     └──────────────────┘──→  Bedrock
```

- **Default (LiteLLM disabilitato)**: `LITELLM_BASE_URL` non settato → la SDK chiama direttamente `https://api.anthropic.com`. Identico al comportamento attuale.
- **LiteLLM attivo**: `LITELLM_BASE_URL=http://litellm:4000` → la SDK Anthropic invia tutto al proxy, che traduce/instrada.

### File modificati / creati

| File | Tipo | Cosa |
|---|---|---|
| `backend/config/agent_config.py` | edit | Nuove env: `LITELLM_BASE_URL`, `LITELLM_API_KEY`. |
| `backend/services/agent/agent_service.py` | edit | `_get_client()` rispetta `LITELLM_BASE_URL`; helper `_strip_cache_for_non_claude()`. |
| `backend/.env.example` | edit | Documenta nuove env (commentate, default off). |
| `docker/litellm.config.yaml` | **nuovo** | Configurazione proxy: model_list, master_key, log level. |
| `docker-compose.yml` | edit | Aggiunge servizio `litellm` opzionale tramite profile. |
| `docker-compose.override.yml` (`docker/docker-compose.dev.yml`) | edit | Override dev: backend riceve `LITELLM_BASE_URL` se profile attivo. |
| `backend/tests/test_agent/test_litellm_routing.py` | **nuovo** | Verifica `_get_client()` con/senza env. |
| `CLAUDE.md` | edit | Una riga sul nuovo flag e come attivarlo. |
| `docs/litellm-integration.md` | **nuovo** | Guida operativa: come aggiungere provider, gestire chiavi, troubleshooting. |

### Modifiche puntuali

#### a) `backend/config/agent_config.py`

Aggiungere in fondo:
```python
# LiteLLM proxy (optional). When LITELLM_BASE_URL is set, the Anthropic SDK
# is pointed at the proxy instead of api.anthropic.com. This lets us route
# the same tool-use loop to OpenAI/Gemini/Bedrock without code changes.
# When unset, the agent talks directly to Anthropic — same as before.
LITELLM_BASE_URL = os.environ.get('LITELLM_BASE_URL', '').strip() or None
LITELLM_API_KEY = os.environ.get('LITELLM_API_KEY', '').strip() or None
```

#### b) `backend/services/agent/agent_service.py`

Sostituire `_get_client()` (riga 115-118):
```python
def _get_client():
    """Lazy-initialize the Anthropic SDK client.

    If LITELLM_BASE_URL is set, point the SDK at the LiteLLM proxy and
    use LITELLM_API_KEY (or fall back to ANTHROPIC_API_KEY). Otherwise
    talk to api.anthropic.com directly — original behaviour.
    """
    import anthropic
    from config.agent_config import LITELLM_BASE_URL, LITELLM_API_KEY

    if LITELLM_BASE_URL:
        return anthropic.Anthropic(
            api_key=LITELLM_API_KEY or ANTHROPIC_API_KEY,
            base_url=LITELLM_BASE_URL,
        )
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
```

Aggiungere un helper per disinnescare `cache_control` quando il modello non è Claude (i provider non-Anthropic ignorano il marker, ma alcuni proxy/loggers possono lamentarsi):
```python
def _is_claude_model(model: str) -> bool:
    return model.lower().startswith('claude-')

def _strip_cache_markers(blocks: list) -> list:
    """Remove cache_control from content blocks. Used when the active model
    is not Claude — non-Anthropic providers don't support ephemeral caching."""
    return [{k: v for k, v in b.items() if k != 'cache_control'} for b in blocks]
```

E nel `_run_chat()` (intorno alla riga 605), prima di costruire `system_prompt`:
```python
system_prompt = _build_system_prompt(context_type)
tools = _get_cached_tools()
if not _is_claude_model(AGENT_MODEL):
    system_prompt = _strip_cache_markers(system_prompt)
    # tools list still works — cache_control on the last tool is just an extra key
    tools = [{k: v for k, v in t.items() if k != 'cache_control'} for t in tools]
```

> Nota: la SDK Anthropic *accetta* extra keys silenziosamente quando va al proxy, quindi lo stripping è prudente ma non strettamente obbligatorio. Lo facciamo solo se `AGENT_MODEL` non è Claude, così su Claude (anche via proxy) il caching continua a funzionare.

#### c) `docker/litellm.config.yaml` (nuovo)

```yaml
# LiteLLM Proxy configuration.
# https://docs.litellm.ai/docs/proxy/configs
#
# Models are referenced by `model_name` from the application — i.e. whatever
# the app sends as `model` in /v1/messages will be matched here. The
# `litellm_params.model` is what LiteLLM uses to route to the underlying
# provider.

model_list:
  # Default — Anthropic Haiku 4.5 (matches AGENT_MODEL default in agent_config.py)
  - model_name: claude-haiku-4-5-20251001
    litellm_params:
      model: anthropic/claude-haiku-4-5-20251001
      api_key: os.environ/ANTHROPIC_API_KEY

  # Anthropic Sonnet 4.6 — use for premium plan generation if we want
  - model_name: claude-sonnet-4-6
    litellm_params:
      model: anthropic/claude-sonnet-4-6
      api_key: os.environ/ANTHROPIC_API_KEY

  # OpenAI GPT-5 — example fallback / A/B target
  - model_name: gpt-5
    litellm_params:
      model: openai/gpt-5
      api_key: os.environ/OPENAI_API_KEY

  # Google Gemini — example
  - model_name: gemini-2.5-pro
    litellm_params:
      model: gemini/gemini-2.5-pro
      api_key: os.environ/GEMINI_API_KEY

litellm_settings:
  drop_params: true            # silently drop unsupported params per provider
  request_timeout: 90
  num_retries: 1               # let LiteLLM retry once on transient errors

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
  # database_url left unset → run in stateless mode (no key DB).
  # Add database_url to enable per-team virtual keys + spend tracking.
```

#### d) `docker-compose.yml` (edit)

Aggiungere il servizio sotto un **profile** in modo che non parta di default:
```yaml
services:
  litellm:
    image: ghcr.io/berriai/litellm:main-stable
    profiles: ["litellm"]
    container_name: pacemind-litellm
    restart: unless-stopped
    ports:
      - "4000:4000"   # solo se vuoi accesso dall'host; in prod meglio interno
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - OPENAI_API_KEY=${OPENAI_API_KEY:-}
      - GEMINI_API_KEY=${GEMINI_API_KEY:-}
      - LITELLM_MASTER_KEY=${LITELLM_MASTER_KEY:?LITELLM_MASTER_KEY must be set when using the litellm profile}
    volumes:
      - ./docker/litellm.config.yaml:/app/config.yaml:ro
    command: --config /app/config.yaml --port 4000 --num_workers 2
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:4000/health/liveliness"]
      interval: 30s
      timeout: 5s
      retries: 3

  backend:
    # … esistente …
    environment:
      # esistenti…
      - LITELLM_BASE_URL=${LITELLM_BASE_URL:-}
      - LITELLM_API_KEY=${LITELLM_API_KEY:-}
```

Avvio:
- **Standard (no proxy)**: `docker compose up backend frontend nginx postgres` — invariato.
- **Con proxy**: `docker compose --profile litellm up` — fa partire anche il container LiteLLM, e il backend riceve `LITELLM_BASE_URL=http://litellm:4000` (settato in `.env` dell'utente).

#### e) `backend/.env.example`

Aggiungere in fondo:
```bash
# --- LiteLLM Proxy (optional) ---
# Leave both empty to talk directly to Anthropic API (default behaviour).
# Set LITELLM_BASE_URL to route the agent's tool-use loop through LiteLLM.
# Inside docker-compose, the value should be http://litellm:4000.
# LITELLM_BASE_URL=http://litellm:4000
# LITELLM_API_KEY=          # uses ANTHROPIC_API_KEY as fallback if empty
# LITELLM_MASTER_KEY=        # required when using the litellm compose profile
# OPENAI_API_KEY=
# GEMINI_API_KEY=
```

#### f) `backend/tests/test_agent/test_litellm_routing.py` (nuovo)

```python
"""Tests for LiteLLM-aware Anthropic client construction."""
from unittest.mock import patch
import pytest

from services.agent.agent_service import _get_client, _is_claude_model, _strip_cache_markers


class TestClientFactory:
    def test_default_uses_anthropic_directly(self, monkeypatch):
        monkeypatch.setattr('config.agent_config.LITELLM_BASE_URL', None)
        monkeypatch.setattr('config.agent_config.LITELLM_API_KEY', None)
        monkeypatch.setattr('services.agent.agent_service.ANTHROPIC_API_KEY', 'sk-ant-test')
        client = _get_client()
        # SDK exposes the base URL as `_base_url` or via .base_url depending on version
        base = str(getattr(client, 'base_url', '') or getattr(client, '_base_url', ''))
        assert 'api.anthropic.com' in base or base == ''  # SDK default

    def test_litellm_base_url_overrides(self, monkeypatch):
        monkeypatch.setattr('config.agent_config.LITELLM_BASE_URL', 'http://litellm:4000')
        monkeypatch.setattr('config.agent_config.LITELLM_API_KEY', 'sk-litellm-key')
        client = _get_client()
        base = str(getattr(client, 'base_url', ''))
        assert 'litellm' in base

    def test_litellm_falls_back_to_anthropic_key(self, monkeypatch):
        monkeypatch.setattr('config.agent_config.LITELLM_BASE_URL', 'http://litellm:4000')
        monkeypatch.setattr('config.agent_config.LITELLM_API_KEY', None)
        monkeypatch.setattr('services.agent.agent_service.ANTHROPIC_API_KEY', 'sk-ant-fallback')
        client = _get_client()
        # client should construct without raising
        assert client is not None


class TestModelRouting:
    def test_is_claude_model(self):
        assert _is_claude_model('claude-haiku-4-5-20251001')
        assert _is_claude_model('claude-sonnet-4-6')
        assert not _is_claude_model('gpt-5')
        assert not _is_claude_model('gemini-2.5-pro')

    def test_strip_cache_markers(self):
        blocks = [
            {'type': 'text', 'text': 'hi', 'cache_control': {'type': 'ephemeral'}},
            {'type': 'text', 'text': 'no cache here'},
        ]
        out = _strip_cache_markers(blocks)
        assert all('cache_control' not in b for b in out)
        assert out[0]['text'] == 'hi'
        assert out[1]['text'] == 'no cache here'
```

### Effetti collaterali e gotcha

- **`AGENT_MODEL` deve coincidere con `model_name` in `litellm.config.yaml`.** Se l'utente setta `AGENT_MODEL=gpt-5` ma non definisce `gpt-5` nel config, LiteLLM risponde 400. Documentato in `docs/litellm-integration.md`.
- **Streaming**: oggi il loop usa `.create()` non-streaming → nessun problema. Se un giorno passassimo a `messages.stream()`, LiteLLM supporta SSE Anthropic-compatibile.
- **Prompt caching su provider non-Claude**: silenziosamente ignorato. Il costo per chat/plan-gen sale ~10-30% (perdi lo sconto del 90% sui prefissi cached). Da documentare.
- **Tool-use schema**: il proxy traduce `input_schema` → JSON Schema su provider OpenAI/Gemini. Per il nostro caso le definizioni in `tools.py` sono già JSON Schema standard → traduzione lossless.
- **Healthcheck**: il container LiteLLM espone `/health/liveliness`. Il backend non aspetta `litellm` perché il `LITELLM_BASE_URL` è opzionale; se il proxy è giù, le chat falliscono ma il resto dell'app funziona.
- **Sicurezza**: `LITELLM_MASTER_KEY` è la chiave che il backend invia come `x-api-key`. Non confondere con le chiavi provider (`ANTHROPIC_API_KEY`, ecc.) che restano lato proxy. Il `master_key` non deve mai uscire dalla rete docker; non esponiamo la porta `4000` sull'host in produzione.
- **Tests esistenti** (`test_agent_service.py`, `test_persistence.py`): mockano `_get_client()` → continuano a funzionare. Da verificare a fine implementazione che siano verdi senza modifiche.

### Verifica end-to-end

1. **Unit**:
   - `pytest backend/tests/test_agent/test_litellm_routing.py -v` → 5 test verdi.
   - `pytest backend/tests/test_agent/ -v` → no regressioni.

2. **Integration locale (proxy attivo)**:
   ```bash
   # In backend/.env
   echo "LITELLM_BASE_URL=http://litellm:4000" >> backend/.env
   echo "LITELLM_MASTER_KEY=sk-pm-dev-$(openssl rand -hex 16)" >> backend/.env
   echo "LITELLM_API_KEY=$LITELLM_MASTER_KEY" >> backend/.env

   docker compose --profile litellm up -d
   curl -f http://localhost:4000/health/liveliness   # 200 OK

   # Smoke test della chat
   curl -s -X POST localhost:5000/api/agent/chat \
     -H 'Content-Type: application/json' \
     -d '{"message": "ciao", "context_type": "training-plan"}' \
     | jq .response
   ```
   Atteso: risposta valida, log del backend mostra `Round 1 tokens: ...`, log del container LiteLLM mostra una request a `anthropic/claude-haiku-4-5-20251001`.

3. **A/B con altro provider** (opzionale, manuale):
   ```bash
   AGENT_MODEL=gpt-5 OPENAI_API_KEY=... docker compose --profile litellm up backend litellm -d
   # Stessa curl di sopra; verificare che la risposta arrivi e che i tool-use funzionino.
   ```
   Le chiamate a `generate_full_plan` devono ancora funzionare (tool-use schema compatibile via LiteLLM).

4. **Fallback (proxy disabilitato)**:
   - Rimuovere `LITELLM_BASE_URL` da `.env`, `docker compose up backend` → comportamento identico al pre-cambio.

### Stima

- ~50 righe di codice modificate (`agent_service.py` + `agent_config.py`).
- 1 file YAML proxy (~40 righe).
- Modifiche docker-compose (~25 righe sommando override).
- 1 test file (~50 righe).
- 1 doc file (~80 righe).
- Rischio: **medio**. Il path direct-to-Anthropic resta default → safety net ampia. Da testare il path proxy in dev prima di abilitarlo in prod.

---

---

## Punto 3 — Coerenza dell'engine (workout types, fasi, downgrade visibili)

### Cosa risolve

L'engine produce piani che non riflettono ciò che il `SYSTEM_PROMPT` dichiara al modello come disponibile. Questo causa:
- L'LLM "annuncia" all'utente workout che non vedrà mai (es. tempo runs).
- La fase Peak non genera mai `race_simulation` — viene relegato all'ultima settimana, perdendo il senso di "race-specific workouts" della fase di affinamento.
- I downgrade da `hill_repeats → intervals` per limiti mountain budget avvengono in silenzio: l'utente non sa che il piano è stato "annacquato" rispetto alla sua specificità di gara.

### Diagnosi precisa

Confermato via grep:
- `tempo` non compare in `plan_engine.py`. Compare solo in:
  - `plan_compliance_service.py:366` — classificazione *runtime* di un'attività esistente.
  - `route_matcher.py:23` — tolleranze di matching su una route.
  - `prompts.py:148` — promesso all'LLM come tipo valido.
- `race_simulation` in `PHASE_CATALOG` solo per `'Race'` (riga 86). Il prompt promette *"Race-specific workouts in Peak"* (riga 136, 198 di `prompts.py`).
- `back_to_back` in `tools.py` come parametro di `generate_full_plan`, ma `PHASE_CATALOG` non lo elenca; la logica sta solo in `distribute_week` come "metti hard prima del lungo se flag attivo".
- `MOUNTAIN_DOWNGRADE` (riga 55) effettua il declassamento silenziosamente. Nessun warning emesso quando ≥ N declassamenti.

### Modifiche puntuali — `backend/services/plan_engine.py`

#### a) Aggiungere `tempo` come tipo first-class

Nelle costanti (righe ~89-115):
```python
WORKOUT_KM_RANGE = {
    'hill_repeats':    (8, 12),
    'vert_session':    (10, 15),
    'intervals':       (6, 10),
    'tempo':           (8, 14),     # NEW — Z3 sustained, longer than intervals
    'easy':            (6, 10),
    'easy_pickups':    (5, 8),
    # …
}

ELEV_MULTIPLIER = {
    # …
    'intervals':       0.8,
    'tempo':           0.7,         # NEW — moderate elevation, sustained effort
    # …
}

RECOVERY_SLOTS = {
    'intervals':    2,
    'hill_repeats': 2,
    'vert_session': 2,
    'tempo':        2,              # NEW — Z3 needs same buffer as intervals
    'long_run':     2,
}
```

In `PHASE_CATALOG`, aggiungerlo a Build e Peak:
```python
PHASE_CATALOG = {
    'Base':     ['long_run', 'hill_repeats', 'easy', 'easy', 'easy', 'recovery', 'rest'],
    'Build':    ['long_run', 'hill_repeats', 'vert_session', 'intervals', 'tempo', 'easy', 'recovery', 'rest'],
    'Peak':     ['long_run', 'race_simulation', 'hill_repeats', 'vert_session', 'intervals', 'tempo', 'easy', 'rest'],
    # …
}
```

In `_generate_title()` (riga ~635), aggiungere prima di `_resolve_intensity`:
```python
if workout_type == 'tempo':
    if phase == 'Build':
        return f'Tempo run — {km:.0f}km sustained Z3 effort'
    return f'Tempo run — {km:.0f}km at threshold'
```

In `_resolve_intensity()` (riga ~580), aggiungere:
```python
if workout_type == 'tempo':
    return 'hard'
```

In `_select_workouts_for_phase` priority dict (riga ~679):
```python
priority = {
    'race_simulation': 0, 'long_run': 1,
    'hill_repeats': 2, 'vert_session': 3, 'intervals': 4, 'tempo': 4,  # NEW
    'easy_pickups': 5, 'easy_strides': 5,
    'easy': 6, 'recovery': 7,
}
```

In `MOUNTAIN_DOWNGRADE`, **non** aggiungere tempo: tempo è terreno-agnostico, non va declassato. Resta solo per i mountain workouts.

#### b) Far comparire `race_simulation` nelle ultime settimane Peak

Già aggiunto a `PHASE_CATALOG['Peak']` sopra. Bisogna però evitare collisione con la `'Race'` week. La logica attuale di `distribute_week` piazza `race_simulation` in `long_run_day` solo per fase `Race`. Va estesa:

In `distribute_week` (riga ~770-771):
```python
# PRIMA
if phase == 'Race':
    day_slots[long_run_day] = 'race_simulation'

# DOPO
if phase == 'Race':
    day_slots[long_run_day] = 'race_simulation'
elif phase == 'Peak' and 'race_simulation' in available_workouts:
    # In late Peak, allow one race_simulation in place of the long_run.
    # Trigger only on the LAST Peak week before Taper to avoid collision
    # with the actual race rehearsal.
    if week_number == last_peak_week_number:
        day_slots[long_run_day] = 'race_simulation'
```

Per sapere `last_peak_week_number` bisogna passarlo dal layer di orchestrazione. Aggiungere parametro `is_last_peak_week: bool = False` alla signature di `distribute_week` e calcolarlo in `generate_plan()` quando assegna le fasi (in pratica: l'ultima settimana con phase=='Peak' prima della prima Taper).

Alternativa più semplice: lasciare la decisione al `_select_workouts_for_phase` che ritorna sempre `race_simulation` come uno degli output di Peak — il distributore poi lo piazza al posto di un long_run se c'è un long_run disponibile. Da finalizzare in implementazione (dipende da come `distribute_week` consuma la lista).

#### c) Warning espliciti sui downgrade mountain

Il declassamento avviene in `distribute_week` (~riga 850-880, da localizzare in implementazione). Aggiungere:

```python
# Inside distribute_week, after the downgrade loop:
downgraded_count = sum(1 for d in day_slots.values()
                       if d.startswith('_downgraded_'))  # marker temporaneo

# Restituire info al chiamante:
return WeekResult(
    days=days,
    downgraded_workouts=downgraded_count,
    downgrade_reason='mountain_budget_exceeded',
)
```

In `validate_plan_feasibility()` aggiungere una nuova classe di warning:
```python
total_downgrades = sum(w.get('_meta', {}).get('downgraded_workouts', 0) for w in weeks)
total_mountain_planned = sum(...)  # quantitativo originario richiesto

if total_mountain_planned > 0 and total_downgrades / total_mountain_planned > 0.30:
    warnings.append({
        'severity': 'warning',
        'code': 'mountain_specificity_lost',
        'message': (
            f"{total_downgrades} mountain-specific workouts were downgraded to "
            f"flat sessions due to your weekly mountain access budget. This is "
            f"{total_downgrades / total_mountain_planned:.0%} of the originally "
            f"prescribed mountain work. Consider raising mountain_access_per_week "
            f"in your training preferences if your race has significant elevation."
        ),
    })
```

Il warning viene sollevato dall'agente all'utente tramite il flusso esistente (`route_match_summary` + `warnings` in `generate_full_plan`).

#### d) `back_to_back` nel catalogo

`PHASE_CATALOG` non va toccato (back_to_back è un *pattern* non un workout). Ma la `_select_workouts_for_phase` deve garantire che, se `back_to_back=True`, ci sia almeno un `hill_repeats` o `intervals` nella lista per essere piazzato adiacente al long run. L'asserzione esiste implicitamente — aggiungere un test esplicito (vedi Punto 4).

#### e) Concentrare il dislivello — niente più "10 km con 36 m D+" senza senso

**Problema osservato.** Per centrare il target settimanale di D+, l'engine spalma piccoli quantitativi di elevation su tutti i giorni di corsa: una easy da 10 km riceve 36 m, che corrisponde a 3.6 m/km — di fatto una corsa piatta. Nessun runner andrà a cercare *esattamente* 36 m di dislivello su 10 km: o trova un percorso con curvatura naturale (5-10 m/km, niente di intenzionale) oppure va sulla salita vera. Il numero `36 m` è rumore matematico, non un'istruzione di allenamento.

**Causa nel codice.** `ELEV_MULTIPLIER` (riga ~104) prevede:
```python
'easy':            0.5,
'recovery':        0.3,
'easy_pickups':    0.5,
'easy_strides':    0.3,
```
Moltiplicato per `training_ratio` (es. 70 m/km su una gara 50K/3500D+) e poi diviso per la distanza giornaliera, dà target di 35 m, 21 m, ecc. che vengono incollati al giorno tale e quale.

**Strategia di fix.** Due regole nuove che si applicano nella distribuzione (`distribute_week`):

1. **Soglia di "dislivello significativo"** (`MIN_MEANINGFUL_ELEV_DENSITY = 10` m/km). Sotto quella soglia, il workout viene snappato a piatto (`elevation_m = 0` per `easy/recovery/cross_train/strength/rest`). Il valore 0 dice all'utente: *"non cercare salita, fai flat"*.
2. **Conservazione del budget settimanale**. Il dislivello sottratto dalle easy non sparisce: viene **redistribuito** sui giorni che hanno già una vocazione di salita (long_run, hill_repeats, vert_session, race_simulation), in proporzione al loro `ELEV_MULTIPLIER`. Se quei giorni saturano il loro elevation cap (`MAX_ELEV_DENSITY = 80`), il residuo si perde silenziosamente — ed emettiamo un warning `weekly_elev_below_target` se la perdita supera il 15%.

**Modifiche puntuali.**

In costanti (`plan_engine.py` testa file):
```python
# Below this density (m D+ / km), an easy/recovery run is effectively flat.
# We snap to 0 D+ and redistribute the budget to climb-focused workouts.
MIN_MEANINGFUL_ELEV_DENSITY = 10.0

# Workout types that "absorb" redistributed elevation.
ELEV_SINK_TYPES = ('long_run', 'hill_repeats', 'vert_session', 'race_simulation')

# Workout types that get snapped to flat when below threshold.
ELEV_FLATTEN_TYPES = ('easy', 'easy_pickups', 'easy_strides', 'recovery', 'tempo')
```

Nuova funzione helper:
```python
def _redistribute_elevation(days: list[dict], training_ratio: float) -> tuple[list[dict], float]:
    """Snap low-density workouts to flat and pour the saved budget onto
    climb-focused days. Returns (days, residual_unused) where residual_unused
    is the elevation that couldn't be reabsorbed because sink days were
    already at their cap.
    """
    saved = 0.0
    # Pass 1: flatten low-density easy/recovery/tempo days
    for d in days:
        if d['workout_type'] not in ELEV_FLATTEN_TYPES:
            continue
        km = d.get('distance_km', 0) or 0
        elev = d.get('elevation_m', 0) or 0
        if km <= 0 or elev <= 0:
            continue
        density = elev / km
        if density < MIN_MEANINGFUL_ELEV_DENSITY:
            saved += elev
            d['elevation_m'] = 0
            d['notes'] = (d.get('notes') or '') + ' [flat — pace focus, ignore elevation]'

    if saved <= 0:
        return days, 0.0

    # Pass 2: distribute saved elevation onto sink days, weighted by ELEV_MULTIPLIER
    sink_days = [d for d in days if d['workout_type'] in ELEV_SINK_TYPES]
    if not sink_days:
        return days, saved   # nothing to absorb — caller decides whether to warn

    weights = [ELEV_MULTIPLIER.get(d['workout_type'], 0) for d in sink_days]
    total_weight = sum(weights) or 1.0

    residual = saved
    for d, w in zip(sink_days, weights):
        share = saved * (w / total_weight)
        # Cap: don't blow past MAX_ELEV_DENSITY on this day
        km = d.get('distance_km', 0) or 0
        current = d.get('elevation_m', 0) or 0
        cap = MAX_ELEV_DENSITY * km if km > 0 else current + share
        addable = max(0, cap - current)
        applied = min(share, addable)
        d['elevation_m'] = round(current + applied)
        residual -= applied

    return days, max(0, residual)
```

Chiamarla dentro `distribute_week`, **dopo** che le distance/elevation sono assegnate ma **prima** di costruire le `DayWorkout` finali. Il residuo va segnalato:

```python
# Inside distribute_week, after elevation assignment:
days, residual = _redistribute_elevation(days, training_ratio)
target_weekly_elev = sum(d['elevation_m'] for d in days) + residual
if residual / max(target_weekly_elev, 1) > 0.15:
    week_meta['warnings'].append({
        'severity': 'info',
        'code': 'weekly_elev_below_target',
        'message': (
            f"Week elevation target couldn't be fully met: {residual:.0f}m "
            f"D+ left unallocated because climb-focused days were already "
            f"at the elevation density cap. Consider raising "
            f"max_mountain_distance_km or adding a vert_session."
        ),
    })
```

**Effetti attesi sull'output.**
- Una easy 10 km su gara con `training_ratio=70` non riceverà più 35 m (era già sotto soglia 10): viene messa a 0 m + nota `[flat — pace focus]`. Il long_run e il hill_repeats della stessa settimana assorbono i ~35 m saltati.
- Una easy 10 km su gara con `training_ratio=20` (rolling hills) riceverà 100 m → 10 m/km, **sopra soglia**: lasciata invariata, è un'andatura collinare credibile.
- Il totale settimanale di D+ resta uguale (al netto del residuo, di solito < 15%).

**Test specifico** (aggiungere a `test_plan_engine_workout_catalog.py` o nuovo `test_plan_engine_elevation_distribution.py`):
```python
def test_no_flat_workout_has_pseudo_elevation():
    """Easy/recovery runs must be either truly flat (0m) or above the
    meaningful-density threshold (>= MIN_MEANINGFUL_ELEV_DENSITY m/km)."""
    weeks = generate_plan(
        total_weeks=10, race_distance_km=50, race_elevation_m=3500,
        race_date='2026-08-01',
        athlete_weekly_km=45, athlete_weekly_elev=1500,
        athlete_longest_run_km=24,
        athlete_category='cat_2',
        long_run_day='Saturday', rest_days=['Monday'],
        prefs={'max_weekly_km': 80, 'terrain_profile': 'mountain'},
    )
    for w in weeks:
        for d in w['days']:
            if d['workout_type'] not in ELEV_FLATTEN_TYPES:
                continue
            km = d.get('distance_km', 0) or 0
            elev = d.get('elevation_m', 0) or 0
            if km <= 0:
                continue
            if elev > 0:
                density = elev / km
                assert density >= MIN_MEANINGFUL_ELEV_DENSITY, (
                    f"Week {w['week_number']} {d['day']}: {d['workout_type']} "
                    f"has {elev}m / {km}km = {density:.1f} m/km — sub-threshold"
                )
```

**Stima Punto 3e.** ~50 righe nuove in `plan_engine.py`, 1 test, ~30 righe.

**Rischio.** Le 4 suite esistenti del plan_engine potrebbero asserire valori esatti di elevation per giorni easy/recovery che ora cambiano. Da rieseguire prima/dopo:
```bash
pytest backend/tests/test_services/test_plan_engine_*.py -v
```
Se qualche test si rompe perché si aspettava `easy.elevation_m == 35`, va aggiornato all'aspettativa nuova (`== 0` o `>= 100` a seconda del training_ratio del fixture).

### Modifiche `backend/services/agent/prompts.py`

Allineare la "Workout Types" section (righe 145-156) con la realtà:
```markdown
### Workout Types (engine output)
- **easy**: Low effort, conversational pace
- **tempo**: Sustained Z3 threshold effort (8-14 km)        ← già listato, ora veramente prodotto
- **intervals**: Z4 hard repeats with recovery
- **long_run**: Extended duration at easy-moderate effort
- **hill_repeats**: Uphill intervals for climbing strength
- **vert_session**: Elevation accumulation (1000m+ D+)
- **race_simulation**: Race-specific effort profile workout — used in
  the last Peak week as a dress rehearsal, and in Race week.       ← chiarito
- **back_to_back**: Multi-day fatigue simulation (long_run + hard
  effort the next day) — enabled via the back_to_back parameter.
- **rest**: Complete rest day
- **cross_train**: Non-running activity
- **recovery**: Very easy, shorter than easy runs
- **strength**: Strength & conditioning (0 km, 0 elev)
```

### Stima Punto 3

- `plan_engine.py`: ~25 righe modificate, ~30 nuove (tempo + race_simulation + warning).
- `prompts.py`: ~12 righe (riformulazione lista workout types).
- Rischio: **medio**. L'engine ha già 4 file di test, ma le modifiche toccano cataloghi e fasi — potrebbero rompere asserzioni esistenti. Da eseguire `pytest backend/tests/test_services/test_plan_engine_*.py` prima e dopo per confronto.

---

## Punto 4 — Test mirati per le regressioni del Punto 3

I test esistenti coprono: audit, capacity caps, mountain budget, terrain. Mancano test su:
- **invariante catalogo**: ogni workout_type emesso esiste in `WORKOUT_KM_RANGE` e `ELEV_MULTIPLIER`;
- **assegnazione fasi** combinatoriale;
- **race_simulation** comparsa solo nell'ultima Peak;
- **back_to_back** adiacenza al long_run;
- **tempo** comparsa in Build/Peak (impedisce regressione del Punto 3a).

### Nuovi file di test

#### a) `backend/tests/test_services/test_plan_engine_workout_catalog.py`

```python
"""Invariant: every workout_type the engine emits is fully described in the
constants tables (WORKOUT_KM_RANGE, ELEV_MULTIPLIER). Catches the historical
gap where 'tempo' was promised in the prompt but never produced.
"""
import pytest
from services import plan_engine
from services.plan_engine import (
    WORKOUT_KM_RANGE, ELEV_MULTIPLIER, PHASE_CATALOG, generate_plan,
)


def _emitted_types(weeks):
    return {d['workout_type'] for w in weeks for d in w['days']}


@pytest.mark.parametrize('category', ['cat_1', 'cat_2'])
@pytest.mark.parametrize('total_weeks', [4, 8, 12, 18])
def test_every_emitted_type_is_in_constants(category, total_weeks):
    weeks = generate_plan(
        total_weeks=total_weeks,
        race_distance_km=50, race_elevation_m=2500,
        race_date='2026-08-01',
        athlete_weekly_km=40, athlete_weekly_elev=1000,
        athlete_longest_run_km=22,
        athlete_category=category,
        long_run_day='Saturday', rest_days=['Monday'],
        prefs={'max_weekly_km': 80, 'terrain_profile': 'rolling_hills'},
    )
    types = _emitted_types(weeks)
    missing_km = types - set(WORKOUT_KM_RANGE.keys())
    missing_elev = types - set(ELEV_MULTIPLIER.keys())
    assert not missing_km, f"types missing from WORKOUT_KM_RANGE: {missing_km}"
    assert not missing_elev, f"types missing from ELEV_MULTIPLIER: {missing_elev}"


def test_phase_catalog_types_all_known():
    """No catalog entry references an unknown workout type."""
    all_known = set(WORKOUT_KM_RANGE.keys()) | {'rest'}
    for phase, catalog in PHASE_CATALOG.items():
        unknown = set(catalog) - all_known
        assert not unknown, f"phase {phase} catalog has unknown types: {unknown}"


def test_tempo_appears_in_build_or_peak():
    """Regression test: tempo must be reachable in build/peak phases."""
    weeks = generate_plan(
        total_weeks=12,
        race_distance_km=42, race_elevation_m=1500,
        race_date='2026-08-01',
        athlete_weekly_km=50, athlete_weekly_elev=1200,
        athlete_longest_run_km=25,
        athlete_category='cat_2',
        long_run_day='Saturday', rest_days=['Monday'],
        prefs={'max_weekly_km': 80, 'terrain_profile': 'rolling_hills'},
    )
    types = _emitted_types(weeks)
    assert 'tempo' in types, (
        f"engine never emitted 'tempo' — produced types: {sorted(types)}"
    )
```

#### b) `backend/tests/test_services/test_plan_engine_phases.py`

```python
"""Phase assignment: combinatorial coverage of total_weeks x category."""
import pytest
from services.plan_engine import assign_phases


@pytest.mark.parametrize('total_weeks', [2, 4, 6, 8, 12, 18, 24])
@pytest.mark.parametrize('category', ['cat_1', 'cat_2'])
def test_assign_phases_invariants(total_weeks, category):
    phases = assign_phases(total_weeks, category)
    assert len(phases) == total_weeks
    assert phases[-1] == 'Race', "last week must be Race"
    if total_weeks >= 6:
        assert phases.count('Taper') == 2
    elif total_weeks >= 2:
        assert phases.count('Taper') == 1
    if total_weeks >= 8:
        # Cat 1 should have more Base than Cat 2 for the same length
        if category == 'cat_1':
            assert phases.count('Base') >= 2


def test_recovery_inserted_in_build_block():
    phases = assign_phases(total_weeks=12, athlete_category='cat_2')
    # 3:1 modulation — at least one Recovery in the middle
    assert 'Recovery' in phases
```

#### c) `backend/tests/test_services/test_plan_engine_race_simulation.py`

```python
"""race_simulation must appear:
- on the long-run day of the last Peak week (dress rehearsal)
- on the long-run day of the Race week
…and nowhere else.
"""
from services.plan_engine import generate_plan, assign_phases


def test_race_simulation_only_in_peak_last_and_race_week():
    total_weeks = 12
    weeks = generate_plan(
        total_weeks=total_weeks,
        race_distance_km=50, race_elevation_m=2500,
        race_date='2026-08-01',
        athlete_weekly_km=45, athlete_weekly_elev=1500,
        athlete_longest_run_km=24,
        athlete_category='cat_2',
        long_run_day='Saturday', rest_days=['Monday'],
        prefs={'max_weekly_km': 80, 'terrain_profile': 'rolling_hills'},
    )
    phases = assign_phases(total_weeks, 'cat_2')
    last_peak_idx = max(i for i, p in enumerate(phases) if p == 'Peak')

    for i, w in enumerate(weeks):
        types = [d['workout_type'] for d in w['days']]
        if i == last_peak_idx or i == total_weeks - 1:
            assert 'race_simulation' in types, f"week {i+1} missing race_simulation"
        else:
            assert 'race_simulation' not in types, (
                f"week {i+1} (phase={phases[i]}) has unexpected race_simulation"
            )
```

#### d) `backend/tests/test_services/test_plan_engine_back_to_back.py`

```python
"""When back_to_back=True, a hard session sits the day before the long_run."""
from services.plan_engine import generate_plan, DAYS_OF_WEEK, HARD_WORKOUTS


def test_back_to_back_pattern():
    weeks = generate_plan(
        total_weeks=10,
        race_distance_km=80, race_elevation_m=4000,
        race_date='2026-08-01',
        athlete_weekly_km=60, athlete_weekly_elev=2000,
        athlete_longest_run_km=35,
        athlete_category='cat_2',
        long_run_day='Sunday', rest_days=['Monday'],
        back_to_back=True,
        prefs={'max_weekly_km': 100, 'terrain_profile': 'mountain'},
    )
    # Find at least one Build/Peak week with the pattern
    found = False
    for w in weeks:
        if w['theme'].lower() not in {'build', 'peak'}:
            continue
        days = {d['day']: d['workout_type'] for d in w['days']}
        # Saturday before Sunday long_run should be a hard effort
        if days.get('Sunday') == 'long_run' and days.get('Saturday') in HARD_WORKOUTS:
            found = True
            break
    assert found, "no Build/Peak week shows the back_to_back pattern"
```

#### e) `backend/tests/test_services/test_plan_engine_mountain_warning.py`

```python
"""When mountain budget forces ≥30% downgrade of mountain workouts,
validate_plan_feasibility raises a 'mountain_specificity_lost' warning.
"""
from services.plan_engine import generate_plan, validate_plan_feasibility


def test_mountain_specificity_warning_when_budget_low():
    # Athlete with very tight mountain access training for a high-D+ race
    weeks = generate_plan(
        total_weeks=12,
        race_distance_km=80, race_elevation_m=5000,
        race_date='2026-08-01',
        athlete_weekly_km=60, athlete_weekly_elev=2500,
        athlete_longest_run_km=30,
        athlete_category='cat_2',
        long_run_day='Saturday', rest_days=['Monday'],
        prefs={
            'max_weekly_km': 100,
            'terrain_profile': 'mountain',
            'mountain_access_per_week': 0.5,   # very limited
        },
    )
    warnings = validate_plan_feasibility(
        weeks,
        prefs={'max_weekly_km': 100, 'terrain_profile': 'mountain',
               'mountain_access_per_week': 0.5},
        terrain_profile='mountain',
        race_distance_km=80, race_elevation_m=5000,
    )
    codes = [w.get('code') for w in warnings if isinstance(w, dict)]
    assert 'mountain_specificity_lost' in codes
```

### Stima Punto 4

- 5 nuovi file di test, ~250 righe totali.
- Rischio: **basso**. Test puri sull'engine deterministico, nessuna I/O.

---

## Verifica end-to-end finale (tutti i punti)

1. **Lint + suite completa**:
   ```bash
   cd backend && source venv/bin/activate
   ruff check .
   pytest -v -m "not slow"   # tutta la suite tranne training modello
   ```
   Atteso: zero errori, zero regressioni.

2. **Smoke test agente (default, no proxy)**:
   ```bash
   docker compose up backend -d
   curl -s -X POST localhost:5000/api/agent/chat \
     -H 'Content-Type: application/json' \
     -d '{"message": "Crea un piano 50K con 3000 D+ tra 12 settimane", "context_type": "training-plan"}' \
     | jq -r '.response, (.tool_calls[].tool)'
   ```
   Verifiche:
   - La risposta NON contiene `book`, `chapter`, `manual`, `libro`, `capitolo`, `sezione [0-9]`.
   - `generate_full_plan` viene chiamato e produce settimane con almeno un `tempo` workout in Build.
   - Le ultime 1-2 settimane Peak contengono `race_simulation`.

3. **Smoke test LiteLLM Proxy**:
   ```bash
   # .env: LITELLM_BASE_URL=http://litellm:4000, LITELLM_MASTER_KEY=...
   docker compose --profile litellm up -d
   curl -f http://localhost:4000/health/liveliness
   # ripetere lo smoke test della chat — tutto deve funzionare identico
   ```

4. **Smoke test multi-provider** (manuale, opzionale):
   ```bash
   AGENT_MODEL=gpt-5 docker compose --profile litellm up backend litellm -d
   # Stessa curl. Verifica che generate_full_plan funzioni anche su GPT-5.
   ```

---

## Ordine commit (su `claude/review-workout-system-zkxWz`)

Tre commit logici, in quest'ordine:

1. **`feat(agent): coaching voice — drop book/chapter references`**
   - Modifiche del Punto 1 (knowledge.py, prompts.py, validation.py).
   - `test_coaching_voice.py`.
   - Cambiamento più visibile per l'utente, ha senso che vada per primo.

2. **`feat(plan-engine): tempo, race_simulation, mountain downgrade warning`**
   - Modifiche del Punto 3 (plan_engine.py, prompts.py allineamento workout types).
   - I 5 test del Punto 4.
   - Coerenza interna; isolato dal Punto 1 e dal Punto 2.

3. **`feat(agent): optional LiteLLM proxy routing`**
   - Modifiche del Punto 2 (config, agent_service, docker, .env.example, docs).
   - `test_litellm_routing.py`.
   - Infrastruttura; default off → zero rischio per chi non l'attiva.

Ogni commit deve passare `pytest -m "not slow"` da solo (no commit-by-commit broken).

**Push finale** (fuori da plan mode):
```bash
git push -u origin claude/review-workout-system-zkxWz
```

Su richiesta esplicita dell'utente, **non** apriamo PR finché non chiede.

---

## Documento di piano nel repo

A inizio implementazione, copia di questo file:
- da `/root/.claude/plans/pianifica-tutti-i-punti-compressed-bee.md`
- a `docs/plans/workout-system-review.md` (o `docs/PLANS/` se preferito)

Così il piano resta versionato e linkabile dal PR.

---

## Decisioni confermate dall'utente

1. **`tempo` first-class** → procedo come da Punto 3a (aggiunta a `WORKOUT_KM_RANGE`, `ELEV_MULTIPLIER`, `PHASE_CATALOG['Build']`/`['Peak']`, `_generate_title`, `_resolve_intensity`, `RECOVERY_SLOTS`). L'engine emetterà tempo run nelle settimane Build/Peak.
2. **Piano in repo** → copio `/root/.claude/plans/pianifica-tutti-i-punti-compressed-bee.md` su `docs/plans/workout-system-review.md` come parte del **primo commit** dell'implementazione, prima delle modifiche di codice. Resta versionato sul branch e linkabile dal PR.
3. **Onboarding time-first** → vedi Punto 5 qui sotto. Approvato:
   - Solo input in ore (km / D+ diventano computed read-only).
   - Pre-fill da Strava con inferenza adattiva (window dinamico).
   - Default conservativi se confidence troppo bassa.

---

## Punto 5 — Onboarding "time-first" + inferenza adattiva da Strava

> Aggiunto dopo il Commit 1. Sostituisce il wizard attuale `_handle_start_onboarding_questionnaire`.

### Cosa risolve

Il wizard di oggi chiede **km settimanali** e **km del lungo** come vincoli primari. Per chi corre lento "max 50 km/sett" può voler dire 6h o 9h di tempo libero richiesto — molto diverso. Il vero vincolo dell'utente è quasi sempre il **tempo**, e il tempo cambia drasticamente con il D+ (10 km piatti ≠ 10 km con 800 m D+). Inoltre il wizard non si pre-compila dai dati Strava già sincronizzati, costringendo l'utente a indovinare valori che il sistema potrebbe dedurre.

### Principio architetturale

**Tempo = unità primaria, km = display derivato.**

L'utente dichiara budget orario (settimanale, midweek, lungo). L'engine converte in km/D+ usando il physics model personalizzato (`UserLearnedParams`: `v_flat`, `k_up`, `fatigue_alpha`). I campi `max_weekly_km` e `max_long_run_km` esistenti restano nel DB ma diventano **derived**, calcolati live e mostrati come anteprima read-only.

### Inferenza adattiva da Strava

**Problema reale**: 50 attività possono coprire 8 settimane (utente 6x/sett) o 25 settimane (utente 2x/sett). Un lookback fisso non funziona.

**Soluzione**: lookback espandibile, confidence basata su densità campioni.

```
Algoritmo:
  window = 12 settimane
  while True:
    activities = Strava activities in last `window` weeks
    weeks_active = settimane con >= 1 attività
    if len(activities) >= 30 AND weeks_active >= 8:
      break  # high confidence
    if window >= 52:
      break  # cap
    window = next_step(window)  # 12 → 16 → 24 → 36 → 52

Classificazione:
  high   → activities >= 30 AND weeks_active >= 8
  medium → activities >= 12 AND weeks_active >= 4 (ma < high)
  low    → activities < 12 OR weeks_active < 4
```

**La sync Strava già pesca 365 giorni di storico** (`strava_service.py:171`, `get_timestamp_for_last_year`). Niente da modificare lato sync — il fix è solo nell'inferenza.

### UX per livello di confidence

| Confidence | Slider pre-fill | Banner | Interazione |
|---|---|---|---|
| `high` | mediane su window adattivo | nessuno | l'utente conferma |
| `medium` | mediane su window adattivo | "Stima da {weeks_active} settimane di Strava — modifica se non corrisponde" | l'utente verifica |
| `low` | default conservativi: 4 h/sett, 1 h midweek, 2 h lungo, 0 mountain | "Non ho abbastanza storico — compila tu" | l'utente compila |

### Nuovo servizio: `services/training_capacity_inference.py`

```python
def infer_capacity(user_id: int) -> dict:
    """Infer training time budget from the user's Strava history.

    Adaptive lookback: starts at 12 weeks and expands up to 52w until we
    have ≥ 30 activities AND ≥ 8 active weeks (high confidence) or hit
    the cap.

    Returns:
      {
        'available_hours_per_week':       float,
        'usual_midweek_hours':            float,
        'max_long_run_hours':             float,
        'long_run_day_inferred':          str,
        'mountain_runs_per_week':         float,    # D+ >= 300m / week
        'mountain_days_inferred':         list[str],
        'usual_mountain_hours':           float,
        'lookback_weeks_used':            int,
        'sample_size_weeks':              int,
        'sample_size_activities':         int,
        'confidence':                     'high' | 'medium' | 'low',
        'fallback_used':                  bool,
      }
    """
```

Riusa `StravaActivity.streams['time']` (durata reale, non stimata da km × pace) e `StravaActivity.total_elevation_gain`. Riusa `infer_user_terrain_profile()` esistente per il profilo terreno.

### Helper conversione ore ↔ km/D+

In `services/physics_model/time_budget.py` (nuovo):

```python
def predict_distance_for_time(
    hours: float,
    training_ratio_m_per_km: float,
    learned_params: UserLearnedParams | None,
    effort: str = 'long_run',  # 'easy' | 'long_run' | 'tempo'
) -> tuple[float, float]:
    """Given a time budget and a target elevation density, return (km, m_d+)
    the runner can realistically cover at the requested effort.

    Uses Minetti pace model + learned v_flat + k_up. Effort discount on
    v_flat: easy=0.85, long_run=0.78, tempo=0.93.
    Falls back to median trail-runner constants if learned_params is None.
    """

def predict_time_for_distance(km, m_d_plus, learned_params, effort) -> float:
    """Inverse for live preview in wizard."""
```

Implementazione thin sopra `physics_model/core.py:predict_segment_pace` (già minetti-based) — non duplicare la formula.

### Wizard ridisegnato

`_handle_start_onboarding_questionnaire` ritorna nuovo schema.

**Step 1 — Time budget** (primario):
- `available_hours_per_week` (slider 3-15 h, default = inferred)
- `usual_midweek_hours` (slider 0.5-2.5 h, default = inferred)
- `max_long_run_hours` (slider 1-8 h, default = inferred, ora **obbligatorio**)
- `long_run_day` (select, default = giorno modale)
- **Live preview**: "≈ 45 km / 1100m D+ in your typical week"

**Step 2 — Mountain** (rivisto, time-first):
- `mountain_access_per_week` (slider 0-7 step 0.5, default = inferred)
- `mountain_days` (multiselect, default = inferred)
- `max_mountain_hours_per_outing` (slider 1-10 h, default = inferred) — sostituisce `max_mountain_distance_km`

**Step 3 — Terrain & strength**: invariato (riusa il codice attuale).

**Step 4 — Preview** (nuovo, terminale):
- Calcolo live tramite `time_budget.py`: "Riepilogo: ≈ {km}km/sett, ~{elev}m D+. Lungo: {lr_km}km / {lr_elev}m D+ in {h:mm}".

### Nuovo agent tool: `preview_capacity`

```python
{
  'name': 'preview_capacity',
  'description': 'Compute the km, elevation gain, and long-run duration that '
                 'a given hours-budget translates to, for the calling user.',
  'input_schema': {
    'properties': {
      'available_hours_per_week':  {'type': 'number'},
      'usual_midweek_hours':       {'type': 'number'},
      'max_long_run_hours':        {'type': 'number'},
      'training_ratio_m_per_km':   {'type': 'number'},
    },
    'required': ['available_hours_per_week', 'max_long_run_hours'],
  },
}
```

Handler in `tool_handlers/training.py`. L'agente può chiamarlo in chat per rispondere a "se aumento di 1h al sabato, quanti km in più?".

### Engine: nuovi cap temporali in `plan_engine.py`

**1. Cap durata workout midweek**:
```python
# In distribute_week, dopo aver assegnato km/elev a un giorno feriale:
estimated_hours = predict_time_for_distance(km, elev, learned_params, effort='easy')
if estimated_hours > prefs.usual_midweek_hours * 1.15:  # 15% tolleranza
    km, elev = scale_to_time_budget(prefs.usual_midweek_hours, ratio)
```

**2. Cap durata lungo** (rafforza l'attuale `max_long_run_hours`):
```python
# In compute_weekly_targets, dopo il calcolo di long_run_km:
estimated_lr_hours = predict_time_for_distance(long_run_km, long_run_elev, ..., effort='long_run')
if prefs.max_long_run_hours and estimated_lr_hours > prefs.max_long_run_hours:
    # priorità: ridurre prima il km, poi il D+ (mantieni specificità di terreno)
    long_run_km, long_run_elev = scale_long_run_to_time(prefs.max_long_run_hours, ...)
```

**3. Warning settimanale `weekly_hours_above_cap`** (in `validate_plan_feasibility`):
```python
weekly_hours_estimate = sum(
    predict_time_for_distance(d['distance_km'], d['elevation_m'], ..., effort=effort_for(d['workout_type']))
    for d in week['days']
)
if weekly_hours_estimate > prefs.available_hours_per_week * 1.10:
    warnings.append({
        'severity': 'warning',
        'code': 'weekly_hours_above_cap',
        'message': f"Week {wn} estimated {weekly_hours_estimate:.1f}h vs your {prefs.available_hours_per_week:.1f}h/week budget.",
    })
```

I cap esistenti su `max_weekly_km` / `max_long_run_km` **rimangono come safety net secondario**. Il driver primario diventa il tempo.

### DB / Migrazione

`UserTrainingPreferences` ha già:
- `max_hours_per_day` ✓ (riusato)
- `max_long_run_hours` ✓ (riusato, ora obbligatorio)

Servono **3 nuovi campi** (Float, nullable):
- `available_hours_per_week` — vincolo primario settimanale
- `usual_midweek_hours` — durata tipica giorni feriali
- `max_mountain_hours_per_outing`

Una sola Alembic migration **additiva**. Backfill on-read: alla prima lettura post-migration, se `available_hours_per_week` è NULL e l'utente ha `max_weekly_km`, derivare `available_hours_per_week ≈ max_weekly_km × pace_min_km / 60`. Persistere al primo `save_training_preferences`.

`max_weekly_km` e `max_long_run_km` **restano nel DB** come campi derivati (aggiornati lato server al save).

### File modificati / creati

| File | Tipo | Cosa |
|---|---|---|
| `backend/services/training_capacity_inference.py` | **nuovo** | `infer_capacity` adattiva. |
| `backend/services/physics_model/time_budget.py` | **nuovo** | `predict_distance_for_time`, `predict_time_for_distance`, `scale_to_time_budget`. |
| `backend/services/agent/tool_handlers/training.py` | edit | Wizard riscritto + nuovo `_handle_preview_capacity`. |
| `backend/services/agent/tools.py` | edit | Tool definition `preview_capacity`. |
| `backend/services/agent/tool_handlers/__init__.py` | edit | Mappa handler. |
| `backend/services/plan_engine.py` | edit | Cap temporali + warning hours. |
| `backend/services/plan_orchestrator.py` | edit | Passa `learned_params` all'engine. |
| `backend/models/user_training_preferences.py` | edit | 3 nuovi campi nullable. |
| `backend/migrations/versions/<hash>_add_time_budget_prefs.py` | **nuovo** | Alembic additive. |
| `backend/api/training_plan.py` | edit | Endpoint preferences ritorna anche derived. |
| `frontend/src/components/TrainingPreferencesWizard.vue` | edit | Render schema in ore + preview live. |
| `frontend/src/locales/{en,it}.json` | edit | Stringhe nuove. |
| `backend/tests/test_services/test_training_capacity_inference.py` | **nuovo** | 3 confidence levels + edge cases. |
| `backend/tests/test_services/test_time_budget.py` | **nuovo** | Round-trip + sanity gradient. |
| `backend/tests/test_plan_engine_time_caps.py` | **nuovo** | Cap orari midweek/lungo. |

Stima: ~700 righe nuovo codice, ~150 righe edit, frontend ~120 righe, migration ~20 righe.

**3 commit logici:**
1. `feat(prefs): time-budget inference + physics conversion helpers` (servizio + helper + test).
2. `feat(onboarding): time-first wizard with adaptive Strava inference` (wizard + tools + frontend + migration).
3. `feat(engine): hours-based caps + weekly_hours_above_cap warning` (engine + orchestrator + test).

### Verifica end-to-end

1. **Unit**:
   - `pytest backend/tests/test_services/test_training_capacity_inference.py -v` — 3 confidence levels.
   - `pytest backend/tests/test_services/test_time_budget.py -v` — round-trip + sanity.
   - `pytest backend/tests/test_plan_engine_time_caps.py -v` — cap orari rispettati.
   - `pytest backend/tests/test_agent/ -v` — no regressioni.

2. **Integration**:
   - Utente con 50 attività su 25 settimane → `confidence='medium'`, `lookback_weeks_used=24`, slider pre-compilati. Banner mostrato.
   - Utente con 8 attività su 4 settimane → `confidence='low'`, default conservativi.
   - Utente regolare 5x/sett, 60+ atti → `confidence='high'`, no banner.
   - Forzare `available_hours_per_week=4`, `max_long_run_hours=2.5`, generare piano 50K trail → engine produce settimane con `weekly_hours_estimate ≤ 4.4h`, lungo `≤ 2.5h`.

3. **Manuale via UI dev**:
   - `docker compose up`, login con storico Strava.
   - `/training-plan` → "Inizia onboarding" → slider pre-compilati, preview live.
   - Cambiare `available_hours_per_week` da 8 a 12 → preview aggiornato live.
   - Salvare → DB ha `available_hours_per_week=12`, `max_weekly_km` derivato e aggiornato.

### Rischi e gotcha

- **Calibrazione mancante** (`UserLearnedParams` vuoto): `predict_distance_for_time` cade su pace default 6:30/km. Sottostima chi è veloce / sovrastima chi è lento. Mitigazione: dopo prima sync calibrazione, ricalcolare i derived al volo nei piani esistenti.
- **Stagionalità**: 25w di lookback può includere fasi di carico diverse. Mitigazione: la mediana è robusta agli outlier; loggare CV e flaggare confidence `low` se CV > 0.6.
- **Onboarding già fatto da utenti esistenti**: backfill on-read evita di rifare tutto. Wizard riapribile a mano.
- **Costo agent del live preview**: implementare il preview come **funzione locale frontend** (formula chiusa lato JS) per i casi semplici (no calibrazione) e fall-back a tool call solo se serve la calibrazione fine.

---

> Punto 5 si esegue **dopo** Commit 2 e Commit 3 del piano originale, oppure prima — è isolato e può andare anche su un branch dedicato `claude/onboarding-time-first-zkxWz`.
