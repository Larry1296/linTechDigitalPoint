from apps.core.fuzzy import fuzzy_score


def test_small_spelling_slips_still_match():
    cover = ("TECNO SPARK 40 HARD COVER (MEN)", "HARD (MEN)", "TEC-SP40-HARD-M")
    assert fuzzy_score("tecmo sprak", *cover) > 0.8
    assert fuzzy_score("spark40", *cover) == 1
    assert fuzzy_score("infinix", *cover) is None
