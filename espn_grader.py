"""ESPN API integration for auto-grading tournament results."""

import logging
from datetime import datetime, timedelta

import requests

from models import db, Team, GameResult
from bracket_data import (
    REGIONS, FIRST_FOUR, FIRST_FOUR_SLOTS, R64_MATCHUPS,
    BRACKET_PROGRESSION, get_round_for_slot,
)

logger = logging.getLogger(__name__)

ESPN_SCOREBOARD_URL = (
    "http://site.api.espn.com/apis/site/v2/sports/basketball/"
    "mens-college-basketball/scoreboard"
)

# ESPN team name mappings for fuzzy matching
ESPN_NAME_OVERRIDES = {
    "UConn": "Connecticut",
    "UConn Huskies": "UConn",
    "Miami Hurricanes": "Miami (FL)",
    "Miami (FL) Hurricanes": "Miami (FL)",
    "Miami RedHawks": "Miami (OH)",
    "Miami (OH) RedHawks": "Miami (OH)",
    "N.C. State": "NC State",
    "NC State Wolfpack": "NC State",
    "Saint Mary's Gaels": "Saint Mary's",
    "St. John's Red Storm": "St. John's",
    "Prairie View": "Prairie View A&M",
    "Prairie View A&M Panthers": "Prairie View A&M",
    "LIU Sharks": "LIU",
    "Long Island University": "LIU",
    "Cal Baptist Lancers": "Cal Baptist",
    "California Baptist": "Cal Baptist",
    "North Dakota St": "North Dakota State",
    "Tennessee St": "Tennessee State",
    "Utah St": "Utah State",
    "Kennesaw St": "Kennesaw State",
    "Wright St": "Wright State",
}


def match_espn_team(espn_name, teams_by_name):
    """Match an ESPN team name to our Team records."""
    # Direct match
    if espn_name in teams_by_name:
        return teams_by_name[espn_name]

    # Check overrides
    if espn_name in ESPN_NAME_OVERRIDES:
        override = ESPN_NAME_OVERRIDES[espn_name]
        if override in teams_by_name:
            return teams_by_name[override]

    # Strip common suffixes and try again
    for suffix in [" Wildcats", " Tigers", " Bears", " Eagles", " Bulldogs",
                   " Huskies", " Wolverines", " Spartans", " Jayhawks",
                   " Cardinals", " Hurricanes", " Cavaliers", " Hoosiers",
                   " Hawkeyes", " Cyclones", " Boilermakers", " Badgers",
                   " Razorbacks", " Cougars", " Volunteers", " Mustangs",
                   " Bruins", " Knights", " Gaels", " Rams", " Zags",
                   " Gators", " Seminoles", " Tar Heels", " Fighting Illini",
                   " Aggies", " Cornhuskers", " Blue Devils", " Red Storm",
                   " Panthers", " Trojans", " Paladins", " Bison", " Owls",
                   " Penguins", " Zips", " Broncos", " Saints", " Lancers",
                   " Sharks", " Hawks", " Peacocks", " Vandals", " Catamounts",
                   " Billikens", " Horned Frogs", " Bulls", " Cowboys",
                   " Highlanders", " Royals", " Flames"]:
        stripped = espn_name.replace(suffix, "")
        if stripped in teams_by_name:
            return teams_by_name[stripped]

    # Substring match as last resort
    for name, team in teams_by_name.items():
        if name in espn_name or espn_name in name:
            return team

    return None


