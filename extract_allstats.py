#!/usr/bin/env python3
"""One-off: extract per-fighter all-time totals from the comprehensive stats
workbook into all_stats_totals.json, which build_data.py uses to reconstruct
dropped players (see DROPPED_PLAYERS there).

The workbook has one sheet per stat; each has a header on row 2 and
(Rank, Portrait, Fighter, Value) columns. Play Time is duration-formatted.
Only summable counting stats are extracted (Peak Damage is a max, Play % is a
per-fighter percentage, and the *-avg sheets are derived — all excluded).

Run:  python3 extract_allstats.py [path-to-xlsx]   (needs `openpyxl`)
"""
import datetime
import json
import os
import sys

import openpyxl

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "SSBU_All_Stats_Final.xlsx")

# xlsx sheet name -> our stat key (must match build_data.py's stat keys)
SHEET2KEY = {
    "KOs": "KOs", "KOs Tilt Attack": "KOs_ Tilt Attack", "KOs Smash Attack": "KOs_ Smash Attack",
    "KOs Air Attack": "KOs_ Air Attack", "KOs Special Move": "KOs_ Special Move",
    "KOs Meteor Smash": "KOs_ Meteor Smash", "KOs Throw": "KOs_ Throw", "KOs Other": "KOs_ Other",
    "Falls": "Falls", "Self-Destructs": "Self-Destructs", "Total Falls": "Total Falls", "Battles": "Battles",
    "Play Time": "Play Time", "Victories (Smash Mode)": "Victories _Smash Mode",
    "Last-Place Finishes": "Last-Place Finishes", "Strong Finishes": "Strong Finishes",
    "Damage Given": "Damage Given", "Damage Taken": "Damage Taken", "Total Sudden Deaths": "Total Sudden Deaths",
    "Sudden Death Wins": "Sudden Death Wins", "Distance Walked": "Distance Walked",
    "Distance Jumped": "Distance Jumped", "Distance Fallen": "Distance Fallen", "Distance Launched": "Distance Launched",
}


def num(v):
    """Numbers pass through; durations ('2 days, 12:34:56', '66:49') -> minutes."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, datetime.timedelta):
        return v.total_seconds() / 60.0
    s = str(v).strip()
    days = 0
    if "day" in s:
        dpart, s = s.split(","); days = int(dpart.strip().split()[0]); s = s.strip()
    if ":" in s:
        parts = [float(x) for x in s.split(":")]
        if len(parts) == 3:
            mins = parts[0] * 60 + parts[1] + parts[2] / 60.0
        elif len(parts) == 2:
            mins = parts[0] * 60 + parts[1]
        else:
            return None
        return round(days * 24 * 60 + mins, 2)
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


def main():
    wb = openpyxl.load_workbook(SRC, read_only=True, data_only=True)
    totals = {}
    for sheet, key in SHEET2KEY.items():
        for r in list(wb[sheet].iter_rows(values_only=True))[2:]:
            if not r or r[2] is None:
                continue
            n = num(r[3])
            if n is not None:
                totals.setdefault(str(r[2]), {})[key] = round(n, 2)
    out = os.path.join(HERE, "all_stats_totals.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(totals, fh)
    print(f"wrote {out}: {len(totals)} fighters")


if __name__ == "__main__":
    main()
