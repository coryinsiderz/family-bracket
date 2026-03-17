"""
2026 NCAA Tournament bracket data.

Game slot naming convention:
  - First Four: ff_{region}_{seed}  (e.g. ff_west_11)
  - R64: {region}_r64_{game}  where game = 1..8 (top to bottom in the region)
  - R32: {region}_r32_{game}  where game = 1..4
  - S16: {region}_s16_{game}  where game = 1..2
  - E8:  {region}_e8_1
  - F4:  f4_{semifinal}  (1 = East/West winner, 2 = Midwest/South winner)
  - Championship: championship

Bracket ordering within each region (R64 games 1-8):
  1: 1v16, 2: 8v9, 3: 5v12, 4: 4v13, 5: 6v11, 6: 3v14, 7: 7v10, 8: 2v15

R32 feeds: game1 = winner(r64_1) vs winner(r64_2), game2 = winner(r64_3) vs winner(r64_4), etc.
S16 feeds: game1 = winner(r32_1) vs winner(r32_2), game2 = winner(r32_3) vs winner(r32_4)
E8 feeds:  winner(s16_1) vs winner(s16_2)
"""

# Teams: (name, seed, region, is_first_four, first_four_group)
# first_four_group links the two teams that play each other in the First Four
TEAMS = [
    # EAST
    ("Duke", 1, "east", False, None),
    ("Siena", 16, "east", False, None),
    ("Ohio State", 8, "east", False, None),
    ("TCU", 9, "east", False, None),
    ("St. John's", 5, "east", False, None),
    ("Northern Iowa", 12, "east", False, None),
    ("Kansas", 4, "east", False, None),
    ("Cal Baptist", 13, "east", False, None),
    ("Louisville", 6, "east", False, None),
    ("South Florida", 11, "east", False, None),
    ("Michigan State", 3, "east", False, None),
    ("North Dakota State", 14, "east", False, None),
    ("UCLA", 7, "east", False, None),
    ("UCF", 10, "east", False, None),
    ("UConn", 2, "east", False, None),
    ("Furman", 15, "east", False, None),

    # WEST
    ("Arizona", 1, "west", False, None),
    ("LIU", 16, "west", False, None),
    ("Villanova", 8, "west", False, None),
    ("Utah State", 9, "west", False, None),
    ("Wisconsin", 5, "west", False, None),
    ("High Point", 12, "west", False, None),
    ("Arkansas", 4, "west", False, None),
    ("Hawaii", 13, "west", False, None),
    ("BYU", 6, "west", False, None),
    ("Texas", 11, "west", True, "ff_west_11"),
    ("NC State", 11, "west", True, "ff_west_11"),
    ("Gonzaga", 3, "west", False, None),
    ("Kennesaw State", 14, "west", False, None),
    ("Miami (FL)", 7, "west", False, None),
    ("Missouri", 10, "west", False, None),
    ("Purdue", 2, "west", False, None),
    ("Queens", 15, "west", False, None),

    # MIDWEST
    ("Michigan", 1, "midwest", False, None),
    ("UMBC", 16, "midwest", True, "ff_midwest_16"),
    ("Howard", 16, "midwest", True, "ff_midwest_16"),
    ("Georgia", 8, "midwest", False, None),
    ("Saint Louis", 9, "midwest", False, None),
    ("Texas Tech", 5, "midwest", False, None),
    ("Akron", 12, "midwest", False, None),
    ("Alabama", 4, "midwest", False, None),
    ("Hofstra", 13, "midwest", False, None),
    ("Tennessee", 6, "midwest", False, None),
    ("SMU", 11, "midwest", True, "ff_midwest_11"),
    ("Miami (OH)", 11, "midwest", True, "ff_midwest_11"),
    ("Virginia", 3, "midwest", False, None),
    ("Wright State", 14, "midwest", False, None),
    ("Kentucky", 7, "midwest", False, None),
    ("Santa Clara", 10, "midwest", False, None),
    ("Iowa State", 2, "midwest", False, None),
    ("Tennessee State", 15, "midwest", False, None),

    # SOUTH
    ("Florida", 1, "south", False, None),
    ("Prairie View A&M", 16, "south", True, "ff_south_16"),
    ("Lehigh", 16, "south", True, "ff_south_16"),
    ("Clemson", 8, "south", False, None),
    ("Iowa", 9, "south", False, None),
    ("Vanderbilt", 5, "south", False, None),
    ("McNeese", 12, "south", False, None),
    ("Nebraska", 4, "south", False, None),
    ("Troy", 13, "south", False, None),
    ("North Carolina", 6, "south", False, None),
    ("VCU", 11, "south", False, None),
    ("Illinois", 3, "south", False, None),
    ("Penn", 14, "south", False, None),
    ("Saint Mary's", 7, "south", False, None),
    ("Texas A&M", 10, "south", False, None),
    ("Houston", 2, "south", False, None),
    ("Idaho", 15, "south", False, None),
]

# First Four matchups: slot -> (team_name_1, team_name_2)
FIRST_FOUR = {
    "ff_west_11": ("Texas", "NC State"),
    "ff_midwest_16": ("UMBC", "Howard"),
    "ff_midwest_11": ("SMU", "Miami (OH)"),
    "ff_south_16": ("Prairie View A&M", "Lehigh"),
}

