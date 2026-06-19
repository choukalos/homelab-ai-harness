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
