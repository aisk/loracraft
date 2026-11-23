from loracraft.server import local_tagger, tagging
from loracraft.server.system import Settings
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


def test_local_tagger_keeps_tags_above_their_threshold():
    labels = [("general", 9), ("1girl", 0), ("long_hair", 0), ("sitting", 0), ("some_character", 4), ("other", 4)]
    scores = [0.99, 0.9, 0.5, 0.2, 0.9, 0.5]
    assert local_tagger.select_tags(scores, labels, 0.35) == {
        "general": ["1girl", "long_hair"],
        "character": ["some_character"],
    }


def test_identity_tags_are_hair_eyes_and_body_but_not_what_changes():
    identity = ["long hair", "silver hair", "blunt bangs", "blue eyes", "ahoge", "medium breasts"]
    changing = ["closed eyes", "hair ribbon", "ponytail", "smile", "school uniform"]
    assert all(local_tagger.is_identity_tag(t) for t in identity)
    assert not any(local_tagger.is_identity_tag(t) for t in changing)


def test_local_suggestion_for_a_character_leaves_out_who_they_are(monkeypatch):
    # A dictionary must not get to "correct" the tagger's own tags.
    monkeypatch.setattr(tagging, "dictionary", lambda: frozenset({"sittin"}))
    found = {"general": ["1girl", "long_hair", "sitting", "blue_eyes", "smile"], "character": ["some_character"]}
    profile = TaggingProfile(goal="character", format="natural", banned_tags=["smile"])
    suggestion = tagging.build_local_suggestion(found, profile, "mychar")

    assert suggestion["caption"] == "mychar, 1girl, sitting"
    assert {(i["tag"], i["kind"]) for i in suggestion["issues"]} == {
        ("some character", "fixed_trait"),
        ("long hair", "fixed_trait"),
        ("blue eyes", "fixed_trait"),
        ("smile", "banned"),
    }


def test_local_suggestion_for_a_style_names_the_character():
    found = {"general": ["1girl", "long_hair"], "character": ["some_character"]}
    suggestion = tagging.build_local_suggestion(found, TaggingProfile(goal="style"), "")
    assert suggestion["caption"] == "some character, 1girl, long hair"


def test_settings_saved_with_a_vision_llm_keep_using_it():
    assert Settings().tagger_backend == "local"
    assert Settings.model_validate({"tagger_base_url": "http://localhost:11434/v1"}).tagger_backend == "llm"
    saved = {"tagger_base_url": "http://localhost:11434/v1", "tagger_backend": "local"}
    assert Settings.model_validate(saved).tagger_backend == "local"
