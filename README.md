# Squad Smash Stats

An offline data-viz dashboard for our group's **Super Smash Bros. Ultimate**
stats — 26 players, 39 tracked stats, broken down per fighter.

## Use it

Just double-click **`index.html`**. No server, no install — the stats are baked into the
file; the only external assets are the fighter portraits in `portraits/` (loaded by
relative path, so they work both on `file://` and when hosted).

Three views:

- **🏆 Leaderboards** — rank all 26 players by any stat. Serious ones (KOs, win rate,
  K/D, damage ratio) and the fun ones (most drownings, self-destructs, distance walked,
  peak-damage king). Top 3 get the podium treatment.
- **👤 Players** — tap any player for a profile: headline stat cards showing where they
  rank in the group, their top-3 "mains" as portraits, their most-played fighters
  (with official portraits) plus per-fighter KOs and win rate, and pie charts of their
  KO-type mix and fighter usage.
- **🎮 Characters** — a portrait grid of every fighter; tap one for group totals on that
  fighter, a "played most by" list, the best players with it (sample-adjusted), and a
  usage-share pie.

Two controls sit under the tabs:

- **⚖️ Weighted ⇄ Raw** — *Weighted* (default) adjusts every rate for sample size, so a
  fighter played once can't top a list; *Raw* shows unadjusted numbers. See below.
- **🔎 Filter players** — a checklist to show/hide any players (e.g. folks who left);
  hidden players drop out of leaderboards, the players grid, *and* character aggregates.
  Both preferences persist per browser.

## Data

- `data/` holds the raw CSVs, one per `<player> - <stat>`. These were OCR'd from
  in-game screenshots (the `candidates` column is the OCR audit trail: `{value: vote_count}`).
- `portraits/` holds the 86 official fighter stock portraits (72×64 PNG), named to match
  the `character` field exactly. The profile view falls back to an initials badge if a
  portrait is ever missing.
- **OCR reconciliation** (`reconcile()` in `build_data.py`): the rows are in the game's
  true rank order, so chosen values must be non-increasing down a file. `read_value` was
  already picked using that order, which hides digit-inflations on the *top* cell (a
  too-big number just sits at the top without breaking the order). For each cell whose OCR
  readings disagree, we keep only candidates consistent with the neighbours' bounds and
  take the most-voted one. This corrects **20 cells out of ~84,000** — all obvious
  digit-inflations like `ace / Young Link` playtime `88216 → 8816` or `Jackson / Hero`
  battles `200 → 20`. Unanimous-but-wrong reads can't be detected and are left as-is.
- **Battles-cap correction** (`cap_by_battles()`): a fighter can't have more strong
  finishes or victories than battles it played. The rank pass misses these when two errors
  are adjacent (an inflated cell props up the one above it) or when the *majority* reading
  is itself the impossible one — so we re-pick the best candidate `<=` that fighter's
  battle count. Fixes 4 cells, e.g. `Oweeeen / Pokemon Trainer` strong finishes `300 → 30`
  (which was showing Oweeeen a 194% Strong Finish Rate) and `Rudizzle / Villager` `913 → 513`.
- **Percentage audit** (`audit_percentages()`): after correction the build asserts that no
  derived rate (Win Rate, Strong Finish Rate) and no inherent game percentage (Play %,
  Win/Strong-Finish Rate Last-10/50) exceeds 100%, and prints a warning if any slips
  through. Currently all pass.
- Player values are aggregated from the per-fighter rows:
  - **Counting stats** (KOs, Battles, Damage, Distances, …) are **summed** across fighters.
  - **Rates/ratios** (Win Rate, K/D, Damage Ratio, Avg Falls/Battle) are **derived** from
    the totals — you can't average per-fighter rates meaningfully.
  - **Peak Damage** is the **max** across fighters.
- `Play Time` is stored in **minutes** in the source data and displayed as hours.
- Echo fighters (Peach/Daisy, etc.) are kept separate — we're ranking players, not fighters.

### Reconstructed (dropped) players

The Switch drops players who haven't played in a long time, so some real players
have no per-player CSVs. They're reconstructed from a comprehensive all-time totals
workbook (`SSBU_All_Stats_Final.xlsx` → `all_stats_totals.json` via
`extract_allstats.py`): for each fighter a dropped player mained, their stats are the
**all-time per-fighter total minus the sum of currently-recorded players** — what's
left is theirs. This only holds when the player is the *sole* missing contributor for
those fighters, which is asserted per-player in `DROPPED_PLAYERS` in `build_data.py`.
Underivable stats (Peak Damage is a max, not a sum; anything absent from the workbook)
are omitted so the UI shows **"—"** rather than a fabricated number. Reconstructed
players are tagged in the UI (a gold `↺` on their card and a "reconstructed" note on
their profile). Currently: **Khiry** (Peach / Daisy / Wii Fit Trainer).

### Sample-size guards

- **Rate-based leaderboards** (Win Rate, K/D, KOs/Battle, Avg Falls/Battle, Damage Ratio,
  Strong Finish Rate) require a player to have at least **`MIN_BATTLES` (100)** battles to
  appear. Counting totals (Total KOs, Damage, Distances, the Hall of Shame boards, etc.)
  are never filtered. All 26 current players clear 100, so today this is a guardrail.
- **Per-fighter Win%** in profiles is dimmed for fighters with fewer than
  **`MIN_FIGHTER_BATTLES` (10)** battles, so a "100% off one game" reads as low-sample
  rather than a real result. Both thresholds are constants at the top of the script block
  in `index.html`.
- **Weighted mode** (default, toggleable) applies empirical-Bayes shrinkage to every rate:
  `weighted = (rawRate × n + prior × C) / (n + C)`, where `n` = battles, `C` = `SHRINK_C`
  (20 pseudo-battles), and `prior` is the context baseline (the group rate on a leaderboard,
  the player's overall rate for a per-fighter Win%, the fighter's group rate on a character
  page). A one-game 100% gets pulled almost all the way to the baseline; a 200-game sample
  barely moves. This is what stops "played Chrom once, tops the list". Flip to **Raw** for
  the unadjusted numbers.

## Regenerate

If you update the CSVs in `data/`, rebuild the embedded dataset:

```bash
python3 build_data.py
```

This reads every `data/*.csv`, aggregates per player, and injects the JSON back into
`index.html` between the `/*DATA_START*/ … /*DATA_END*/` markers.
