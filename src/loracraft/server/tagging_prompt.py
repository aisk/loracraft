"""Tagging profiles: turn "what is this LoRA for" into instructions for a vision model.

The principle behind every goal: what a caption mentions stays controllable at generation
time; what it leaves out gets absorbed into the trigger word. So the goals differ mainly in
what they tell the model to leave out.
"""

from typing import Literal

from pydantic import BaseModel

CATEGORIES = ["subject", "appearance", "clothing", "pose", "expression", "background", "composition", "style"]


class TaggingProfile(BaseModel):
    goal: Literal["character", "style", "concept", "general"] = "character"
    format: Literal["danbooru", "natural", "mixed"] = "danbooru"
    # character: traits that never change (hair colour, eye colour...), to leave out of captions
    fixed_traits: list[str] = []
    # concept: the thing being taught (an outfit, a pose...), to leave out of captions
    concept: str = ""
    preferred_tags: list[str] = []  # vocabulary to favour
    preferred_only: bool = False  # restrict output to preferred_tags
    banned_tags: list[str] = []
    extra_instructions: str = ""


GOAL_INSTRUCTIONS = {
    "character": """\
These captions will train a LoRA that teaches one specific CHARACTER.
The character's permanent identity must NOT be described, so that it binds to the trigger word.
- Do NOT tag permanent physical traits of the character: hair colour, hair style, hair length, eye colour,
  skin tone, body type, permanent accessories or markings.{fixed_traits}
- DO tag everything that can change between images: clothing and accessories that are not part of the
  character's identity, pose, action, expression, held objects, background, lighting, camera angle and framing.
- DO tag the number and kind of subjects (for example "1girl", "solo").""",
    "style": """\
These captions will train a LoRA that teaches an ART STYLE.
The style itself must NOT be described, so that it binds to the trigger word.
- Do NOT tag anything about the rendering: art style, medium, line quality, colouring technique, shading,
  artist names, quality words.
- DO tag the CONTENT of the image thoroughly: subjects, their appearance (including hair and eye colour),
  clothing, pose, expression, objects, background, composition.""",
    "concept": """\
These captions will train a LoRA that teaches one specific CONCEPT: {concept}.
The concept itself must NOT be described, so that it binds to the trigger word.
- Do NOT tag the concept or anything that is part of it.
- DO tag everything else: subjects and their appearance, other clothing, pose, expression, background,
  composition.""",
    "general": """\
These captions are general-purpose descriptions for training.
- Tag everything visible: subjects, appearance, clothing, pose, expression, background, composition, style.""",
}

FORMAT_INSTRUCTIONS = {
    "danbooru": """\
Write Danbooru tags: lowercase, spaces instead of underscores, each tag a real and commonly used Danbooru
tag (for example "long hair", "looking at viewer", "school uniform", "outdoors"). Do not invent tags and do
not write phrases or sentences.""",
    "natural": """\
Write one natural-language description of 1-3 sentences in plain English. No tag lists.""",
    "mixed": """\
Write Danbooru tags (lowercase, spaces instead of underscores, real tags only), and additionally one short
natural-language sentence describing the scene.""",
}

OUTPUT_TAGS = """\
Answer with a single JSON object and nothing else, in this shape:
{{"tags": {{{categories}}}{sentence}}}
Each list holds the tags of that category; use an empty list when nothing applies. 5-30 tags in total."""

OUTPUT_NATURAL = """\
Answer with a single JSON object and nothing else, in this shape:
{"caption": "<the description>"}"""


def build_prompt(profile: TaggingProfile) -> str:
    """The full instruction text sent alongside each image."""
    goal = GOAL_INSTRUCTIONS[profile.goal]
    if profile.goal == "character":
        traits = ", ".join(profile.fixed_traits)
        goal = goal.format(
            fixed_traits=f"\n  For this character that specifically means never tagging: {traits}." if traits else ""
        )
    elif profile.goal == "concept":
        goal = goal.format(concept=profile.concept or "(not specified)")

    parts = [
        "You are captioning an image for a Stable Diffusion XL LoRA training dataset.",
        goal,
        FORMAT_INSTRUCTIONS[profile.format],
    ]

    if profile.preferred_tags and profile.format != "natural":
        vocabulary = ", ".join(profile.preferred_tags)
        if profile.preferred_only:
            parts.append(f"Use ONLY tags from this list, choosing those that apply to the image: {vocabulary}")
        else:
            parts.append(f"Prefer these tags whenever they apply, and add other tags as needed: {vocabulary}")
    if profile.banned_tags:
        parts.append(f"Never use these tags: {', '.join(profile.banned_tags)}")
    if profile.extra_instructions.strip():
        parts.append(f"Additional instructions from the user:\n{profile.extra_instructions.strip()}")

    if profile.format == "natural":
        parts.append(OUTPUT_NATURAL)
    else:
        parts.append(
            OUTPUT_TAGS.format(
                categories=", ".join(f'"{c}": [...]' for c in CATEGORIES),
                sentence=', "caption": "<one sentence>"' if profile.format == "mixed" else "",
            )
        )
    return "\n\n".join(parts)
