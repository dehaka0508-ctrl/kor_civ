"""leader_balance.py 결과(JSONL)로 지도자 밸런스 보고서(마크다운 표)를 만든다.

  python tools/leader_report.py main.jsonl [flat.jsonl]
"""
from __future__ import annotations

import json
import math
import os
import statistics as st
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from korciv.config import VICTORY_TYPES  # noqa: E402
from korciv.leaders import LEADER_BY_KEY  # noqa: E402

VT = ["economic", "conquest", "peace", "landmark"]
FX_NAMES = {
    "happy_turn": "행복도 +/턴", "cost_air": "공군 생산비", "bomb_art": "포병 폭격", "cost_naval": "해군 생산비",
    "atk_assault": "돌격 공격", "war_period": "전쟁 지속 페널티", "line_k": "방어선 효과", "start_opinion": "시작 우호도",
    "upkeep_land": "육군 유지비", "trade_m": "거래 배수", "cost_line": "방어선 건설비", "landmark_turns": "랜드마크 기간",
    "rebel_prob": "반란 확률", "treaty_threshold": "조약 문턱", "no_ally_assault": "무동맹 돌격", "cost_tank": "전차 생산비",
    "occ_time": "점령·편입 턴", "inf_cost_early": "초반 보병비", "occupied_happy_extra": "점령지 행복도",
    "surprise": "기습 성공률", "wanggeon_occupy": "점령지 행복 보정", "tax_max": "세율 상한", "war_start_happy": "개전 행복도",
    "suppress": "진압 성공률", "atk_inf": "보병 공격", "amphib_extra": "상륙 돌격", "build_time_prod": "생산 건물 기간",
    "cost_mil": "군 생산비", "neutral_diplomacy": "중립 외교", "happy_cap": "행복도 상한", "output_bank": "은행 산출",
    "tax_lock": "세율 잠금", "instant_annex_h": "즉시 병합", "defense_small": "소국 방어", "ally_war_atk": "동맹 공동전 공격",
    "avg_rebel": "평균 불행 반란", "build_time_factory": "공장 건설 기간", "market_buy": "시장 구매가",
    "market_sell": "시장 판매가", "output_factory": "공장 산출", "tax_over15": "15% 초과 세율", "ai_opinion_turn": "AI 우호도/턴",
    "start_money": "시작 자금",
}


def load(path):
    return [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]


def per_leader(games):
    by = defaultdict(list)
    for g in games:
        for r in g["factions"]:
            by[r["leader"]].append(r)
    return by


def pct(x):
    return f"{x * 100:.1f}%"


