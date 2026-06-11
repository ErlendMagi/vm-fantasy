"""Fallback when the scraper is broken: rebuild my_team.json by hand.

    python scraper/manual_entry.py

Type your 15 player names (fuzzy-matched against the last good players.json),
your bank and free transfers. Writes data/tv2/my_team.json with
scraper_mode=manual; projections and transfer suggestions keep working.
"""
import difflib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import config, data_access  # noqa: E402


def pick_player(players, prompt: str) -> str:
    names = {f"{r['name']} ({r['team']}, {r['position']})": pid
             for pid, r in players.iterrows()}
    while True:
        query = input(prompt).strip()
        if not query:
            continue
        matches = difflib.get_close_matches(query, names.keys(), n=5, cutoff=0.3)
        also = [k for k in names if query.lower() in k.lower() and k not in matches]
        options = (matches + also)[:6]
        if not options:
            print("  no match, try again")
            continue
        for i, m in enumerate(options, 1):
            print(f"   {i}. {m}")
        choice = input("  pick number (or blank to retype): ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(options):
            return names[options[int(choice) - 1]]


def main() -> None:
    players = data_access.load_players()
    if players is None:
        sys.exit("data/tv2/players.json missing - need at least one successful sync (or the seed data).")

    print(f"Enter your {config.SQUAD_SIZE} players.")
    squad = []
    while len(squad) < config.SQUAD_SIZE:
        pid = pick_player(players, f"[{len(squad)+1}/{config.SQUAD_SIZE}] name: ")
        if pid in squad:
            print("  already in squad")
            continue
        squad.append(pid)

    captain = pick_player(players, "captain name: ")
    bank = float(input("bank (money left, e.g. 0.5): ").strip() or 0)
    free = int(input("free transfers available (default 2): ").strip() or 2)

    now = datetime.now(timezone.utc).isoformat()
    out = {
        "synced_at": now, "squad": squad, "starting_xi": squad[:11],
        "captain_id": captain, "bank": bank, "free_transfers": free, "round_history": {},
    }
    (config.TV2_DIR / "my_team.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    meta = data_access.load_meta()
    meta.update({"last_synced": now, "scraper_mode": "manual"})
    meta.pop("is_stale", None), meta.pop("age_hours", None)
    (config.TV2_DIR / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print("wrote my_team.json - run 'git add data/ && git commit && git push' to update the site")


if __name__ == "__main__":
    main()
