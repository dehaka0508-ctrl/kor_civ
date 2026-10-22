"""QA 퍼저: 게임 엔진을 무작위로 두드리며 예외와 불변식 위반을 찾는다(개발용).

  python tools/qa_fuzz.py sim --games 6 --turns 300          # 전원 AI, 매 턴 불변식 점검
  python tools/qa_fuzz.py player --games 6 --turns 200       # 플레이어가 매 턴 무작위 행동
문제가 생기면 시드·턴·내용을 출력하고 계속 진행한다(마지막에 요약).
"""
from __future__ import annotations

import argparse
import math
import os
import pickle
import random
import sys
import traceback
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from korciv import config as C                    # noqa: E402
from korciv import diplomacy as D                 # noqa: E402
from korciv import negotiation as NG              # noqa: E402
from korciv.game import Game                      # noqa: E402
from korciv.leaders import GOVERNMENTS, LEADERS   # noqa: E402
from korciv.state import NEUTRAL, Settings        # noqa: E402

PROBLEMS = Counter()
EXAMPLES = {}


def report(tag, msg):
    PROBLEMS[tag] += 1
    if tag not in EXAMPLES:
        EXAMPLES[tag] = msg
        print("  [문제]", tag, "-", msg, flush=True)


def finite(x):
    return isinstance(x, (int, float)) and math.isfinite(x)


