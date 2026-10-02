"""leader_balance.py --factions 8 --govs 결과(JSONL)로 정치체제·지도자·병종·공격 유형 요약(마크다운)을 출력한다.

  python tools/gov_report.py gov8.jsonl
"""
import json, sys, os, statistics as st, math
from collections import Counter, defaultdict
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from korciv.leaders import LEADER_BY_KEY, GOV_BY_KEY, LEADER_CATEGORIES
from korciv.config import VICTORY_TYPES, UNITS, UNIT_ORDER

G = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
rows = [r for g in G for r in g["factions"]]
out = []
p = out.append
def pct(x): return f"{x*100:.1f}%"
def mean(xs, d=float("nan")):
    xs = [x for x in xs if x is not None]
    return st.mean(xs) if xs else d
GOVN = {k: v["name"] for k, v in GOV_BY_KEY.items()}
CAT = {k: name for _, name, ks in LEADER_CATEGORIES for k in ks}

n = len(G)
vc = Counter(g["victory"] for g in G)
p(f"## 개요\n")
p(f"- {n}판 × 8세력, 360턴 제한. 평균 종료 턴 {mean([g['turns'] for g in G]):.0f}. 판당 반란 국가 {mean([g['rebel_states'] for g in G]):.2f}, 종료 시 생존 세력 {mean([g['alive_end'] for g in G]):.1f}.")
p("\n| 결과 | 판 | 비율 | 평균 종료 턴 |\n|---|---|---|---|")
for v in list(VICTORY_TYPES) + [None]:
    gs = [g for g in G if g["victory"] == v]
    p(f"| {VICTORY_TYPES.get(v, '승자 없음')} | {len(gs)} | {pct(len(gs)/n)} | {mean([g['turns'] for g in gs]):.0f} |")

# 체제
p("\n## 정치체제\n")
gc = Counter(r["gov"] for r in rows)
p("| 체제 | 선택 비율 | 승률 | 1위율 | GDP 점유 | 평균 순위 | 멸망률 | 판당 선포 | 전쟁 턴 | 평균 전쟁 피로 | 실질 행복도 | 세율 |")
p("|---|---|---|---|---|---|---|---|---|---|---|---|")
for gv, c in gc.most_common():
    rs = [r for r in rows if r["gov"] == gv]
    alive = sum(r["alive_turns"] for r in rs)
    p(f"| {GOVN.get(gv, gv)} | {pct(c/len(rows))} | {pct(mean([r['win'] for r in rs]))} | {pct(mean([r['first'] for r in rs]))} | "
      f"{pct(mean([r['gdp_share'] for r in rs]))} | {mean([r['rank'] for r in rs]):.2f} | {pct(mean([0 if r['alive'] else 1 for r in rs]))} | "
      f"{mean([r['wars_declared'] for r in rs]):.1f} | {pct(sum(r['beh'].get('war_turns',0) for r in rs)/max(1,alive))} | "
      f"{mean([r.get('weary_avg',0) for r in rs]):.1f} | {mean([r.get('eff_happy_avg',0) for r in rs]):+.1f} | {mean([r['tax_avg'] for r in rs])*100:.1f}% |")

