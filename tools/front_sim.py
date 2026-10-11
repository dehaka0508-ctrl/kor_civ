"""전쟁 중 AI 전선 측정: 전원 AI 게임을 돌리며 전쟁 중인 AI 마다 매 턴
- 전선 칸: 전쟁 상대 땅과 육상으로 맞닿은 내 지역
- 빈 전선 비율: 육군이 하나도 없는 전선 칸 / 전선 칸
- 쏠림: 전선 병력 중 가장 많은 한 칸의 비율, 가장 큰 부대 / 전체 육군
- 전과: 전쟁 중 빼앗은·빼앗긴 지역
python tools/front_sim.py --games 20 --turns 240
"""
import argparse
import statistics as S
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from korciv import diplomacy as D
from korciv.game import Game
from korciv.state import Settings, NEUTRAL


def land_units(a):
    return sum(n for k, n in a.units.items() if k in ("inf", "tank", "art"))


def measure(g, fid):
    w = g.world
    enemies = set(D.enemies(g, fid))
    if not enemies:
        return None
    front = [r.id for r in g.regions_of(fid)
             if any(g.regions[n].owner in enemies for n in w.land_adj[r.id])]
    if not front:
        return None
    at = {rid: 0 for rid in front}
    total = 0
    biggest = 0
    for a in g.armies.values():
        if a.owner != fid or w.is_sea(a.loc):
            continue
        n = land_units(a)
        total += n
        biggest = max(biggest, n)
        if a.loc in at:
            at[a.loc] += n
    fr_units = sum(at.values())
    return dict(front=len(front), empty=sum(1 for v in at.values() if v == 0) / len(front),
                peak=(max(at.values()) / fr_units) if fr_units else 0.0,
                big=(biggest / total) if total else 0.0, units=total, fr_units=fr_units)


BATTLES = [0]
_gb = Game._ground_battle


def _count_battle(self, *a, **k):
    BATTLES[0] += 1
    return _gb(self, *a, **k)


Game._ground_battle = _count_battle


def run(seed, turns, n):
    g = Game(Settings(n_enemies=n, seed=seed, all_ai=True))
    BATTLES[0] = 0
    rows = []
    taken = lost = 0
    nb = 0
    for _ in range(turns):
        if g.game_over:
            break
        own = {rid: r.owner for rid, r in g.regions.items()}
        g.end_turn()
        for rid, r in g.regions.items():
            o0 = own[rid]
            if o0 != r.owner and o0 != NEUTRAL and r.owner != NEUTRAL and D.at_war(g, o0, r.owner):
                taken += 1
        for f in g.factions:
            if f.alive:
                m = measure(g, f.id)
                if m:
                    rows.append(m)
    dead = sum(1 for f in g.factions if not f.alive)
    return rows, taken, g.turn, BATTLES[0], dead


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=10)
    ap.add_argument("--turns", type=int, default=240)
    ap.add_argument("--n", type=int, default=7)
    ap.add_argument("--seed0", type=int, default=1)
    a = ap.parse_args()
    allr, tk, nbs, deads = [], 0, 0, 0
    for s in range(a.seed0, a.seed0 + a.games):
        rows, taken, t, nb, dead = run(s, a.turns, a.n)
        allr += rows
        tk += taken
        nbs += nb
        deads += dead
    if not allr:
        print("전쟁 없음")
        return
    def avg(k): return S.mean(r[k] for r in allr)
    print(f"전쟁 중 나라-턴 {len(allr)}  전선 칸 평균 {avg('front'):.1f}")
    print(f"빈 전선 비율 {avg('empty')*100:.1f}%   전선 칸 하나에 몰린 비율 {avg('peak')*100:.1f}%"
          f"   가장 큰 부대 / 전체 육군 {avg('big')*100:.1f}%")
    print(f"육군 평균 {avg('units'):.1f}  그중 전선 {avg('fr_units'):.1f}   전쟁으로 넘어간 지역 {tk/a.games:.1f}/판"
          f"   전투 {nbs/a.games:.0f}/판   멸망 {deads/a.games:.2f}/판")


if __name__ == "__main__":
    main()