def check(g, where):
    """불변식."""
    nf = len(g.factions)
    if g.winner and g.winner[1] == "conquest" and len(g.alive_ids()) > 1:
        w = g.winner[0][0]
        if D.enemies(g, w):                              # v1.3.0: 전쟁 중에는 정복승리 불발
            report("전쟁 중 정복승리", f"{where} f{w} 전쟁 {D.enemies(g, w)}")
    for rid, r in g.regions.items():
        if not (r.owner == NEUTRAL or 0 <= r.owner < nf):
            report("소유자 범위", f"{where} {rid} owner={r.owner}")
        elif r.owner != NEUTRAL and not g.factions[r.owner].alive:
            report("멸망 세력 소유", f"{where} {rid} owner={r.owner}")
        if not finite(r.pop) or r.pop < 0:
            report("인구 이상", f"{where} {rid} pop={r.pop}")
        if not finite(r.happy):
            report("행복도 NaN", f"{where} {rid}")
        for k, v in r.b.items():
            top = 6 if r.metro is not None and k in C.METRO_L6_KEYS else 5
            if not isinstance(v, int) or v < 0 or v > top:
                report("건물 단계 범위", f"{where} {rid} {k}={v}")
        if r.queue and g.queue_region(rid) is not r:
            report('광역시 대기열 위치', f'{where} {rid}')
        for queued in r.queue:
            if queued is r.project or not finite(queued.paid) or queued.paid < 0:
                report('대기열 상태', f'{where} {rid}')
        p = r.project
        if p is not None:
            if p.progress > p.turns or p.turns < 1:
                report("프로젝트 진행", f"{where} {rid} {p.kind}:{p.key} {p.progress}/{p.turns}")
            if r.owner == NEUTRAL:
                report("중립 지역 프로젝트", f"{where} {rid}")
            mt = getattr(p, "metro", None)
            if mt is not None and getattr(r, "metro", None) != mt:
                report("광역시 작업 불일치", f"{where} {rid} 작업 metro={mt} 지역 metro={getattr(r, 'metro', None)}")
            grp = getattr(p, "group", None)
            if grp is not None and (rid not in grp["lines"] or set(grp["lines"]) != set(grp["cost"])
                                    or p.per_turn < -1e-9 or p.paid < -1e-6):
                report("묶음 공사 불일치", f"{where} {rid} {p.name} {sorted(grp['lines'])}")
        mid = getattr(r, "metro", None)
        if mid is not None:
            m = getattr(g, "metros", {}).get(mid)
            if m is None or rid not in m["members"]:
                report("광역시 소속 불일치", f"{where} {rid} metro={mid}")
            elif len(m["members"]) > C.METRO_MAX_REGIONS:
                report("광역시 지역 수 초과", f"{where} {m['name']} {len(m['members'])}곳")
            elif len({g.regions[x].owner for x in m["members"]}) != 1:
                report("광역시 주인 갈라짐", f"{where} {m['name']} {[g.regions[x].owner for x in m['members']]}")
            elif len({id(g.regions[x].project) for x in m["members"]}) != 1 and not any(
                    getattr(g.regions[x], "lost_project", None) for x in m["members"]):
                report("광역시 슬롯 불일치", f"{where} {m['name']}")
        for fid, o in r.occs.items():
            if o["progress"] > o["need"] + 1:
                report("점령 진행 초과", f"{where} {rid} {o}")
    for f in g.factions:
        if not finite(f.money):
            report("돈 NaN", f"{where} f{f.id}")
        if not finite(f.admin) or f.admin < 0 or not finite(f.sci_points) or f.sci_points < 0:
            report("행정·과학 자원 불변식", f"{where} f{f.id} {f.admin}/{f.sci_points}")
        if not 0 <= f.policy_level <= 5:
            report("정책 단계 범위", f"{where} f{f.id} {f.policy_level}")
        for k, v in f.res.items():
            # v1.3.0: 판매 계약분은 배정보다 먼저 보내므로 석유·석탄·전기는 '보낸 계약량'까지 음수일 수 있다
            # (전기는 턴 끝 발전으로, 나머지는 시장 구매로 메운다)
            floor = -getattr(f, "sent", {}).get(k, 0) if k in C.ENERGY else 0
            if not finite(v) or v < floor - 1e-6:
                report("자원 음수/NaN", f"{where} f{f.id} {k}={v} (허용 {floor})")
        for k, v in f.specialty.items():
            if not finite(v) or v < -1e-6:
                report("특산물 음수", f"{where} f{f.id} {k}={v}")
        if f.alive:
            if g.regions.get(f.capital) is None or g.regions[f.capital].owner != f.id:
                if g.region_count(f.id) > 0:
                    report("수도 소유 불일치", f"{where} f{f.id} cap={f.capital} owner={g.regions.get(f.capital).owner}")
            if g.region_count(f.id) == 0:
                report("영토 없는 생존 세력", f"{where} f{f.id}")
        if not (0 <= f.tax <= 1):
            report("세율 범위", f"{where} f{f.id} {f.tax}")
        if not finite(f.war_weary) or f.war_weary < -1e-6:
            report("전쟁 피로 이상", f"{where} f{f.id} {f.war_weary}")
    for f in g.factions:
        for rr in g.regions.values():
            rl = getattr(rr, "rally", None)
            if rl is not None and rr.owner == f.id and rl not in g.regions:
                report("집결지 이상", f"{where} {rr.id} rally={rl}")
        if f.alive and getattr(f, "rally", None) is not None and f.rally not in g.regions:
            report("일괄 집결지 이상", f"{where} f{f.id} rally={f.rally}")
    for r in g.regions.values():
        if getattr(r, "rally", None) is not None and r.owner == NEUTRAL:
            report("중립 지역 집결지", f"{where} {r.id} rally={r.rally}")
    for aid, a in g.armies.items():
        if a.id != aid:
            report("부대 id 불일치", f"{where} {aid}")
        if a.loc not in g.regions and a.loc not in g.world.seas:
            report("부대 위치 이상", f"{where} {aid} {a.loc}")
        if not a.units or any(n <= 0 for n in a.units.values()):
            report("빈 부대/음수 유닛", f"{where} {aid} {a.units}")
        if a.owner != NEUTRAL and (a.owner >= nf or not g.factions[a.owner].alive):
            report("멸망 세력 부대", f"{where} {aid} owner={a.owner}")
        if a.loc in g.world.seas and a.domain() == "land" and a.owner != NEUTRAL:
            report("육군만 바다에", f"{where} {aid} {a.units}")
        if a.domain() == "naval" and (a.cargo_used() > a.cargo_cap() or a.air_used() > a.air_cap()):
            report("함대 수송·탑재 초과", f"{where} {aid} loc={a.loc} {a.units} 수송 {a.cargo_used()}/{a.cargo_cap()} "
                                      f"탑재 {a.air_used()}/{a.air_cap()}")
        if not g.solo_ok(a.units):
            report("포병·폭격기 혼성 부대", f"{where} {aid} loc={a.loc} {a.units}")
        stale = [k for k, d in a.dmg.items() if k not in a.units and d > 1e-9]
        if stale:
            report("없는 유닛의 피해 기록", f"{where} {aid} units={a.units} dmg={a.dmg}")
        for k, d in a.dmg.items():
            if not finite(d) or d < -1e-6 or (k in a.units and d > a.hp_max(k) + 1e-6):
                report("피해량 범위", f"{where} {aid} {k} dmg={d} max={a.hp_max(k) if k in a.units else '-'}")
    names = [gp["name"] for gp in g.great_people]
    if len(set(names)) != len(names) or not set(names) <= g.spawned_great_people:
        report("위인 중복·기록", where)
    for gp in g.great_people:
        escort = gp["kind"] == "general" and bool(g.armies_at(gp["loc"], gp["owner"]))
        if (gp["loc"] not in g.regions and gp["loc"] not in g.world.seas
                or (gp["loc"] not in g.regions or g.regions[gp["loc"]].owner != gp["owner"]) and not escort):
            report("위인 위치·소유", f"{where} {gp}")
    for key, v in vars(g.dip).items():
        if isinstance(v, dict):
            for kk, vv in v.items():
                if isinstance(vv, float) and not math.isfinite(vv):
                    report("외교 수치 NaN", f"{where} {key}")


