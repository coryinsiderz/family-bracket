# Patterns and Conventions — Family Bracket App

## Slot Naming

All game slots follow `{region}_{round}_{number}` format:
- R64: `east_r64_1` through `east_r64_8` (8 games per region)
- R32: `east_r32_1` through `east_r32_4` (4 games per region)
- S16: `east_s16_1`, `east_s16_2` (2 games per region)
- E8: `east_e8_1` (1 game per region)
- F4: `f4_1` (East/West), `f4_2` (Midwest/South) — no region prefix
- Championship: `championship` — no region or number
- First Four: `ff_west_11`, `ff_midwest_16`, etc.

## PROGRESSION and FEEDS_INTO

Two complementary data structures define the bracket tree:

```javascript
// Parent -> [child1, child2] (which games feed into this game)
PROGRESSION["east_r32_1"] = ["east_r64_1", "east_r64_2"];
PROGRESSION["east_s16_1"] = ["east_r32_1", "east_r32_2"];
PROGRESSION["f4_1"] = ["east_e8_1", "west_e8_1"];
PROGRESSION["championship"] = ["f4_1", "f4_2"];

// Child -> {parent, position} (which game this feeds into)
FEEDS_INTO["east_r64_1"] = { parent: "east_r32_1", position: 0 };
FEEDS_INTO["east_r64_2"] = { parent: "east_r32_1", position: 1 };
```

Both are built from `BRACKET_PROGRESSION` in `bracket_data.py` and replicated in JS.

## Projection Functions

### injectUserBracket(userId, prefix)
Replaces R32+ game slots with the user's projected picks. For each slot in order (R32, S16, E8, F4, Championship):
1. Hide all existing team elements and TBDs in the slot
2. For each feeder, find the user's pick (the team they picked to win that feeder)
3. Create a `.master-projected` div with the team's seed/name
4. If phase 2 is open and it's the user's own bracket, make S16+ elements clickable

Key attributes on projected elements:
- `data-slot`, `data-team-id`, `data-seed`, `data-name` — standard team data
- `data-feeder-slot` — which feeder game this team came from (critical for coloring)
- `data-phase="2"` — only set when element is clickable (phase 2 editing)

The optional `prefix` parameter (default `"mgame-"`) supports the cloned opponent bracket (`"mgame-opp-"`).

### injectProjectedPicks(userId, prefix)
Different from `injectUserBracket`. Only injects teams for feeders with NO result yet. Used by Leverage and What If overlays where actual results should remain visible.

### applyMyPicksTo(userId, prefix)
Applies green/red/strikethrough coloring to projected elements. Reusable for both the main bracket and the cloned opponent bracket on vs Player.

## Overlay Color Rules

### The R64 Rule
R64 elements NEVER get overlay colors on ANY tab. Only raw game data + point annotations (My Picks only).

### My Picks / Bracket Page
For each projected team in R32+:
- **Green** (`overlay-correct`): feeder game played AND team won the feeder (team is alive)
- **Red + strikethrough** (`overlay-wrong`): feeder game played AND team lost the feeder
- **Strikethrough only** (`pick-eliminated`): team is eliminated but the feeder game for THIS round hasn't been played
- **No color**: feeder game hasn't been played and team isn't eliminated (pending)
- **Bold**: team the user picked to WIN this specific round

### vs Player
Shows YOUR picks in R32+, colored by agreement with the opponent:

Resolved games (feeder played):
- **Steel blue** (`overlay-match`): both picked the same team. + strikethrough if eliminated.
- **Green** (`overlay-correct`): your pick was right, they picked differently.
- **Orange** (`vs-them`): your pick was wrong, they picked differently. + strikethrough.

Pending games:
- **Steel blue** (`overlay-match`): both agree
- **Purple** (`vs-diff`): different picks (swing game)
- **Strikethrough only** (`pick-eliminated`): eliminated but game not played

### Leverage
No visual coloring on the bracket. Every R32+ game is clickable for a detail modal showing net leverage calculation.

### What If
Click teams in upcoming games to simulate outcomes. Simulated winners get blue highlight with dashed border.

## Phase Locking Logic

```python
# app.py
PHASE1_LOCK = datetime(2026, 3, 19, 12, 15, 0, tzinfo=ET)
PHASE2_UNLOCK = datetime(2026, 3, 23, 4, 20, 0, tzinfo=ET)
PHASE2_LOCK = datetime(2026, 3, 26, 12, 0, 0, tzinfo=ET)

def phase1_open(): return now_et() < PHASE1_LOCK
def phase2_open(): return PHASE2_UNLOCK <= now_et() < PHASE2_LOCK
```

Phase 1 (R64+R32): editable before March 19 12:15 PM ET. After that, locked forever.
Phase 2 (S16+): editable between March 23 4:20 AM and March 26 12:00 PM ET.

The old `/bracket` page is deleted. Phase 1 editing was done there (and via Paste Bracket). Phase 2 editing now happens on the My Picks toggle of `/master`.

Admin edit routes bypass all phase locks by setting `phase1_open=True, phase2_open=True` in the template context and `admin_edit=True` in the save payload.

## Pick Editing (Phase 2 on Master Page)

When phase 2 is open, the My Picks toggle enables interactive S16+ picking:

### Client-side state
```javascript
let editPicks = {};      // slot -> { id, name, seed }
let pendingPicks = {};   // slot -> teamId or null (for deletes)
let hasChanges = false;
```

