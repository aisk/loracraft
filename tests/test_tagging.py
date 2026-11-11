from loracraft.server import tagging
from loracraft.server.tagging_prompt import TaggingProfile, build_prompt


def test_character_prompt_names_the_fixed_traits():
    prompt = build_prompt(TaggingProfile(goal="character", fixed_traits=["silver hair", "red eyes"]))
    assert "never tagging: silver hair, red eyes" in prompt
    assert '"clothing": [...]' in prompt


def test_style_prompt_keeps_content_and_drops_style():
    prompt = build_prompt(TaggingProfile(goal="style", preferred_tags=["a", "b"], preferred_only=True))
    assert "ART STYLE" in prompt and "Use ONLY tags from this list" in prompt


def test_parse_reply_tolerates_code_fences():
    assert tagging.parse_reply('```json\n{"tags": {"pose": ["sitting"]}}\n```') == {"tags": {"pose": ["sitting"]}}


def test_suggestion_applies_profile_rules(monkeypatch):
    monkeypatch.setattr(tagging, "dictionary", lambda: frozenset({"1girl", "silver hair", "sitting", "school uniform"}))
    profile = TaggingProfile(goal="character", fixed_traits=["silver hair"], banned_tags=["smile"])
    reply = {
        "tags": {
            "subject": ["1girl", "Silver_Hair"],
            "clothing": ["school unifrom", "made up tag"],
            "pose": ["sitting", "1girl"],
            "expression": ["smile"],
        }
    }
    suggestion = tagging.build_suggestion(reply, profile, "mychar")

    assert suggestion["caption"] == "mychar, 1girl, school uniform, made up tag, sitting"
    kinds = {(i["tag"], i["kind"]) for i in suggestion["issues"]}
    assert kinds == {
        ("silver hair", "fixed_trait"),
        ("school uniform", "corrected"),
        ("made up tag", "unknown"),
        ("smile", "banned"),
    }


def test_natural_format_prefixes_trigger():
    suggestion = tagging.build_suggestion({"caption": "A girl sits."}, TaggingProfile(format="natural"), "mychar")
    assert suggestion["caption"] == "mychar, A girl sits."


def test_misspelt_banned_tags_and_fixed_traits_are_still_caught(monkeypatch):
    monkeypatch.setattr(tagging, "dictionary", lambda: frozenset({"blonde hair", "smile", "1girl"}))
    profile = TaggingProfile(goal="character", fixed_traits=["blonde hair"], banned_tags=["smile"])
    reply = {"tags": {"subject": ["1girl"], "appearance": ["blonde hairs"], "expression": ["smiles"]}}
    suggestion = tagging.build_suggestion(reply, profile, "mychar")

    assert suggestion["caption"] == "mychar, 1girl"
    assert {(i["tag"], i["kind"]) for i in suggestion["issues"]} == {
        ("blonde hair", "fixed_trait"),
        ("smile", "banned"),
    }
