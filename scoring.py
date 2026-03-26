"""Scoring logic for bracket pool."""

from models import db, Pick, GameResult, User
from bracket_data import ROUNDS, get_round_for_slot


def calculate_upset_bonus(team1_seed, team2_seed, winner_seed):
    """
    Calculate upset bonus for a correct pick.
    Bonus = round(higher_seed_number / lower_seed_number) ONLY when the
    numerically higher seed (underdog) wins.
    e.g. 13-seed beats 4-seed: bonus = round(13/4) = 3
         4-seed beats 13-seed: no bonus (favorite won)
    """
    higher_seed = min(team1_seed, team2_seed)  # favorite (lower number)
    lower_seed = max(team1_seed, team2_seed)   # underdog (higher number)
    if higher_seed == 0 or higher_seed == lower_seed:
        return 0
    # Only award bonus when the underdog (higher seed number) wins
    if winner_seed != lower_seed:
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
    # Determine winner's seed
    if game_result.winner_id == game_result.team1_id:
        winner_seed = game_result.team1_seed
    else:
        winner_seed = game_result.team2_seed
    bonus = calculate_upset_bonus(
        game_result.team1_seed, game_result.team2_seed, winner_seed
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
    # Count graded games excluding First Four (FF games don't score)
    all_graded = GameResult.query.filter(
        GameResult.winner_id.isnot(None)
    ).all()
    total_graded = sum(
        1 for r in all_graded if get_round_for_slot(r.game_slot) != 'ff'
    )
    board = []
    for user in users:
        score = calculate_user_score(user.id)
        # Per-round totals (round pts + bonus combined)
        pr = score["per_round"]
        board.append({
            "user_id": user.id,
            "name": user.name,
            "paid": user.paid,
            "phase2_complete": Pick.query.filter(
                Pick.user_id == user.id,
                db.or_(
                    Pick.game_slot.like('%s16%'),
                    Pick.game_slot.like('%e8%'),
                    Pick.game_slot.like('%f4%'),
                    Pick.game_slot.like('%championship%'),
                )
            ).count() == 15,
            "total": score["total"],
            "round_points": score["round_points"],
            "bonus_points": score["bonus_points"],
            "correct_picks": score["correct_picks"],
            "r64": pr.get("r64", {}).get("points", 0) + pr.get("r64", {}).get("bonus", 0),
            "r32": pr.get("r32", {}).get("points", 0) + pr.get("r32", {}).get("bonus", 0),
            "s16": pr.get("s16", {}).get("points", 0) + pr.get("s16", {}).get("bonus", 0),
            "e8": pr.get("e8", {}).get("points", 0) + pr.get("e8", {}).get("bonus", 0),
            "f4": pr.get("f4", {}).get("points", 0) + pr.get("f4", {}).get("bonus", 0),
            "championship": pr.get("championship", {}).get("points", 0) + pr.get("championship", {}).get("bonus", 0),
            "total_graded": total_graded,
        })
    # Sort by total descending, then alphabetical by name for tiebreaker
    board.sort(key=lambda x: (-x["total"], x["name"].lower()))
    # Standard competition ranking: ties get the same rank,
    # next rank skips (e.g. 1, 1, 3, 4, 4, 6)
    for i, entry in enumerate(board):
        if i > 0 and entry["total"] == board[i - 1]["total"]:
            entry["rank"] = board[i - 1]["rank"]
        else:
            entry["rank"] = i + 1
    return board
