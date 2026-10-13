import argparse
from pathlib import Path

from engine import load_bot_class, play_match

HERE = Path(__file__).resolve().parent
PLACE_POINTS = [3, 2, 1, 0]


def print_match(result):
    for entry in result["log"]:
        hp, energy, score, alive = entry["states"][0]
        state = f"hp {hp} en {energy} score {score}" if alive else f"dead, score {score}"
        print(f"T{entry['turn']:02d} YOU > {entry['outcomes'].get(0, 'idle')}   [{state}]")
        for event in entry["events"]:
            print(f"     * {event}")
    print()
    print(f"{'place':<7}{'bot':<6}{'score':>7}{'kills':>7}{'deaths':>8}{'banked':>8}{'illegal':>9}")
    for r in result["rows"]:
        print(f"{r['place']:<7}{r['name']:<6}{r['score']:>7}{r['kills']:>7}"
              f"{r['deaths']:>8}{r['banked']:>8}{r['illegal']:>9}")


def print_summary(results, label):
    you = [next(r for r in res["rows"] if r["id"] == 0) for res in results]
    places = [r["place"] for r in you]
    scores = [r["score"] for r in you]
    print(f"Maps played: {len(you)} vs 3 x {label}")
    print("Places: " + "  ".join(f"{p}{s}: {places.count(p)}" for p, s in
                                  [(1, "st"), (2, "nd"), (3, "rd"), (4, "th")]))
    avg_place = sum(places) / len(places)
    avg_points = sum(PLACE_POINTS[p - 1] for p in places) / len(places)
    print(f"Average place {avg_place:.2f}, series rank points per map {avg_points:.2f}")
    print(f"Score: average {sum(scores) / len(scores):.1f}, min {min(scores)}, max {max(scores)}")
    print(f"Illegal actions {sum(r['illegal'] for r in you)}, "
          f"bad turns {sum(r['bad_turns'] for r in you)}, "
          f"slowest decide {max(r['max_decide_ms'] for r in you):.2f} ms")


def main():
    parser = argparse.ArgumentParser(description="Play my_bot.py in the practice arena.")
    parser.add_argument("--seed", type=int, default=1, help="map seed for a single match")
    parser.add_argument("--seeds", type=int, default=0, help="play seeds 1..N and print a summary")
    parser.add_argument("--vs", type=Path, help="bot file for the three opponents (e.g. sparring.py)")
    args = parser.parse_args()

    you_cls = load_bot_class(HERE / "my_bot.py")
    opp_cls = load_bot_class(args.vs) if args.vs else you_cls
    label = args.vs.name if args.vs else "copies of my_bot.py"

    if args.seeds:
        print_summary([play_match(you_cls, opp_cls, s) for s in range(1, args.seeds + 1)], label)
    else:
        print_match(play_match(you_cls, opp_cls, args.seed))


if __name__ == "__main__":
    main()
