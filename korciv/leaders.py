"""지도자(8절)와 정치체제(9절).

효과는 키-값으로 적고, 엔진은 mult/add/value 로 합산해 쓴다.
- mult 키: 값 v 를 (1 + v) 배수로 곱한다. 지도자와 체제 효과는 곱으로 합산(9절).
- add 키: 더한다.
- value 키: 지도자·체제 중 하나가 정한 값(없으면 기본값).
"""
from __future__ import annotations

LEADERS = [
    dict(key="dangun", name="단군왕검", aggr=3,
         buff=("홍익인간", "전 지역 행복도 +0.1/턴"), debuff=("신화 시대", "공군 생산비 +20%"),
         fx={"happy_turn": 0.1, "cost_air": 0.20}),
    dict(key="jumong", name="동명성왕", aggr=6,
         buff=("신궁", "포병 폭격 피해 +30%"), debuff=("내륙 건국", "해군 생산비 +15%"),
         fx={"bomb_art": 0.30, "cost_naval": 0.15}),
    dict(key="gwanggaeto", name="광개토대왕", aggr=9,
         buff=("정복군주", "돌격 공격력 +15%"), debuff=("약탈경제", "점령지 저항 기간 +50%"),
         fx={"atk_assault": 0.15, "resist_time": 0.5}),
    dict(key="yeon", name="연개소문", aggr=8,
         buff=("천리장성", "방어선 효과 0.30L → 0.40L"), debuff=("삼형제의 내분", "수도가 함락되면 8턴 동안 전 지역 반란 확률 ×2"),
         fx={"line_k": 0.40, "capital_fall_rebel": 2.0}),
    dict(key="geunchogo", name="근초고왕", aggr=6,
         buff=("해상 왕국", "해군 생산비 -20%, 상륙 돌격 감소 없음(×0.8 → ×1.0)"), debuff=("양면 전선", "육군 유지비 +5%"),
         fx={"cost_naval": -0.20, "amphib_extra": 1.25, "upkeep_land": 0.05}),
    dict(key="muryeong", name="무령왕", aggr=3,
         buff=("중흥 외교", "거래 요구 배수 m -0.1"), debuff=("웅진 천도", "방어선 건설비 +15%"),
         fx={"trade_m": -0.1, "cost_line": 0.15}),
    dict(key="seondeok", name="선덕여왕", aggr=2,
         buff=("첨성대", "랜드마크 건설 15턴 → 10턴"), debuff=("대야성 함락", "선전포고를 당하면 4턴 동안 국경 지역 방어력 −15%"),
         fx={"landmark_turns": 10, "ambushed_def": 0.15}),
    dict(key="muyeol", name="태종 무열왕", aggr=5,
         buff=("나당 외교", "조약·동맹·연합 체결 우호도 문턱 -10"), debuff=("외세 의존", "동맹 없이 전쟁 시 돌격 공격력 -10%"),
         fx={"treaty_threshold": -10, "no_ally_assault": -0.10}),
    dict(key="suro", name="수로왕", aggr=4,
         buff=("철의 왕국", "전차 생산비 -15%"), debuff=("연맹 체제", "점령·편입 소요 턴 +20%"),
         fx={"cost_tank": -0.15, "occ_time": 0.20}),
    dict(key="daejoyeong", name="대조영", aggr=7,
         buff=("천문령 승리", "첫 48턴 보병 생산비 -30%"), debuff=("유민 국가", "점령지 행복도(회복 목표) 추가 -10"),
         fx={"inf_cost_early": -0.30, "occupied_happy_extra": -10}),
    dict(key="gyeonhwon", name="견훤", aggr=8,
         buff=("기습의 명수", "기습 성공률 +10%p"), debuff=("금산사 유폐", "반란 세력이 자국과 전쟁 중인 가장 강한 적국과 즉시 동맹"),
         fx={"surprise": 0.1, "rebel_ally_enemy": True}),
    dict(key="wanggeon", name="태조 왕건", aggr=5,
         buff=("호족 포용", "점령지 저항 4 → 2턴, 행복도 회복 20 → 10턴"), debuff=("호족 연합", "수도에서 2칸보다 먼 지역 산출 -5%"),
         fx={"wanggeon_occupy": True, "far_output": 0.05}),
    dict(key="gongmin", name="공민왕", aggr=5,
         buff=("반원 개혁", "개전 전쟁 피로 절반(선포 +15 → +7.5, 피선포 +10 → +5)"), debuff=("영전 공사", "랜드마크 건설비 +25%"),
         fx={"war_start_weary": -0.5, "cost_landmark": 0.25}),
    dict(key="seonggye", name="태조 이성계", aggr=7,
         buff=("백전백승", "보병 공격력 +15%"), debuff=("위화도 회군", "상륙 돌격 추가 x0.85"),
         fx={"atk_inf": 0.15, "amphib_extra": 0.85}),
    dict(key="sejong", name="세종대왕", aggr=2,
         buff=("민본 과학", "생산 건물 건설 시간 -15%"), debuff=("부민고소금지법", "생산 건물(농장·어장·공장·은행) 산출 −8%"),
         fx={"build_time_prod": -0.15, "output_prod": -0.08}),
    dict(key="gwanghae", name="광해군", aggr=3,
         buff=("중립 외교", "제3국 전쟁 때문에 생기는 우호도 감소 없음"), debuff=("정통성 약화", "지역 행복도 상한 80"),
         fx={"neutral_diplomacy": True, "happy_cap": 80}),
    dict(key="jeongjo", name="정조", aggr=4,
         buff=("신해통공", "은행 산출 +20%"), debuff=("문체반정", "공장·정유·탄광·석탄액화공장·발전소 건설 시간 +20%"),
         fx={"output_bank": 0.20, "build_time_industry": 0.20}),
    dict(key="honggyeongrae", name="홍경래", aggr=8,
         buff=("민란의 불꽃", "점령지 행복도(회복 목표) +15"), debuff=("반란", "모든 AI 시작 우호도 -15"),
         fx={"occupied_happy_extra": 15, "start_opinion": -15}),
    dict(key="kimgu", name="김구", aggr=4,
         buff=("임시정부", "영토 3칸 이하일 때 방어력 +30%"), debuff=("무장 열세", "전차·공군 생산비 +15%"),
         fx={"defense_small": 0.30, "cost_tank": 0.15, "cost_air": 0.15}, dkeys=["cost_tank", "cost_air"]),
    dict(key="syngman", name="이승만", aggr=5,
         buff=("한미동맹", "동맹과 공동 전쟁 시 공격력 +20%"), debuff=("3·15의 그늘", "평균 행복도 -30 이하에서 반란 확률 x2"),
         fx={"ally_war_atk": 0.20, "avg_rebel": 2.0}),
    dict(key="kimilsung", name="김일성", aggr=9,
         buff=("천리마 운동", "공장 건설 시간 -25%"), debuff=("자력갱생", "시장 구매가 +30%, 판매가 -30%"),
         fx={"build_time_factory": -0.25, "market_buy": 0.30, "market_sell": -0.30}, dkeys=["market_buy", "market_sell"]),
    dict(key="parkcj", name="박정희", aggr=6,
         buff=("경제개발계획", "공장 산출 +15%"), debuff=("유신 체제", "세율 15% 초과분 행복도 감소 x1.5"),
         fx={"output_factory": 0.15, "tax_over15": 1.5}),
    dict(key="kimdj", name="김대중", aggr=1,
         buff=("햇볕정책", "모든 AI 우호도 +0.3/턴, 우호 선언 때 적대 세력의 반감 없음"), debuff=("외환위기 수습", "시작 자금 -20%"),
         fx={"ai_opinion_turn": 0.3, "friend_no_backlash": True, "start_money": -0.20}),
    # ---- 추가 지도자
    dict(key="onjo", name="온조왕", aggr=4,
         buff=("위례성 건설", "모든 건물 건설 시간 -10%"), debuff=("십제", "시작 수도 인구 −10%"),
         fx={"build_time_all": -0.1, "start_pop": -0.1}),
    dict(key="hyeokgeose", name="박혁거세", aggr=2,
         buff=("6부의 추대", "모든 AI 시작 우호도 +15"), debuff=("교대 계승", "매년 12월 4주차에는 건설·생산 명령 불가"),
         fx={"start_opinion": 15, "dec_freeze": True}),
    dict(key="jinheung", name="진흥왕", aggr=7,
         buff=("화랑도", "보병 공격력 +10%"), debuff=("나제동맹 파기", "조약·동맹·연합 체결 우호도 문턱 +10"),
         fx={"atk_inf": 0.10, "treaty_threshold": 10}),
    dict(key="gungye", name="궁예", aggr=8,
         buff=("태봉 건국", "돌격 공격력 +15%"), debuff=("관심법", "반란이 일어나면 반란군 보병 +2"),
         fx={"atk_assault": 0.15, "rebel_extra_inf": 2}),
    dict(key="jangbogo", name="장보고", aggr=4,
         buff=("청해진", "해군 생산비 -25%, 시장 판매가 +10%"), debuff=("골품의 벽", "동맹·연합 체결 불가(조약은 가능)"),
         fx={"cost_naval": -0.25, "market_sell": 0.1, "no_alliance": True}),
    dict(key="jungbu", name="정중부", aggr=8,
         buff=("무신정권", "군 생산비 -15%"), debuff=("문신 탄압", "은행 산출 −15%"),
         fx={"cost_mil": -0.15, "output_bank": -0.15}),
    dict(key="choiyoung", name="최영", aggr=7,
         buff=("황금 보기를 돌같이", "육군 유지비 -15%"), debuff=("요동 정벌 반대", "개전 전쟁 피로 x1.3"),
         fx={"upkeep_land": -0.15, "war_start_weary": 0.30}),
    dict(key="yisunsin", name="이순신", aggr=4,
         buff=("23전 23승", "해전 전투력 +30%, 함포 사격 피해 +25%"), debuff=("백의종군", "해전에서 지면 12턴 동안 '23전 23승' 비활성"),
         fx={"naval_power": 0.3, "naval_bomb": 0.25, "naval_loss_off": 12}),
    dict(key="honggildong", name="홍길동", aggr=6,
         buff=("신출귀몰", "기습 성공률 +5%p"), debuff=("적서차별", "군주제 계열 정치체제(전제군주제·입헌군주제) 선택 불가"),
         fx={"surprise": 0.05, "no_monarchy": True}),
    dict(key="dosan", name="안창호", aggr=1,
         buff=("무실역행", "생산 건물 건설 시간 -15%"), debuff=("실력 양성 우선", "군 생산비 +10%"),
         fx={"build_time_prod": -0.15, "cost_mil": 0.10}),
    dict(key="yangdi", name="수 양제", aggr=9,
         buff=("백만 대군", "군 생산비 -20%"), debuff=("무리한 원정", "전쟁 중 전쟁 피로 증가 +30%"),
         fx={"cost_mil": -0.20, "war_weary_rate": 0.30}),
    dict(key="taizong", name="당 태종", aggr=8,
         buff=("정관의 치", "세율 10% 초과분 행복도 감소 -20%"), debuff=("안시성", "방어선이 있는 지역 공격 시 공격력 −15%"),
         fx={"tax_over10": 0.8, "atk_vs_line": -0.15}),
    dict(key="kublai", name="쿠빌라이 칸", aggr=9,
         buff=("몽골 기병", "전차 생산비 -20%"), debuff=("일본 원정 실패", "상륙 돌격 추가 ×0.75, 해전 전투력 −15%"),
         fx={"cost_tank": -0.2, "amphib_extra": 0.75, "naval_power": -0.15}, dkeys=["amphib_extra", "naval_power"]),
    dict(key="hideyoshi", name="도요토미 히데요시", aggr=9,
         buff=("조총 부대", "보병 공격력 +15%"), debuff=("보급로 차단", "수도와 육로로 이어지지 않은 곳의 부대 유지비 +100%"),
         fx={"atk_inf": 0.15, "cut_supply": 1.0}),
    dict(key="hongtaiji", name="홍타이지", aggr=8,
         buff=("팔기군", "점령·편입 소요 턴 -20%"), debuff=("소수민족", "보유 지역이 40곳을 넘으면 넘는 1곳마다 전 지역 행복도 −0.3"),
         fx={"occ_time": -0.2, "minority_rule": 0.3}),
    dict(key="ito", name="이토 히로부미", aggr=6,
         buff=("한국통감", "점령·편입 소요 턴 -15%"), debuff=("정미의병", "저항 중인 점령지의 주둔 부대가 매 턴 보병 1개와 싸운 만큼 피해"),
         fx={"occ_time": -0.15, "guerrilla": 1}),
    dict(key="custom", name="직접 입력", aggr=5,
         buff=("없음", "효과 없음"), debuff=("없음", "효과 없음"), fx={}),
]
# 지도자 분류 (선택 화면 탭)
LEADER_CATEGORIES = [
    ("founders", "나라의 문을 연 자들",
     ["dangun", "jumong", "onjo", "hyeokgeose", "suro", "daejoyeong", "wanggeon", "gungye", "gyeonhwon",
      "seonggye", "syngman", "kimilsung"]),
    ("footprints", "역사의 커다란 발자취",
     ["gwanggaeto", "geunchogo", "jinheung", "muryeong", "seondeok", "muyeol", "gongmin", "sejong", "gwanghae",
      "jeongjo", "parkcj", "kimdj"]),
    ("uncrowned", "왕관 없는 지도자들",
     ["yeon", "jangbogo", "jungbu", "choiyoung", "yisunsin", "honggyeongrae", "honggildong", "dosan", "kimgu"]),
    ("invaders", "한반도를 넘본 외적들",
     ["yangdi", "taizong", "kublai", "hideyoshi", "hongtaiji", "ito"]),
]
_CAT_OF = {k: cid for cid, _, keys in LEADER_CATEGORIES for k in keys}
_ORDER = [k for _, _, keys in LEADER_CATEGORIES for k in keys] + ["custom"]
LEADERS.sort(key=lambda l: _ORDER.index(l["key"]))

