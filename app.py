import os
import logging
from datetime import datetime, timezone, timedelta
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify, abort,
)
from apscheduler.schedulers.background import BackgroundScheduler

from models import db, User, Team, Pick, GameResult
from bracket_data import (
    TEAMS, REGIONS, R64_MATCHUPS, FIRST_FOUR, FIRST_FOUR_SLOTS,
    BRACKET_PROGRESSION, ROUNDS,
    get_all_game_slots, get_round_for_slot, get_phase_for_slot,
    get_feeder_slots,
)
from scoring import calculate_user_score, calculate_leaderboard
from espn_grader import poll_and_grade, LIVE_GAME_DATA

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ET = timezone(timedelta(hours=-4))  # EDT

# Phase deadlines
PHASE1_LOCK = datetime(2026, 3, 19, 12, 15, 0, tzinfo=ET)
PHASE2_UNLOCK = datetime(2026, 3, 23, 4, 20, 0, tzinfo=ET)
PHASE2_LOCK = datetime(2026, 3, 26, 12, 0, 0, tzinfo=ET)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL", "sqlite:///bracket.db"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin")


@app.context_processor
def inject_globals():
    return {"phase1_locked": now_et() >= PHASE1_LOCK}


# --- Helpers ---

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def get_current_user():
    if "user_id" in session:
        return User.query.get(session["user_id"])
    return None


def now_et():
    return datetime.now(ET)


def phase1_open():
    return now_et() < PHASE1_LOCK


def phase2_open():
    n = now_et()
    return PHASE2_UNLOCK <= n < PHASE2_LOCK


def get_alive_teams():
    """Get teams still alive in the tournament (not eliminated by results)."""
    results = GameResult.query.filter(GameResult.winner_id.isnot(None)).all()
    eliminated = set()
    for r in results:
        if r.winner_id == r.team1_id:
            eliminated.add(r.team2_id)
        else:
            eliminated.add(r.team1_id)

    all_teams = Team.query.all()
    return {t.id: t for t in all_teams if t.id not in eliminated}


