"""지도자(8절)와 정치체제(9절).

효과는 키-값으로 적고, 엔진은 mult/add/value 로 합산해 쓴다.
- mult 키: 값 v 를 (1 + v) 배수로 곱한다. 지도자와 체제 효과는 곱으로 합산(9절).
- add 키: 더한다.
- value 키: 지도자·체제 중 하나가 정한 값(없으면 기본값).
"""
from __future__ import annotations

from .leader_rework import LEADERS

# 지도자 분류 (선택 화면 탭)
LEADER_CATEGORIES = [
    ("founders", "나라의 문을 연 자들",
     ["dan", "jum", "onz", "egg", "sur", "dae", "wan", "gun", "dog",
      "tae", "lee", "kim"]),
    ("footprints", "역사의 커다란 발자취",
     ["ggt", "gcg", "jin", "mur", "sen", "muy", "gon", "sej", "hae",
      "jjo", "pak", "kdj", "sun"]),
    ("uncrowned", "왕관 없는 지도자들",
     ["yon", "jan", "jun", "cho", "yis", "hon", "gil", "ahn", "kgu", "kgc", "kwb"]),
    ("invaders", "한반도를 넘본 외적들",
     ["yan", "tai", "kan", "toy", "taj", "ito", "yyl", "mac", "sta", "mao"]),
]
_CAT_OF = {k: cid for cid, _, keys in LEADER_CATEGORIES for k in keys}
# 게임 안 순서(AI 지도자 무작위 배정 등): 시드가 같으면 예전과 같은 지도자가 나오도록 고정해 둔다
_ORDER = [k for _, _, keys in LEADER_CATEGORIES for k in keys] + ["cus"]
LEADERS.sort(key=lambda l: _ORDER.index(l["key"]))

# 시대(즉위·활동을 시작한 해, 기원전은 음수): 선택 화면은 분류마다 시대순으로 보여 준다(v1.3.0)
LEADER_ERA = {
    "dan": -2333, "egg": -57, "jum": -37, "onz": -18, "sur": 42, "dae": 698, "dog": 892, "gun": 901,
    "wan": 918, "tae": 1392, "lee": 1948.6, "kim": 1948.7,
    "gcg": 346, "ggt": 391, "mur": 501, "jin": 540, "sen": 632, "muy": 654, "sun": 818, "gon": 1351,
    "sej": 1418, "hae": 1608, "jjo": 1776, "pak": 1961, "kdj": 1998,
    "yon": 642, "jan": 828, "kgc": 1018, "jun": 1170, "cho": 1358, "gil": 1500, "yis": 1592, "hon": 1811,
    "ahn": 1907, "kgu": 1919.3, "kwb": 1919.9,
    "yan": 612, "tai": 645, "yyl": 993, "kan": 1260, "toy": 1592, "taj": 1636, "ito": 1905, "sta": 1945,
    "mac": 1950.7, "mao": 1950.8,
}
LEADER_CATEGORIES = [(cid, title, sorted(keys, key=lambda k: LEADER_ERA.get(k, 9999)))
                     for cid, title, keys in LEADER_CATEGORIES]

for _l in LEADERS:
    _l["cat"] = _CAT_OF.get(_l["key"], "cus")
LEADER_BY_KEY = {l["key"]: l for l in LEADERS}

_LEGACY_GOVERNMENTS = [
    dict(key="absolute", buff_keys=("tax_base",), name="전제군주제", target=7.5,
         buff=("왕권 통치", "기준 세율 +2%"),
         debuff=("", "수도에서 3칸 밖 지역 산출 −5%"),
         fx={"tax_base": 2, "far_output_gov": 0.05}),
    dict(key="constitutional", buff_keys=("happy_turn",), name="입헌군주제", target=3.5,
         buff=("", "전 지역 행복도 +0.1/턴"), debuff=("", "개전 전쟁 피로 ×1.5"),
         fx={"happy_turn": 0.1, "war_start_weary": 0.5}),
    dict(key="presidential", buff_keys=("build_time_all",), name="대통령제", target=5.5,
         buff=("", "모든 건물 건설 시간 −10%"), debuff=("", "전쟁 중 전쟁 피로 증가 +20%"),
         fx={"build_time_all": -0.10, "war_weary_rate": 0.20}),
    dict(key="parliamentary", buff_keys=("output_bank",), name="의원내각제", target=1.5,
         buff=("", "시장 산출 +10%"), debuff=("", "선전포고 후 2턴 동안 공격 불가(의회 동의)"),
         fx={"output_bank": 0.10, "parliament_delay": 2}),
    dict(key="socialist", buff_keys=("cost_factory",), name="사회주의", target=6.0,
         buff=("", "공장 건설비 −15%"), debuff=("", "시장 산출 −20%"),
         fx={"cost_factory": -0.15, "output_bank": -0.20}),
    dict(key="fascist", buff_keys=("cost_mil",), name="파시즘", target=9.5,
         buff=("", "군 생산비 −15%"), debuff=("", "모든 AI 시작 우호도 −5"),
         fx={"cost_mil": -0.15, "start_opinion": -5}),
]
POLICY_COSTS = (100, 250, 500, 900, 1500)