def fetch_espn_scores(date_str):
    """
    Fetch NCAA tournament scores from ESPN for a given date.
    date_str format: YYYYMMDD
    Returns list of completed game dicts.
    """
    params = {
        "dates": date_str,
        "groups": 100,
        "limit": 100,
    }

    try:
        resp = requests.get(ESPN_SCOREBOARD_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.error(f"ESPN API error: {e}")
        return []

    completed = []
    for event in data.get("events", []):
        competition = event.get("competitions", [{}])[0]
        status = competition.get("status", {})

        if status.get("type", {}).get("completed", False):
            competitors = competition.get("competitors", [])
            if len(competitors) != 2:
                continue

            game = {"teams": []}
            for comp in competitors:
                team_data = comp.get("team", {})
                game["teams"].append({
                    "name": team_data.get("displayName", ""),
                    "short_name": team_data.get("shortDisplayName", ""),
                    "abbreviation": team_data.get("abbreviation", ""),
                    "seed": int(comp.get("curatedRank", {}).get("current", 0)
                               or comp.get("seed", 0) or 0),
                    "score": int(comp.get("score", 0)),
                    "winner": comp.get("winner", False),
                })
            completed.append(game)

    return completed


def determine_game_slot(team1, team2, round_number, teams_by_name, existing_results):
    """
    Determine which game_slot a completed ESPN game corresponds to.
    Uses team identities and round to find the right slot.
    """
    t1 = match_espn_team(team1["name"], teams_by_name)
    t2 = match_espn_team(team2["name"], teams_by_name)

    if not t1 and team1.get("short_name"):
        t1 = match_espn_team(team1["short_name"], teams_by_name)
    if not t2 and team2.get("short_name"):
        t2 = match_espn_team(team2["short_name"], teams_by_name)

    if not t1 or not t2:
        logger.warning(
            f"Could not match teams: {team1['name']} / {team2['name']}"
        )
        return None, None, None

    # Check First Four
    if round_number == 0:
        for ff_slot, (name1, name2) in FIRST_FOUR.items():
            ff_teams = {name1, name2}
            if t1.name in ff_teams and t2.name in ff_teams:
                return ff_slot, t1, t2
        return None, None, None

    # For R64, find the matchup in R64_MATCHUPS
    if round_number == 1:
        for region, matchups in R64_MATCHUPS.items():
            for idx, (s1, n1, s2, n2) in enumerate(matchups):
                game_num = idx + 1
                slot = f"{region}_r64_{game_num}"

                # Check if this slot has a First Four component
                ff_key = (region, idx)
                if ff_key in FIRST_FOUR_SLOTS:
                    ff_slot = FIRST_FOUR_SLOTS[ff_key]
                    ff_result = existing_results.get(ff_slot)
                    if ff_result and ff_result.winner:
                        # The FF winner occupies this slot
                        if n1 is None:
                            actual_n1 = ff_result.winner.name
                        else:
                            actual_n1 = n1
                        if n2 is None:
                            actual_n2 = ff_result.winner.name
                        else:
                            actual_n2 = n2
                    else:
                        actual_n1 = n1
                        actual_n2 = n2
                else:
                    actual_n1 = n1
                    actual_n2 = n2

                team_names = {actual_n1, actual_n2}
                if t1.name in team_names and t2.name in team_names:
                    return slot, t1, t2

    # For later rounds, check which slots have both teams as possible occupants
    round_map = {2: "r32", 3: "s16", 4: "e8", 5: "f4", 6: "championship"}
    round_key = round_map.get(round_number)
    if not round_key:
        return None, None, None

    # Find slot where both teams could be playing
    if round_key == "f4":
        candidates = ["f4_1", "f4_2"]
    elif round_key == "championship":
        candidates = ["championship"]
    else:
        candidates = []
        for region in REGIONS:
            if round_key == "r32":
                candidates.extend(f"{region}_r32_{i}" for i in range(1, 5))
            elif round_key == "s16":
                candidates.extend(f"{region}_s16_{i}" for i in range(1, 3))
            elif round_key == "e8":
                candidates.append(f"{region}_e8_1")

    for slot in candidates:
        if slot in existing_results:
            continue  # Already recorded

        # Check if both teams could reach this slot via feeder results
        feeders = BRACKET_PROGRESSION.get(slot)
        if not feeders:
            continue

        feeder1_result = existing_results.get(feeders[0])
        feeder2_result = existing_results.get(feeders[1])

        if feeder1_result and feeder2_result:
            if (feeder1_result.winner_id in (t1.id, t2.id) and
                    feeder2_result.winner_id in (t1.id, t2.id)):
                return slot, t1, t2

    return None, None, None


def infer_round_number(date_str):
    """Infer tournament round from date. Rough heuristic."""
    dt = datetime.strptime(date_str, "%Y%m%d")
    # 2026 tournament dates (approximate)
    # First Four: March 17-18
    # R64: March 19-20
    # R32: March 21-22
    # S16: March 26-27
    # E8: March 28-29
    # F4: April 4
    # Championship: April 6
    month, day = dt.month, dt.day
    if month == 3:
        if day <= 18:
            return 0  # First Four
        if day <= 20:
            return 1  # R64
        if day <= 22:
            return 2  # R32
        if day <= 27:
            return 3  # S16
        if day <= 29:
            return 4  # E8
    if month == 4:
        if day <= 5:
            return 5  # F4
        return 6  # Championship
    return 1  # Default to R64


def poll_and_grade(app):
    """Main polling function. Call periodically during tournament."""
    with app.app_context():
        teams = Team.query.all()
        teams_by_name = {t.name: t for t in teams}

        existing_results = {
            r.game_slot: r for r in GameResult.query.all()
        }

        # Check today and yesterday
        today = datetime.utcnow()
        dates = [
            today.strftime("%Y%m%d"),
            (today - timedelta(days=1)).strftime("%Y%m%d"),
        ]

        new_results = 0

        for date_str in dates:
            games = fetch_espn_scores(date_str)
            round_number = infer_round_number(date_str)

            for game in games:
                t1_data, t2_data = game["teams"]

                slot, t1, t2 = determine_game_slot(
                    t1_data, t2_data, round_number, teams_by_name,
                    existing_results,
                )

                if not slot or slot in existing_results:
                    continue

                winner = t1 if t1_data.get("winner") else t2

                result = GameResult(
                    game_slot=slot,
                    team1_id=t1.id,
                    team1_seed=t1.seed,
                    team2_id=t2.id,
                    team2_seed=t2.seed,
                    winner_id=winner.id,
                    round_number=round_number,
                )
                db.session.add(result)
                existing_results[slot] = result
                new_results += 1
                logger.info(
                    f"Recorded result: {slot} - {winner.name} wins"
                )

        if new_results > 0:
            db.session.commit()
            logger.info(f"Committed {new_results} new results")
