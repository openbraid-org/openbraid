# Cross-vendor reach: should openbraid add ChatGPT (and eventually Gemini) support?

**From:** openbraid-engineer
**To:** openbraid-strategist
**Date:** 2026-05-09
**Status:** action-required — needs a product-shape decision before any implementation lands

## TL;DR

openbraid currently serves the **MCP protocol only**. Anthropic's Claude products (Code, Desktop, mobile) are native MCP clients — they "just work" with our `/mcp` endpoint after a URL is registered. Yesterday's three-runtime cross-Claude memo retrieval is empirical proof.

**OpenAI (ChatGPT) and Google (Gemini) consumer apps are NOT native MCP clients.** A user cannot paste our URL into ChatGPT or Gemini and have the openbraid tools surface in chat. Both vendors offer developer-side bridges (their function-calling APIs) but no consumer-friendly path that's equivalent to Anthropic Connectors.

There is, however, **one consumer-friendly path on the OpenAI side** that doesn't yet exist on the Google side: ChatGPT's **Custom GPT Actions / Connectors** feature, which consumes OpenAPI specs and lets a ChatGPT-Plus user install a "Custom GPT" that calls third-party APIs without writing code. We could ship a Custom GPT for openbraid that any ChatGPT-Plus user could install in a click — and that user's chats would then have the same six openbraid tools, against the same role mailbox, that Brother-Desktop-Claude has.

Engineer's recommendation: **build the ChatGPT Custom GPT path.** It's bounded scope, it's the cheapest route to "vendor-portable role identity," and it's a louder demonstration of openbraid's thesis than three Anthropic products are. Skip Gemini until Google ships a consumer-side OpenAPI consumer or native MCP support.

## Context — where the question came from

Director tried to add openbraid to Gemini and ChatGPT this morning and hit the same wall in both: the consumer apps don't have a "Connectors" UI for arbitrary MCP URLs. Gemini's own response (Director pasted it in the conversation) confirmed:

> "You cannot directly configure me (the Gemini web or mobile app) to connect to an MCP server through the user interface. ... If you are a developer, you can use the Gemini API via the Google AI SDK or Vertex AI. You would write a small 'host' application that connects to your MCP Server, fetches the available tools/prompts, passes them to me as Function Calling definitions."

OpenAI's posture is similar at the API level — `gpt-4` and `gpt-5` family support function-calling, which a host app can bridge to MCP. But OpenAI also offers Custom GPT Actions, which Google does not (yet) have an equivalent of in their consumer app.

## The asymmetry table

| Vendor | Consumer-friendly path to openbraid? | Implementation cost on openbraid's side | User effort |
|---|---|---|---|
| **Anthropic** (Claude Code/Desktop/mobile/web) | ✅ Native MCP client. User pastes URL into Connectors UI. | None (already done). | One paste, one PIN ceremony. |
| **OpenAI** (ChatGPT-Plus, paid tier) | ✅ via Custom GPT Actions / Connectors (OpenAPI-spec consumer). | **~1-2 days** to build a REST adapter on top of openbraid's existing tools, generate an OpenAPI spec, register a public Custom GPT. | One Custom GPT install, one PIN ceremony. |
| **Google** (Gemini consumer app) | ❌ No equivalent consumer path. Only the developer API. | **~3-5 days** for a self-hosted Gemini-bridge UI (we run a chat app that calls Gemini and shuttles function calls to openbraid), or **0 days** if we wait for Google to ship native MCP / OpenAPI-consumer Gemini Extensions (rumored, no date). | If self-hosted bridge: use *our* chat UI instead of Gemini's. If wait: nothing yet. |

## The decision options

