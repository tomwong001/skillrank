"""
Bradley-Terry rating system for pairwise skill comparison.

Unlike Elo (assumes stable population, noisy with small N),
Bradley-Terry gives proper uncertainty intervals and handles
small populations well.

P(A beats B) = rating_A / (rating_A + rating_B)

After each comparison, update via maximum likelihood.
We use an online approximation for real-time updates.
"""

import math
from dataclasses import dataclass


@dataclass
class Rating:
    """A skill's Bradley-Terry rating with uncertainty."""
    value: float = 1.0       # BT parameter (higher = better)
    variance: float = 1.0    # uncertainty (decreases with more comparisons)
    wins: int = 0
    losses: int = 0
    ties: int = 0

    @property
    def comparisons(self) -> int:
        return self.wins + self.losses + self.ties

    @property
    def win_rate(self) -> float:
        total = self.wins + self.losses + self.ties
        if total == 0:
            return 0.0
        return (self.wins + 0.5 * self.ties) / total

    @property
    def confidence_95(self) -> float:
        """95% confidence interval half-width."""
        return 1.96 * math.sqrt(self.variance)

    @property
    def is_trusted(self) -> bool:
        """Minimum 10 comparisons before rating is 'trusted'."""
        return self.comparisons >= 10

    def to_dict(self) -> dict:
        return {
            "rating": round(self.value, 3),
            "variance": round(self.variance, 4),
            "confidence_95": round(self.confidence_95, 3),
            "wins": self.wins,
            "losses": self.losses,
            "ties": self.ties,
            "comparisons": self.comparisons,
            "win_rate": round(self.win_rate, 3),
            "trusted": self.is_trusted,
        }


def expected_score(rating_a: float, rating_b: float) -> float:
    """P(A beats B) under Bradley-Terry model."""
    return rating_a / (rating_a + rating_b)


def update_ratings(winner: Rating, loser: Rating, is_tie: bool = False) -> tuple[Rating, Rating]:
    """
    Update Bradley-Terry ratings after a single comparison.

    Uses online stochastic gradient approximation:
    - Learning rate decreases with more comparisons (adaptive)
    - Variance shrinks after each observation
    - Ties count as half-win for each side
    """
    # Adaptive learning rate: aggressive early, conservative later
    lr_w = max(0.05, 0.5 / (1 + 0.1 * winner.comparisons))
    lr_l = max(0.05, 0.5 / (1 + 0.1 * loser.comparisons))

    # Expected scores
    e_w = expected_score(winner.value, loser.value)
    e_l = 1.0 - e_w

    if is_tie:
        # Tie: actual score = 0.5 for both
        s_w, s_l = 0.5, 0.5
        winner.ties += 1
        loser.ties += 1
    else:
        # Win/loss: actual score = 1/0
        s_w, s_l = 1.0, 0.0
        winner.wins += 1
        loser.losses += 1

    # Update ratings (multiplicative for BT parameters, ensures positivity)
    winner.value *= math.exp(lr_w * (s_w - e_w))
    loser.value *= math.exp(lr_l * (s_l - e_l))

    # Shrink variance (Bayesian update approximation)
    winner.variance *= (1.0 / (1.0 + winner.variance * 0.1))
    loser.variance *= (1.0 / (1.0 + loser.variance * 0.1))

    return winner, loser


def rate_first_skill(skill: Rating) -> Rating:
    """First skill in an intent gets a baseline rating."""
    skill.value = 1.0
    skill.variance = 1.0
    return skill