# 초상화 파일 이름 코드(3글자): korciv/assets/portraits/<코드>.png. 내부 키(세이브·AI가 쓰는 값)와는 따로 둔다.
PORTRAIT_CODES = {
    "dangun": "dan", "jumong": "jum", "onjo": "onz", "hyeokgeose": "egg", "suro": "sur", "daejoyeong": "dae",
    "wanggeon": "wan", "gungye": "gun", "gyeonhwon": "dog", "seonggye": "tae", "syngman": "lee", "kimilsung": "kim",
    "gwanggaeto": "ggt", "geunchogo": "gcg", "jinheung": "jin", "muryeong": "mur", "seondeok": "sen", "muyeol": "muy",
    "gongmin": "gon", "sejong": "sej", "gwanghae": "hae", "jeongjo": "jjo", "parkcj": "pak", "kimdj": "kdj",
    "yeon": "yon", "jangbogo": "jan", "jungbu": "jun", "choiyoung": "cho", "yisunsin": "yis", "honggyeongrae": "hon",
    "honggildong": "gil", "dosan": "ahn", "kimgu": "kgu",
    "yangdi": "yan", "taizong": "tai", "kublai": "kan", "hideyoshi": "toy", "hongtaiji": "taj", "ito": "ito",
    "custom": "cus",
}
for _l in LEADERS:
    _l["img"] = PORTRAIT_CODES[_l["key"]]
