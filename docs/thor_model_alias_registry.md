# Thor Model Alias Registry

> Phase 4.1 — Define the strategy for model aliasing so clients never reference Matrix ports directly.
> Date: 2026-07-03
> Status: Documentation only.

---

## Strategy

Clients never reference Matrix ports directly. All model access goes through LiteLLM using aliases of the form:

```
local/<alias-name>
```

This gives us stable names, easy model swapping, per-key scoping, and channel control.

### One Model Rule

**One main model handles almost everything:** Qwen 3.6 27B. The harness, Siri, skills, research, coding, general chat — all use this model by default. `qwen-long` is the same model with a larger context window for when you need more room. Aliases differ only in context window or system prompt, not the underlying model.

Gemma 26B is the sole alternative — for family chat, copywriting, translations.

---

## Alias Table

| alias | category | backend_model | quantization | vllm_profile | max_context | system_prompt_ref | tool_bundle | allowed_channels | intended_users | public_access | status |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `local/qwen-coder` | coding | Lorbus/Qwen3.6-27b-int4-AutoRound | q4 | qwen36 | 128k | coding-default | `{ chat, file-read, code-gen }` | `{ cli, pi, ide, openwebui }` | `{ chuck, son }` | `false` | `draft` |
| `local/qwen-long` | general | Lorbus/Qwen3.6-27b-int4-AutoRound | q4 | qwen36-long (same profile, more context)_ | 200k | general-default | `{ chat, web-search, kb-read, deep-research }` | `{ cli, openwebui, llm.ch, pi }` | `{ chuck, son }` | `true` | `draft` |
| `local/gemma-family` | family | gemma4:26b | q4 | gemma4moe | 80k | family-default | `{ chat }` | `{ openwebui, siri, portal }` | `{ chuck, wife, daughter }` | `false` | `draft` |
| `local/experiment` | experiment | Qwen3-72B (see recommendation below) | q4 | experiment | 80k | none | `{ chat }` | `{ cli }` | `{ chuck }` | `false` | `draft` |
| `local/embed` | embed | nomic-embed-text:latest | q4 | _TBD_ | _TBD_ | none | `{ embeddings }` | `{ openwebui, cli, automation }` | `{ system }` | `false` | `draft` |

---

## Per-Key LiteLLM Restrictions

| Key | Allowed Aliases |
|---|---|
| `chuck` | All aliases |
| `son` | `local/qwen-coder`, `local/qwen-long`, `local/experiment` |
| `openwebui` | `local/qwen-coder`, `local/qwen-long`, `local/gemma-family`, `local/embed` |
| `siri` | `local/qwen-coder`, `local/gemma-family` |
| `automation` | `local/qwen-coder`, `local/qwen-long` |
| `experiment` | `local/experiment` |

---

## Rules

- Aliases are defined and managed in the LiteLLM config on Thor.
- Clients never reference Matrix ports directly.
- Adding a new alias requires Chuck to update the LiteLLM config and the Matrix profile.
- Per-key allowlists prevent unauthorized model access.
- Qwen provides strategy and naming. Chuck owns the actual model-to-alias mapping.

---

## 70B-72B Model Recommendation for `experiment` Alias

You have 72GB VRAM on Matrix. For a 70-80B class model at INT4 quantization, here are the top candidates:

| Model | Params | VRAM at INT4 (weights) | VRAM with KV headroom (est.) | MMLU | MATH | SWE-bench | License | Notes |
|---|---|---|---|---|---|---|---|---|
| **Qwen3 72B** | 72B | ~36 GB | ~43-50 GB | ~85% | ~84% | — | Apache 2.0 | Best overall pick — top dense model. 128K context. 29 languages. Strong coding + reasoning. |
| **Llama 3.3 70B** | 70B | ~35 GB | ~40-49 GB | 82% | 77% | — | Llama Community | English-first. Mature ecosystem. Widely fine-tuned. |
| **Llama 4 Scout** | 109B (17B active) | ~55 GB | ~65-72 GB | — | — | — | Llama Community | 10M context, multimodal. MoE. **Tight fit** — leaves almost no KV cache room at 128K+ context. |

**Recommendation: Qwen3 72B at INT4.**

- Fits comfortably in 72GB (~36 GB weights + ~7-14 GB KV cache overhead = ~43-50 GB total)
- Leaves ~22-29 GB headroom for long contexts (80K-128K tokens)
- Beats Llama 3.3 on MMLU (+3%), MATH (+7%), and coding
- 29 native languages (Qwen strength)
- Apache 2.0 license
- Same family as your current main model (Qwen 3.6 27B) — consistent behavior, easy to swap

**How to test:** Load Qwen3 72B INT4 on a separate vLLM profile (e.g., `experiment-72b`) and point `local/experiment` to it. When you need heavy reasoning or very long context, switch the alias. When done, free the VRAM.

**Llama 4 Scout** is tempting (10M context!) but at ~55 GB weights it eats most of your 72GB card. With any meaningful context length, you'll be pushing 70+ GB and risk OOM. Only consider it if you can limit context to ~32K tokens.