def _policy(name, description, **fx):
    return dict(name=name, description=description, fx=fx)


POLICIES = {
    "absolute": [
        _policy("왕실 직할령", "수도 금전 산출 +15%, 수도 행정력 +10", capital_money=.15, capital_admin=10),
        _policy("중앙집권 관료제", "행정 건물 건설비 -20%, 소요 -1턴", cost_admin=-.2, build_admin_turns=-1),
        _policy("흠정 헌법", "행복도 감소 없는 기준 세율 +2%p", tax_base=2),
        _policy("근위대 창설", "수도 및 수도 인접 지역 방어력 +20%", capital_guard_def=.2),
        _policy("어전 회의", "중립 편입 비용 -20%, 재상·장군 구매비 -15%",
                cost_annex=-.2, gp_chancellor_cost=-.15, gp_general_cost=-.15),
    ],
    "constitutional": [
        _policy("대헌장", "전 지역 행복도 +0.15/턴, 무법 유예 +2턴", happy_turn=.15, lawless_grace=2),
        _policy("왕립 학술원", "연구 건물 과학력 +10%, 과학자·예술가 구매비 -15%",
                science_edu=.1, gp_scientist_cost=-.15, gp_artist_cost=-.15),
        _policy("권리장전", "세율 행복도 감소 -25%, 점령 저항 -1턴", tax_penalty=-.25, resist_turns=-1),
        _policy("내각 책임제", "행정 건물 산출 +15%, 특산물 행복도 +50%",
                admin_building_output=.15, specialty_happy=.5),
        _policy("국왕의 상징적 통합", "전쟁 피로 회복 +0.5/턴, 양수 우호도 자연 감소율 절반",
                war_weary_recovery_add=.5, positive_op_decay=-.5),
    ],
    "presidential": [
        _policy("제헌 국회", "지역당 기본 행정력 +2, 행정 건물 건설 -1턴", admin_each=2, build_admin_turns=-1),
        _policy("삼권분립", "시장·공장 산출 +10%, 자금 적자 행복도 페널티 절반",
                output_bank=.1, output_factory=.1, debt_happy=-.5),
        _policy("국책 사업 추진단", "생산 건물 건설 시간 -15%, 침수 복구 즉시 완료",
                build_time_prod=-.15, flood_instant=True),
        _policy("산학협력 연구단지", "연구 3단계 이상 지역 시장·공장 산출 +15%", educated_output=.15),
        _policy("대통령 긴급재정명령", "경제·과학 승리 단계 턴당 비용 -15%", victory_turn_cost=-.15),
    ],
    "parliamentary": [
        _policy("의회 주권 확립", "시장 산출 +10%, 국가 행정력 +10%", output_bank=.1, admin_output=.1),
        _policy("자유무역협정(FTA)", "시장 판매가 +20%, 외교 자원 거래 우호도 ×1.5",
                market_sell=.2, trade_opinion=.5),
        _policy("연립 내각 구성", "우호 선언·불가침·동맹 우호도 문턱 -10, 선물 효율 +20%",
                treaty_threshold=-10, friend_threshold=-10, gift_opinion=.2),
        _policy("중앙은행 독립", "시장 3단계 이상 지역 금전 산출 +300/턴", bank3_income=300),
        _policy("복지 국가 기틀", "인구 성장률 +10%, 행복도 +0.15/턴",
                growth=.1, happy_turn=.15),
    ],
    "socialist": [
        _policy("토지 개혁 및 집단화", "농장 식량·산출 +10%, 식량 배급 성장 보너스 ×1.3",
                output_farm=.1, ration_growth=.3),
        _policy("경제개발 5개년 계획", "공장·발전소·탄광·정유공장 건설비 -20%",
                cost_factory=-.2, cost_power=-.2, cost_extract=-.2),
        _policy("무상 교육·무상 의료", "초·중등교육기관 건설비 -30%, 행정 건물 건설비 -20%", cost_edu_low=-.3, cost_admin=-.2),
        _policy("중공업 우선 정책", "공장 산출 +15%, 3단계 이상 탄광·정유 생산 +1",
                output_factory=.15, extract3_extra=1),
        _policy("인민 과학원", "국가 과학력 +15%, 과학승리 유닛 생산 -3턴",
                science_output=.15, science_unit_turns=-3),
    ],
    "fascist": [
        _policy("선전", "전쟁 피로 증가 -30%, 개전 피로 -50%", war_weary_rate=-.3, war_start_weary=-.5),
        _policy("국가 총동원령", "군사 유닛 생산비 -15%, 생산 착수 행복도 감소 면제",
                cost_mil=-.15, unit_happy_free=True),
        _policy("군수산업 복합체", "사관학교·방어선·방공호·대공포 건설비 -25%, 군 유지비 -15%",
                cost_academy=-.25, cost_line=-.25, cost_shelter=-.25, cost_aa=-.25, upkeep_mil=-.15),
        _policy("비밀경찰 및 계엄령", "점령 저항 -2턴, 반란 임계 행복도 -70", resist_turns=-2, rebel_threshold=-70),
        _policy("기갑·기동전 교리", "육군·공군 공격력 +10%, 적 지역 무력 점령 시간 -25%",
                atk_land=.1, atk_air=.1, enemy_occ_time=-.25),
    ],
}
POLICY_COMPLETION = {
    "absolute": _policy("절대왕정 확립", "전 지역 금전 산출 +10%, 수도 인구 산출 +30%",
                        output_money=.1, capital_pop_output=.3),
    "constitutional": _policy("군림하되 통치하지 않는다", "실질 행복도 +10, 광역시 방어력 페널티 면제",
                              effective_happy=10, metro_def_exempt=True),
    "presidential": _policy("선진 민주 공화국", "인구 성장 +20%, 모든 건물 건설비 -15%, 국가 과학력 +15%",
                            growth=.2, cost_build=-.15, science_output=.15),
    "parliamentary": _policy("책임 의회정치 완성", "시장 산출 +25%, 경제승리 -3턴, 연합 동맹 유지 조건 12턴",
                             output_bank=.25, econ_turns=-3, coalition_alliance_turns=12),
    "socialist": _policy("계획경제 완성", "공장·발전소·채굴 산출 +20%, 징집 피로 무페널티 기준 8턴",
                         output_factory=.2, output_power=.2, output_extract=.2, conscript_free_turns=8),
    "fascist": _policy("전체주의 총력전 국가", "전 병종 공격·방어·폭격 +15%, 적 지역 점령 완료 시 보병 1기",
                       combat_all=.15, capture_infantry=1),
}
for _tree in POLICIES.values():
    for _stage, _cost in zip(_tree, POLICY_COSTS):
        _stage["cost"] = _cost