for _l in LEADERS:
    _l["cat"] = _CAT_OF.get(_l["key"], "custom")
LEADER_BY_KEY = {l["key"]: l for l in LEADERS}

GOVERNMENTS = [
    dict(key="absolute", name="전제군주제", target=7.5,
         buff=("왕권 통치", "세율 10% 초과분의 행복도 감소 -30%"), debuff=("", "은행 산출 -10%"),
         fx={"tax_over10": 0.7, "output_bank": -0.10}),
    dict(key="constitutional", name="입헌군주제", target=3.5,
         buff=("", "전 지역 행복도 +0.1/턴"), debuff=("", "개전 전쟁 피로 x1.5"),
         fx={"happy_turn": 0.1, "war_start_weary": 0.5}),
    dict(key="presidential", name="대통령제", target=5.5,
         buff=("", "모든 건물 건설 시간 -10%"), debuff=("", "전쟁 중 전쟁 피로 증가 +25%"),
         fx={"build_time_all": -0.10, "war_weary_rate": 0.25}),
    dict(key="parliamentary", name="의원내각제", target=1.5,
         buff=("", "은행 산출 +10%"), debuff=("", "선전포고 후 2턴간 공격 불가(의회 동의)"),
         fx={"output_bank": 0.10, "parliament_delay": 2}),
    dict(key="socialist", name="사회주의", target=6.0,
         buff=("", "공장 건설비 -15%"), debuff=("", "은행 산출 -25%"),
         fx={"cost_factory": -0.15, "output_bank": -0.25}),
    dict(key="fascist", name="파시즘", target=9.5,
         buff=("", "군 생산비 -15%"), debuff=("", "모든 AI 시작 우호도 -10"),
         fx={"cost_mil": -0.15, "start_opinion": -10}),
    dict(key="philosopher", name="철인통치", target=None,
         buff=("", "없음"), debuff=("", "없음"), fx={}),
]
GOV_BY_KEY = {g["key"]: g for g in GOVERNMENTS}

