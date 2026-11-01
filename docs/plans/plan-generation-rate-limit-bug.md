# Plan generation hits Anthropic 429 rate limit — non-deterministic LLM path used despite deterministic engine being available

**Tag:** `coach-review` / `agent-architecture`
**Status:** open
**Severity:** high (blocks plan creation for any race ≥ ~10 weeks)

## Summary

Creating a training plan for a long race (e.g. 6h target → ~12-16 weeks) reliably triggers an Anthropic `rate_limit_error` (429, 50k ITPM on `claude-haiku-4-5-20251001`):

> This request would exceed your organization's rate limit of 50,000 input tokens per minute (org: 14a8d64d-…, model: claude-haiku-4-5-20251001).

The plan **never finishes generating** — the user sees a hard error mid-flow and the calendar is left in an inconsistent partial state.

## Root cause

There are two coexisting code paths for plan creation, and the agent is taking the wrong one:

| Tool | Implementation | API calls | Deterministic? |
|---|---|---|---|
| `generate_full_plan` (`backend/services/agent/tool_handlers/training.py:392`) | Calls `plan_engine.generate_plan()` (pure Python) via `plan_orchestrator.generate_plan_with_routes` | **1** | **Yes** |
| `generate_training_week` (`backend/services/agent/tool_handlers/training.py:151`) | LLM emits the JSON for each week, Python validates | **N** (one per week) | **No** |

`generate_full_plan`'s own tool description (`backend/services/agent/tools.py:665`) flags it as **"PREFERRED over generate_training_week"**.

But the system prompt still steers the agent the other way (`backend/services/agent/prompts.py:139-143`):

> "Design ALL weeks at once and submit them in a single `generate_training_week` call using the `weeks` array (batch mode)."

…and the batch mode referenced there has since been removed (per project memory: *"generate_training_week simplified to single-week mode only — Haiku can't handle batch"*), so what actually runs is **N sequential single-week calls** with SSE streaming (one week per call → one Claude API request per week).

### Why this hits the 50k ITPM limit

Each `generate_training_week` call carries:

- System prompt (~5.3k tokens, coaching knowledge auto-injected for `training-plan` context — see `agent_service.py:236`)
- Tool schemas (`tools.py` is 1354 lines → ~15-25k tokens)
- Growing message history across tool-use rounds (`agent_service.py:653`)

Even with prompt caching enabled (`cache_control: ephemeral` on system + last tool), **`cache_read_input_tokens` still count toward the ITPM rate limit at face value**. So for a 12-16 week plan:

- Week 1 request: ~25k cache_create + a few k uncached
- Week 2 request (within the same minute): ~25k cache_read + history
- → 2 weeks ≈ 50k ITPM → **429**

Claude Haiku 4.5 default org tier is 50k ITPM, which this flow saturates after **~2 weeks of generation**. Anything longer than ~10 weeks is essentially guaranteed to fail.

## Reproducer

1. Authenticated user, default tier (Haiku 4.5, 50k ITPM).
2. Open agent in `training-plan` context.
3. Ask for a plan targeting a long race (e.g. *"piano per gara fino a 6h"*, ≥12 weeks).
4. Agent calls `generate_training_week` once per week via SSE.
5. After ~2-3 weeks the next call fails with:

```
Claude API error: Error code: 429 - rate_limit_error
"This request would exceed your organization's rate limit of 50,000 input tokens per minute"
```

The partial plan is left in an inconsistent state on the calendar.

## Why this is bad design (beyond the immediate bug)

1. **Plan generation should be deterministic.** The deterministic engine (`plan_engine.generate_plan`) already exists, is already tested, and is gated by the same readiness checks. Routing it through an LLM that re-emits week JSON adds non-determinism (different plans for the same inputs), validation churn (`quality_warnings` retries), and N× cost — for zero coaching benefit, since the engine outputs are then *validated against the same coaching rules anyway*.
2. **The streaming UX is the only justification for the LLM path**, and it can be preserved without LLM round-trips: run `plan_engine.generate_plan()` once on the server, then emit SSE `week` events from the result on a timer to keep the per-week reveal animation.
3. **`tools.py` schema is huge** (~15-25k tokens) and is sent on every call. The `training-plan` context only needs a small subset — sending the whole schema burns ITPM on every request.
4. **Stale guidance in `prompts.py`** still references a `weeks` batch array that the handler no longer accepts in practice. Either the prompt or the handler is wrong; today they disagree.

## Suggested fix (preferred: option 1)

1. **(Preferred) Make plan generation deterministic by default.**
   - Update `prompts.py` (training-plan context) to instruct: *"For full-plan creation, ALWAYS use `generate_full_plan`. Use `generate_training_week` only for ad-hoc single-week edits."*
   - In the agent route handler / SSE layer, when `generate_full_plan` returns successfully, emit synthetic `week` SSE events week-by-week (e.g. one every 150–300 ms) so the calendar still animates. **UX preserved, 1 API call, fully deterministic, no rate-limit risk.**
   - Remove the *"design all weeks at once"* batch guidance from `prompts.py:139-143` since batch mode no longer exists.

2. **(Defense in depth)** Filter `tools.py` by context in `_get_cached_tools()` (`agent_service.py:99`) — for `training-plan` context, expose only plan-relevant tools. Cuts ~30-40% input tokens per call.

3. **(Defense in depth)** Add server-side throttling between `generate_training_week` calls in the streaming loop so token usage stays under ITPM even on the LLM path, and surface a friendly *"rate-limited, retrying in Xs"* message instead of a hard error that abandons the plan mid-generation.

4. **(Hygiene)** Decide whether `generate_training_week` should even remain a tool the agent can pick during full-plan creation, or whether it should be restricted to single-week edits via a separate, narrower tool name (e.g. `edit_training_week`).

## Affected files

- `backend/services/agent/agent_service.py:99` (`_get_cached_tools`), `:236` (`_build_system_prompt`), `:653` (tool-use loop)
- `backend/services/agent/tool_handlers/training.py:151` (`_handle_generate_training_week`), `:392` (`_handle_generate_full_plan`)
- `backend/services/agent/tools.py:542` (`generate_training_week` schema), `:662` (`generate_full_plan` schema)
- `backend/services/agent/prompts.py:118-143` (Week Quality + Building the Plan)
- `backend/services/plan_engine.py` — deterministic engine, already correct, just needs to be the default path
- `backend/services/plan_orchestrator.py` — already wires engine → routes → feasibility in one call

## Acceptance criteria

- [ ] Generating a 12-16 week plan for a 6h race completes successfully on the default Haiku tier (50k ITPM) without any 429.
- [ ] Same inputs produce the same plan (determinism check — run twice, diff weeks).
- [ ] Calendar still reveals weeks progressively (UX preserved).
- [ ] No partial-plan state left on the calendar if generation fails.
- [ ] `prompts.py` no longer references the removed batch mode.
