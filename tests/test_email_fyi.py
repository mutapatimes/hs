"""Every journey email ends with one clienteling figure from McKinsey & Company; a sequence
rotates through them; transactional mail (no unsubscribe link) stays clean."""
from halia import emails


def test_every_journey_template_carries_a_figure():
    for key in emails._TEMPLATES:
        subject, html, text = emails.render(key, {"first": "A", "store_name": "Maison", "recap": {}, "book": {},
                                                  "moment": {}, "birthdays": {}, "team": {}}, "https://x/u")
        assert "Worth knowing:" in html and "McKinsey &amp; Company, 2023" in html, key
        assert text.rstrip().endswith("McKinsey & Company, 2023."), key


def test_a_sequence_rotates_the_figures():
    seen = {emails.render(k, {"first": "A"}, "https://x/u")[2].split("Worth knowing: ")[1]
            for k in ("free_scored", "free_reveal", "free_moved", "free_last")}
    assert len(seen) == 4


def test_transactional_mail_has_no_figure():
    subject, html, text = emails.render("client_welcome", {"first": "A"}, "")
    assert "Worth knowing" not in html and "McKinsey" not in text
