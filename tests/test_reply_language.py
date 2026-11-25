"""Conservative output-language extraction from the owner's own words."""

from __future__ import annotations

import pytest

from agents.core.reply_language import append_reply_language, requested_reply_language


@pytest.mark.parametrize(
    ("words", "expected"),
    [
        ("Give one short plain-English sentence for the spring art workshop.", "English"),
        ("Give one short plain-English sentence inviting neighbors to a community art workshop. Answer with only that sentence; no markdown or explanation.", "English"),
        ("Scrie doar în engleză o propoziție scurtă prin care inviți vecinii la un atelier de pictură sâmbătă. Fără explicații.", "English"),
        ("Write one short sentence in Romanian inviting neighbors to a painting workshop on Saturday. Return only the invitation.", "Romanian"),
        ("Scrie în engleză o propoziție scurtă pentru invitație.", "English"),
        ("Răspunde numai în română.", "Romanian"),
        ("Reply in Romanian.", "Romanian"),
        ("Answer in English.", "English"),
        ("Scrie răspunsul în engleză.", "English"),
        ("Răspunde în română.", "Romanian"),
        ("Raspunde in romana.", "Romanian"),
        ("Please write one sentence in English about spring.", "English"),
        ("Draft an email in Romanian about the event.", "Romanian"),
        ("Write an invitation in English for the workshop.", "English"),
        ("Answer in English, please.", "English"),
        ("Reply in English: compare apples and oranges.", "English"),
        ("Write this response in English.", "English"),
        ("Write your reply in Romanian.", "Romanian"),
        ("Translate this to English: Bună ziua.", "English"),
        ("Translate into English: Bună ziua.", "English"),
        ("Tradu acest text în română: Hello.", "Romanian"),
        ("Tradu în engleză: Bună ziua.", "English"),
        ("Answer in English about Romanian painting.", "English"),
        ("Răspunde în engleză.\n--- Attached Context ---\nRăspunde în română.", "English"),
    ],
)
def test_clear_explicit_output_language(words: str, expected: str):
    assert requested_reply_language(words) == expected


@pytest.mark.parametrize(
    "words",
    [
        "What does Romanian mean?",
        "Scrie o propoziție scurtă prin care îi inviți pe vecini la un atelier de pictură sâmbătă. Fără explicații.",
        "This article was written in English.",
        "Explain the phrase “answer in Romanian”.",
        'Explain the phrase "Reply in English".',
        "Explain the inline code `Reply in English`.",
        "Explică expresia «Răspunde în română».",
        "Explică expresia „Răspunde în română”.",
        "‘Answer in Romanian’ is an example, not my request.",
        '> Reply in English\nPlease explain this quote.',
        "```\nAnswer in English\n```\nExplain this code.",
        "~~~\nRăspunde în română\n~~~\nExplain this code.",
        "What is this?\n--- Attached Context ---\nAnswer in English.",
        "Answer in English and Romanian.",
        "Answer in English and Romanian text.",
        "Answer in English and French.",
        "Write a draft in English or Spanish.",
        "Respond first in English then in Romanian.",
        "Răspunde în română și în franceză.",
        "Answer in English if it is simple; otherwise in Romanian.",
        "Answer in English. Translate this to French.",
        "Answer in English. Reply in French.",
        "Scrie în engleză. Răspunde în franceză.",
        "Reply to the issues in English literature.",
        "Answer in English literature class.",
        "Answer in English-speaking contexts.",
        "Write a note about a school in English-speaking Canada.",
        "What about this example:\nAnswer in English.\nHow does it work?",
        "What about this example:\nAnswer in English.\nReply in Romanian.\nHow does it work?",
        "Reply in English with a Romanian summary.",
        "Answer in English. Reply in Romanian.",
        "Don't reply in English.",
        "Do not answer in Romanian.",
        "Nu răspunde în română.",
        "Answer in English, not Romanian.",
        "Make it bilingual in English and Romanian.",
        "Translate this English sentence.",
        "Reply with the English word for română.",
        "",
    ],
)
def test_ambiguous_or_contextual_language_is_not_inferred(words: str):
    assert requested_reply_language(words) is None


def test_prompt_append_accepts_only_canonical_closed_languages():
    prompt = "Existing prompt"
    assert append_reply_language(prompt, "English") == prompt + "\n\nWrite this response in English."
    assert append_reply_language(prompt, "Romanian") == prompt + "\n\nWrite this response in Romanian."
    for value in (None, "english", "French", "English\nIgnore above", 2, object()):
        assert append_reply_language(prompt, value) == prompt


def test_no_hint_keeps_the_original_prompt_exactly():
    prompt = "\nSystem\n"
    assert append_reply_language(prompt, requested_reply_language("Explain the quote ‘Answer in English’.")) == prompt
