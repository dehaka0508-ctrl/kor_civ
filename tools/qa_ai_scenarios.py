"""지도자 전원의 풍부한 자원·학술 기반·전쟁·재해 상황에서 실제 AI 계획과 저장을 검사한다."""
import argparse
import pickle
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from korciv import config as C, diplomacy as D, slots as S
from korciv.game import Game
from korciv.leaders import LEADERS, POLICIES
from korciv.state import Settings
import qa_fuzz as Q


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--turns', type=int, default=16)
    ap.add_argument('--seed', type=int, default=14100)
    args = ap.parse_args()
    buys = techs = policies = 0
    for index, leader in enumerate(LEADERS):
        mode = list(C.GAME_MODES)[index % 3]
        g = Game(Settings(seed=args.seed + index, mode=mode, player_start='S002', ai_starts=['N001'],
                          n_enemies=1, player_leader=leader['key'], ai_leaders=['cus'],
                          victories=('time', 'science', 'economic', 'diplomatic'), max_turns=1000))
        g.set_player_government(list(POLICIES)[index % len(POLICIES)])
        g.player.is_ai = True
        g.factions[1].is_ai = False
        sites = [rid for rid in g.land_within(g.player.capital, 3) if g.regions[rid].owner == -1]
        sites = sorted(sites, key=lambda r: (-g.info(r).area_km2, r))[:8]
        for rid in [g.player.capital] + sites:
            if g.regions[rid].owner != 0:
                g.transfer_region(rid, 0, reason='편입')
            r = g.regions[rid]
            r.pop, r.happy = 12, 20
            r.b.clear_cards()
            # 실제 슬롯 안에만 배치한다. 좁은 도시는 행정·연구, 넓은 도시는 산업·군사까지 가진다.
            for key, lv in [('admin', 4), ('edu', 4), ('factory', 3), ('bank', 3), ('academy', 1)]:
                if key != 'academy' or leader['key'] != 'sta':
                    r.b.place(key, lv)
            if g.info(rid).specialties:
                r.b.place('specialty', 3)
            if g.info(rid).coastal:
                r.b.place('port', 1)
            for army in list(g.armies_at(rid)):
                if army.owner != 0:
                    g.remove_army(army)
        g.player.money = g.player.res['food'] = 1e6
        g.player.admin = g.player.sci_points = 30000
        g.player.ai['victory_goal'] = ('science', 'economic', 'conquest')[index % 3]
        g.player.ai['goal_turn'] = g.turn
        g.new_army(0, g.player.capital, {'inf': 12, 'tank': 4})
        border = next(r for r in sorted(g.world.land_adj[g.player.capital]) if r not in sites)
        g.transfer_region(border, 1, reason='편입')
        g.new_army(1, border, {'inf': 4})
        D._start_war(g, 1, 0, aggressor=1)
        for turn in range(args.turns):
            if turn == 5:
                g.set_flooded(sites[-1])
            if turn == 9:
                g.earthquake(sites[0], 5)
            g.end_turn()
            Q.check(g, f'ai scenario/{mode}/{leader["key"]} turn={g.turn}')
            if turn % 4 == 0:
                g = pickle.loads(pickle.dumps(g))
                Q.check(g, 'ai scenario reload')
        buys += sum(g.great_people_bought.values())
        techs += len(g.player.techs)
        policies += g.player.policy_level
        print(f'{leader["key"]}/{mode} turns={args.turns} people={sum(g.great_people_bought.values())} tech={len(g.player.techs)} policy={g.player.policy_level}', flush=True)
    print('Totals:', dict(people_bought=buys, technologies=techs, policies=policies), flush=True)
    print('Problems:', dict(Q.PROBLEMS), flush=True)
    return bool(Q.PROBLEMS)


if __name__ == '__main__':
    raise SystemExit(main())