# 체제 선택 자체에는 고정 효과가 없다. 정책을 해금하면서 단계별 효과가 누적된다.
GOVERNMENTS = [
    {**g, "fx": {}, "buff_keys": (),
     "buff": ("정책 트리", "행정력으로 5단계 정책을 순차 해금"),
     "debuff": ("", "없음")} if g["key"] in POLICIES else g
    for g in _LEGACY_GOVERNMENTS
]
GOV_BY_KEY = {g["key"]: g for g in GOVERNMENTS}

GOV_OFFICES = {
    "absolute": "국왕 집무실", "constitutional": "수상 집무실",
    "presidential": "대통령 집무실", "parliamentary": "총리 집무실",
    "socialist": "서기장 집무실", "fascist": "총통 집무실",
}
GOV_DESCRIPTIONS = {
    "absolute": "수도와 왕권을 강화하고 편입·군사 지휘에 집중합니다.",
    "constitutional": "행복도와 학술·행정을 함께 키우는 군주정입니다.",
    "presidential": "건설과 인구 성장, 과학 발전에 집중합니다.",
    "parliamentary": "시장·교역과 외교 협력으로 경제를 키웁니다.",
    "socialist": "공장·자원·전력과 대규모 생산 기반을 강화합니다.",
    "fascist": "군사 생산과 전투, 점령을 통한 확장에 집중합니다.",
}

