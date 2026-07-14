#!/usr/bin/env python3
"""Aggregate the per-player / per-stat SSBU CSVs in data/ into a single compact
JSON dataset, then inject it into index.html between the DATA markers.

Each CSV is named "<player> - <stat>.csv" and holds that player's per-character
breakdown for one stat, with columns: rank,character,read_value,candidates,correct.
We only use `character` and `read_value`.

Run:  python3 build_data.py
"""
import ast
import csv
import glob
import json
import os
import re
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
HTML_PATH = os.path.join(HERE, "index.html")

# Stats that are counting totals -> a player's value is the sum across characters.
SUMMABLE = {
    "KOs", "Falls", "Total Falls", "Battles", "Victories _Smash Mode",
    "Damage Given", "Damage Taken", "Damage Recovered",
    "Distance Fallen", "Distance Jumped", "Distance Launched",
    "Distance Swam", "Distance Walked",
    "Drownings", "Final Smashes", "Items Grabbed", "Self-Destructs",
    "Strong Finishes", "Sudden Death Wins", "Total Sudden Deaths",
    "Last-Place Finishes", "Play Time",
    "KOs_ Air Attack", "KOs_ Final Smash", "KOs_ Item", "KOs_ Meteor Smash",
    "KOs_ Other", "KOs_ Smash Attack", "KOs_ Special Move", "KOs_ Throw",
    "KOs_ Tilt Attack",
}
# Stats where a player's value is the max across characters.
MAXABLE = {"Peak Damage"}

# Per-character fields we keep for profiles (from these stats).
CHAR_FIELDS = {
    "Battles": "battles",
    "KOs": "kos",
    "Victories _Smash Mode": "victories",
    "Total Falls": "falls",
    "Play Time": "playTime",
    "Damage Given": "damageGiven",
}


def parse_value(raw):
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def parse_candidates(s):
    """The `candidates` column is a Python-dict literal: {read_value: vote_count}."""
    s = (s or "").strip()
    if not s:
        return {}
    try:
        return {float(k): int(v) for k, v in ast.literal_eval(s).items()}
    except (ValueError, SyntaxError):
        return {}


def reconcile(rows):
    """Rank-bounded majority-vote OCR correction.

    Files are in the game's true rank order, so chosen values must be
    non-increasing. `read_value` was already picked using that order, which
    hides digit-inflations on top-ranked cells (a too-big number just sits at
    the top and never breaks the order). For each cell with disagreeing OCR
    readings, we keep only candidates consistent with the neighbours' bounds,
    then take the most-voted one. This touches only genuinely ambiguous cells.

    rows: list of {char, val, cand}. Returns (corrected_values, changes).
    """
    n = len(rows)
    out = [r["val"] for r in rows]
    changes = []
    for i, r in enumerate(rows):
        cand = dict(r["cand"])
        cand.setdefault(r["val"], 0)  # current reading is always an option
        if len(cand) <= 1:
            continue  # unanimous / single reading -> trust it
        prev_v = out[i - 1] if i > 0 else float("inf")
        next_v = rows[i + 1]["val"] if i + 1 < n else float("-inf")
        valid = {v: c for v, c in cand.items()
                 if v <= prev_v + 1e-9 and v >= next_v - 1e-9}
        pool = valid or cand
        best = max(pool.values())
        top = [v for v, c in pool.items() if c == best]
        if r["val"] in top:                 # prefer the original on a tie
            choice = r["val"]
        elif len(top) == 1:
            choice = top[0]
        else:                               # pick nearest the neighbour midpoint
            mid = (min(prev_v, 1e12) + max(next_v, 0)) / 2
            choice = min(top, key=lambda v: abs(v - mid))
        out[i] = choice
        if abs(choice - r["val"]) > 1e-6:
            changes.append((r["char"], r["val"], choice))
    return out, changes


# Per-character counts that can never exceed that character's battle count.
CAPPED_BY_BATTLES = ["Strong Finishes", "Victories _Smash Mode"]

# Game fields that are inherently 0-100 percentages.
PCT_STATS = ["Play %", "Win Rate _Last 10", "Win Rate _Last 50",
             "Strong Finish Rate _Last 10", "Strong Finish Rate _Last 50"]


