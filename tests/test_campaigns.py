"""Campaign rule checker."""
from clipstudio.campaigns import check

CAMP = {"name": "Whop GTA", "min_len": 15, "max_len": 45, "disclosure": "#ad Paid by Whop",
        "hashtags": "#gta6, @rockstar", "required_source": "lacy", "platforms": '["tiktok","youtube"]'}


def clip(**kw):
    c = {"start": 100, "end": 130, "disclosure_burned": 1,
         "description": "#ad Paid by Whop\nLacy gets wrecked\n\n#gta6 @rockstar", "title": "Lacy gets wrecked"}
    c.update(kw)
    return c


def test_clean_clip_has_no_warnings():
    assert check(clip(), CAMP, channel="Lacy", platform="tiktok") == []


def test_length_rules():
    assert any("Too long" in w for w in check(clip(end=160), CAMP, channel="lacy"))
    assert any("Too short" in w for w in check(clip(end=110), CAMP, channel="lacy"))


def test_disclosure_rules():
    w = check(clip(disclosure_burned=0), CAMP, channel="lacy")
    assert any("burned" in x for x in w)
    w = check(clip(description="Lacy gets wrecked #gta6 @rockstar"), CAMP, channel="lacy")
    assert any("start with the disclosure" in x for x in w)


def test_tags_source_and_platform():
    w = check(clip(description="#ad Paid by Whop\nno tags"), CAMP, channel="lacy")
    assert any("#gta6" in x and "@rockstar" in x for x in w)
    assert any("must come from" in x for x in check(clip(), CAMP, channel="marlon"))
    assert any("doesn't allow" in x for x in check(clip(), CAMP, channel="lacy", platform="instagram"))


def test_no_rules_no_warnings():
    assert check(clip(description=""), {"name": "Loose"}, channel="") == []