MULT_KEYS = {
    "cost_air", "cost_naval", "cost_tank", "cost_mil", "cost_line", "cost_factory",
    "upkeep_land", "bomb_art", "atk_assault", "atk_inf", "build_time_prod", "build_time_all",
    "build_time_factory", "output_bank", "output_factory", "rebel_prob", "market_buy",
    "market_sell", "start_money", "occ_time", "inf_cost_early", "no_ally_assault",
    "ally_war_atk", "defense_small", "war_weary_rate", "war_start_weary", "def_coast", "naval_power", "naval_bomb",
    "start_pop", "cost_science", "output_prod", "war_weary_recovery", "multi_attack", "atk_vs_line", "resist_time", "build_time_industry",
    "river_def_dmg", "amphib_atk", "outnumbered_dmg", "output_farm", "inf_wave", "food_prod",
    "cost_noninf", "early_output",
}
ADD_KEYS = {"tax_base", "happy_turn", "surprise", "trade_m", "treaty_threshold", "start_opinion",
            "ai_opinion_turn", "suppress", "occupied_happy_extra", "power_elec_add"}


def effects(leader_key: str, gov_key: str | None, policy_level: int = 0):
    out = []
    l = LEADER_BY_KEY.get(leader_key)
    if l:
        out.append(l["fx"])
    g = GOV_BY_KEY.get(gov_key) if gov_key else None
    if g:
        k = gov_buff_scale(leader_key)
        stages = POLICIES.get(gov_key, ())[:max(0, min(5, int(policy_level)))]
        if policy_level >= 5 and gov_key in POLICY_COMPLETION:
            stages = [*stages, POLICY_COMPLETION[gov_key]]
        for stage in stages:
            # 값으로 지정한 기준은 기본값과의 차이를 절반만 적용한다.
            bases = {"rebel_threshold": -50, "conscript_free_turns": 6, "coalition_alliance_turns": 24}
            fx = {key: (v if isinstance(v, bool) else
                        bases[key] + (v - bases[key]) * k if key in bases else v * k)
                  for key, v in stage["fx"].items()}
            out.append(fx)
    return out


def gov_buff_scale(leader_key: str) -> float:
    """정치체제 버프에 곱하는 배수(광해군 '폐모살제' 0.7, 그 밖 1)."""
    return float(LEADER_BY_KEY.get(leader_key, {}).get("fx", {}).get("gov_buff_scale", 1.0))


class Mods:
    """한 세력의 지도자·체제 효과 합산기."""

    def __init__(self, leader_key: str, gov_key: str | None, policy_level: int = 0):
        self.fx = effects(leader_key, gov_key, policy_level)

    def mult(self, key: str) -> float:
        m = 1.0
        for fx in self.fx:
            if key in fx:
                m *= 1.0 + fx[key]
        return m

    def add(self, key: str) -> float:
        return sum(fx.get(key, 0) for fx in self.fx)

    def value(self, key: str, default=None):
        for fx in self.fx:
            if key in fx:
                return fx[key]
        return default

    def has(self, key: str) -> bool:
        return any(key in fx for fx in self.fx)


AI_PHILOSOPHER_P = 0.0       # AI는 실제 정책 트리가 있는 여섯 체제 중 선택한다.


def banned_govs(leader_key: str) -> set:
    """지도자가 고를 수 없는 정치체제(홍길동 '적서차별': 군주제 계열)."""
    fx = LEADER_BY_KEY.get(leader_key, {}).get("fx", {})
    if fx.get("no_monarchy"):
        return {k for k, fam in GOV_FAMILIES.items() if "군주정" in fam}
    return set()