def cap_by_battles(raw, cands):
    """A fighter can't strong-finish or win more battles than it played.

    The rank pass can miss these when errors are adjacent (an inflated cell
    props up the one above it) or when the majority reading is itself the
    impossible one. Here we re-pick the best candidate <= the battle count.
    """
    changes = []
    for player, stats in raw.items():
        battles = stats.get("Battles", {})
        for stat in CAPPED_BY_BATTLES:
            for ch, v in list(stats.get(stat, {}).items()):
                cap = battles.get(ch)
                if cap is None or v <= cap + 0.5:
                    continue
                cand = cands[player][stat].get(ch, {})
                options = {val: votes for val, votes in cand.items() if val <= cap + 0.5}
                if options:                       # best candidate under the cap
                    best = max(options.values())
                    pick = max(val for val, votes in options.items() if votes == best)
                else:                             # no candidate fits -> drop a digit
                    pick = next((round(v / d) for d in (10, 100, 1000)
                                 if v / d <= cap + 0.5), cap)
                if abs(pick - v) > 1e-6:
                    raw[player][stat][ch] = pick
                    changes.append((player, stat, ch, v, pick))
    return changes


# (player, character) OCR errors confirmed by domain knowledge that the
# automated passes can't catch — the reading is internally consistent (in rank
# order, within battle caps) but still wrong. "min" re-picks the smallest OCR
# candidate for every stat of that player+character (these rows were inflated
# across the board and the small candidate is the true value); "drop" removes
# the character from that player entirely.
MANUAL_FIXES = {
    # Wolf is barely played across the group; several players' Wolf rows read
    # inflated (a big OCR value alongside a coherent small one). Confirmed by
    # the group that none of these are real Wolf players — take the small reading.
    ("keg", "Wolf"): "min",
    ("chrisw", "Wolf"): "min",
    ("ace", "Wolf"): "min",
    ("Jackson", "Wolf"): "min",
    ("seanrad", "Wolf"): "min",
}


def apply_manual_fixes(raw, cands):
    changes = []
    for (player, char), action in MANUAL_FIXES.items():
        for stat, per_char in list(raw.get(player, {}).items()):
            if char not in per_char:
                continue
            if action == "drop":
                old = per_char.pop(char)
                changes.append((player, stat, char, old, 0))
            elif action == "min":
                cand = cands.get(player, {}).get(stat, {}).get(char, {})
                if not cand:
                    continue
                lo = min(cand.keys())
                if abs(lo - per_char[char]) > 1e-6:
                    changes.append((player, stat, char, per_char[char], lo))
                    per_char[char] = lo
    return changes


def audit_percentages(raw):
    """Report any percentage or derived rate that still exceeds 100%."""
    problems = []
    for player, stats in raw.items():
        for stat in PCT_STATS:
            for ch, v in stats.get(stat, {}).items():
                if v > 100.5:
                    problems.append(f"{player} / {stat} / {ch} = {v}")
    for player, stats in raw.items():
        b = sum(stats.get("Battles", {}).values())
        if not b:
            continue
        wr = sum(stats.get("Victories _Smash Mode", {}).values()) / b * 100
        sfr = sum(stats.get("Strong Finishes", {}).values()) / b * 100
        if wr > 100.5:
            problems.append(f"{player} Win Rate = {wr:.1f}%")
        if sfr > 100.5:
            problems.append(f"{player} Strong Finish Rate = {sfr:.1f}%")
    if problems:
        print(f"WARNING: {len(problems)} percentage(s) still exceed 100%:")
        for p in problems:
            print("  " + p)
    else:
        print("percentage audit: all rates <= 100% OK")


def _report_changes(label, changes):
    if not changes:
        return
    print(f"{label}: corrected {len(changes)} cell(s):")
    for player, stat, ch, old, new in sorted(changes, key=lambda c: -abs(c[4] - c[3])):
        print(f"  {player:12s} {stat:22s} {ch:18s} {old:g} -> {new:g}")


