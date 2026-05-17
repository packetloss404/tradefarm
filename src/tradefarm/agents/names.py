"""Deterministic agent display names.

Maps a numeric agent_id (0..N) to a stable office-style handle of the
form ``first_last``. Pure function of agent_id, so names survive
restarts and DB rebuilds.

The 100 first names and 100 last names below are each unique within their
column and paired 1:1 with the agent_id — so every component appears
exactly once across the roster and every full name is distinct. For
agent_ids beyond 100 we fall back to ``trader_NNN``; the orchestrator
ships with agent_count=100 so the fallback is just defensive.
"""
from __future__ import annotations

_FIRSTS: tuple[str, ...] = (
    "michael", "jennifer", "david", "sarah", "james", "lisa", "robert", "amy",
    "kevin", "emily", "brian", "rachel", "eric", "melissa", "chris", "jenna",
    "andrew", "kate", "ryan", "hannah", "paul", "anna", "thomas", "claire",
    "peter", "olivia", "joseph", "sophia", "matthew", "ava", "samuel", "mia",
    "jacob", "ella", "nathan", "lily", "anthony", "grace", "jonathan", "chloe",
    "benjamin", "zoe", "scott", "ruby", "patrick", "julia", "gregory", "kayla",
    "edward", "brooke", "derek", "alyssa", "frank", "taylor", "neil", "danielle",
    "ian", "vanessa", "glenn", "stephanie", "todd", "natalie", "alan", "monica",
    "philip", "christine", "vincent", "holly", "harold", "jasmine", "marcus", "simone",
    "leon", "autumn", "jeremy", "isabel", "dennis", "victoria", "calvin", "paige",
    "randy", "nora", "alex", "sienna", "chad", "audrey", "terrence", "miles",
    "oliver", "bianca", "henry", "willow", "raj", "priya", "arjun", "devi",
    "li", "mei", "wei", "yuki",
)

_LASTS: tuple[str, ...] = (
    "smith", "johnson", "williams", "brown", "jones", "garcia", "miller", "davis",
    "rodriguez", "martinez", "hernandez", "lopez", "gonzalez", "wilson", "anderson", "thomas",
    "wagner", "moore", "jackson", "martin", "lee", "perez", "thompson", "white",
    "harris", "sanchez", "clark", "ramirez", "lewis", "robinson", "walker", "young",
    "allen", "king", "wright", "novak", "torres", "nguyen", "hill", "flores",
    "green", "adams", "nelson", "baker", "hall", "rivera", "campbell", "mitchell",
    "carter", "roberts", "gomez", "phillips", "evans", "turner", "diaz", "parker",
    "cruz", "edwards", "collins", "reyes", "stewart", "morris", "morales", "murphy",
    "cook", "rogers", "gutierrez", "ortiz", "morgan", "cooper", "peterson", "bailey",
    "reed", "kelly", "howard", "ramos", "kim", "cox", "ward", "richardson",
    "watson", "brooks", "chavez", "wood", "bennett", "gray", "mendoza", "ruiz",
    "hughes", "price", "alvarez", "castillo", "sanders", "patel", "myers", "long",
    "ross", "foster", "jimenez", "okafor",
)


def agent_display_name(agent_id: int) -> str:
    if 0 <= agent_id < len(_FIRSTS):
        return f"{_FIRSTS[agent_id]}_{_LASTS[agent_id]}"
    return f"trader_{agent_id:03d}"
