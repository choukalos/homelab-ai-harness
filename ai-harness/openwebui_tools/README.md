# AI Harness Open WebUI Tools

## Install

In Open WebUI:

- Workspace
- Tools
- Add Tool
- Paste `harness_tools.py`
- Save

## Environment Variables

Optional environment variables:

```env
HARNESS_URL=http://ai-harness:8090
HARNESS_API_KEY=your_api_key

## Use during a chat
- Enable the tool
- Prompts like:
-- Use summarize_web_search to find current best practices for FastAPI health checks.
-- Use research_brief_web_search to research local-first AI knowledge base architecture for a homelab.
-- Use generate_image to create a cinematic photo of a silver 1980s sports car at sunset.
-- Use edit_image to turn /tmp/car.png into a cinematic rainy night scene.


