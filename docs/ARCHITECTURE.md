# Architecture — Family Bracket App

## Tech Stack

- **Backend**: Python 3.9, Flask, SQLAlchemy ORM
- **Database**: Neon Postgres (production), SQLite (local dev)
- **Frontend**: Jinja2 templates, vanilla JavaScript (no framework), CSS custom properties
- **Hosting**: Railway
- **External API**: ESPN scoreboard API for live scores and auto-grading
- **Scheduler**: APScheduler (BackgroundScheduler) for ESPN polling every 5 minutes

## Directory Structure

```
family-bracket/
  app.py                    # Flask app, routes, auth, phase logic
  models.py                 # SQLAlchemy models
  scoring.py                # Leaderboard calculation, scoring logic
  espn_grader.py            # ESPN API integration, auto-grading
  bracket_data.py           # Tournament structure: teams, matchups, progression
  templates/
    base.html               # Layout shell, nav bar
    master.html             # Main bracket page with 6 toggle overlays
    bracket.html            # Legacy pick-editing (admin routes only)
    leaderboard.html        # Leaderboard table
    login.html              # Combined login/guest/claim page
    admin.html              # Admin panel
    admin_login.html        # Admin password prompt
  static/
    style.css               # All styles
  docs/
    CLAUDE.md               # Claude Code behavioral rules
    ARCHITECTURE.md         # This file
    CONTEXT.md              # Patterns and conventions
    BACKLOG.md              # Current state and future work
  .claude/
    launch.json             # Dev server config (port 5050)
```

## Database Models

### User (`users` table)
| Column | Type | Notes |
|--------|------|-------|
| id | Integer | Primary key |
| name | String(80) | Unique, required |
| password_hash | String(256) | Empty string = unclaimed admin-created entry |
| paid | Boolean | Default false. Toggled by admin. |
| submitted | Boolean | Default false. Auto-set when all 48 phase 1 picks saved. |
| submitted_at | DateTime | Timestamp when bracket was completed |
| picks | relationship | One-to-many with Pick |

### Team (`teams` table)
| Column | Type | Notes |
|--------|------|-------|
| id | Integer | Primary key |
| name | String(100) | e.g. "Duke", "TCU", "Miami (FL)" |
| seed | Integer | Tournament seed (1-16) |
| region | String(20) | "east", "west", "midwest", "south" |
| is_first_four | Boolean | True for First Four teams |
| first_four_group | String(40) | Links paired FF teams, e.g. "ff_west_11" |

### Pick (`picks` table)
| Column | Type | Notes |
|--------|------|-------|
| id | Integer | Primary key |
| user_id | Integer | FK to users.id |
| game_slot | String(40) | e.g. "east_r64_1", "west_r32_3" |
| picked_team_id | Integer | FK to teams.id |
| phase | Integer | 1 = R64+R32, 2 = S16+ |

Unique constraint: (user_id, game_slot)

### GameResult (`game_results` table)
| Column | Type | Notes |
|--------|------|-------|
| id | Integer | Primary key |
| game_slot | String(40) | Unique. e.g. "east_r64_1" |
| team1_id | Integer | FK to teams.id |
| team1_seed | Integer | |
| team2_id | Integer | FK to teams.id |
| team2_seed | Integer | |
| winner_id | Integer | FK to teams.id, nullable |
| round_number | Integer | 1-6 |
| score_team1 | Integer | nullable |
| score_team2 | Integer | nullable |

## Route Map

| Path | Method | Auth | Purpose |
|------|--------|------|---------|
| `/` | GET | Any | Redirect: logged-in -> /master, guest -> /master, else -> /login |
| `/login` | GET/POST | None | Combined page: guest access, claim entry, log in |
| `/logout` | GET | Any | Clear session, redirect to /login |
| `/master` | GET | Required | Main bracket page with toggle overlays |
| `/bracket/save` | POST | Required | Save picks (supports admin edit bypass via admin_edit flag) |
| `/leaderboard` | GET | Required | Leaderboard page |
| `/admin` | GET/POST | Admin PW | Admin panel: manage users, record results, toggle paid |
| `/admin/bracket/<id>` | GET | Admin PW | Read-only bracket view for a user |
| `/admin/bracket/<id>/edit` | GET | Admin PW | Editable bracket for a user (bypasses phase locks) |
| `/api/bracket` | GET | Required | JSON bracket state for current user |
| `/api/leaderboard` | GET | None | JSON leaderboard (blocked before tipoff) |

## Scoring System

### Round Points (linear)
| Round | Points |
|-------|--------|
| R64 | 1 |
| R32 | 2 |
| S16 | 3 |
| E8 | 4 |
| F4 | 5 |
| Championship | 6 |

### Upset Bonus
Awarded ONLY when the higher seed number (underdog) wins:
- Formula: `round(underdog_seed / favorite_seed)`
- Example: 13-seed beats 4-seed = `round(13/4)` = 3 bonus points
- Example: 1-seed beats 16-seed = NO bonus (favorite won)
- Total points for a correct pick = round_points + upset_bonus (if applicable)

