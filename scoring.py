"""Scoring logic for bracket pool."""

from models import db, Pick, GameResult, User
from bracket_data import ROUNDS, get_round_for_slot


def calculate_upset_bonus(team1_seed, team2_seed, winner_seed):
    """
    Calculate upset bonus for a correct pick.
    Bonus = round(lower_seed / higher_seed) where lower_seed is the
    numerically higher seed number.
    Applied based on the actual seeds of the two teams in the real game.
    """
    higher_seed = min(team1_seed, team2_seed)
    lower_seed = max(team1_seed, team2_seed)
    if higher_seed == 0:
        return 0
    return round(lower_seed / higher_seed)


def score_pick(pick, game_result):
    """
    Score a single pick against a game result.
    Returns (round_points, upset_bonus) or (0, 0) if incorrect.
    """
    if game_result is None or game_result.winner_id is None:
        return 0, 0

    if pick.picked_team_id != game_result.winner_id:
        return 0, 0

    round_key = get_round_for_slot(pick.game_slot)
    if round_key == "ff":
        return 0, 0  # First Four games don't score

    round_info = ROUNDS.get(round_key)
    if not round_info:
        return 0, 0

    round_points = round_info["points"]
    bonus = calculate_upset_bonus(
        game_result.team1_seed, game_result.team2_seed, 0
    )

    return round_points, bonus


def calculate_user_score(user_id):
    """
    Calculate total score for a user.
    Returns dict with total, round_points, bonus_points, and per-round breakdown.
    """
    picks = Pick.query.filter_by(user_id=user_id).all()
    results = {r.game_slot: r for r in GameResult.query.all()}

    total_round_points = 0
    total_bonus = 0
    correct_picks = 0
    per_round = {}

    for pick in picks:
        result = results.get(pick.game_slot)
        rp, bonus = score_pick(pick, result)
        if rp > 0:
            correct_picks += 1
            total_round_points += rp
            total_bonus += bonus

            round_key = get_round_for_slot(pick.game_slot)
            if round_key not in per_round:
                per_round[round_key] = {"points": 0, "bonus": 0, "correct": 0}
            per_round[round_key]["points"] += rp
            per_round[round_key]["bonus"] += bonus
            per_round[round_key]["correct"] += 1

    return {
        "total": total_round_points + total_bonus,
        "round_points": total_round_points,
        "bonus_points": total_bonus,
        "correct_picks": correct_picks,
        "per_round": per_round,
    }


def calculate_leaderboard():
    """Calculate scores for all users and return sorted leaderboard."""
    users = User.query.all()
    board = []
    for user in users:
        score = calculate_user_score(user.id)
        board.append({
            "user_id": user.id,
            "name": user.name,
            "paid": user.paid,
            "total": score["total"],
            "round_points": score["round_points"],
            "bonus_points": score["bonus_points"],
            "correct_picks": score["correct_picks"],
        })
    board.sort(key=lambda x: x["total"], reverse=True)
    for i, entry in enumerate(board):
        entry["rank"] = i + 1
    return board