MULT_KEYS = {
    "cost_air", "cost_naval", "cost_tank", "cost_mil", "cost_line", "cost_factory",
    "upkeep_land", "bomb_art", "atk_assault", "atk_inf", "build_time_prod", "build_time_all",
    "build_time_factory", "output_bank", "output_factory", "rebel_prob", "market_buy",
    "market_sell", "start_money", "occ_time", "inf_cost_early", "no_ally_assault",
    "ally_war_atk", "defense_small", "war_weary_rate", "war_start_weary", "def_coast", "naval_power", "naval_bomb",
    "start_pop", "cost_landmark", "output_prod", "atk_vs_line", "resist_time", "build_time_industry",
}
ADD_KEYS = {"happy_turn", "surprise", "trade_m", "treaty_threshold", "start_opinion",
            "ai_opinion_turn", "suppress", "occupied_happy_extra"}


def effects(leader_key: str, gov_key: str | None):
    out = []
    l = LEADER_BY_KEY.get(leader_key)
    if l:
        out.append(l["fx"])
    g = GOV_BY_KEY.get(gov_key) if gov_key else None
    if g:
        out.append(g["fx"])
    return out


class Mods:
    """한 세력의 지도자·체제 효과 합산기."""

    def __init__(self, leader_key: str, gov_key: str | None):
        self.fx = effects(leader_key, gov_key)

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