### Leaderboard
- Sorted by total descending, then alphabetical by name for tiebreaker
- Standard competition ranking: ties get same rank, next rank skips (1, 1, 3, 4, 4, 6)
- Per-round breakdown columns: R64, R32, S16, E8, F4, Champ (each = round pts + bonus)
- Total Bonus column shows sum of all upset bonuses

## Phase System

### Phase 1: Opening Weekend (R64 + R32)
- **Lock time**: March 19, 2026 at 12:15 PM ET
- **Editable**: R64 and R32 picks
- **Total slots**: 48 (32 R64 + 16 R32)
- **Auto-submit**: When all 48 picks saved, `user.submitted = True`

### Phase 2: Rest of the Way (S16 through Championship)
- **Unlock**: March 23, 2026 at 4:20 AM ET
- **Lock**: March 26, 2026 at 12:00 PM ET
- **Editable**: S16, E8, F4, Championship picks
- **Constraint**: Can only pick teams still alive (not eliminated)
- **Editing location**: My Picks toggle on the master bracket page

### Admin Override
Admin edit routes (`/admin/bracket/<id>/edit`) bypass all phase locks. The save endpoint accepts `admin_edit: true` in the payload to skip phase validation.

## ESPN API Integration

### Polling
- `poll_and_grade()` runs every 5 minutes via APScheduler
- Fetches ESPN scoreboard API for yesterday through 4 days ahead
- First poll runs synchronously on startup for immediate data

### Game Matching
1. ESPN returns team names (e.g. "UConn Huskies")
2. `ESPN_NAME_OVERRIDES` maps ESPN names to internal names (e.g. "UConn")
3. Fuzzy matching via Levenshtein distance as fallback
4. Each ESPN game is matched to a bracket slot by teams + round number

### Auto-Grading
- When a game is final: creates/updates GameResult with winner, scores, seeds
- In-progress games: stored in `LIVE_GAME_DATA` (in-memory, not persisted)
- Scheduled games: tip times stored in `LIVE_GAME_DATA`

### LIVE_GAME_DATA Structure
```python
LIVE_GAME_DATA[slot] = {
    "status": "in_progress" | "scheduled" | "final",
    "team1_score": int,
    "team2_score": int,
    "clock": "H2 5:32",  # in_progress only
    "tip_time": "Thu 7:10 PM",  # scheduled only
}
```

## Master Page Toggle System

The master bracket page (`/master`) has 6 toggle modes:

| Toggle | Mode | Description |
|--------|------|-------------|
| Results | `off` | Ground truth bracket — actual game results, no overlays |
| My Picks | `picks` | User's projected bracket with green/red/strikethrough status. Editable for S16+ when phase 2 is open. |
| Leverage | `leverage` | Clean bracket + click-modal showing net leverage per game |
| vs Player | `vs` | User's bracket with agreement coloring + opponent's bracket cloned below |
| What If | `whatif` | Click teams in upcoming games to simulate outcomes and see rank changes |
| Exposure | `exposure` | Table view (no bracket) showing field pick percentages per round |

Toggle logic: radio-button behavior (one active at a time). `clearOverlays()` strips all overlay classes and removes projected/cloned elements when switching.

## Slot Naming Convention

```
Format: {region}_{round}_{game_number}

Examples:
  east_r64_1    = East region, Round of 64, game 1 (1 vs 16)
  west_r32_3    = West region, Round of 32, game 3
  midwest_s16_1 = Midwest Sweet 16, game 1
  south_e8_1    = South Elite 8
  f4_1          = Final Four semifinal 1 (East vs West)
  f4_2          = Final Four semifinal 2 (Midwest vs South)
  championship  = Championship game
  ff_west_11    = First Four play-in, West 11-seed
```

R64 game ordering within a region: 1v16, 8v9, 5v12, 4v13, 6v11, 3v14, 7v10, 2v15

## Data Flow

### Pick Submission
1. User clicks team in My Picks toggle (phase 2) or admin edit page
2. Client updates `editPicks` / `picks` object + `pendingPicks` tracker
3. Cascade-clear downstream picks if a pick changes
4. Propagate pick forward to populate parent game slots
5. User clicks "Save" -> POST `/bracket/save` with `{picks: {slot: teamId}, phase: N}`
6. Server validates phase timing + alive team status
7. Server upserts picks, deletes cleared ones
8. If phase 1 complete (48 picks), auto-sets `user.submitted = True`

### Auto-Grading (ESPN)
1. Scheduler triggers `poll_and_grade()` every 5 minutes
2. Fetch ESPN scoreboard for multiple dates
3. Match each game to a bracket slot via team name fuzzy matching
4. If game is final: create/update GameResult in DB
5. If in-progress/scheduled: update LIVE_GAME_DATA (in-memory)
6. Next page load picks up new results from DB

### Overlay Rendering (My Picks example)
1. `applyMyPicks()` called when toggle activated
2. `injectUserBracket(userId)` replaces R32+ slots with user's projected picks
3. For each projected element: check feeder result + eliminated status
4. Apply CSS classes: `overlay-correct`, `overlay-wrong`, `pick-eliminated`, or none
5. Add point annotations on correct picks
6. Update summary bar with total points and rank