def main(main_path, flat_path=None):
    A = load(main_path)
    B = load(flat_path) if flat_path else []
    la, lb = per_leader(A), per_leader(B) if B else {}
    out = []
    p = out.append
    # 1. 승리 유형 빈도
    p("### 승리 유형 빈도\n")
    p("| 실험 | 판 | " + " | ".join(VICTORY_TYPES[v] for v in VT) + " | 승자 없음(360턴) | 평균 종료 턴 |")
    p("|---|---|" + "---|" * (len(VT) + 2))
    for name, games in (("본 실험", A), ("통제 실험", B)):
        if not games:
            continue
        c = Counter(g["victory"] for g in games)
        n = len(games)
        p(f"| {name} | {n} | " + " | ".join(f"{c[v]} ({c[v] / n * 100:.0f}%)" for v in VT)
          + f" | {c[None]} ({c[None] / n * 100:.0f}%) | {st.mean(g['turns'] for g in games):.0f} |")
    # AI 목표 vs 실제 승리
    goal_c, goal_win = Counter(), Counter()
    for g in A:
        for r in g["factions"]:
            for k, v in r.get("goals", {}).items():
                goal_c[k] += v
            if r.get("victory_type"):
                gl = max(r.get("goals", {"?": 1}), key=lambda k: r["goals"][k]) if r.get("goals") else "?"
                goal_win[(gl, r["victory_type"])] += 1
    tot = sum(goal_c.values()) or 1
    p("\nAI가 고른 승리 목표(연 1회 표본, 본 실험): " + ", ".join(
        f"{VICTORY_TYPES.get(k, k)} {v / tot * 100:.0f}%" for k, v in goal_c.most_common()))
    p("목표별 실제 승리: " + ", ".join(f"{VICTORY_TYPES.get(a, a)}→{VICTORY_TYPES[b]} {n}"
                                   for (a, b), n in goal_win.most_common()) + "\n")
    # 2. 지도자별 승률
    p("### 지도자별 승률\n")
    p("| 지도자 | 호전성 | 판 | 승률 | 1위율 | 승리 유형(경제/정복/평화/랜드마크) | GDP 점유 | 통제 승률 | 통제 GDP 점유 | 종합 점유 |")
    p("|---|---|---|---|---|---|---|---|---|---|")
    rows = []
    for k, rs in la.items():
        n = len(rs)
        win = sum(r["win"] for r in rs) / n
        first = sum(r["first"] for r in rs) / n
        share = st.mean(r["gdp_share"] for r in rs)
        vt = Counter(r["victory_type"] for r in rs if r.get("victory_type"))
        fb = lb.get(k, [])
        fwin = sum(r["win"] for r in fb) / len(fb) if fb else float("nan")
        fshare = st.mean(r["gdp_share"] for r in fb) if fb else float("nan")
        comb = (share + fshare) / 2 if fb else share
        rows.append((comb, k, n, win, first, vt, share, fwin, fshare))
    rows.sort(reverse=True)
    for comb, k, n, win, first, vt, share, fwin, fshare in rows:
        L = LEADER_BY_KEY[k]
        p(f"| {L['name']} | {L['aggr']} | {n} | {pct(win)} | {pct(first)} | "
          + "/".join(str(vt[v]) for v in VT) + f" | {pct(share)} | {pct(fwin)} | {pct(fshare)} | **{pct(comb)}** |")
    p("\n승률 = 실제 승리(공동 승리는 나눔). 1위율 = 승리 또는 승자 없이 끝난 판의 GDP 1위. 기대값 16.7%.\n")
    # 3. 행동 패턴
    p("### 행동 패턴 (본 실험, 판당 평균)\n")
    p("| 지도자 | 주 목표 | 평균 세율 | 선포 | 강화 | 전쟁 턴 비율 | 편입 착공 | 경제 건물 | 방어 건물 | 보병/포병/전차 | 기습 비율 | 반란 | 평균 전쟁 피로 |")
    p("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for comb, k, *_ in rows:
        rs = la[k]
        n = len(rs)

        def avg(key):
            return sum(r["beh"].get(key, 0) for r in rs) / n
        goals = Counter()
        for r in rs:
            goals.update(r.get("goals", {}))
        gtot = sum(goals.values()) or 1
        main_goal = ", ".join(f"{VICTORY_TYPES[g][:2]} {c / gtot * 100:.0f}%" for g, c in goals.most_common(2))
        econ = sum(avg(f"build_{b}") for b in ("farm", "fishery", "factory", "bank", "power", "liquefy", "specialty", "extract"))
        dfn = sum(avg(f"build_{b}") for b in ("line", "shelter", "aa"))
        alive = sum(r["alive_turns"] for r in rs)
        war_share = sum(r["beh"].get("war_turns", 0) for r in rs) / max(1, alive)
        sur, asl = avg("order_attack_surprise"), avg("order_attack_assault")
        p(f"| {LEADER_BY_KEY[k]['name']} | {main_goal} | {st.mean(r['tax_avg'] for r in rs) * 100:.1f}% | "
          f"{st.mean(r['wars_declared'] for r in rs):.1f} | {avg('peace'):.1f} | {war_share * 100:.0f}% | "
          f"{avg('start_annex'):.0f} | {econ:.0f} | {dfn:.1f} | {avg('unit_inf'):.0f}/{avg('unit_art'):.0f}/{avg('unit_tank'):.0f} | "
          f"{sur / max(1e-9, sur + asl) * 100:.0f}% | {avg('ev_rebel'):.1f} | {st.mean(r['weary_avg'] for r in rs):.1f} |")
    # 4. 효과 발동
    p("\n### 버프·디버프 발동 빈도 (본 실험)\n")
    p("발동률 = 살아 있던 턴 중 그 효과가 실제로 적용된 턴의 비율. 횟수 = 판당 적용 횟수.\n")
    p("| 지도자 | 종합 점유 | 버프 | 발동률 / 횟수 | 디버프 | 발동률 / 횟수 |")
    p("|---|---|---|---|---|---|")
    for comb, k, *_ in rows:
        L = LEADER_BY_KEY[k]
        rs = la[k]
        n = len(rs)
        keys = list(L["fx"].keys())
        # 리더 정의 순서: 버프 효과 키가 먼저, 디버프가 나중(leaders.py 관례). 버프/디버프 설명으로 나눈다.
        cells = []
        for key in keys:
            turns = sum(r["fx"].get(key, {}).get("turns", 0) for r in rs)
            cnt = sum(r["fx"].get(key, {}).get("count", 0) for r in rs) / n
            alive = sum(r["alive_turns"] for r in rs)
            rate = turns / max(1, alive)
            cells.append((key, rate, cnt))
        buff_keys, debuff_keys = split_fx(L)
        def fmt(ks):
            parts = [c for c in cells if c[0] in ks]
            return ("<br>".join(f"{FX_NAMES.get(c[0], c[0])}" for c in parts),
                    "<br>".join(("**미발동**" if c[1] < 0.005 and c[2] < 0.05 else f"{c[1] * 100:.0f}% / {c[2]:.1f}")
                                for c in parts))
        bn, bv = fmt(buff_keys)
        dn, dv = fmt(debuff_keys)
        p(f"| {L['name']} | {pct(comb)} | {L['buff'][0]}: {bn} | {bv} | {L['debuff'][0]}: {dn} | {dv} |")
    print("\n".join(out))


def split_fx(L):
    """leaders.py 의 fx 에서 버프/디버프 키를 나눈다(설명 문자열에 나오는 낱말로 판정, 실패 시 순서)."""
    keys = list(L["fx"].keys())
    debuff_hint = {"cost_air": "공군", "cost_naval": "해군", "war_period": "전쟁", "start_opinion": "우호도",
                   "upkeep_land": "유지비", "cost_line": "방어선", "rebel_prob": "반란", "no_ally_assault": "동맹",
                   "occ_time": "점령", "occupied_happy_extra": "점령지", "tax_max": "세율", "suppress": "진압",
                   "amphib_extra": "상륙", "cost_mil": "군 생산비", "happy_cap": "상한", "tax_lock": "세율",
                   "cost_tank": "전차", "avg_rebel": "반란", "market_buy": "시장", "market_sell": "시장",
                   "tax_over15": "세율", "start_money": "자금"}
    deb = [k for k in keys if k in debuff_hint and debuff_hint[k] in L["debuff"][1]]
    buf = [k for k in keys if k not in deb]
    return buf, deb


if __name__ == "__main__":
    main(*sys.argv[1:3])