AI_GOV_AGGR_JITTER = 2.0      # 체제를 고를 때 호전성을 ±2 범위에서 흔든다(같은 지도자도 다른 체제를 고를 수 있게)
AI_PHILOSOPHER_P = 0.10       # 10% 확률로 철인통치(효과 없음)


def banned_govs(leader_key: str) -> set:
    """지도자가 고를 수 없는 정치체제(홍길동 '적서차별': 군주제 계열)."""
    fx = LEADER_BY_KEY.get(leader_key, {}).get("fx", {})
    if fx.get("no_monarchy"):
        return {k for k, fam in GOV_FAMILIES.items() if "군주정" in fam}
    return set()


def ai_pick_government(rng, aggression: float, factory_level: int, bank_level: int, banned=()) -> str:
    """9절: 1 - |호전성' - 목표| / 10 + U(0, 0.1), 공장 > 은행이면 사회주의 +0.2.
    호전성' = 호전성 + U(−2, +2). 전체의 10%는 철인통치. banned 체제는 고르지 않는다."""
    if rng.random() < AI_PHILOSOPHER_P:
        return "philosopher"
    aggression = aggression + rng.uniform(-AI_GOV_AGGR_JITTER, AI_GOV_AGGR_JITTER)
    best, best_score = None, -1e9
    for g in GOVERNMENTS:
        if g["target"] is None or g["key"] in banned:
            continue
        s = 1 - abs(aggression - g["target"]) / 10 + rng.random() * 0.1
        if g["key"] == "socialist" and factory_level > bank_level:   # 공장이 은행보다 많을 때만
            s += 0.2
        if s > best_score:
            best, best_score = g["key"], s
    return best


# 정치체제 계열 (반란 세력끼리 우호/적대 판정). 계열이 겹치면 '유사'.
GOV_FAMILIES = {
    "absolute": {"군주정", "권위주의"},
    "constitutional": {"군주정", "민주정"},
    "presidential": {"민주정"},
    "parliamentary": {"민주정"},
    "socialist": {"권위주의"},
    "fascist": {"권위주의"},
    "philosopher": {"철인"},
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
