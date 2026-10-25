from content_engine.config import EditorialRules
from content_engine.mechanical import check_article

RULES = EditorialRules()


def codes(rep):
    return rep.counts()


def test_raw_em_dash_in_prose_fails():
    rep = check_article("<p>Clean books — until they are not.</p>", RULES)
    assert codes(rep) == {"em_dash": 1} and not rep.passed


def test_dash_entity_in_label_is_allowed():
    rep = check_article('<div><strong>Expert Take &#8212; Jane Doe</strong></div><p>Short and clear.</p>', RULES)
    assert rep.passed


def test_banned_phrase_and_competitor():
    rep = check_article('<p>It is important to note that <a href="https://rivalledger.example/x">RivalLedger Software</a> sells it.</p>', RULES)
    assert codes(rep)["banned_phrase"] == 1
    assert codes(rep)["competitor"] == 2


def test_unconfirmed_first_person_claim():
    html = "<p>In my experience closing the books, day one sets the pace.</p>"
    assert "unconfirmed_first_person" in codes(check_article(html, RULES))
    assert check_article(html, RULES, first_person_confirmed=True).passed


def test_honest_disclosure_is_not_a_claim():
    assert check_article("<p>I haven't run this close myself.</p>", RULES).passed


def test_hedging_is_a_warning_not_a_block():
    rep = check_article("<p>It can be fine. It may need care. It might work. It may be ok. Sometimes.</p>", RULES)
    assert "hedging" in codes(rep) and rep.passed


def test_invalid_jsonld_fails():
    rep = check_article('<p>x y</p><script type="application/ld+json">{"a": }</script>', RULES)
    assert "jsonld_invalid" in codes(rep)


def test_preservation_against_original():
    original = ('<h2>Care</h2><p>' + "word " * 100 + '</p><img src="a.jpg"><a href="/guide/">guide</a>'
                '<a href="https://rivalledger.example/x">shop</a>')
    upgraded = '<h2>Care</h2><p>' + "word " * 50 + "</p>"
    c = codes(check_article(upgraded, RULES, original=original))
    assert c["content_loss"] == 1 and c["image_missing"] == 1 and c["link_missing"] == 1  # competitor link may go
    assert "heading_missing" not in c