def load():
    files = glob.glob(os.path.join(DATA_DIR, "*.csv"))
    # player -> stat -> {character: value}
    raw = defaultdict(lambda: defaultdict(dict))
    cands = defaultdict(lambda: defaultdict(dict))
    rank_changes = []
    for path in files:
        base = os.path.basename(path)[:-4]  # strip .csv
        if " - " not in base:
            continue
        player, stat = base.split(" - ", 1)
        rows = []
        with open(path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                char = (row.get("character") or "").strip()
                val = parse_value(row.get("read_value"))
                if char and val is not None:
                    rows.append({
                        "char": char,
                        "val": val,
                        "cand": parse_candidates(row.get("candidates")),
                    })
        corrected, changes = reconcile(rows)
        for r, v in zip(rows, corrected):
            raw[player][stat][r["char"]] = v
            cands[player][stat][r["char"]] = r["cand"]
        for ch, old, new in changes:
            rank_changes.append((player, stat, ch, old, new))

    _report_changes("OCR reconciliation (rank order)", rank_changes)
    _report_changes("OCR reconciliation (battles cap)", cap_by_battles(raw, cands))
    _report_changes("Manual OCR fixes (domain knowledge)", apply_manual_fixes(raw, cands))
    audit_percentages(raw)
    return raw


def aggregate(raw):
    players = {}
    for player, stats in raw.items():
        agg = {"name": player, "totals": {}, "characters": {}}

        for stat, per_char in stats.items():
            if stat in SUMMABLE:
                agg["totals"][stat] = round(sum(per_char.values()), 2)
            elif stat in MAXABLE:
                agg["totals"][stat] = round(max(per_char.values()), 2) if per_char else 0

        # per-character breakdown for profiles
        chars = defaultdict(dict)
        for stat, field in CHAR_FIELDS.items():
            for char, val in stats.get(stat, {}).items():
                chars[char][field] = round(val, 2)
        agg["characters"] = dict(chars)

        players[player] = agg
    return players


def derive(players):
    """Add computed stats that can't be summed (rates/ratios)."""
    for p in players.values():
        t = p["totals"]
        battles = t.get("Battles", 0) or 0
        victories = t.get("Victories _Smash Mode", 0) or 0
        kos = t.get("KOs", 0) or 0
        falls = t.get("Total Falls", t.get("Falls", 0)) or 0
        dmg_given = t.get("Damage Given", 0) or 0
        dmg_taken = t.get("Damage Taken", 0) or 0
        strong = t.get("Strong Finishes", 0) or 0

        d = {}
        d["Win Rate"] = round(victories / battles * 100, 1) if battles else 0
        d["K/D Ratio"] = round(kos / falls, 2) if falls else 0
        d["Damage Ratio"] = round(dmg_given / dmg_taken, 2) if dmg_taken else 0
        d["Avg Falls/Battle"] = round(falls / battles, 2) if battles else 0
        d["KOs/Battle"] = round(kos / battles, 2) if battles else 0
        d["Strong Finish Rate"] = round(strong / battles * 100, 1) if battles else 0
        p["derived"] = d
    return players


def main():
    raw = load()
    players = derive(aggregate(raw))

    # Build the stat catalog for the leaderboard dropdown.
    # (label, key, group, source, unit, higherIsBetter)
    dataset = {
        "players": players,
        "generatedFrom": len(glob.glob(os.path.join(DATA_DIR, "*.csv"))),
    }

    payload = json.dumps(dataset, separators=(",", ":"))
    print(f"players: {len(players)}  payload: {len(payload)/1024:.0f} KB")

    with open(HTML_PATH, encoding="utf-8") as fh:
        html = fh.read()

    new_html = re.sub(
        r"(/\*DATA_START\*/).*?(/\*DATA_END\*/)",
        lambda m: m.group(1) + "window.SSBU=" + payload + ";" + m.group(2),
        html,
        flags=re.DOTALL,
    )
    with open(HTML_PATH, "w", encoding="utf-8") as fh:
        fh.write(new_html)
    print(f"injected into {HTML_PATH}")


if __name__ == "__main__":
    main()
