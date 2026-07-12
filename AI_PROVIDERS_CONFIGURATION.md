# AI Providers — Configuration Guide

How to set up each of the AI providers this bot can use for document
analysis (`pdf_extraction`), strategy/bot generation (`code_generation`),
and trade review/refinement (`ten_trade_review`, `code_refinement`). Design
background and rationale live in `AI_PROVIDER_SETTINGS_PLAN.md`; this file
is the practical "how do I turn X on" guide.

`configs/ai.yaml`'s `provider_per_task` is the default for each task (restart
required to change). To change a task's provider live, without restarting the
backend, use the **Settings** page (`/settings` in the frontend) — it writes
a per-task override that `LLMRouter` picks up on the next call; clearing the
override there reverts to the `configs/ai.yaml` default.

**API keys** for every provider below (except `ollama` and `claude_code`,
which don't take one) can be set either as an env var in `.env`, or entered
directly on the Settings page (`PUT /ai/settings/providers/{id}/key`). A
Settings-page key is Fernet-encrypted at rest (key held in the OS keyring,
never next to the ciphertext), takes effect immediately with no restart, and
always wins over the `.env` fallback when both are set. Neither the API nor
the settings page ever echoes a key back once saved.

| Provider | Needs | Best for |
|---|---|---|
| [`claude`](#claude-direct-anthropic-api) | An Anthropic API key | High-frequency tasks (e.g. `ten_trade_review` after every 10 trades) — cheapest/fastest per call. |
| [`openai`](#openai-compatible-providers) | An OpenAI API key | GPT-5.6 generation models. |
| [`gemini`](#gemini-google) | A Gemini API key | Google's Gemini 3.x models. |
| [`mistral`](#openai-compatible-providers) | A Mistral API key | Mistral Large/Small/Magistral models. |
| [`groq`](#openai-compatible-providers) | A Groq API key | Very low-latency open-weight models (GPT-OSS, Kimi K2). |
| [`deepseek`](#openai-compatible-providers) | A DeepSeek API key | DeepSeek V4 chat/reasoning models. |
| [`xai`](#openai-compatible-providers) | An xAI API key | Grok 4.x models. |
| [`claude_code`](#claude-code) | Claude Code CLI installed + logged in | Occasional, high-context tasks (e.g. `code_generation`) where you'd rather use your Claude subscription than metered API billing. |
| [`ollama`](#ollama-including-the-hermes-agent-preset) | Ollama running locally, model pulled | Fully offline / free, or when you want a specific open-weight model. |
| [`openclaw`](#openclaw-unverified) | `TB_OPENCLAW_URL` + an OpenClaw API key | **Beta/unverified** — only if you're testing against a real OpenClaw instance. |

---

## `claude` (direct Anthropic API)

The default for all four tasks today (`configs/ai.yaml`).

**Setup**
1. Get an API key from the Anthropic Console.
2. Add it to `.env` (copy `.env.example` if you haven't):
   ```
   TB_ANTHROPIC_API_KEY=sk-ant-...
   ```
3. Restart the backend (`make dev-backend`).

**Select it for a task** in `configs/ai.yaml`:
```yaml
provider_per_task:
  ten_trade_review: { provider: claude, model: claude-haiku-4-5 }
```
Use a cheaper model (`claude-haiku-4-5`) for high-frequency/low-stakes tasks
and a stronger one (`claude-sonnet-5`) for code generation/refinement —
that's the split the shipped defaults already use.

**Verify**: with the key set, trigger the task (e.g. upload a PDF via
`POST /ai/pdf-strategy/drafts`) and confirm you get a `200`, not a `503`. A
`503` with a message mentioning `TB_ANTHROPIC_API_KEY` means the key is
missing or empty.

**Cost**: standard Anthropic API metered billing, per token, no extra
overhead — this is the cheapest option for frequent calls.

---

## OpenAI-compatible providers

`openai`, `mistral`, `groq`, `deepseek`, and `xai` all speak the same
`POST /chat/completions` bearer-token wire format
(`backend/src/ai/adapters/openai_compatible.py` — one adapter class, a
different `base_url` per provider), so they share this section.

**Setup**
1. Get an API key from the provider's console (OpenAI platform, Mistral La
   Plateforme, Groq console, DeepSeek platform, or the xAI console).
2. Either add it to `.env`:
   ```
   TB_OPENAI_API_KEY=
   TB_MISTRAL_API_KEY=
   TB_GROQ_API_KEY=
   TB_DEEPSEEK_API_KEY=
   TB_XAI_API_KEY=
   ```
   and restart the backend, **or** enter it on the Settings page
   (`PUT /ai/settings/providers/{openai|mistral|groq|deepseek|xai}/key`) —
   takes effect immediately, no restart.

**Select it for a task** in `configs/ai.yaml`:
```yaml
provider_per_task:
  code_generation: { provider: openai, model: gpt-5.6-sol }
```
The Settings page's model dropdown offers a curated preset per provider
(e.g. GPT-5.6 Sol/Terra/Luna, Mistral Large/Small, Groq's GPT-OSS/Kimi K2,
DeepSeek V4 Flash/Pro, Grok 4.5/4.3) — pick "Custom" there to type any other
model id the provider supports.

**Verify**: with the key set, trigger the task and confirm you get a `200`,
not a `503` (missing key) or a `502`/adapter error (bad key/model id).

---

## Gemini (Google)

Google's Generative Language REST API — a different wire contract from the
OpenAI-compatible group above (query-string key auth, `contents`/`parts`
request shape), so it has its own adapter (`adapters/gemini.py`).

**Setup**
1. Get a Gemini API key from Google AI Studio (or a Google Cloud project
   with the Generative Language API enabled).
2. Either add it to `.env` (`TB_GEMINI_API_KEY=...`) and restart, **or**
   enter it on the Settings page (`PUT /ai/settings/providers/gemini/key`).

**Select it for a task** in `configs/ai.yaml`:
```yaml
provider_per_task:
  ten_trade_review: { provider: gemini, model: gemini-3.1-flash-lite }
```

**Verify**: trigger the task and confirm a `200`, not a `503` (missing key)
or an HTTP error from Google (bad key/model id).

---

## Claude Code

Uses the `claude` CLI in headless mode (`claude -p ...`), authenticated with
your local Claude Code login/subscription instead of an API key.

**Setup**
1. Install the Claude Code CLI and make sure `claude` is on `PATH` for the
   user the backend runs as: `claude --version` should print a version.
2. Log in once, interactively, as that same user: `claude login` (or
   `claude setup-token` for a long-lived token if you're running the
   backend as a service account without an interactive terminal).
3. `.env` — usually nothing to set; only override if `claude` isn't on
   `PATH` or you need extra flags:
   ```
   TB_CLAUDE_CODE_BINARY=claude
   TB_CLAUDE_CODE_EXTRA_ARGS=
   ```
4. Restart the backend.

**Select it for a task** in `configs/ai.yaml`:
```yaml
provider_per_task:
  code_generation: { provider: claude_code, model: sonnet }
```
`model` accepts the same aliases the CLI does (`sonnet`, `opus`, `fable`) or
a full model name.

**Verify**: `claude --version` and `claude -p "say pong" --output-format
json --tools "" --no-session-persistence` from the backend's user/shell
should return `{"result":"pong",...}` with no login prompt.

**Cost/latency — read before picking this for a frequent task.** Measured
directly against a real install: every headless call carries **~8,500 to
11,800 tokens of fixed overhead** (environment/tool-schema blocks baked into
the CLI's system prompt) *in addition to* your actual prompt, even with
tools fully disabled. A trivial "reply with pong" call cost **$0.05-$0.07**
and ~3 seconds, almost entirely overhead. Good fit for `code_generation` /
`code_refinement` (occasional, already-large prompts, code quality matters
more than $/latency). Poor fit for `ten_trade_review` if you review every 10
trades around the clock — use `claude` (raw API) for that instead.

**Sandboxing note**: the adapter runs `claude -p` with `--tools ""` and
`--strict-mcp-config` (no `--mcp-config` passed), so the CLI itself has zero
tool/file/network/MCP access during this call — it's a pure text
completion, same guarantee as every other provider. Generated strategy code
still goes through the sandbox in `backend/src/strategies/sandbox.py`
regardless of which provider produced it.

---

## Ollama (including the Hermes Agent preset)

Fully local/offline models over Ollama's HTTP API — no per-call cost.

**Setup**
1. Install and start Ollama (https://ollama.com), default listens on
   `http://127.0.0.1:11434`.
2. Pull a model, e.g.:
   ```
   ollama pull hermes3:8b        # "Hermes Agent" default preset
   ollama pull hermes3:70b       # heavier, higher quality, needs a beefy GPU
   ollama pull qwen2.5-coder:14b # any other model you prefer
   ```
3. `.env`:
   ```
   TB_OLLAMA_URL=http://127.0.0.1:11434
   ```
   Point this at a remote host if Ollama isn't running on the same machine
   as the backend.
4. Restart the backend.

**Select it for a task** in `configs/ai.yaml`:
```yaml
provider_per_task:
  ten_trade_review: { provider: ollama, model: "hermes3:8b" }
```

**"Hermes Agent" is not a separate provider** — in the Settings page it's
shown as a one-click preset that sets `provider: ollama, model: hermes3:8b`
under the hood. If you're editing `configs/ai.yaml` by hand instead, just use
`provider: ollama` with whichever Hermes (or other) model you've pulled —
there's nothing else to configure.

**Verify**: `curl http://127.0.0.1:11434/api/tags` should list your pulled
models. `ollama run hermes3:8b "say pong"` should respond without errors.

**Cost**: free beyond your own compute; latency/quality depend entirely on
your hardware and the model size you pick.

---

## OpenClaw (UNVERIFIED)

**This integration is a placeholder, not a confirmed one.** OpenClaw's real
API contract wasn't available when this adapter was written
(`AI_PROVIDER_SETTINGS_PLAN.md` §2.4). The code assumes OpenClaw exposes an
OpenAI-compatible `/v1/chat/completions` HTTP endpoint (bearer-token auth,
response text in `choices[0].message.content`) — the most common
self-hosted-agent contract, used as a best-guess default. **Do not rely on
this in production until it's been confirmed against a real OpenClaw
instance.**

**Setup (if you're testing it)**
1. Have an OpenClaw instance reachable over HTTP, with an API key.
2. `.env`:
   ```
   TB_OPENCLAW_URL=http://your-openclaw-host:port
   TB_OPENCLAW_API_KEY=your-key
   ```
   (the key can also be entered on the Settings page instead — the URL
   itself is still `.env`-only, since it's a deployment address, not a
   secret).
3. Restart the backend.

**Select it for a task** in `configs/ai.yaml`:
```yaml
provider_per_task:
  pdf_extraction: { provider: openclaw, model: "<openclaw-model-id>" }
```

**Verify**: trigger the task and check backend logs for the actual HTTP
request/response OpenClaw returns. If the shape doesn't match
`choices[0].message.content`, the adapter will raise a `KeyError` — that's
expected until `backend/src/ai/adapters/openclaw.py::OpenClawAdapter.complete()`
is updated to match OpenClaw's real response format. Report back what the
real contract looks like so the adapter (and this doc) can be corrected —
nothing else in the system needs to change, since every caller only ever
sees the provider-agnostic `LLMPort` interface.

---

## Picking a provider per task — current guidance

| Task | Frequency | Suggested provider |
|---|---|---|
| `pdf_extraction` | Manual, on demand (you upload a PDF) | `claude` or `claude_code` — either is fine, it's infrequent. |
| `code_generation` | Manual, after approving a draft | `claude_code` if you want subscription billing and don't mind the overhead; `claude`/`openai`/`mistral` for speed. |
| `ten_trade_review` | Automatic, every 10 trades | `claude`, `groq`, or `deepseek` (cheap/fast) — or `ollama`/Hermes Agent if you want it fully offline. Avoid `claude_code` here — the overhead adds up. |
| `code_refinement` | Automatic, only when a review proposes a refinement (infrequent) | `claude` or `claude_code`, either is reasonable; any of the other API providers work too. |

`openclaw` isn't recommended for any task yet — beta/unverified until its
real contract is confirmed. `openai`/`gemini`/`mistral`/`groq`/`deepseek`/`xai`
are all straightforward metered-API providers with no special caveats beyond
"needs its own API key" — pick whichever you already have billing set up
with, or whichever model quality/latency/cost tradeoff fits the task.
