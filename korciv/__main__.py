"""실행: python -m korciv  (헤드리스 시뮬레이션: python -m korciv --simulate 100)"""
import argparse
import sys


def simulate(turns, enemies, seed):
    from .game import Game
    from .state import Settings
    g = Game(Settings(n_enemies=enemies, seed=seed, all_ai=True))
    for _ in range(turns):
        g.end_turn()
        if g.game_over:
            break
    print(g.date_label())
    for f in sorted(g.factions, key=lambda f: -g.region_count(f.id)):
        if f.alive:
            print(f"  {f.name:10s} {f.leader_name:8s} 지역 {g.region_count(f.id):3d}  GDP {g.gdp(f.id):10,.0f}"
                  f"  자금 {f.money:12,.0f}  행복도 {g.avg_happiness(f.id):+6.1f}")
    if g.winner:
        from .config import VICTORY_TYPES
        print("승리:", ", ".join(g.fname(x) for x in g.winner[0]), VICTORY_TYPES[g.winner[1]])


def main():
    ap = argparse.ArgumentParser(prog="python -m korciv")
    ap.add_argument("--simulate", type=int, metavar="TURNS", help="AI끼리 N턴 진행하고 결과 출력(창 없음)")
    ap.add_argument("--enemies", type=int, default=5)
    ap.add_argument("--seed", type=int, default=1)
    args, rest = ap.parse_known_args()
    if args.simulate:
        simulate(args.simulate, args.enemies, args.seed)
        return
    from .ui.app import main as ui_main
    if sys.stderr is None:
        # pythonw(콘솔 창 없음)로 실행: 오류를 파일로 남긴다
        import os
        import traceback
        log = os.path.join(os.path.expanduser("~"), ".korciv", "error.log")
        try:
            ui_main(rest)
        except Exception:
            os.makedirs(os.path.dirname(log), exist_ok=True)
            with open(log, "w", encoding="utf-8") as f:
                traceback.print_exc(file=f)
            raise
        return
    ui_main(rest)


if __name__ == "__main__":
    sys.exit(main())