# R64 matchups per region: game_number -> (top_seed, bottom_seed)
# For First Four slots, the seed listed is the FF seed, and the actual team
# is determined by the FF result.
R64_MATCHUPS = {
    "east": [
        (1, "Duke", 16, "Siena"),
        (8, "Ohio State", 9, "TCU"),
        (5, "St. John's", 12, "Northern Iowa"),
        (4, "Kansas", 13, "Cal Baptist"),
        (6, "Louisville", 11, "South Florida"),
        (3, "Michigan State", 14, "North Dakota State"),
        (7, "UCLA", 10, "UCF"),
        (2, "UConn", 15, "Furman"),
    ],
    "west": [
        (1, "Arizona", 16, "LIU"),
        (8, "Villanova", 9, "Utah State"),
        (5, "Wisconsin", 12, "High Point"),
        (4, "Arkansas", 13, "Hawaii"),
        (6, "BYU", 11, None),  # None = First Four slot ff_west_11
        (3, "Gonzaga", 14, "Kennesaw State"),
        (7, "Miami (FL)", 10, "Missouri"),
        (2, "Purdue", 15, "Queens"),
    ],
    "midwest": [
        (1, "Michigan", 16, None),  # FF slot ff_midwest_16
        (8, "Georgia", 9, "Saint Louis"),
        (5, "Texas Tech", 12, "Akron"),
        (4, "Alabama", 13, "Hofstra"),
        (6, "Tennessee", 11, None),  # FF slot ff_midwest_11
        (3, "Virginia", 14, "Wright State"),
        (7, "Kentucky", 10, "Santa Clara"),
        (2, "Iowa State", 15, "Tennessee State"),
    ],
    "south": [
        (1, "Florida", 16, None),  # FF slot ff_south_16
        (8, "Clemson", 9, "Iowa"),
        (5, "Vanderbilt", 12, "McNeese"),
        (4, "Nebraska", 13, "Troy"),
        (6, "North Carolina", 11, "VCU"),
        (3, "Illinois", 14, "Penn"),
        (7, "Saint Mary's", 10, "Texas A&M"),
        (2, "Houston", 15, "Idaho"),
    ],
}

# Map R64 game positions that have First Four teams
# (region, game_index 0-based) -> first_four_slot
FIRST_FOUR_SLOTS = {
    ("west", 4): "ff_west_11",
    ("midwest", 0): "ff_midwest_16",
    ("midwest", 4): "ff_midwest_11",
    ("south", 0): "ff_south_16",
}

REGIONS = ["east", "west", "midwest", "south"]

# Round names and point values
ROUNDS = {
    "r64": {"name": "Round of 64", "points": 1, "number": 1},
    "r32": {"name": "Round of 32", "points": 2, "number": 2},
    "s16": {"name": "Sweet 16", "points": 3, "number": 3},
    "e8": {"name": "Elite 8", "points": 4, "number": 4},
    "f4": {"name": "Final Four", "points": 5, "number": 5},
    "championship": {"name": "Championship", "points": 6, "number": 6},
}

# Game slot progression: defines which two game slots feed into each subsequent slot
BRACKET_PROGRESSION = {}

for region in REGIONS:
    # R64 -> R32
    for i in range(1, 5):
        parent = f"{region}_r32_{i}"
        child1 = f"{region}_r64_{2 * i - 1}"
        child2 = f"{region}_r64_{2 * i}"
        BRACKET_PROGRESSION[parent] = (child1, child2)

    # R32 -> S16
    for i in range(1, 3):
        parent = f"{region}_s16_{i}"
        child1 = f"{region}_r32_{2 * i - 1}"
        child2 = f"{region}_r32_{2 * i}"
        BRACKET_PROGRESSION[parent] = (child1, child2)

    # S16 -> E8
    parent = f"{region}_e8_1"
    child1 = f"{region}_s16_1"
    child2 = f"{region}_s16_2"
    BRACKET_PROGRESSION[parent] = (child1, child2)

# E8 -> F4
BRACKET_PROGRESSION["f4_1"] = ("east_e8_1", "west_e8_1")
BRACKET_PROGRESSION["f4_2"] = ("midwest_e8_1", "south_e8_1")

# F4 -> Championship
BRACKET_PROGRESSION["championship"] = ("f4_1", "f4_2")


def get_all_game_slots():
    """Return all game slots in order: FF, R64, R32, S16, E8, F4, Championship."""
    slots = []

    # First Four
    for ff_slot in FIRST_FOUR:
        slots.append(ff_slot)

    # R64
    for region in REGIONS:
        for i in range(1, 9):
            slots.append(f"{region}_r64_{i}")

    # R32
    for region in REGIONS:
        for i in range(1, 5):
            slots.append(f"{region}_r32_{i}")

    # S16
    for region in REGIONS:
        for i in range(1, 3):
            slots.append(f"{region}_s16_{i}")

    # E8
    for region in REGIONS:
        slots.append(f"{region}_e8_1")

    # F4
    slots.append("f4_1")
    slots.append("f4_2")

    # Championship
    slots.append("championship")

    return slots


def get_round_for_slot(slot):
    """Return the round key for a game slot."""
    if slot.startswith("ff_"):
        return "ff"
    if slot == "championship":
        return "championship"
    if slot.startswith("f4_"):
        return "f4"
    # Format: {region}_{round}_{game}
    parts = slot.split("_")
    return parts[1]


def get_phase_for_slot(slot):
    """Return which phase (1 or 2) a game slot belongs to."""
    round_key = get_round_for_slot(slot)
    if round_key in ("ff", "r64", "r32"):
        return 1
    return 2


def get_feeder_slots(slot):
    """Return the two feeder slots for a given game slot, or None for R64/FF."""
    return BRACKET_PROGRESSION.get(slot)
