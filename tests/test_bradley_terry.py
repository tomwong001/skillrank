"""Tests for Bradley-Terry rating system."""

import pytest
from eval.bradley_terry import Rating, update_ratings, expected_score, rate_first_skill


def test_initial_rating():
    r = Rating()
    assert r.value == 1.0
    assert r.variance == 1.0
    assert r.comparisons == 0
    assert r.win_rate == 0.0
    assert not r.is_trusted


def test_expected_score_equal():
    """Equal ratings should give 50% expected score."""
    assert expected_score(1.0, 1.0) == 0.5


def test_expected_score_stronger():
    """Higher rating should have >50% expected score."""
    assert expected_score(2.0, 1.0) > 0.5
    assert expected_score(2.0, 1.0) == pytest.approx(2/3, abs=0.01)


def test_update_ratings_win():
    """Winner's rating should increase, loser's should decrease."""
    a = Rating(value=1.0)
    b = Rating(value=1.0)
    a, b = update_ratings(a, b)
    assert a.value > 1.0
    assert b.value < 1.0
    assert a.wins == 1
    assert b.losses == 1


def test_update_ratings_tie():
    """Tie should move ratings slightly toward each other."""
    a = Rating(value=1.5)
    b = Rating(value=0.5)
    a_before = a.value
    b_before = b.value
    a, b = update_ratings(a, b, is_tie=True)
    # Stronger player should lose a bit, weaker should gain
    assert a.value < a_before
    assert b.value > b_before
    assert a.ties == 1
    assert b.ties == 1


def test_variance_shrinks():
    """Variance should decrease with each comparison."""
    a = Rating(value=1.0, variance=1.0)
    b = Rating(value=1.0, variance=1.0)
    a, b = update_ratings(a, b)
    assert a.variance < 1.0
    assert b.variance < 1.0


def test_trusted_after_10():
    """Rating becomes trusted after 10 comparisons."""
    a = Rating(wins=5, losses=4, ties=0)
    assert not a.is_trusted
    a.wins = 6  # now 10 total
    assert a.is_trusted


def test_confidence_interval():
    """Confidence interval should be wider with higher variance."""
    high_var = Rating(variance=1.0)
    low_var = Rating(variance=0.1)
    assert high_var.confidence_95 > low_var.confidence_95


def test_rate_first_skill():
    """First skill gets baseline rating."""
    r = rate_first_skill(Rating())
    assert r.value == 1.0


def test_to_dict():
    """Rating should serialize to dict."""
    r = Rating(value=1.5, variance=0.3, wins=5, losses=2, ties=1)
    d = r.to_dict()
    assert d["rating"] == 1.5
    assert d["wins"] == 5
    assert d["losses"] == 2
    assert d["ties"] == 1
    assert d["comparisons"] == 8
    assert "win_rate" in d
    assert "confidence_95" in d
    assert "trusted" in d


def test_multiple_updates_converge():
    """After many comparisons, stronger skill should have much higher rating."""
    a = Rating(value=1.0)
    b = Rating(value=1.0)
    # A wins 8 out of 10
    for _ in range(8):
        a, b = update_ratings(a, b)
    for _ in range(2):
        b, a = update_ratings(b, a)
    assert a.value > b.value
    assert a.win_rate > 0.5
