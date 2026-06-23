"""
LLM prompts for outline generation.

Used by the presentation module to generate structured markdown outlines
that Presenton can consume directly for slide creation.
"""

# Prompt for generating a presentation outline from a topic + optional context material.
# The outline should be in the markdown format that Presenton expects:
# a title line followed by numbered slide sections with bullet points.
OUTLINE_GENERATION_PROMPT = """\
You are an expert presentation designer. Create a structured outline for a \
presentation on the following topic.

Topic: {topic}

{instructions}
{research_context}

Requirements:
- Generate approximately {n_slides} content slides (not counting title or TOC).
- Use the following format EXACTLY (this is what the presentation engine expects):

    # Presentation Title

    ## 1. Slide Title
    - Key point or bullet 1
    - Key point or bullet 2
    - Key point or bullet 3

    ## 2. Next Slide Title
    - Key point or bullet 1
    - Key point or bullet 2

- Each slide should have 3-5 bullet points max — keep them concise and impactful.
- Use the following tone: {tone}
- Use the following verbosity level: {verbosity}
- Language: {language}
- Make each slide title descriptive and action-oriented.
- Number slides sequentially starting from 1.
- If research or knowledge base material is provided, incorporate key facts and
  data points into the relevant slides.

Output ONLY the markdown outline — no preamble, no explanation, no wrapping
quotes or code fences.
"""

# Prompt for generating a clean, concise presentation title from a topic.
TITLE_GENERATION_PROMPT = """\
Generate a concise, engaging presentation title for the following topic.

Topic: {topic}

Requirements:
- Keep it under 60 characters.
- Make it compelling and clear.
- Output ONLY the title text — no quotes, no explanation.
"""

# Prompt for parsing natural-language update instructions into structured
# PresentationUpdateRequest fields. Used by Siri's update_presentation handler.
UPDATE_INSTRUCTION_PROMPT = """\
You are a presentation update assistant. Parse the user's natural-language
instructions into structured update parameters for an existing presentation.

Presentation title: {title}
Current version: {version}
Current slide count: {slide_count}
Current template: {template}
Current tone: {tone}
Current verbosity: {verbosity}
Current language: {language}

User's update instructions: {instructions}

Output ONLY a JSON object with the fields that should change. Valid fields:
- title (string) - new presentation title
- content (string) - new content description
- outline (string) - new markdown outline
- n_slides (integer, 3-50) - new slide count
- template (string, e.g. "general", "academic", "dark", "creative")
- tone (string: "default", "casual", "professional", "funny", "educational", "sales_pitch")
- verbosity (string: "concise", "standard", "text-heavy")
- language (string) - new language
- export_as (string: "pptx" or "pdf") - output format
- instructions (string) - additional free-form instructions for the AI
- include_table_of_contents (boolean) - include TOC slide
- include_title_slide (boolean) - include title slide
- research (boolean) - whether to do deep research
- kb_search (boolean) - whether to search knowledge base

Only include fields that the user explicitly asked to change. Omit fields
the user didn't mention. If the user said something ambiguous or complex
that doesn't map cleanly to a field, put it in the "instructions" field
as free-text for the AI to interpret.

Examples:
- "more casual" -> {{"tone": "casual"}}
- "12 slides" -> {{"n_slides": 12}}
- "dark template" -> {{"template": "dark"}}
- "less text per slide" -> {{"verbosity": "concise"}}
- "add a slide about budget" -> {{"instructions": "add a slide about budget"}}
- "make it professional and use the dark template" -> {{"tone": "professional", "template": "dark"}}

Output ONLY the JSON object — no preamble, no explanation, no code fences.
"""