def _government_policy_value(m, aggression, resources):
    """정책 적용 전후의 효용. 실제 배수·부호와 사용할 수 없는 혜택을 구별한다."""
    war = .25 + .75 * aggression / 10
    happy_need = 1 + min(1, max(0, m.value('capital_unhappy_rebel', 1) - 1) * .4
                        + m.value('minority_rule', 0) + abs(m.value('focus_release_happy', 0)) * .1)
    food_need = 1 + max(0, 1 - m.mult('food_prod')) * 2
    factory = m.mult('output_factory') * (1 + 3 * m.add('factory_fuel_output'))
    bank = m.mult('output_bank') * (1 + m.value('city_bank_output', 0))
    food = m.mult('output_farm') * m.mult('food_prod')
    build = m.mult('cost_build') * (.5 * m.mult('cost_factory') + .5 * m.mult('cost_admin')
             + .3 * m.mult('cost_extract') + .3 * m.mult('cost_edu_low'))
    time = m.mult('build_time_all') * m.mult('build_time_prod') * m.mult('build_time_industry')
    attack = m.mult('atk_land') * m.mult('combat_all') * m.mult('atk_assault') * m.mult('inf_wave')
    value = 3 * bank + 3 * factory + 2 * food * food_need
    value += 2 * m.mult('science_output') * m.mult('science_edu') + 2 * m.mult('admin_output') * m.mult('admin_building_output')
    value += .06 * m.add('admin_each') + .015 * m.add('capital_admin') - 1.2 * build - .8 * time
    value += happy_need * (2 * m.add('happy_turn') + .025 * m.add('effective_happy')
                          + .08 * m.add('lawless_grace') + .02 * (-50 - m.value('rebel_threshold', -50)))
    value += war * (2 * attack - .8 * m.mult('cost_mil') - .4 * m.mult('upkeep_mil') * m.mult('upkeep_land')
                    - .5 * m.mult('war_weary_rate') * (1 + m.value('no_allies_weary', 0))
                    - .3 * m.mult('war_start_weary') - .06 * m.add('resist_turns'))
    diplomacy_need = 1 + abs(m.value('no_allies_atk', 0)) * 2
    value += diplomacy_need * (.3 * m.mult('gift_opinion') - .02 * m.add('treaty_threshold'))
    if not m.value('no_resource_trade'):
        value += .3 * m.mult('trade_opinion')
    if not m.value('no_coalition'):
        value += .01 * (24 - m.value('coalition_alliance_turns', 24))
    if not m.value('no_academy'):
        value -= .2 * war * m.mult('cost_academy')
    if not m.value('no_chancellor'):
        value -= .2 * m.mult('gp_chancellor_cost')
    value -= .2 * m.mult('gp_scientist_cost') + .1 * m.mult('gp_artist_cost')
    value += .15 * resources * m.add('extract3_extra') - .06 * m.add('science_unit_turns')
    return value


def ai_government_scores(aggression, factory_level, bank_level, *, leader_key='cus', resources=0,
                         coastal=False, neighbors=0):
    """환경 기본 편차를 20% 줄이고 호전성·지도자 선호·실제 정책 시너지를 합산한다."""
    aggression = max(0, min(10, aggression))
    factory_level, bank_level = max(0, min(6, factory_level)), max(0, min(6, bank_level))
    resources, neighbors = max(0, min(2, resources)), max(0, min(8, neighbors))
    environment = dict(absolute=.10 * neighbors, constitutional=.22 * neighbors,
                       presidential=.15 * (factory_level + bank_level),
                       parliamentary=.35 * bank_level + .45 * bool(coastal),
                       socialist=.35 * factory_level + .45 * resources,
                       fascist=.12 * neighbors + .25 * resources)
    scores = {key: 1 + .8 * value for key, value in environment.items()}
    from .ai_personality import PROFILES
    pref = PROFILES.get(leader_key, {})
    synergy = {
        'absolute': {'admin': 1.5, 'protect_capital': 1, 'growth': .5},
        'constitutional': {'edu': 1.5, 'scientist': 1.5, 'science': 1, 'line': .5},
        'presidential': {'bank': 1, 'factory': 1, 'growth': 1, 'admin': .5},
        'parliamentary': {'bank': 1.5, 'ally': 1, 'trade': 1},
        'socialist': {'factory': 1.5, 'power': 1, 'extract': 1, 'farm': 1},
        'fascist': {'inf': 1, 'tank': 1, 'art': 1, 'general': 1, 'war': 1},
    }
    leader_base = _government_policy_value(Mods(leader_key, None), aggression, resources)
    neutral_base = _government_policy_value(Mods('cus', None), aggression, resources)
    for gov, weights in synergy.items():
        scores[gov] += .8 * sum(pref.get(action, 0) * weight for action, weight in weights.items())
        scores[gov] += .4 * (1 - abs(aggression - GOV_BY_KEY[gov]['target']) / 10)
        interaction = 0.0
        for level, weight in ((1, .4), (3, .35), (5, .25)):
            gain = _government_policy_value(Mods(leader_key, gov, level), aggression, resources) - leader_base
            ordinary = _government_policy_value(Mods('cus', gov, level), aggression, resources) - neutral_base
            interaction += weight * (gain - ordinary)
        scores[gov] += max(-.6, min(.6, interaction))
    return scores