def run_sim(seed, turns, n, mode="standard"):
    rng = random.Random(seed)
    leaders = [l["key"] for l in LEADERS if l["key"] != "cus"]
    lineup = rng.sample(leaders, n)
    g = Game(Settings(mode=mode, n_enemies=n - 1, seed=seed, all_ai=True, max_turns=turns, fog=rng.choice([0, 1, 2]),
                      difficulty=rng.randrange(len(C.DIFFICULTIES)), player_leader=lineup[0], ai_leaders=lineup[1:]))
    t = 0
    try:
        while not g.game_over and g.turn <= turns:
            g.end_turn()
            t += 1
            check(g, f"sim seed={seed} turn={g.turn}")
            if t % 60 == 0:
                g = pickle.loads(pickle.dumps(g))
                print(f'진행: sim/{mode} seed={seed} turn={g.turn}', flush=True)
    except Exception:
        report("예외(sim)", f"seed={seed} turn={g.turn}\n" + traceback.format_exc())
    return g


def player_turn(g, rng):
    """플레이어(0번)가 무작위로 이것저것 시도한다. 실패 메시지는 정상, 예외만 문제."""
    pid = g.player_id
    f = g.player
    mine = [r.id for r in g.regions_of(pid)]
    acts = 0
    from korciv.progression import TECHS, GREAT_PEOPLE
    if rng.random() < .4:
        g.unlock_policy(pid)
        g.unlock_tech(pid, rng.choice(list(TECHS)))
    if mine and rng.random() < .3:
        g.recruit_great_person(pid, rng.choice(list(GREAT_PEOPLE)), rng.choice(mine))
    people = [p for p in g.great_people if p["owner"] == pid]
    if people and mine:
        person = rng.choice(people)
        g.move_great_person(person["id"], rng.choice(mine))
        if rng.random() < .4:
            g.activate_great_person(person["id"], rng.choice(("project", "science")))
    # 반란·제안 응답
    for rid in list(g.pending_rebellions):
        g.resolve_rebellion(pid, rid, rng.choice(["pay", "tax", "suppress"]))
    for prop in list(g.pending_proposals):
        if rng.random() < 0.5 and g.factions[prop["from"]].alive:
            if prop["kind"] == "trade":                    # AI 자원 거래 제의: 협상(v1.3.0)
                st = prop.get("nego")
                if st and st["status"] == "open":
                    for _ in range(rng.randint(0, 5)):
                        if st["status"] != "open":
                            break
                        NG.player_offer(g, st, max(1, st["n"] + rng.choice([-1, 0, 0, 1, 3])),
                                        max(1, int(st["price"] * rng.uniform(0.3, 1.6))))
                    if st["status"] == "open" and rng.random() < 0.5:
                        NG.accept_ai_price(g, st)
            elif prop["kind"] != "coalition_war":
                D.sign_treaty(g, prop["from"], pid, prop["kind"])
        g.pending_proposals.remove(prop)
    # 슬롯
    for rid in rng.sample(mine, min(len(mine), 6)):
        rr = g.regions[rid]
        if rr.project and rng.random() < 0.08:
            g.cancel_project(pid, rid)
            continue
        ps = g.local_projects(rid)
        if len(ps) > 1 and rng.random() < .2:
            g.move_queued_project(pid, rid, rng.randrange(len(ps)), rng.randrange(len(ps)))
        if rr.queue and rng.random() < .15:
            g.cancel_queued_project(pid, rid, rng.randint(1, len(rr.queue)))
        if len(ps) > 8:
            continue
        opts = g.options(pid, rid)
        if opts:
            o = rng.choice(opts)
            if rng.random() < .15 and g.can_chain(o['kind'], o['key']):
                g.start_project_max(pid, rid, o['kind'], o['key'], site=o.get('site'), pool=o.get('pool'))
            else:
                g.start_project(pid, rid, o["kind"], o["key"], border=o.get("border"), site=o.get('site'), pool=o.get('pool'))
            acts += 1
        if rng.random() < 0.1:
            g.set_focus(pid, rid, rng.random() < 0.5)
        if rng.random() < 0.1:
            g.set_pop_focus(pid, rid, rng.random() < 0.5)
    # 부대
    armies = [a for a in g.armies.values() if a.owner == pid]
    for a in rng.sample(armies, min(len(armies), 6)):
        if a.id not in g.armies:
            continue
        r = rng.random()
        if r < 0.5:
            reach = list(g.reachable(a)) if a.id in g.armies else []
            near = list(g.world.node_neighbors(a.loc)) + reach
            if near:
                cmd = g.act_now if rng.random() < 0.6 else g.order_army     # 플레이어 명령은 바로 실행(v1.3.0)
                cmd(a.id, rng.choice(near), rng.choice(["assault", "surprise"]), force_bombard=rng.random() < 0.2,
                    move_only=g.solo_army(a) and rng.random() < 0.5)         # 포병·폭격기 부대 우클릭(v1.3.0)
        elif r < 0.6 and a.count() > 1:
            k = rng.choice(list(a.units))
            g.split_army(a.id, {k: max(1, a.units[k] // 2)})
        elif r < 0.7:
            others = [b for b in g.armies_at(a.loc, pid) if b.id != a.id]
            if others:
                g.merge_armies(a.id, others[0].id)
        elif r < 0.74:
            k = rng.choice(list(a.units))
            g.disband(a.id, {k: 1})
        elif r < 0.77 and g.boarding_target(a.id) is not None:
            if rng.random() < 0.5:
                g.board(a.id)                                      # 상륙함·항모에 태워 짐 실은 함대를 만든다
            else:
                k = rng.choice(list(a.units))
                g.load_cargo(g.boarding_target(a.id).id, a.id, {k: rng.randint(1, a.units[k])})
        elif r < 0.8 and a.domain() == "naval" and g.cargo_of(a):
            tg = list(g.landing_targets(a)) or [None]
            k = rng.choice(list(g.cargo_of(a)))
            g.unload_cargo(a.id, {k: rng.randint(1, a.units[k])} if rng.random() < 0.5 else None, rng.choice(tg))
        elif r < 0.8:
            g.order_army(a.id, rng.choice(list(g.regions)))      # 먼 곳 경로 계획
    # 국정
    if rng.random() < 0.2:
        g.set_tax(pid, rng.choice([0, 0.05, 0.1, 0.15, 0.2, 0.3, 1.0, -0.5, 2.0]))
    if rng.random() < 0.2:
        res = rng.choice(["food", "oil", "coal", "elec"])
        if rng.random() < 0.5:
            g.market_buy(pid, res, rng.choice([1, 5, 50, 10 ** 6, 0, -3]))
        else:
            g.market_sell(pid, res, rng.choice([1, 5, 50, 10 ** 6, 0, -3]))
    if rng.random() < 0.1:
        g.set_auto_energy(pid, rng.random() < 0.5)
    if rng.random() < 0.15 and mine:
        rid = rng.choice(mine)
        g.set_energy(pid, rid, rng.choice(["p", "f"]), rng.choice(["coal", "oil", "elec"]), rng.choice([0, 1, 3, 9, -1]))
    if rng.random() < 0.1 and mine:
        rid = rng.choice(mine)
        kinds = list(g.specialty_kinds(pid)) if hasattr(g, "specialty_kinds") else []
        if kinds:
            g.set_specialty(pid, rid, rng.choice(kinds), rng.choice(["pin", "block", "auto"]))
    if rng.random() < 0.05:                              # 국경 방어선 일괄 건설(v1.3.0, 묶음 공사)
        nbs = g.border_nations(pid)
        if nbs:
            g.build_border_lines(pid, rng.choice(nbs)[0], rng.randint(1, 5))
    if rng.random() < 0.02:                              # 묶음 공사 취소
        grp = [r.id for r in g.regions_of(pid) if r.project is not None and getattr(r.project, "group", None)]
        if grp:
            g.cancel_project(pid, rng.choice(grp))
    if rng.random() < 0.05:
        ids = [r.id for r in g.projects_by_priority(pid)] if hasattr(g, "projects_by_priority") else []
        rng.shuffle(ids)
        if ids:
            g.set_priority_order(pid, ids, manual=rng.random() < 0.5)
    if rng.random() < 0.04 and mine:                    # 광역시 지정·해제(v1.3.0): 조건을 맞춰 가끔 지정
        from korciv import metro as MT
        inm = [r for r in mine if MT.of(g, r) is not None]
        free = [r for r in mine if MT.can_center(g, pid, r)[0]
                and any(n in mine and MT.can_center(g, pid, n)[0] for n in g.world.land_adj[r])]
        if inm and (not free or rng.random() < 0.25):
            g.dissolve_metro(pid, rng.choice(inm))
        elif free:
            c = rng.choice(free)
            cands = MT.candidates(g, pid, c)
            sel = [c] + [r for r in cands[1:] if c in g.world.land_adj[r]][:rng.randint(1, 4)]
            if rng.random() < 0.3:
                sel = MT.auto_pick(g, pid, c)            # [모두]: 3칸 안 가까운 25곳까지(v1.3.0)
                if rng.random() < 0.3:
                    sel = sel + [r for r in cands if r not in sel][:1]   # 26곳: 거절되어야 한다
            if len(sel) >= 2 and rng.random() < 0.5:
                for r in sel:
                    rr = g.regions[r]
                    rr.b["farm"] = max(rr.b["farm"], 5)
                    rr.happy = max(rr.happy, 1.0)
                    rr.pop = max(rr.pop, 100.0 / len(sel))
                    rr.pop = min(rr.pop, 60.0)
                g.regions[c].b["factory"] = 5
                g.regions[c].b["bank"] = 5
            g.create_metro(pid, c, sel, rng.choice(["", "시험"]))
    if rng.random() < 0.03:                              # 지출 우선순위 자동 정렬 켜기/끄기(v1.3.0)
        g.set_priority_mode(pid, rng.choice(list(g.PRIORITY_SORTS) + [None]))
    # v1.3.0 편의 기능: 여러 부대 한 번에 공격, 중립 지역 [편입]/[최대 편입]·자동 해산, 우선순위 고정, 생산 집결지
    if rng.random() < 0.3:
        tgts = {n for r in mine for n in g.world.land_adj[r] if g.regions[n].owner != pid}
        hot = [t for t in sorted(tgts) if g.attack_candidates(pid, t)]
        if hot:
            t = rng.choice(hot)
            cands = g.attack_candidates(pid, t)
            lead = rng.choice(cands)
            extra = [x.id for x in cands if x.id != lead.id and rng.random() < 0.7] + [rng.choice([999999, lead.id])]
            g.attack_now(lead.id, t, rng.choice(["assault", "surprise"]), extra=extra)
    if rng.random() < 0.2:
        neu = sorted({n for r in mine for n in g.world.land_adj[r] if g.regions[n].owner == NEUTRAL})
        if neu:
            t = rng.choice(neu)
            g.annex_from(pid, t, every=rng.random() < 0.5)
            if rng.random() < 0.5:
                (f.annex_disband.add if rng.random() < 0.7 else f.annex_disband.discard)(t)
    if rng.random() < 0.05:
        rows = g.priority_rows(pid)
        if rows:
            g.toggle_pin(pid, rng.choice(rng.choice(rows)).id)
    if rng.random() < 0.06 and mine:
        tgt = rng.choice(list(g.regions)) if rng.random() < 0.2 else rng.choice(mine + [None])
        g.set_rally(pid, rng.choice(mine + [None, None]), tgt)
    if rng.random() < 0.03:
        k = rng.choice(["reject_buy", "reject_sell"])
        f.ai[k] = not f.ai.get(k)
        if others_ := [o.id for o in g.factions if o.alive and o.id != pid]:
            rf = f.ai.setdefault("reject_from", set())
            o = rng.choice(others_)
            (rf.discard if o in rf else rf.add)(o)
    # 외교
    others = [o.id for o in g.factions if o.alive and o.id != pid]
    if others and rng.random() < 0.3:
        o = rng.choice(others)
        r = rng.random()
        if r < 0.1:
            D.declare_war(g, pid, o)
        elif r < 0.3:
            D.propose_treaty(g, pid, o, rng.choice(["nonaggr", "passage", "alliance", "coalition", "peace"]))
        elif r < 0.4:
            D.declare_friendship(g, pid, o)
        elif r < 0.5:
            D.denounce(g, pid, o)
        elif r < 0.55:
            D.break_nonaggr(g, pid, o)
        elif r < 0.6:
            D.leave_alliance(g, pid, o)
        elif r < 0.62:
            D.leave_coalition(g, pid)
        else:
            offer = D.empty_offer()
            offer["give"]["money"] = rng.choice([0, 100, 10 ** 9])
            offer["take"]["food"] = rng.choice([0, 1, 10 ** 6])
            border = [r_.id for r_ in g.regions_of(o) if any(g.regions[n].owner == pid for n in g.world.land_adj[r_.id])]
            if border and rng.random() < 0.3:
                offer["take"]["regions"] = [rng.choice(border)]
            res, counter, info = D.evaluate_offer(g, o, pid, offer)
            D.respond_offer(g, o, pid, offer)
            # 플레이어가 먼저 여는 자원·특산물 협상(v1.3.0)
            k = rng.choice(NG.RES)
            st = NG.start(g, o, pid, k, rng.randint(1, 6), ai_sells=rng.random() < 0.5)
            for _ in range(rng.randint(1, 6)):
                if st["status"] != "open":
                    break
                NG.player_offer(g, st, max(1, st["n"] + rng.choice([-1, 0, 2])),
                                max(1, int(st["price"] * rng.uniform(0.4, 1.5))))
    return acts


def run_player(seed, turns, n, mode="standard"):
    rng = random.Random(seed * 7 + 1)
    leaders = [l["key"] for l in LEADERS]
    g = Game(Settings(mode=mode, n_enemies=n - 1, seed=seed, max_turns=turns, fog=rng.choice([0, 1, 2]),
                      difficulty=rng.randrange(len(C.DIFFICULTIES)), player_leader=rng.choice(leaders),
                      player_leader_name="퍼저"))
    g.set_player_government(rng.choice(GOVERNMENTS)["key"])
    if not g.setup_done:
        g.finalize_setup()
    try:
        while not g.game_over and g.turn <= turns and g.player.alive:
            player_turn(g, rng)
            check(g, f"player seed={seed} turn={g.turn} (행동 후)")
            g.end_turn()
            check(g, f"player seed={seed} turn={g.turn}")
            if g.turn % 50 == 0:
                g = pickle.loads(pickle.dumps(g))
                print(f'진행: player/{mode} seed={seed} turn={g.turn}', flush=True)
    except Exception:
        report("예외(player)", f"seed={seed} turn={g.turn}\n" + traceback.format_exc())
    return g


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["sim", "player"])
    ap.add_argument("--games", type=int, default=4)
    ap.add_argument("--turns", type=int, default=200)
    ap.add_argument("--seed", type=int, default=100)
    ap.add_argument("--factions", type=int, default=0, help="0이면 판마다 2~10 무작위")
    ap.add_argument("--game-mode", choices=["all"] + list(C.GAME_MODES), default="all")
    a = ap.parse_args()
    for i in range(a.games):
        seed = a.seed + i
        n = a.factions or random.Random(seed).randint(2, 10)
        mode = list(C.GAME_MODES)[i % 3] if a.game_mode == "all" else a.game_mode
        g = (run_sim if a.mode == "sim" else run_player)(seed, a.turns, n, mode)
        alive = sum(f.alive for f in g.factions)
        print(f"{a.mode}/{mode} seed={seed} 세력{n} → 턴 {g.turn - 1}, 생존 {alive}/{len(g.factions)}, "
              f"승리 {g.winner[1] if g.winner else '-'}", flush=True)
    print("== 요약 ==")
    for k, v in PROBLEMS.most_common():
        print(f"{k}: {v}회")
    if not PROBLEMS:
        print("문제 없음")
    return bool(PROBLEMS)


if __name__ == "__main__":
    sys.exit(main())
