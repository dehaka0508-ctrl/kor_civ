"""새 규칙 통합 퍼징: 3모드·대기열 교환·매 재해·지진 5~9·저장 복원을 반복한다.

python tools/qa_systems.py --turns 160 --seeds 4
"""
import argparse
from collections import Counter
from pathlib import Path
import pickle
import random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from korciv import config as C, rules as R, ai
from korciv.disasters import WEATHER
from korciv.game import Game
from korciv.state import Settings
import qa_fuzz as QA


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--turns', type=int, default=160)
    parser.add_argument('--seeds', type=int, default=4)
    args = parser.parse_args()
    counts = Counter()
    for mode in C.GAME_MODES:
        for seed in range(args.seeds):
            rng = random.Random(seed + 9100)
            g = Game(Settings(mode=mode, seed=seed + 9100, n_enemies=3, player_start='S002',
                              player_leader='cus', victories=('time',), max_turns=1200))
            g.set_player_government('presidential')
            # 한 나라 50개 지역: 대규모 국가의 재해와 복구·중앙 지출·광역 명령 상호작용을 검사.
            picked, frontier = {'S002'}, ['S002']
            while frontier and len(picked) < 50:
                rid = frontier.pop(0)
                for n in sorted(g.world.land_adj[rid]):
                    if n not in picked and g.regions[n].owner in (-1, 0):
                        picked.add(n)
                        frontier.append(n)
                        if len(picked) == 50:
                            break
            for rid in picked:
                g.transfer_region(rid, 0, '시험 편입')
                g._take_garrison(rid, 0)
                r = g.regions[rid]
                r.pop, r.happy = 1, 30
                r.b.update(farm=1, bank=1)
            g.player.res['food'] = 100000
            for _ in range(args.turns):
                if not g.player.alive or g.game_over:
                    break
                g.player.money = 1e8
                g.pending_proposals.clear()
                for rid in list(g.pending_rebellions):
                    g.resolve_rebellion(0, rid, 'suppress')
                for rid in rng.sample(sorted(r.id for r in g.regions_of(0)), min(8,g.region_count(0))):
                    options = [o for o in g.options(0,rid) if o['ok'] and o['kind'] in ('build','unit','repair','annex')]
                    if options and len(g.local_projects(rid)) < 12:
                        o = rng.choice(options)
                        g.start_project(0,rid,o['kind'],o['key'],border=o.get('border'),site=o.get('site'),pool=o.get('pool'))
                        counts['예약'] += 1
                    ps = g.local_projects(rid)
                    if len(ps) > 1 and rng.random() < .5:
                        g.move_queued_project(0,rid,rng.randrange(len(ps)),rng.randrange(len(ps)))
                        counts['순서 변경'] += 1
                    if len(ps) > 1 and rng.random() < .2:
                        g.cancel_queued_project(0,rid,rng.randrange(1,len(ps)))
                        counts['대기 취소'] += 1
                if (g.turn-1) % 12 == 0:
                    kind = list(WEATHER)[((g.turn-1)//12) % len(WEATHER)]
                    rid = rng.choice(sorted(picked))
                    g.forecast_disaster(kind, rid=rid, duration=2)
                    counts[kind] += 1
                if g.turn % 25 == 0:
                    magnitude = 5 + ((g.turn // 25 - 1) % 5)
                    g.earthquake(rng.choice(sorted(picked)), magnitude)
                    counts[f'quake{magnitude}'] += 1
                ai._disaster_response(g, g.player)
                QA.check(g, f'{mode} seed={seed} turn={g.turn} 명령 후')
                g.end_turn()
                QA.check(g, f'{mode} seed={seed} turn={g.turn} 턴 종료')
                if g.turn % 20 == 0:
                    g = pickle.loads(pickle.dumps(g))
                    counts['저장 복원'] += 1
                    QA.check(g, f'{mode} seed={seed} turn={g.turn} 복원 후')
            print(f'{mode} seed={seed} turn={g.turn} 완료', flush=True)
    print(dict(counts))
    print('문제 없음' if not QA.PROBLEMS else dict(QA.PROBLEMS))
    return bool(QA.PROBLEMS)


if __name__ == '__main__':
    sys.exit(main())