### Key functions
- `initEditPicks()`: Loads existing phase 2 picks from `ALL_PICKS` into `editPicks`
- `pickTeamMaster(el)`: Handles click on S16+ projected element. Validates alive team, updates `editPicks` and `ALL_PICKS`, cascade-clears downstream, re-renders overlay.
- `cascadeClearMaster(slot, oldTeamId)`: Walks up the bracket tree clearing picks that depended on the old team.
- `savePicksMaster()`: POSTs phase 2 picks to `/bracket/save`.

### Save bar
Appears at bottom when `hasChanges` is true. Has "Save Rest of the Way" button. Hidden when switching away from My Picks.

## Guest vs Logged-in User

### Guest
- Session has `guest=True`, no `user_id`
- Can see: Leaderboard, Master Bracket (all toggles)
- Player selector dropdown appears on My Picks/Leverage/vs Player to browse any player's data
- Cannot: edit picks, access admin

### Logged-in User
- Session has `user_id`
- All guest capabilities plus: pick editing (when phases are open)
- My Picks defaults to own picks without dropdown

## Admin Panel (`/admin`)

Protected by `ADMIN_PASSWORD` env var. Capabilities:
- **Record/delete game results**: manual override for any game slot
- **Toggle paid status**: mark users as paid/unpaid
- **Create user**: name only, empty password (claimable on login page)
- **Reset password**: set new password for any user
- **Delete user**: removes user and all their picks
- **View bracket**: read-only view of any user's bracket
- **Edit bracket**: full pick editing for any user, bypasses phase locks

## CSS Theme

Dark minimalist. Key variables:
```css
--bg: #0a0a0f
--bg-card: #12121a
--border: #2a2a3a
--text: #e0e0e0
--text-dim: #6a6a8a
--green: #4caf50
--red: #f44336
--yellow: #ffc107
--accent: #4a9eff (blue)
```

No emojis. Monospace-inspired font stack. Compact spacing.

## Paste Bracket Feature

Located in `bracket.html` (used by admin edit routes). Allows pasting 32 lines to fill R64+R32 at once.

### Format
32 lines, 8 per region (East, West, Midwest, South). Each line is an R64 game winner. UPPERCASE = R32 winner in each pair.

### Matching
1. Exact alias lookup (~200 aliases covering abbreviations, mascots, nicknames)
2. Substring match
3. Levenshtein distance (max 2 for 5+ char names, 1 for shorter)

### Error handling
Unmatched lines show a dropdown with the 2 valid teams from that R64 matchup. User selects the correct team, R32 winner recalculates, preview updates live.

## Key JS Globals (master.html)

| Variable | Type | Source | Purpose |
|----------|------|--------|---------|
| `RESULTS` | Object | Server | `{slot: {winner_id, team1_id, team2_id, score_team1, score_team2}}` |
| `LIVE_DATA` | Object | Server | Live/scheduled game data from ESPN |
| `TEAMS` | Object | Server | `{teamId: {id, name, seed, region}}` |
| `ALL_PICKS` | Object | Server | `{userId: {slot: teamId}}` — all users' picks |
| `BOARD` | Array | Server | Leaderboard entries with scores and ranks |
| `USERS` | Array | Server | `[{id, name}]` for all users |
| `PROGRESSION` | Object | Server | `{slot: [feeder1, feeder2]}` bracket tree |
| `ROUNDS` | Object | Server | `{roundKey: {name, points, number}}` |
| `FEEDS_INTO` | Object | Client | Reverse of PROGRESSION: `{slot: {parent, position}}` |
| `CURRENT_USER_ID` | Number | Server | Logged-in user's ID (null for guests) |
| `VIEWING_USER_ID` | Number | Client | Who we're viewing (changeable by guest dropdown) |
| `IS_GUEST` | Boolean | Server | True if guest session |
| `PHASE2_OPEN` | Boolean | Server | Whether phase 2 picking is currently open |
| `ALIVE_TEAM_IDS` | Set | Server | Team IDs still alive (only populated when phase 2 open) |
| `activeMode` | String | Client | Current toggle: 'off', 'picks', 'leverage', 'vs', 'whatif', 'exposure' |

## Common Gotchas

1. **Template changes need server restart**: Flask caches templates. Always restart after editing `.html` files.
2. **R64 overlay colors**: Every new overlay function must explicitly skip R64 slots. Check `if (rk === 'r64') return;`.
3. **Feeder result vs slot result**: A team's color in R32 depends on the R64 feeder result (did they win R64?), NOT the R32 result. The R32 result determines coloring in S16.
4. **Eliminated set is global**: `getEliminatedTeams()` returns ALL eliminated teams from ALL results. A team eliminated in R64 shows up as eliminated everywhere.
5. **Cloned bracket ID conflicts**: When cloning `#master-bracket-wrapper` for vs Player, all `mgame-` IDs must be re-prefixed to `mgame-opp-` to avoid `getElementById` conflicts.
6. **Phase 2 alive teams**: Only populated when `phase2_open()` is true. When false, `ALIVE_TEAM_IDS` is an empty set. Don't rely on it outside phase 2.
7. **Upset bonus in leverage modal**: Must check which team is the underdog. Bonus only applies to the scenario where the higher seed number wins.
8. **ALL_PICKS mutation**: Phase 2 editing mutates `ALL_PICKS[CURRENT_USER_ID]` client-side so overlay re-renders see the changes. This is intentional but means the data diverges from server state until saved.
