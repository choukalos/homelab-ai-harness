# Presenton LLM Integration Fix Plan

> **Issue**: Presenton returns HTTP 500 on `/api/v1/ppt/presentation/generate`
> due to a JSON parsing error in its LLM client (llmai library).
>
> **Error trace**:
> ```
> json.decoder.JSONDecodeError: Unterminated string starting at: line 4 column 32 (char 86)
> llmai.shared.errors.LLMError: 500: Unterminated string starting at: line 4 column 32 (char 86)
> ```
>
> **Root cause**: Presenton uses the llmai library with `JSONSchemaResponse(strict=True)`,
> which expects the LLM to return perfectly valid JSON. The model `matrix-gemma4-moe`
> (→ `ollama/gemma4:26b`) is returning a malformed/truncated JSON response that
> the llmai library cannot parse.
>
> **Directory**: `/home/chuck/homelab/`
> **Presenton container**: `presenton` (port 5000:80)
> **LiteLLM proxy**: `litellm-proxy` (port 4000)
> **Ollama server**: `matrix:11434` (internal Docker network)

---

## Architecture Context

```
Presenton (container)
    │
    │  LLM=custom
    │  CUSTOM_LLM_URL=http://litellm-proxy:4000/v1
    │  CUSTOM_MODEL=matrix-gemma4-moe
    │  CUSTOM_LLM_API_KEY=sk-homelab
    │
    ▼
LiteLLM Proxy (litellm-proxy:4000)
    │
    │  model_name: matrix-gemma4-moe
    │  → model: ollama/gemma4:26b
    │  → api_base: http://matrix:11434
    │
    ▼
Ollama (matrix:11434)
    │
    │  gemma4:26b model
    │  (streaming JSON response)
```

### The flow

1. Presenton sends a structured chat completion request to LiteLLM with:
   - `response_format: JSONSchemaResponse(name="response", json_schema=..., strict=True)`
   - `stream: true`
2. LiteLLM proxies to Ollama's gemma4:26b
3. Ollama streams back a response that is **not valid JSON**
4. llmai library tries `json.loads(text_content)` → fails at char 86
5. Presenton returns HTTP 500

---

## Investigation Steps

### Step 1: Confirm the exact LLM response causing the failure

Capture what LiteLLM/Ollama is actually returning:

```bash
# From any machine on the Docker network (or use docker exec)
curl -s -X POST http://192.168.4.54:4000/v1/chat/completions \
  -H "Authorization: Bearer sk-homelab" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "matrix-gemma4-moe",
    "messages": [
      {"role": "system", "content": "You are a presentation outline generator. Return ONLY valid JSON matching this schema."},
      {"role": "user", "content": "Generate a 3-slide outline about AI-powered presentations."}
    ],
    "response_format": {
      "type": "json_schema",
      "json_schema": {
        "name": "response",
        "schema": {
          "type": "object",
          "properties": {
            "title": {"type": "string"},
            "outline": {"type": "string"}
          },
          "required": ["title", "outline"]
        },
        "strict": true
      }
    },
    "stream": true
  }' | head -50
```

**Look for**: Does the streamed response contain valid JSON fragments, or is it
plain text? If it's plain text with markdown, that's the root cause.

### Step 2: Test without JSON schema (plain text)

```bash
curl -s -X POST http://192.168.4.54:4000/v1/chat/completions \
  -H "Authorization: Bearer sk-homelab" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "matrix-gemma4-moe",
    "messages": [
      {"role": "user", "content": "Generate a 3-slide outline about AI-powered presentations. Return ONLY JSON: {\"title\": \"...\", \"outline\": \"...\"}"}
    ],
    "stream": false
  }'
```

**Look for**: Can the model produce JSON at all when asked directly?

### Step 3: Test with a different model (studio-gemma4-4b)

```bash
curl -s -X POST http://192.168.4.54:4000/v1/chat/completions \
  -H "Authorization: Bearer sk-homelab" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "studio-gemma4-4b",
    "messages": [
      {"role": "system", "content": "You are a presentation outline generator."},
      {"role": "user", "content": "Generate a 3-slide outline about AI-powered presentations."}
    ],
    "response_format": {
      "type": "json_schema",
      "json_schema": {
        "name": "response",
        "schema": {
          "type": "object",
          "properties": {
            "title": {"type": "string"},
            "outline": {"type": "string"}
          },
          "required": ["title", "outline"]
        },
        "strict": true
      }
    },
    "stream": true
  }' | head -50
```

**Look for**: Does `studio-gemma4-4b` (via LMStudio) handle JSON schema better?

### Step 4: Test Presenton directly with a working model

```bash
# Temporarily change Presenton's model to studio-gemma4-4b
docker exec presenton sh -c 'export CUSTOM_MODEL=studio-gemma4-4b && echo "Changed to studio-gemma4-4b"'

# Then test via the harness
curl -s -X POST http://192.168.4.54:8090/presentation/generate \
  -H "Content-Type: application/json" \
  -H "X-API-Key: sk-homelab" \
  -d '{
    "title": "Test Presentation",
    "content": "A test presentation.",
    "outline": "# Test\n\n## 1. Intro\n\nIntro text.\n\n## 2. Body\n\nBody text.\n\n## 3. Conclusion\n\nConclusion.",
    "n_slides": 3,
    "template": "general",
    "tone": "professional",
    "verbosity": "concise"
  }' --max-time 300
```

---

## Hypotheses (in order of likelihood)

