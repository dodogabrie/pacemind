"""Coaching voice — verify the agent never tells the user advice came from
a book, manual, chapter, or numbered section.

The fix lives in three places:
- the `note` returned by the lookup_coaching_knowledge tool result
- the docstring of assess_training_readiness (visible as the tool description)
- a `## Coaching Voice` section in the system prompt
"""

import re

from services.agent.prompts import SYSTEM_PROMPT
from services.agent.tool_handlers.knowledge import (
    _handle_assess_training_readiness,
    _handle_lookup_coaching_knowledge,
)


# Words/phrases that must NEVER appear in user-facing strings the LLM
# is told to emit. We allow "section" only as part of "key_sections" /
# "course section" patterns (race-route stretches), which we test for.
_FORBIDDEN_WORDS = ['book', 'books', 'manual', 'chapter', 'chapters']


class TestLookupNote:
    def test_note_does_not_tell_llm_to_cite_books(self):
        result = _handle_lookup_coaching_knowledge(
            {'topics': ['aerobic_base'], 'query_context': 'easy runs'},
            user_id=1,
        )
        note = (result.get('note') or '').lower()
        for word in _FORBIDDEN_WORDS:
            assert f' {word} ' not in f' {note} ', (
                f"lookup_coaching_knowledge note still references {word!r}: {note!r}"
            )

    def test_note_instructs_first_person_voice(self):
        result = _handle_lookup_coaching_knowledge(
            {'topics': ['periodization'], 'query_context': 'plan structure'},
            user_id=1,
        )
        note = result.get('note', '').lower()
        # Must explicitly forbid mentioning external sources
        assert 'never tell the user' in note or 'first person' in note


class TestAssessReadinessDocstring:
    def test_docstring_no_book_references(self):
        doc = (_handle_assess_training_readiness.__doc__ or '').lower()
        for word in _FORBIDDEN_WORDS:
            assert f' {word}' not in f' {doc}', (
                f"assess_training_readiness docstring references {word!r}"
            )


class TestSystemPrompt:
    def test_coaching_voice_section_present(self):
        assert '## Coaching Voice' in SYSTEM_PROMPT, (
            "Coaching Voice HARD RULE section is missing from SYSTEM_PROMPT"
        )

    def test_explicit_examples_of_forbidden_phrases(self):
        # The HARD RULE must give the model concrete examples to refuse
        prompt_lower = SYSTEM_PROMPT.lower()
        assert 'section 4.3' in prompt_lower or 'sezione' in prompt_lower, (
            "Prompt should give explicit examples of section references to avoid"
        )

    def test_course_section_remains_legitimate(self):
        # The "rocky section from km 15-18" phrasing is allowed and used
        # as an example of valid usage. Make sure we didn't accidentally
        # forbid course-section language.
        assert 'rocky section' in SYSTEM_PROMPT.lower() or 'km 15-18' in SYSTEM_PROMPT


class TestValidationWarnings:
    def test_10pct_warning_phrasing_dropped_methodology(self):
        # Check the user-facing warning string built in validation.py no
        # longer references "training methodology" or "the rule from".
        # We assert via inspection of the source so we don't need to
        # construct a full plan to trigger it.
        from services.agent.tool_handlers import validation as val_mod
        src = open(val_mod.__file__).read()
        # The only legitimate appearance of "methodology" should be gone
        offending = re.findall(
            r'progression rule from training methodology', src, re.IGNORECASE
        )
        assert not offending, (
            "validation.py still emits 'progression rule from training "
            "methodology' in user-facing warnings"
        )