# 지도자
p("\n## 지도자별\n")
p("| 분류 | 지도자 | 호전 | 판 | 승률 | 1위율 | GDP 점유 | 평균 순위 | 체제 선택(상위) | 승리 평균 턴 | 멸망률 | 멸망 평균 턴 | 선포/판 | 전쟁 턴 | 최대 영토 | 반란 |")
p("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
by = defaultdict(list)
for r in rows: by[r["leader"]].append(r)
order = sorted(by, key=lambda k: -(mean([r['first'] for r in by[k]]) + mean([r['gdp_share'] for r in by[k]])))
for k in order:
    rs = by[k]; L = LEADER_BY_KEY[k]
    govs = Counter(r["gov"] for r in rs)
    gtxt = " ".join(f"{GOVN[gv][:2]}{c/len(rs)*100:.0f}" for gv, c in govs.most_common(3))
    alive = sum(r["alive_turns"] for r in rs)
    p(f"| {CAT.get(k,'')[:6]} | {L['name']} | {L['aggr']} | {len(rs)} | {pct(mean([r['win'] for r in rs]))} | {pct(mean([r['first'] for r in rs]))} | "
      f"{pct(mean([r['gdp_share'] for r in rs]))} | {mean([r['rank'] for r in rs]):.1f} | {gtxt} | "
      f"{mean([r['victory_turn'] for r in rs if r['win']>0], float('nan')):.0f} | {pct(mean([0 if r['alive'] else 1 for r in rs]))} | "
      f"{mean([r['eliminated'] for r in rs if not r['alive']], float('nan')):.0f} | {mean([r['wars_declared'] for r in rs]):.1f} | "
      f"{pct(sum(r['beh'].get('war_turns',0) for r in rs)/max(1,alive))} | {mean([r['peak'] for r in rs]):.0f} | {mean([r['beh'].get('ev_rebel',0) for r in rs]):.1f} |")

# 분류
p("\n## 지도자 분류별\n")
p("| 분류 | 지도자 수 | 승률 | 1위율 | GDP 점유 | 멸망률 | 판당 선포 |")
p("|---|---|---|---|---|---|---|")
for cid, name, ks in LEADER_CATEGORIES:
    rs = [r for r in rows if r["leader"] in ks]
    p(f"| {name} | {len(ks)} | {pct(mean([r['win'] for r in rs]))} | {pct(mean([r['first'] for r in rs]))} | {pct(mean([r['gdp_share'] for r in rs]))} | "
      f"{pct(mean([0 if r['alive'] else 1 for r in rs]))} | {mean([r['wars_declared'] for r in rs]):.1f} |")

# 병종
p("\n## 병종별 생산 착수 비율\n")
uc = Counter()
for r in rows:
    for kk, v in r["beh"].items():
        if kk.startswith("unit_"): uc[kk[5:]] += v
tot = sum(uc.values()) or 1
p("| 병종 | 착수 수 | 비율 | 판당 |\n|---|---|---|---|")
for u in UNIT_ORDER:
    p(f"| {UNITS[u]['name']} | {uc[u]:,} | {pct(uc[u]/tot)} | {uc[u]/n:.1f} |")
p("\n호전성별 병종 비율(보병/포병/전차):")
for lo, hi in ((1,3),(4,6),(7,9)):
    c = Counter()
    for r in rows:
        if lo <= r["aggr"] <= hi:
            for u in ("inf","art","tank"): c[u] += r["beh"].get(f"unit_{u}",0)
    t = sum(c.values()) or 1
    p(f"- 호전성 {lo}~{hi}: " + " / ".join(f"{UNITS[u]['name']} {c[u]/t*100:.0f}%" for u in ("inf","art","tank")) + f" (세력당 {t/max(1,sum(1 for r in rows if lo<=r['aggr']<=hi)):.0f}개)")

# 공격 유형
p("\n## 공격 유형\n")
b = Counter()
for r in rows: b.update(r["beh"])
orders = b["order_attack_surprise"] + b["order_attack_assault"]
p(f"- 공격 명령: 기습 {pct(b['order_attack_surprise']/max(1,orders))}, 돌격 {pct(b['order_attack_assault']/max(1,orders))} (판당 {orders/n:.0f}회), 폭격 명령 판당 {b['order_bombard']/n:.1f}회, 이동 명령 판당 {b['order_move']/n:.0f}회")
battles = b["surprise_win"] + b["surprise_fail"] + b["assault_battle"]
p(f"- 실제 교전: 판당 {battles/n:.0f}회 — 기습 {pct((b['surprise_win']+b['surprise_fail'])/max(1,battles))}(성공률 {pct(b['surprise_win']/max(1,b['surprise_win']+b['surprise_fail']))}), 돌격 {pct(b['assault_battle']/max(1,battles))}")
p(f"- 돌격 방어선 파괴 판당 {b['line_break']/n:.1f}회, 폭격 판당 {(b['bomb_gun']+b['bomb_air']+b['bomb_gunair'])/n:.1f}회(건물 파괴 {b['bomb_hit']/n:.1f}회)")
p(f"- 적 지역 점령 판당 {b['resist_start']/n:.0f}회, 그중 저항 중 탈환 {b['retake']/n:.0f}회")
p(f"- 조약 체결 판당: 불가침 {b['treaty_nonaggr']/n/2:.1f}, 동맹 {b['treaty_alliance']/n/2:.1f}, 연합 {b['treaty_coalition']/n/2:.1f} · 강화 {b['peace']/n/2:.1f}")
p(f"- 착공 판당: 편입 {b['start_annex']/n:.0f}, 건설 {b['start_build']/n:.0f}, 유닛 {b['start_unit']/n:.0f}, 랜드마크 {b['start_landmark']/n:.1f}")

# 승리자 특성
p("\n## 승리·1위 세력의 특징\n")
win = [r for r in rows if r["win"] > 0]
first = [r for r in rows if r["first"] >= 1]
for name, rs in (("승리", win), ("GDP 1위", first), ("전체", rows)):
    if not rs: continue
    p(f"- {name}({len(rs)}): 호전성 {mean([r['aggr'] for r in rs]):.1f}, 선포 {mean([r['wars_declared'] for r in rs]):.1f}, "
      f"최대 영토 {mean([r['peak'] for r in rs]):.0f}, 시작 지역 산출 {mean([r['start']['output'] for r in rs]):,.0f}, "
      f"전쟁 피로 {mean([r.get('weary_avg',0) for r in rs]):.1f}, 체제 " + ", ".join(f"{GOVN[gv]} {c/len(rs)*100:.0f}%" for gv, c in Counter(r['gov'] for r in rs).most_common(3)))
print("\n".join(out))