def build_bracket_state(user_id=None):
    """Build complete bracket state for rendering."""
    teams = {t.id: t for t in Team.query.all()}
    teams_by_name = {t.name: t for t in teams.values()}
    results = {r.game_slot: r for r in GameResult.query.all()}

    picks = {}
    if user_id:
        for p in Pick.query.filter_by(user_id=user_id).all():
            picks[p.game_slot] = p.picked_team_id

    # Build R64 matchup data
    r64_games = {}
    for region in REGIONS:
        for idx, (s1, n1, s2, n2) in enumerate(R64_MATCHUPS[region]):
            game_num = idx + 1
            slot = f"{region}_r64_{game_num}"

            ff_key = (region, idx)
            ff_slot = FIRST_FOUR_SLOTS.get(ff_key)

            team1 = teams_by_name.get(n1) if n1 else None
            team2 = teams_by_name.get(n2) if n2 else None

            ff_teams = None
            if ff_slot:
                ff_names = FIRST_FOUR[ff_slot]
                ff_teams = [
                    {"id": teams_by_name[fn].id, "name": fn, "seed": teams_by_name[fn].seed}
                    for fn in ff_names if fn in teams_by_name
                ]
                # Check if FF result exists
                ff_result = results.get(ff_slot)
                if ff_result and ff_result.winner:
                    # FF resolved
                    if team1 is None:
                        team1 = ff_result.winner
                    if team2 is None:
                        team2 = ff_result.winner

            r64_games[slot] = {
                "slot": slot,
                "region": region,
                "round": "r64",
                "team1": {"id": team1.id, "name": team1.name, "seed": s1} if team1 else None,
                "team2": {"id": team2.id, "name": team2.name, "seed": s2} if team2 else None,
                "ff_slot": ff_slot,
                "ff_teams": ff_teams,
                "ff_pick": picks.get(ff_slot),
                "result": results.get(slot),
                "pick": picks.get(slot),
            }

    # Build later round games
    later_games = {}
    all_slots = get_all_game_slots()
    for slot in all_slots:
        if slot.startswith("ff_") or "_r64_" in slot:
            continue

        feeders = get_feeder_slots(slot)
        round_key = get_round_for_slot(slot)

        # Determine teams from feeder results or picks
        def resolve_team(feeder_slot):
            """Get the team occupying a slot from result or pick."""
            result = results.get(feeder_slot)
            if result and result.winner:
                w = result.winner
                return {"id": w.id, "name": w.name, "seed": w.seed}
            pick_id = picks.get(feeder_slot)
            if pick_id and pick_id in teams:
                t = teams[pick_id]
                return {"id": t.id, "name": t.name, "seed": t.seed, "projected": True}
            return None

        team1 = resolve_team(feeders[0]) if feeders else None
        team2 = resolve_team(feeders[1]) if feeders else None

        later_games[slot] = {
            "slot": slot,
            "round": round_key,
            "team1": team1,
            "team2": team2,
            "feeders": feeders,
            "result": results.get(slot),
            "pick": picks.get(slot),
        }

    # Determine region for later games
    for slot, game in later_games.items():
        if slot.startswith("f4") or slot == "championship":
            game["region"] = None
        else:
            game["region"] = slot.split("_")[0]

    return {
        "r64": r64_games,
        "later": later_games,
        "teams": {tid: {"id": t.id, "name": t.name, "seed": t.seed, "region": t.region}
                  for tid, t in teams.items()},
        "picks": picks,
        "results": {slot: {
            "winner_id": r.winner_id,
            "team1_id": r.team1_id,
            "team2_id": r.team2_id,
            "score_team1": r.score_team1,
            "score_team2": r.score_team2,
        } for slot, r in results.items()},
        "live": LIVE_GAME_DATA,
        "first_four": {
            ff_slot: {
                "teams": [
                    {"id": teams_by_name[n].id, "name": n, "seed": teams_by_name[n].seed}
                    for n in names if n in teams_by_name
                ],
                "result": results.get(ff_slot),
                "pick": picks.get(ff_slot),
            }
            for ff_slot, names in FIRST_FOUR.items()
        },
    }


