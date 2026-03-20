# Backlog — Family Bracket App

## What's Complete and Live (on main)

### Core Features
- [x] User authentication: login, guest access, claim entry flow
- [x] Combined login page: guest / log in / claim entry (single `/login` route)
- [x] Admin panel: create users, reset passwords, delete users, toggle paid, record results
- [x] Admin bracket edit: edit any user's picks bypassing phase locks
- [x] Phase 1 pick submission: R64+R32 picks with save/submit flow
- [x] Paste Bracket: 32-line paste with fuzzy matching, dropdown fallback for unmatched teams
- [x] Auto-grading: ESPN API polling every 5 minutes, automatic result recording
- [x] Scoring: linear round points (1-6) + upset bonus (round(underdog/favorite) when underdog wins)
- [x] Leaderboard: per-round columns (R64-Champ), total bonus, alphabetical tiebreaker, standard competition ranking
- [x] Prize display: "1st Place: $80 | 2nd Place: $20" on leaderboard

### Master Bracket Page (single main page, replaces old /bracket)
- [x] Results toggle: ground truth bracket with scores
- [x] My Picks toggle: user's projected bracket with green/red/strikethrough
- [x] Leverage toggle: clean bracket + click-modal with net leverage calculation
- [x] vs Player toggle: comparison overlay with 5 colors + opponent bracket clone below
- [x] What If toggle: simulate game outcomes, see rank changes
- [x] Exposure toggle: table view of field pick percentages per round
- [x] Guest mode: player selector dropdown on My Picks/Leverage/vs Player
- [x] Phase 2 pick editing: S16+ picks editable in My Picks when phase 2 opens

### Display Rules
- [x] R64 column never gets overlay colors (universal rule across all tabs)
- [x] Forward-looking overlay coloring (results shown in the round team advanced to)
- [x] Red vs strikethrough distinction (feeder played vs game not played)
- [x] Point annotations on correct picks in the round where points were earned

## Phase 2 Status

Phase 2 editing (S16+ picks on My Picks toggle) has been implemented and tested locally:
- Tested by temporarily setting `PHASE2_UNLOCK` to a past date
- Click-to-pick, cascade clear, propagation, and save all verified working
- Phase 2 unlock date: March 23, 2026 at 4:20 AM ET
- Phase 2 lock date: March 26, 2026 at 12:00 PM ET

## Known Areas to Watch

### When R32 Results Start Coming In
- My Picks overlay should handle R32 results correctly (tested with R64 results only so far)
- S16 projected picks should transition from strikethrough-only to red+strikethrough as R32 games complete
- Leverage modal calculations for R32+ games are implemented but only tested with R64 results
- Point annotations for R32 correct picks should appear in R32 column

### When Phase 2 Opens (March 23)
- `ALIVE_TEAM_IDS` will be populated with teams that won R64
- S16+ projected elements become clickable
- Save bar appears on My Picks toggle
- Need to verify that saving phase 2 picks works with the production database

### ESPN Grader Edge Cases
- Games spanning midnight may need attention
- Doubleheader days with many games
- Possible ESPN API changes or outages (app continues to work, just doesn't auto-grade)

## Potential Improvements (Not Prioritized)

### UI/UX
- Mobile responsiveness: bracket needs horizontal scroll or collapsible regions on small screens
- Toggle buttons could be a dropdown on mobile
- Leverage modal: mobile bottom-sheet pattern instead of centered modal
- vs Player: ability to compare any two players (not just "you vs X")

### Technical
- Caching: leaderboard calculation runs on every page load. Could cache with short TTL.
- WebSocket or SSE for live score updates instead of polling
- Move inline JS from templates to separate .js files
- Add error boundaries / graceful degradation when JS globals are missing

### Features
- Head-to-head record across multiple years
- Historical bracket archive
- Tiebreaker game (total championship score prediction)
- Notification system (email/SMS when results change standings)
- Export bracket as image/PDF

## Completed Feature Branches (Merged to Main)

- `fix/bracket-mypicks-display`: Unified My Picks and bracket page display logic
- `fix/vs-player-colors`: vs Player 5-color scheme, opponent bracket clone, R64/strikethrough fixes
- `fix/leverage-rework`: Leverage formula fix (net leverage with ownership discount), modal rework
- `fix/leverage-r32-clicks`: Event delegation for leverage modal on projected picks
- `feature/master-bracket`: Original master bracket with all 6 toggles
- `feature/my-picks-editing`: Phase 2 pick editing on My Picks toggle, opponent bracket on vs Player