def ai_pick_government(rng, aggression: float, factory_level: int, bank_level: int, banned=(),
                       *, leader_key="cus", resources=0, coastal=False, neighbors=0) -> str:
    scores = ai_government_scores(aggression, factory_level, bank_level, leader_key=leader_key,
                                 resources=resources, coastal=coastal, neighbors=neighbors)
    scores = {key: value + rng.uniform(-.04, .04) for key, value in scores.items()}
    blocked = set(banned) | banned_govs(leader_key)
    allowed = [key for key in scores if key not in blocked]
    return max(allowed, key=scores.get) if allowed else "presidential"


# 정치체제 계열 (반란 세력끼리 우호/적대 판정). 계열이 겹치면 '유사'.
GOV_FAMILIES = {
    "absolute": {"군주정", "권위주의"},
    "constitutional": {"군주정", "민주정"},
    "presidential": {"민주정"},
    "parliamentary": {"민주정"},
    "socialist": {"권위주의"},
    "fascist": {"권위주의"},
}


def gov_similar(a: str | None, b: str | None) -> bool:
    if a is None or b is None:
        return False
    return a == b or bool(GOV_FAMILIES.get(a, set()) & GOV_FAMILIES.get(b, set()))


# ------------------------------------------------------------------ 체제 간 기본 관계 (AI 외교)
# 우호도는 매 턴 이 기본값 쪽으로 서서히 수렴한다. 외교(선물·거래·조약·공동의 적)로 충분히 뒤집을 수 있는 크기.
GOV_BLOC = {"absolute": "monarchy", "constitutional": "monarchy",
            "presidential": "democracy", "parliamentary": "democracy", "socialist": "socialist"}
# 군주제 계열 → 사회주의 → 민주주의 계열 → 군주제 계열: 앞쪽이 뒤쪽을 약간 적대한다(한쪽 방향)
GOV_RIVAL = {"monarchy": "socialist", "socialist": "democracy", "democracy": "monarchy"}
GOV_AFFINITY = 10      # 군주정끼리·민주정끼리(입헌군주제는 양쪽 모두)
GOV_RIVALRY = -10
# 체제별 호전성 보정: 의회 동의가 필요한 체제는 전쟁을 덜, 권위주의 체제는 더 쉽게 결정한다
GOV_AGGR_ADJ = {"fascist": 1.0, "absolute": 0.5, "socialist": 0.5, "presidential": 0.0,
                "constitutional": -0.5, "parliamentary": -1.0}


def gov_opinion_bias(viewer_gov: str | None, target_gov: str | None) -> float:
    """viewer 체제가 target 체제를 볼 때의 기본 우호도(시작값이자 수렴값)."""
    if not viewer_gov or not target_gov:
        return 0.0
    v = 0.0
    fa, fb = GOV_FAMILIES.get(viewer_gov, set()), GOV_FAMILIES.get(target_gov, set())
    if fa & fb & {"군주정", "민주정"}:
        v += GOV_AFFINITY
    ba, bb = GOV_BLOC.get(viewer_gov), GOV_BLOC.get(target_gov)
    if ba and bb and GOV_RIVAL.get(ba) == bb:
        v += GOV_RIVALRY
    return v
