# LiteLLM model config pass: capability tags, fast alias, fallback, cleanup

- slug: tier1-litellm-model-config-pass
- date: 2026-11-19
- status: open
- tier: 1
- target user: chuck
- source: workspace/ideas/2026-11-17-litellm-model-info-and-uptime.md (Group 1)

## What
One edit to `litellm/config.yml`, one restart, one rollback:

1. **`model_info` capability tags** on all model entries (cost blocks unchanged). ⚠️ Verify with probes before flipping any flag to `true` (a wrong `true` makes the proxy strip/alter params): tool call, `image_url` content, `response_format: {type: json_schema}` against `studio-gemma4-26b`; context via upstream `/v1/models`.
   - `studio-gemma4-26b`: `mode: chat`, `max_input_tokens` (verify, ~128k), `supports_function_calling` (verify), `supports_vision` (verify), `supports_reasoning: false`
   - `matrix-coder`: `mode: chat`, `max_input_tokens: 196608`, `supports_function_calling: true` (verified: pi runs tools against it), `supports_parallel_function_calling: true`, `supports_vision: false`, `supports_reasoning: true`, `supports_response_schema: true`, `supports_prompt_caching: true`
   - `embeddings` + `homelab-embedding-v1`: `mode: embedding`, `max_input_tokens: 8192` (fixes the `mode: chat` misclassification)
2. **`matrix-coder-fast` alias** — Qwen3 thinking is binary; add a fast alias with thinking OFF baked in (`extra_body.chat_template_kwargs.enable_thinking: false` — verified end-to-end 2026-11-17: 0 reasoning tokens vs 52–53 baseline; `reasoning_effort` is ignored by the model). Same cost block as `matrix-coder`.
3. **Make the backup real**: `matrix-coder` `fallbacks: [{model: studio-gemma4-26b}]`. `enable_pre_call_checks: true` (already set) skips the dead deployment while gemma is down, so this is safe to land before `tier1-macstudio-omlx-restart`; it becomes meaningful once OMLX is back.
4. **Remove `hf-sd3`** — no consumer (open-webui removed 2026-11-15; media pipeline uses ComfyUI at matrix:8188 directly). Also remove the `HF_TOKEN` env from `compose/compose.ai-core.yml` if nothing else uses it (check first).
5. **Embedding alias cleanup** — add `drop_params: true` to `embeddings` (parity with `homelab-embedding-v1`) and replace both comments with consumer documentation (`embeddings` → mcp_knowledge `EMBED_MODEL=embeddings`; `homelab-embedding-v1` → long-term memory via Mem0, versioned so a model swap doesn't mix vector spaces).
6. **Drop `set_verbose: true`** from `general_settings` (debug flag in a production config).

## Why (evidence)
- Verified live 2026-11-19: `GET /model/info` shows **all `supports_*` flags null** for all 5 models and embedding models misclassified `mode: chat` → pi's discovery marks every model "(incomplete metadata)" with guessed context windows.
- Thinking test (2026-11-17): session ran `PI_REASONING_LEVEL=off` yet `matrix-coder` had **2.57M reasoning tokens billed (≈ $11.60 at $4.50/M)** — pi's thinking level currently controls nothing for this model. `matrix-coder-fast` gives a real off-switch for straightforward tasks.
- The config comment calls gemma the "Backup LLM" but nothing routes to it.

## Risk + rollback
Low; rollback = `git revert` of `litellm/config.yml` + `docker compose ... restart litellm` (read-only mount, restart picks it up). Main risk is a wrong capability tag → mitigated by the verify-first probes in §What(1) and one-request checks on the fast alias + fallback.

## Files touched
- `litellm/config.yml` (all six items)
- `compose/compose.ai-core.yml` (HF_TOKEN env, if unused after item 4)

---
_Drafted 2026-11-19 (pi, thor) from the workspace/ideas review. Review with `cli/proposals.sh`; applying is a human decision._