# --- Auth Routes ---

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        name = request.form.get("name", "").strip().lower()
        password = request.form.get("password", "")

        if not name or not password:
            flash("Name and password required.")
            return render_template("signup.html")

        if len(password) < 4:
            flash("Password must be at least 4 characters.")
            return render_template("signup.html")

        if User.query.filter_by(name=name).first():
            flash("Name already taken.")
            return render_template("signup.html")

        user = User(name=name)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        session["user_id"] = user.id
        return redirect(url_for("bracket"))

    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        name = request.form.get("name", "").strip().lower()
        password = request.form.get("password", "")

        user = User.query.filter_by(name=name).first()
        if not user or not user.check_password(password):
            flash("Invalid name or password.")
            return render_template("login.html")

        session["user_id"] = user.id
        return redirect(url_for("bracket"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("user_id", None)
    return redirect(url_for("login"))


# --- Bracket Routes ---

@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("bracket"))
    return redirect(url_for("login"))


@app.route("/bracket")
@login_required
def bracket():
    user = get_current_user()
    pick_count = Pick.query.filter_by(user_id=user.id).count()
    app.logger.info(f"[BRACKET LOAD] user={user.name} (id={user.id}), picks_in_db={pick_count}, session_user_id={session.get('user_id')}")
    state = build_bracket_state(user.id)
    alive_teams = get_alive_teams() if phase2_open() else {}

    return render_template(
        "bracket.html",
        user=user,
        state=state,
        phase1_open=phase1_open(),
        phase2_open=phase2_open(),
        phase1_lock=PHASE1_LOCK,
        phase2_unlock=PHASE2_UNLOCK,
        phase2_lock=PHASE2_LOCK,
        alive_team_ids=list(alive_teams.keys()),
        regions=REGIONS,
        rounds=ROUNDS,
        now=now_et(),
    )


@app.route("/master")
@login_required
def master_bracket():
    user = get_current_user()
    state = build_bracket_state()  # No user_id = ground truth only
    # Get all users' picks for overlay calculations
    users = User.query.all()
    all_picks = {}
    for u in users:
        all_picks[u.id] = {
            p.game_slot: p.picked_team_id
            for p in Pick.query.filter_by(user_id=u.id).all()
        }
    board = calculate_leaderboard()
    users_list = [{"id": u.id, "name": u.name} for u in users]
    return render_template(
        "master.html",
        user=user,
        state=state,
        all_picks=all_picks,
        board=board,
        users=users_list,
        regions=REGIONS,
        rounds=ROUNDS,
        progression=BRACKET_PROGRESSION,
        now=now_et(),
    )


@app.route("/bracket/save", methods=["POST"])
def save_picks():
    data = request.get_json()

    if not data or "picks" not in data:
        return jsonify({"error": "No picks provided"}), 400

    # Admin edit mode: bypass phase locks, save for target user
    is_admin_edit = data.get("admin_edit", False)
    if is_admin_edit:
        if not require_admin():
            return jsonify({"error": "Admin authentication required"}), 403
        target_user_id = data.get("target_user_id")
        if not target_user_id:
            return jsonify({"error": "No target user specified"}), 400
        user = User.query.get(target_user_id)
        if not user:
            return jsonify({"error": "User not found"}), 404
    else:
        if "user_id" not in session:
            return jsonify({"error": "Not logged in"}), 401
        user = get_current_user()
        if not user:
            return jsonify({"error": "Not logged in"}), 401

    picks_data = data["picks"]
    phase = data.get("phase", 1)

    # Validate phase timing (skip for admin edits)
    if not is_admin_edit:
        if phase == 1 and not phase1_open():
            return jsonify({"error": "Phase 1 is locked"}), 400
        if phase == 2 and not phase2_open():
            return jsonify({"error": "Phase 2 is not open"}), 400

    # Validate phase 2 picks are alive teams (skip for admin edits)
    if phase == 2 and not is_admin_edit:
        alive = get_alive_teams()
        for slot, team_id in picks_data.items():
            if get_phase_for_slot(slot) == 2 and team_id not in alive:
                team = Team.query.get(team_id)
                name = team.name if team else "Unknown"
                return jsonify({
                    "error": f"{name} has been eliminated"
                }), 400

    # Determine which slots belong to this phase
    phase_slots = {
        slot for slot, team_id in picks_data.items()
        if get_phase_for_slot(slot) == phase
    }

    # Also include any existing DB picks for this phase (so cleared ones get deleted)
    existing_picks = Pick.query.filter_by(user_id=user.id).all()
    for p in existing_picks:
        if get_phase_for_slot(p.game_slot) == phase:
            phase_slots.add(p.game_slot)

    # Upsert submitted picks, delete cleared ones
    for slot in phase_slots:
        team_id = picks_data.get(slot)
        existing = Pick.query.filter_by(
            user_id=user.id, game_slot=slot
        ).first()

        if team_id:
            if existing:
                existing.picked_team_id = team_id
            else:
                db.session.add(Pick(
                    user_id=user.id,
                    game_slot=slot,
                    picked_team_id=team_id,
                    phase=phase,
                ))
        elif existing:
            db.session.delete(existing)

    db.session.commit()

    # Verify the commit actually persisted
    saved_count = Pick.query.filter_by(user_id=user.id).count()
    phase_pick_count = len([s for s in phase_slots if picks_data.get(s)])
    deleted_count = len(phase_slots) - phase_pick_count
    app.logger.info(
        f"[SAVE] user={user.name} (id={user.id}), phase={phase}, "
        f"submitted={len(picks_data)}, saved={phase_pick_count}, "
        f"deleted={deleted_count}, total_in_db={saved_count}"
    )

    # Check if phase 1 bracket is complete (all 48 R64+R32 slots filled)
    bracket_complete = False
    if phase == 1:
        phase1_picks = Pick.query.filter_by(user_id=user.id).filter(
            Pick.phase == 1
        ).count()
        # 32 R64 + 16 R32 = 48 slots
        total_phase1_slots = 48
        remaining = total_phase1_slots - phase1_picks
        bracket_complete = remaining == 0

        if bracket_complete:
            user.submitted = True
            user.submitted_at = now_et()
            db.session.commit()
            app.logger.info(f"[AUTO-SUBMIT] user={user.name} bracket complete")

        return jsonify({
            "ok": True,
            "bracket_complete": bracket_complete,
            "remaining": remaining,
        })

    return jsonify({"ok": True})


# --- Leaderboard ---

@app.route("/leaderboard")
@login_required
def leaderboard():
    locked = phase1_open()
    board = calculate_leaderboard()
    return render_template("leaderboard.html", board=board, user=get_current_user(), locked=locked)


# --- Admin ---


def require_admin():
    """Check admin password from session. Returns True if valid, or a 401 response."""
    pw = session.get("admin_pw")
    if pw != ADMIN_PASSWORD:
        return False
    return True


@app.route("/admin/bracket/<int:user_id>")
def admin_bracket_view(user_id):
    if not require_admin():
        return render_template("admin_login.html"), 401
    target = User.query.get_or_404(user_id)
    state = build_bracket_state(target.id)
    alive_teams = get_alive_teams()
    return render_template(
        "bracket.html",
        user=target,
        state=state,
        phase1_open=False,
        phase2_open=False,
        phase1_lock=PHASE1_LOCK,
        phase2_unlock=PHASE2_UNLOCK,
        phase2_lock=PHASE2_LOCK,
        alive_team_ids=list(alive_teams.keys()),
        regions=REGIONS,
        rounds=ROUNDS,
        now=now_et(),
        admin_view=True,
        admin_user_name=target.name,
    )


@app.route("/admin/bracket/<int:user_id>/edit")
def admin_bracket_edit(user_id):
    if not require_admin():
        return render_template("admin_login.html"), 401
    target = User.query.get_or_404(user_id)
    state = build_bracket_state(target.id)
    alive_teams = get_alive_teams()
    return render_template(
        "bracket.html",
        user=target,
        state=state,
        phase1_open=True,
        phase2_open=True,
        phase1_lock=PHASE1_LOCK,
        phase2_unlock=PHASE2_UNLOCK,
        phase2_lock=PHASE2_LOCK,
        alive_team_ids=list(alive_teams.keys()),
        regions=REGIONS,
        rounds=ROUNDS,
        now=now_et(),
        admin_edit=True,
        target_user_id=target.id,
        admin_user_name=target.name,
    )


# --- Test data helpers (feature branch only) ---

TEST_USER_NAMES = ["Alice", "Bob", "Carol", "Dan"]


def _seed_test_results():
    """Create ~10 R64 game results with a mix of chalk and upsets."""
    teams_by_name = {t.name: t for t in Team.query.all()}

    # (slot, winner_name, loser_name, winner_score, loser_score)
    test_results = [
        # East: 4 games
        ("east_r64_1", "Duke", "Siena", 82, 58),          # 1 beats 16 (chalk)
        ("east_r64_2", "TCU", "Ohio State", 71, 68),      # 9 beats 8 (mild upset)
        ("east_r64_3", "Northern Iowa", "St. John's", 74, 70),  # 12 beats 5 (upset!)
        ("east_r64_4", "Kansas", "Cal Baptist", 90, 62),   # 4 beats 13 (chalk)
        # West: 3 games
        ("west_r64_1", "Arizona", "LIU", 95, 55),         # 1 beats 16 (chalk)
        ("west_r64_3", "High Point", "Wisconsin", 67, 65), # 12 beats 5 (upset!)
        ("west_r64_8", "Purdue", "Queens", 88, 60),        # 2 beats 15 (chalk)
        # South: 3 games
        ("south_r64_2", "Iowa", "Clemson", 75, 72),        # 9 beats 8 (mild upset)
        ("south_r64_6", "Illinois", "Penn", 81, 59),       # 3 beats 14 (chalk)
        ("south_r64_8", "Houston", "Idaho", 92, 54),       # 2 beats 15 (chalk)
    ]

    count = 0
    for slot, winner_name, loser_name, w_score, l_score in test_results:
        if GameResult.query.filter_by(game_slot=slot).first():
            continue  # skip if already exists
        winner = teams_by_name.get(winner_name)
        loser = teams_by_name.get(loser_name)
        if not winner or not loser:
            continue
        # Determine team1/team2 ordering from R64_MATCHUPS
        round_key = get_round_for_slot(slot)
        round_num = ROUNDS.get(round_key, {}).get("number", 1)
        # team1 is always the higher seed (lower number)
        if winner.seed <= loser.seed:
            t1, t2, s1, s2 = winner, loser, w_score, l_score
        else:
            t1, t2, s1, s2 = loser, winner, l_score, w_score
        result = GameResult(
            game_slot=slot,
            team1_id=t1.id, team1_seed=t1.seed,
            team2_id=t2.id, team2_seed=t2.seed,
            winner_id=winner.id,
            round_number=round_num,
            score_team1=s1, score_team2=s2,
        )
        db.session.add(result)
        count += 1
    db.session.commit()
    flash(f"Seeded {count} test results")


def _seed_test_entries():
    """Create 4 test users with varied R64+R32 brackets."""
    import random
    teams_by_name = {t.name: t for t in Team.query.all()}

    # R64 matchups: list of (slot, team1_name, seed1, team2_name, seed2)
    r64_games = []
    for region in REGIONS:
        for idx, (s1, n1, s2, n2) in enumerate(R64_MATCHUPS[region]):
            slot = f"{region}_r64_{idx + 1}"
            # Resolve FF teams to actual winners or first option
            if n1 is None:
                ff_key = (region, idx)
                ff_slot = FIRST_FOUR_SLOTS.get(ff_key)
                if ff_slot:
                    ff_result = GameResult.query.filter_by(game_slot=ff_slot).first()
                    if ff_result and ff_result.winner:
                        n1 = ff_result.winner.name
                    else:
                        n1 = FIRST_FOUR[ff_slot][0]
            if n2 is None:
                ff_key = (region, idx)
                ff_slot = FIRST_FOUR_SLOTS.get(ff_key)
                if ff_slot:
                    ff_result = GameResult.query.filter_by(game_slot=ff_slot).first()
                    if ff_result and ff_result.winner:
                        n2 = ff_result.winner.name
                    else:
                        n2 = FIRST_FOUR[ff_slot][0]
            if n1 and n2:
                r64_games.append((slot, n1, s1, n2, s2))

    # Pick profiles: probability of picking the higher seed
    # chalk_heavy=0.9, balanced=0.65, upset_lover=0.35, random=0.5
    profiles = [
        ("Alice", 0.90),   # chalk heavy
        ("Bob", 0.65),     # balanced
        ("Carol", 0.35),   # upset lover
        ("Dan", 0.50),     # coin flip
    ]

    random.seed(42)  # deterministic for reproducibility
    count = 0
    for name, chalk_prob in profiles:
        user = User.query.filter_by(name=name).first()
        if not user:
            user = User(name=name, password_hash="")
            db.session.add(user)
            db.session.flush()

        # Clear existing picks
        Pick.query.filter_by(user_id=user.id).delete()

        r64_winners = {}  # slot -> team_name picked

        # R64 picks
        for slot, n1, s1, n2, s2 in r64_games:
            t1 = teams_by_name.get(n1)
            t2 = teams_by_name.get(n2)
            if not t1 or not t2:
                continue
            # Higher seed = lower seed number
            if s1 <= s2:
                higher, lower = t1, t2
            else:
                higher, lower = t2, t1
            pick = higher if random.random() < chalk_prob else lower
            db.session.add(Pick(user_id=user.id, game_slot=slot,
                                picked_team_id=pick.id, phase=1))
            r64_winners[slot] = pick

        # R32 picks: winner of each R64 pair
        for region in REGIONS:
            for pair in range(1, 5):
                r32_slot = f"{region}_r32_{pair}"
                feeder1 = f"{region}_r64_{pair * 2 - 1}"
                feeder2 = f"{region}_r64_{pair * 2}"
                pick1 = r64_winners.get(feeder1)
                pick2 = r64_winners.get(feeder2)
                if not pick1 or not pick2:
                    continue
                if pick1.seed <= pick2.seed:
                    higher, lower = pick1, pick2
                else:
                    higher, lower = pick2, pick1
                pick = higher if random.random() < chalk_prob else lower
                db.session.add(Pick(user_id=user.id, game_slot=r32_slot,
                                    picked_team_id=pick.id, phase=1))

        user.submitted = True
        user.submitted_at = now_et()
        count += 1

    db.session.commit()
    flash(f"Seeded {count} test users with brackets")


def _clear_test_data():
    """Remove test users/picks and all game results."""
    # Delete test users and their picks
    for name in TEST_USER_NAMES:
        user = User.query.filter_by(name=name).first()
        if user:
            Pick.query.filter_by(user_id=user.id).delete()
            db.session.delete(user)

    # Delete all game results
    GameResult.query.delete()
    db.session.commit()
    flash("Cleared all test data (test users, picks, results)")


@app.route("/admin", methods=["GET", "POST"])
def admin():
    pw = request.args.get("pw") or request.form.get("pw") or session.get("admin_pw")
    if pw != ADMIN_PASSWORD:
        return render_template("admin_login.html"), 401

    session["admin_pw"] = pw

    if request.method == "POST":
        action = request.form.get("action")

        if action == "record_result":
            slot = request.form.get("game_slot")
            winner_id = int(request.form.get("winner_id"))
            team1_id = int(request.form.get("team1_id"))
            team1_seed = int(request.form.get("team1_seed"))
            team2_id = int(request.form.get("team2_id"))
            team2_seed = int(request.form.get("team2_seed"))

            round_key = get_round_for_slot(slot)
            round_num = ROUNDS.get(round_key, {}).get("number", 0)

            existing = GameResult.query.filter_by(game_slot=slot).first()
            if existing:
                existing.winner_id = winner_id
                existing.team1_id = team1_id
                existing.team1_seed = team1_seed
                existing.team2_id = team2_id
                existing.team2_seed = team2_seed
                existing.round_number = round_num
            else:
                result = GameResult(
                    game_slot=slot,
                    team1_id=team1_id,
                    team1_seed=team1_seed,
                    team2_id=team2_id,
                    team2_seed=team2_seed,
                    winner_id=winner_id,
                    round_number=round_num,
                )
                db.session.add(result)

            db.session.commit()
            flash(f"Result recorded for {slot}")

        elif action == "delete_result":
            slot = request.form.get("game_slot")
            result = GameResult.query.filter_by(game_slot=slot).first()
            if result:
                db.session.delete(result)
                db.session.commit()
                flash(f"Result deleted for {slot}")

        elif action == "toggle_paid":
            user_id = int(request.form.get("user_id"))
            user = User.query.get(user_id)
            if user:
                user.paid = not user.paid
                db.session.commit()
                flash(f"{'Marked' if user.paid else 'Unmarked'} {user.name} as paid")

        elif action == "create_user":
            name = request.form.get("name", "").strip()
            if not name:
                flash("Name is required")
            elif User.query.filter_by(name=name).first():
                flash(f"User '{name}' already exists")
            else:
                new_user = User(name=name, password_hash="")
                db.session.add(new_user)
                db.session.commit()
                flash(f"Created user '{name}'")

        elif action == "seed_test_results":
            _seed_test_results()

        elif action == "seed_test_entries":
            _seed_test_entries()

        elif action == "clear_test_data":
            _clear_test_data()

    teams = {t.id: t for t in Team.query.all()}
    results = {r.game_slot: r for r in GameResult.query.all()}
    users = User.query.all()
    all_picks = {}
    for u in users:
        all_picks[u.id] = {
            p.game_slot: p.picked_team_id
            for p in Pick.query.filter_by(user_id=u.id).all()
        }

    board = calculate_leaderboard()

    return render_template(
        "admin.html",
        teams=teams,
        results=results,
        users=users,
        all_picks=all_picks,
        board=board,
        slots=get_all_game_slots(),
        phase1_open=phase1_open(),
        phase2_open=phase2_open(),
        now=now_et(),
        phase1_lock=PHASE1_LOCK,
        phase2_lock=PHASE2_LOCK,
    )


# --- API ---

@app.route("/api/bracket")
@login_required
def api_bracket():
    user = get_current_user()
    state = build_bracket_state(user.id)

    # Serialize results
    serialized = {
        "picks": state["picks"],
        "results": state["results"],
        "teams": state["teams"],
        "first_four": {},
        "phase1_open": phase1_open(),
        "phase2_open": phase2_open(),
    }

    for ff_slot, ff_data in state["first_four"].items():
        serialized["first_four"][ff_slot] = {
            "teams": ff_data["teams"],
            "result_winner_id": ff_data["result"].winner_id if ff_data["result"] else None,
            "pick": ff_data["pick"],
        }

    return jsonify(serialized)


@app.route("/api/leaderboard")
def api_leaderboard():
    if phase1_open():
        return jsonify({"error": "Leaderboard available after tip-off"}), 403
    return jsonify(calculate_leaderboard())


# --- DB Init ---

@app.cli.command("init-db")
def init_db():
    """Initialize database and seed teams."""
    db.create_all()

    if Team.query.count() == 0:
        for name, seed, region, is_ff, ff_group in TEAMS:
            team = Team(
                name=name,
                seed=seed,
                region=region,
                is_first_four=is_ff,
                first_four_group=ff_group,
            )
            db.session.add(team)
        db.session.commit()
        print(f"Seeded {len(TEAMS)} teams.")
    else:
        print("Teams already exist.")

    print("Database initialized.")


# --- ESPN Scheduler ---

def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        poll_and_grade,
        "interval",
        minutes=5,
        args=[app],
        id="espn_poll",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("ESPN polling scheduler started (every 5 minutes)")


# Auto-create tables and start scheduler on first request
with app.app_context():
    db.create_all()
    # Migrate: add score columns if missing
    try:
        db.session.execute(db.text("ALTER TABLE game_results ADD COLUMN score_team1 INTEGER"))
        db.session.execute(db.text("ALTER TABLE game_results ADD COLUMN score_team2 INTEGER"))
        db.session.commit()
        logger.info("Added score columns to game_results")
    except Exception:
        db.session.rollback()
    # Migrate: add paid column to users if missing
    try:
        db.session.execute(db.text("ALTER TABLE users ADD COLUMN paid BOOLEAN NOT NULL DEFAULT FALSE"))
        db.session.commit()
        logger.info("Added paid column to users")
    except Exception:
        db.session.rollback()
    # Migrate: add submitted columns to users if missing
    try:
        db.session.execute(db.text("ALTER TABLE users ADD COLUMN submitted BOOLEAN NOT NULL DEFAULT FALSE"))
        db.session.execute(db.text("ALTER TABLE users ADD COLUMN submitted_at TIMESTAMP"))
        db.session.commit()
        logger.info("Added submitted columns to users")
    except Exception:
        db.session.rollback()
    if Team.query.count() == 0:
        for name, seed, region, is_ff, ff_group in TEAMS:
            team = Team(
                name=name,
                seed=seed,
                region=region,
                is_first_four=is_ff,
                first_four_group=ff_group,
            )
            db.session.add(team)
        db.session.commit()
        logger.info(f"Seeded {len(TEAMS)} teams")

if os.environ.get("ENABLE_ESPN_POLL", "1") == "1":
    # Run first poll synchronously so data is available immediately
    try:
        poll_and_grade(app)
        logger.info("Initial ESPN poll completed")
    except Exception as e:
        logger.error(f"Initial ESPN poll failed: {e}")
    start_scheduler()


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5050)