| # | Hypothesis | Probability | Fix |
|---|-----------|-------------|-----|
| **A** | `gemma4:26b` via Ollama doesn't support `response_format` JSON schema | 🔴 High | Switch to a model that does (e.g. `matrix-coder`, `studio-gemma4-4b`) |
| **B** | Ollama's `ollama/` provider in LiteLLM strips JSON schema, returning plain text | 🟡 Medium | Switch LiteLLM model to `openai/gemma4:26b` or use native Ollama provider in Presenton |
| **C** | Model truncates output (token limit) before JSON is complete | 🟢 Low | Increase `max_tokens` in Presenton config |
| **D** | llmai library version is too new/old for this Presenton version | 🟢 Low | Pin llmai version or update Presenton container |

---

## Fix Options

### Fix 1: Switch to a model with better JSON schema support (Recommended)

Change Presenton's `CUSTOM_MODEL` from `matrix-gemma4-moe` to `studio-gemma4-4b`
(which runs via LMStudio on the Mac Studio and likely handles JSON schema properly):

```bash
# Edit the compose file
# /home/chuck/homelab/compose/compose.ai-core.yml

# Find:
#   - CUSTOM_MODEL=${HARNESS_MODEL}
# Change to:
#   - CUSTOM_MODEL=studio-gemma4-4b

# Or update .env:
# HARNESS_MODEL=studio-gemma4-4b
```

Then restart Presenton:
```bash
docker compose -f /home/chuck/homelab/compose/compose.ai-core.yml restart presenton
```

**Pros**: Simple, uses a proven LMStudio model
**Cons**: May be slower (gemma-4b is smaller than gemma4:26b)

### Fix 2: Try `matrix-coder` (Qwen3.6-27B via vLLM)

Qwen models are known for excellent JSON/schema compliance:

```bash
# Edit compose file or .env
# HARNESS_MODEL=matrix-coder
```

Then restart Presenton.

**Pros**: Qwen is excellent at structured output, runs on local GPU
**Cons**: May be slower than Gemma

### Fix 3: Configure LiteLLM to handle Ollama JSON schema properly

The issue might be that LiteLLM's `ollama/` provider doesn't translate
`response_format.json_schema` to Ollama's format. Check if Ollama supports
JSON schema natively:

```bash
# Test if Ollama supports json_schema response format directly
curl -s -X POST http://192.168.4.54:11434/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemma4:26b",
    "messages": [{"role": "user", "content": "Test"}],
    "response_format": {"type": "json_schema", "json_schema": {"name": "test", "schema": {"type": "object", "properties": {"msg": {"type": "string"}}, "required": ["msg"]}}}
  }'
```

If Ollama supports it natively, the issue is in LiteLLM's translation.

### Fix 4: Use Presenton's native Ollama provider instead of Custom

Presenton has a native `ollama` LLM provider. Instead of routing through LiteLLM,
connect directly:

```bash
# /home/chuck/homelab/compose/compose.ai-core.yml
# Change:
#   - LLM=custom
#   - CUSTOM_LLM_URL=http://litellm-proxy:4000/v1
#   - CUSTOM_MODEL=${HARNESS_MODEL}
# To:
#   - LLM=ollama
#   - OLLAMA_BASE_URL=http://matrix:11434
#   - OLLAMA_MODEL=gemma4:26b
```

**Pros**: Direct connection, no LiteLLM translation layer
**Cons**: Loses the LiteLLM abstraction, may need more env vars

### Fix 5: Increase max_tokens for Presenton

If the model is truncating the JSON output:

Presenton doesn't expose a max_tokens env var directly, but you can try:
- Increasing the model's context window
- Using a model with higher output token limits

---

## Testing Checklist

After applying any fix:

| Test | Command | Expected |
|------|---------|----------|
| 1. Presenton LLM direct test | `docker exec presenton python3 -c "from utils.llm_provider import get_model, get_llm_client; print(get_model())"` | Returns model name without error |
| 2. Outline generation via harness | `curl -s -X POST http://192.168.4.54:8090/presentation/outline -H "Content-Type: application/json" -H "X-API-Key: sk-homelab" -d '{"topic":"test","instructions":"3 slides","research":false}' --max-time 120` | Returns 200 with outline |
| 3. Sync generation | `curl -s -X POST http://192.168.4.54:8090/presentation/generate -H "Content-Type: application/json" -H "X-API-Key: sk-homelab" -d '{"title":"Test","content":"Test content","outline":"# Test\n\n## 1. Intro\n\nIntro.\n\n## 2. Body\n\nBody.\n\n## 3. Conclusion\n\nDone.","n_slides":3,"template":"general"}' --max-time 300` | Returns 200 with download_url |
| 4. Async generation | Same as #3 but to `/generate/async` | Returns 200 with task_id |
| 5. Smoke test | `bash /home/chuck/homelab/ai-harness/tests/test_presentation.sh` | All 16 tests pass |

---

## Recommended Action Plan

1. **Quick test**: Try Fix 1 (switch to `studio-gemma4-4b`) — 5 min
2. **If Fix 1 works**: Update `HARNESS_MODEL` in `.env` and restart Presenton
3. **If Fix 1 doesn't work**: Try Fix 2 (`matrix-coder`)
4. **If neither works**: Investigate Fix 3 (LiteLLM translation issue)
5. **Fallback**: Fix 4 (direct Ollama provider in Presenton)

Start with the investigation steps above to confirm the root cause, then apply
the appropriate fix.
