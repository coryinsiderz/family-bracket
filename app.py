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
PHASE1_LOCK = datetime(2026, 3, 19, 12, 0, 0, tzinfo=ET)
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


@app.route("/bracket/save", methods=["POST"])
@login_required
def save_picks():
    user = get_current_user()
    data = request.get_json()

    if not data or "picks" not in data:
        return jsonify({"error": "No picks provided"}), 400

    picks_data = data["picks"]
    phase = data.get("phase", 1)

    # Validate phase timing
    if phase == 1 and not phase1_open():
        return jsonify({"error": "Phase 1 is locked"}), 400
    if phase == 2 and not phase2_open():
        return jsonify({"error": "Phase 2 is not open"}), 400

    # Validate phase 2 picks are alive teams
    if phase == 2:
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
    return jsonify({"ok": True})


@app.route("/bracket/submit", methods=["POST"])
@login_required
def submit_bracket():
    user = get_current_user()

    # Verify the relevant phase is still open
    if not phase1_open() and not phase2_open():
        return jsonify({"error": "Bracket is locked"}), 400

    # Check user has at least some picks
    pick_count = Pick.query.filter_by(user_id=user.id).count()
    if pick_count == 0:
        return jsonify({"error": "No picks to submit"}), 400

    user.submitted = True
    user.submitted_at = now_et()
    db.session.commit()
    app.logger.info(f"[SUBMIT] user={user.name} (id={user.id}), picks={pick_count}")
    return jsonify({"ok": True})


@app.route("/bracket/unsubmit", methods=["POST"])
@login_required
def unsubmit_bracket():
    user = get_current_user()

    if not phase1_open() and not phase2_open():
        return jsonify({"error": "Bracket is locked"}), 400

    user.submitted = False
    db.session.commit()
    app.logger.info(f"[UNSUBMIT] user={user.name} (id={user.id})")
    return jsonify({"ok": True})


# --- Leaderboard ---

@app.route("/leaderboard")
@login_required
def leaderboard():
    locked = phase1_open()
    board = calculate_leaderboard()
    return render_template("leaderboard.html", board=board, user=get_current_user(), locked=locked)


# --- Admin ---

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
