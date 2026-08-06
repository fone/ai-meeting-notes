from meeting_notes.live_notes import format_live_notes, parse_live_notes


def test_parse_live_notes_recognizes_conservative_inline_conventions():
    parsed = parse_live_notes(
        """- [ ] Send the proposal
ACTION: Confirm pricing
? Who owns rollout?
QUESTION: When does launch happen?
[12:34] Demo starts
@1:02:03 Customer objection
Discuss #client-a with #Sales
"""
    )

    assert parsed.action_items == ["Send the proposal", "Confirm pricing"]
    assert parsed.questions == ["Who owns rollout?", "When does launch happen?"]
    assert parsed.markers == [("12:34", "Demo starts"), ("1:02:03", "Customer objection")]
    assert parsed.tags == ["client-a", "sales"]
    assert parsed.notes == "Discuss #client-a with #Sales"


def test_tag_only_lines_do_not_pollute_freeform_notes():
    parsed = parse_live_notes("#alpha #beta\nA normal note")
    assert parsed.tags == ["alpha", "beta"]
    assert parsed.notes == "A normal note"


def test_format_live_notes_uses_only_populated_sections():
    parsed = parse_live_notes("- [ ] Follow up\n[03:21] Contract mention")
    rendered = format_live_notes(parsed)

    assert "## Live Notes" in rendered
    assert "### Action Items" in rendered
    assert "- [ ] Follow up" in rendered
    assert "### Markers" in rendered
    assert "**[03:21]** Contract mention" in rendered
    assert "### Questions" not in rendered
    assert "### Notes" not in rendered


def test_format_live_notes_puts_freeform_text_directly_under_parent_heading():
    rendered = format_live_notes(parse_live_notes("My actual meeting note\n- [ ] Follow up"))

    assert "## Live Notes\n\nMy actual meeting note\n\n### Action Items" in rendered
    assert "### Notes" not in rendered


def test_empty_live_notes_render_nothing():
    assert format_live_notes(parse_live_notes("  \n")) == ""
