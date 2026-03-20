# Claude Code Rules — Family Bracket App

## Critical Rules

- **Git safety**: Never force-push, never reset --hard, never amend without explicit permission. Create new commits. Use feature branches for non-trivial work.
- **No production DB mutations**: Never write startup code that modifies, deletes, or seeds picks, users, or game results. The production database on Railway/Neon has real user data.
- **Feature branches**: For anything beyond a quick fix, work on a branch (`git checkout -b feature/name` or `fix/name`). Merge to main only when the user says to.
- **No emojis in code or UI**: The app uses a dark minimalist style. No emojis anywhere except the favicon.
- **Test before pushing**: Use the dev server (port 5050) and preview tools to verify changes visually before committing. Flask caches templates — restart the server after template changes.
- **Port 5050**: The bracket app runs on port 5050. Port 5001 is occupied by a golf tool — never use it.

## Key Gotchas

- **R64 column never gets overlay colors**: On every toggle (My Picks, Leverage, vs Player, What If), the R64 column must have zero CSS overlay classes — no green, red, blue, orange, strikethrough, or dimming. Only raw game data (seed, name, score) and point annotations. This is an absolute rule across the entire app.
- **Flask template caching**: After editing any `.html` template, you MUST restart the dev server. Changes won't appear otherwise. The preview server reuse often masks this.
- **LIVE_GAME_DATA is in-memory**: `espn_grader.py` maintains `LIVE_GAME_DATA` as a module-level dict that gets mutated each poll cycle. It's not persisted. Don't write code that depends on its state across server restarts.
- **Upset bonus direction**: The upset bonus ONLY applies when the higher seed number (underdog) wins. `round(higher_seed / lower_seed)` where higher_seed is the bigger number. Duke (1) beating Siena (16) = NO bonus. TCU (9) beating Ohio State (8) = bonus.
- **Overlay coloring is forward-looking**: A correct R64 pick shows green in R32 (where the team advanced to), not in R64 (where the game was played). Point annotations DO show in R64 though.
- **Red vs strikethrough distinction**: `overlay-wrong` (red + strikethrough) = feeder game was played and your pick lost. `pick-eliminated` (strikethrough only, no red) = team is eliminated but the game in THIS round hasn't been played yet.
- **injectUserBracket vs injectProjectedPicks**: `injectUserBracket()` replaces R32+ with the user's picks (for My Picks/vs Player). `injectProjectedPicks()` only injects for feeders with no result yet (for Leverage/What If). They serve different purposes.
- **Element IDs use `mgame-` prefix**: Master bracket game elements are `mgame-east_r32_1`, etc. The cloned opponent bracket uses `mgame-opp-` prefix. Both `injectUserBracket` and `applyMyPicksTo` accept an optional prefix parameter.
- **ALL_PICKS is the data backbone**: `ALL_PICKS[userId][slot] = teamId` holds every user's picks. It's passed from the server as JSON. The phase 2 editing functions mutate it client-side before re-rendering.

## Starting a Session

1. Check which branch you're on: `git branch --show-current`
2. Check for uncommitted changes: `git status`
3. Start the dev server: use `preview_start` with the `flask-dev` config (or verify it's running with `preview_list`)
4. The app runs at `http://localhost:5050`
5. Log in as "test" user for development

## Key File Locations

| File | Purpose |
|------|---------|
| `app.py` | Flask routes, auth, phase logic, DB init |
| `models.py` | SQLAlchemy models (User, Team, Pick, GameResult) |
| `scoring.py` | Leaderboard calculation, upset bonus, per-round scoring |
| `espn_grader.py` | ESPN API polling, team name matching, auto-grading |
| `bracket_data.py` | Tournament data: 68 teams, matchups, progression tree, rounds |
| `templates/master.html` | Main bracket page with all 6 toggle overlays |
| `templates/bracket.html` | Legacy pick-editing page (still used by admin routes) |
| `templates/leaderboard.html` | Leaderboard display |
| `templates/admin.html` | Admin panel |
| `templates/login.html` | Combined login/guest/claim page |
| `templates/base.html` | Nav bar, flash messages, page skeleton |
| `static/style.css` | All CSS — dark theme, bracket layout, overlay colors |
| `.claude/launch.json` | Dev server config for preview tools |

## Deployment

- **Hosting**: Railway (web service)
- **Database**: Neon Postgres via `DATABASE_URL` env var, SQLite fallback for local dev
- **ESPN polling**: Enabled via `ENABLE_ESPN_POLL` env var (default "1"). Set to "0" for local dev to skip ESPN calls.
- **Environment variables**: `SECRET_KEY`, `DATABASE_URL`, `ADMIN_PASSWORD`, `ENABLE_ESPN_POLL`

## Working Style

- No emojis in code, UI, or commit messages
- Direct communication — no filler phrases
- Show actual code blocks, not summaries, when asked for code
- Feature branches for anything non-trivial
- Test visually with preview server before pushing
- Commit messages: imperative mood, explain the "why" not the "what"