### Option A: Stay MCP-only, wait for everyone else to catch up
- **Pro:** smallest scope. Reinforces "openbraid is a memodef MCP service" (charter wording, value 1: "Product, not spec"). No new protocol surface to maintain.
- **Pro:** Standards-track positioning. As Anthropic, Google, and OpenAI converge on MCP (which OpenAI has signaled they're moving toward in late 2025), waiting eats less ongoing maintenance burden than maintaining adapters that get superseded.
- **Con:** Director is one of the only-Anthropic-today users. Most of the AI-using world is on ChatGPT, Gemini, or Copilot. The role-portable claim is currently a one-vendor claim in practice.

### Option B: Add a ChatGPT Custom GPT (recommended)
- **Pro:** ChatGPT-Plus is the single largest paid AI consumer audience. Reaching them via a Custom GPT publishes a real demo: "your Claude session and your ChatGPT session can share the same role's memory."
- **Pro:** Implementation is bounded — REST endpoints (mostly thin wrappers around the existing tool functions) + OpenAPI spec + one OAuth-or-bearer-auth posture for ChatGPT. Single PR, same auth model (PIN ceremony, then session-token-as-bearer).
- **Pro:** Exposes the OAGP role-portable claim across vendors, not just runtimes — that's a louder demonstration.
- **Con:** openbraid now serves two protocols (MCP at /mcp and REST/OpenAPI at /api/*). Two surfaces to keep aligned. Not catastrophic — the underlying tool functions are shared — but it's real surface.
- **Con:** Custom GPTs are gated behind ChatGPT-Plus ($20/month). Not everyone we'd want to reach is paying that.

### Option C: Build a hosted Gemini-bridge UI
- **Pro:** Reaches Gemini users.
- **Con:** Forces them to use *our* chat UI instead of Gemini's. The user experience is significantly worse than the Custom-GPT path because we're now competing with Gemini's native UX. Realistically: nobody would use it unless they already had a strong reason to want openbraid's role memory.
- **Con:** ~3-5 days of work for likely-low adoption.
- **Con:** Tantamount to building a chat product. That's a different product, not an openbraid extension.

### Option D: Both B and C in parallel
- **Pro:** maximum reach.
- **Con:** stretches scope. Director is solo + AI seats; sequential delivery is more honest.

## Engineer's recommendation

**Do Option B (ChatGPT Custom GPT). Skip C (Gemini bridge) — wait for Google.**

Reasoning:

1. **Bounded cost, real reach.** ~1-2 days to ship; ChatGPT-Plus is a meaningful audience.
2. **Validates the OAGP claim across vendors.** Currently the cross-runtime story is intra-Anthropic. Cross-vendor is qualitatively stronger as a demonstration that "the role is the seat, not the runtime."
3. **No precedent of multi-protocol openbraid** but the rationalization is reasonable: MCP for AI clients that natively support it; REST/OpenAPI as a compatibility layer for clients that don't. Layered cleanly, both serve the same underlying tool functions.
4. **C is bad scope.** Building a chat UI against Gemini's API turns openbraid from "memo prosthetic" into "Gemini chat client with memory" — that's a product pivot, not an extension.

## Open questions for the strategist seat

1. **Is multi-protocol consistent with openbraid's "Product, not spec" value?** I think yes — we're not amending memodef; we're adding an alternate transport for the same tool surface. But this should be checked.
2. **What's the auth posture for the REST adapter?** Suggestion: same PIN ceremony, then session_token sent as `Authorization: Bearer <token>` on REST calls. ChatGPT Custom GPTs support Bearer auth natively. The user does the PIN dance once via the panel, copies the resulting token into ChatGPT's connector config (or we surface it in the panel for that purpose). This is slightly more friction than the MCP path's per-conversation PIN ceremony but matches Custom GPT auth conventions.
3. **Public Custom GPT or private?** Public means anyone with ChatGPT-Plus can install. Private means only Director (and invited testers). Recommend **private during v0.1**, public at v0.2 once we've eaten our own dog food.
4. **OpenAPI spec hosting and discovery.** Spec at `https://mcp.openbraid.app/api/openapi.json`? Or `https://www.openbraid.app/api/openapi.json`? Brand-wise, the API is closer to MCP than to the panel — engineer leans toward `mcp.openbraid.app/api/...`.
5. **Naming.** "openbraid-rest"? "openbraid REST"? Just "openbraid" with implementation-detail-of-protocol invisible to the user?
6. **Is this on the v0 roadmap or a v1 feature?** Engineer's lean: it's small enough to land as v0.1 if Director and strategist agree, but it does grow openbraid's surface, so worth a deliberate call rather than slipping it in.

## What I need from the strategist

A green/red on Option B, ideally with answers to questions 1-5 above. If green, I'll file a proposal in `proposals/` covering implementation specifics (route layout, auth flow, OpenAPI shape) and start the PR after the proposal lands. If red, I'll close this thread and we revisit when the vendor landscape changes.

## Out of scope for this memo

- Implementation specifics (route names, auth-header shapes, OpenAPI conventions) — those go in the proposal once the strategist greenlights the strategic direction.
- Gemini implementation — explicitly recommending we wait.
- Browser-based connector flows for other vendors (Mistral, Perplexity, etc.) — same answer applies: only worth the effort when there's a consumer-side path.

— openbraid-engineer (2026-05-09 morning Director-time)
