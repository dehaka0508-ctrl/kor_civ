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
         buff=("명궁", "포병 폭격 피해 +15%"), debuff=("내륙 건국", "해군 생산비 +15%"),
         fx={"bomb_art": 0.15, "cost_naval": 0.15}),
    dict(key="gwanggaeto", name="광개토대왕", aggr=9,
         buff=("정복군주", "돌격 공격력 +15%"), debuff=("원정 피로", "전쟁 중 전쟁 피로 증가 +25%"),
         fx={"atk_assault": 0.15, "war_weary_rate": 0.25}),
    dict(key="yeon", name="연개소문", aggr=8,
         buff=("천리장성", "방어선 효과 0.30L → 0.36L"), debuff=("권신 정치", "모든 AI 시작 우호도 -10"),
         fx={"line_k": 0.36, "start_opinion": -10}),
    dict(key="geunchogo", name="근초고왕", aggr=6,
         buff=("해상 왕국", "해군 생산비 -20%"), debuff=("양면 전선", "육군 유지비 +10%"),
         fx={"cost_naval": -0.20, "upkeep_land": 0.10}),
    dict(key="muryeong", name="무령왕", aggr=3,
         buff=("중흥 외교", "거래 요구 배수 m -0.1"), debuff=("웅진 천도", "방어선 건설비 +15%"),
         fx={"trade_m": -0.1, "cost_line": 0.15}),
    dict(key="seondeok", name="선덕여왕", aggr=2,
         buff=("첨성대", "랜드마크 건설 15턴 → 10턴"), debuff=("비담의 난", "반란 확률 x1.2"),
         fx={"landmark_turns": 10, "rebel_prob": 0.2}),
    dict(key="muyeol", name="태종 무열왕", aggr=5,
         buff=("나당 외교", "조약·동맹·연합 체결 우호도 문턱 -15"), debuff=("외세 의존", "동맹 없이 전쟁 시 돌격 공격력 -10%"),
         fx={"treaty_threshold": -15, "no_ally_assault": -0.10}),
    dict(key="suro", name="수로왕", aggr=4,
         buff=("철의 왕국", "전차 생산비 -15%"), debuff=("연맹 체제", "점령·편입 소요 턴 +20%"),
         fx={"cost_tank": -0.15, "occ_time": 0.20}),
    dict(key="daejoyeong", name="대조영", aggr=7,
         buff=("천문령 승리", "첫 48턴 보병 생산비 -30%"), debuff=("유민 국가", "점령지 행복도(회복 목표) 추가 -10"),
         fx={"inf_cost_early": -0.30, "occupied_happy_extra": -10}),
    dict(key="gyeonhwon", name="견훤", aggr=8,
         buff=("기습의 명수", "기습 성공률 +10%p"), debuff=("금산사 유폐", "반란 확률 x1.3"),
         fx={"surprise": 0.10, "rebel_prob": 0.3}),
    dict(key="wanggeon", name="태조 왕건", aggr=5,
         buff=("호족 포용", "점령지 저항 4 → 2턴, 행복도 회복 20 → 10턴"), debuff=("호족 연합", "세율 상한 50% → 40%"),
         fx={"wanggeon_occupy": True, "tax_max": 0.40}),
    dict(key="gongmin", name="공민왕", aggr=5,
         buff=("반원 개혁", "개전 전쟁 피로 절반(선포 +15 → +7.5, 피선포 +10 → +5)"), debuff=("개혁 반발", "반란 진압 성공률 -15%p"),
         fx={"war_start_weary": -0.5, "suppress": -0.15}),
    dict(key="seonggye", name="태조 이성계", aggr=7,
         buff=("백전백승", "보병 공격력 +15%"), debuff=("위화도 회군", "상륙 돌격 추가 x0.85"),
         fx={"atk_inf": 0.15, "amphib_extra": 0.85}),
    dict(key="sejong", name="세종대왕", aggr=2,
         buff=("민본 과학", "생산 건물 건설 시간 -20%"), debuff=("문치주의", "군 생산비 +10%"),
         fx={"build_time_prod": -0.20, "cost_mil": 0.10}),
    dict(key="gwanghae", name="광해군", aggr=3,
         buff=("중립 외교", "제3국 전쟁 때문에 생기는 우호도 감소 없음"), debuff=("정통성 약화", "지역 행복도 상한 80"),
         fx={"neutral_diplomacy": True, "happy_cap": 80}),
    dict(key="jeongjo", name="정조", aggr=4,
         buff=("신해통공", "은행 산출 +15%"), debuff=("벽파 견제", "세율 변경 후 4턴간 재변경 불가"),
         fx={"output_bank": 0.15, "tax_lock": 4}),
    dict(key="honggyeongrae", name="홍경래", aggr=8,
         buff=("민란의 불꽃", "점령지 행복도(회복 목표) +10"), debuff=("반란군 출신", "모든 AI 시작 우호도 -15"),
         fx={"occupied_happy_extra": 10, "start_opinion": -15}),
    dict(key="kimgu", name="김구", aggr=4,
         buff=("임시정부", "영토 3칸 이하일 때 방어력 +30%"), debuff=("무장 열세", "전차·공군 생산비 +15%"),
         fx={"defense_small": 0.30, "cost_tank": 0.15, "cost_air": 0.15}),
    dict(key="syngman", name="이승만", aggr=5,
         buff=("한미동맹", "동맹과 공동 전쟁 시 공격력 +15%"), debuff=("3·15의 그늘", "평균 행복도 -30 이하에서 반란 확률 x2"),
         fx={"ally_war_atk": 0.15, "avg_rebel": 2.0}),
    dict(key="kimilsung", name="김일성", aggr=9,
         buff=("천리마 운동", "공장 건설 시간 -25%"), debuff=("자력갱생", "시장 구매가 +30%, 판매가 -30%"),
         fx={"build_time_factory": -0.25, "market_buy": 0.30, "market_sell": -0.30}),
    dict(key="parkcj", name="박정희", aggr=6,
         buff=("경제개발계획", "공장 산출 +15%"), debuff=("유신 체제", "세율 15% 초과분 행복도 감소 x1.5"),
         fx={"output_factory": 0.15, "tax_over15": 1.5}),
    dict(key="kimdj", name="김대중", aggr=1,
         buff=("햇볕정책", "모든 AI 우호도 +0.2/턴"), debuff=("외환위기 수습", "시작 자금 -30%"),
         fx={"ai_opinion_turn": 0.2, "start_money": -0.30}),
    # ---- 추가 지도자
    dict(key="onjo", name="온조왕", aggr=4,
         buff=("위례성 건설", "모든 건물 건설 시간 -10%"), debuff=("형제의 분열", "모든 AI 시작 우호도 -5"),
         fx={"build_time_all": -0.10, "start_opinion": -5}),
    dict(key="hyeokgeose", name="박혁거세", aggr=2,
         buff=("6부의 추대", "모든 AI 시작 우호도 +10"), debuff=("작은 시작", "시작 자금 -20%"),
         fx={"start_opinion": 10, "start_money": -0.20}),
    dict(key="jinheung", name="진흥왕", aggr=7,
         buff=("화랑도", "보병 공격력 +10%"), debuff=("나제동맹 파기", "조약·동맹·연합 체결 우호도 문턱 +10"),
         fx={"atk_inf": 0.10, "treaty_threshold": 10}),
    dict(key="gungye", name="궁예", aggr=8,
         buff=("후고구려 건국", "돌격 공격력 +10%"), debuff=("관심법 폭정", "반란 확률 x1.3"),
         fx={"atk_assault": 0.10, "rebel_prob": 0.30}),
    dict(key="jangbogo", name="장보고", aggr=4,
         buff=("청해진 무역", "시장 판매가 +20%"), debuff=("염장의 배신", "반란 진압 성공률 -10%p"),
         fx={"market_sell": 0.20, "suppress": -0.10}),
    dict(key="jungbu", name="정중부", aggr=8,
         buff=("무신정변", "군 생산비 -15%"), debuff=("문신 탄압", "세율 10% 초과분 행복도 감소 x1.3"),
         fx={"cost_mil": -0.15, "tax_over10": 1.3}),
    dict(key="choiyoung", name="최영", aggr=7,
         buff=("황금 보기를 돌같이", "육군 유지비 -15%"), debuff=("요동 정벌 반대", "개전 전쟁 피로 x1.3"),
         fx={"upkeep_land": -0.15, "war_start_weary": 0.30}),
    dict(key="yisunsin", name="이순신", aggr=4,
         buff=("23전 23승", "해안 지역 방어력 +20%"), debuff=("백의종군", "세율 변경 후 3턴간 재변경 불가"),
         fx={"def_coast": 0.20, "tax_lock": 3}),
    dict(key="dosan", name="안창호", aggr=1,
         buff=("무실역행", "생산 건물 건설 시간 -15%"), debuff=("실력 양성 우선", "군 생산비 +15%"),
         fx={"build_time_prod": -0.15, "cost_mil": 0.15}),
    dict(key="yangdi", name="수 양제", aggr=9,
         buff=("백만 대군", "군 생산비 -20%"), debuff=("무리한 원정", "전쟁 중 전쟁 피로 증가 +30%"),
         fx={"cost_mil": -0.20, "war_weary_rate": 0.30}),
    dict(key="taizong", name="당 태종", aggr=8,
         buff=("정관의 치", "세율 10% 초과분 행복도 감소 -20%"), debuff=("안시성 패배", "점령·편입 소요 턴 +15%"),
         fx={"tax_over10": 0.8, "occ_time": 0.15}),
    dict(key="kublai", name="쿠빌라이 칸", aggr=9,
         buff=("몽골 기병", "전차 생산비 -20%"), debuff=("정복 왕조", "모든 AI 시작 우호도 -15"),
         fx={"cost_tank": -0.20, "start_opinion": -15}),
    dict(key="hideyoshi", name="도요토미 히데요시", aggr=9,
         buff=("조총 부대", "보병 공격력 +15%"), debuff=("의병의 저항", "점령지 행복도(회복 목표) 추가 -10"),
         fx={"atk_inf": 0.15, "occupied_happy_extra": -10}),
    dict(key="hongtaiji", name="홍타이지", aggr=8,
         buff=("팔기군", "점령·편입 소요 턴 -20%"), debuff=("교역 단절", "시장 구매가 +20%"),
         fx={"occ_time": -0.20, "market_buy": 0.20}),
    dict(key="terauchi", name="데라우치 마사타케", aggr=7,
         buff=("무단 통치", "반란 진압 성공률 +25%p"), debuff=("민족의 저항", "반란 확률 x1.4"),
         fx={"suppress": 0.25, "rebel_prob": 0.40}),
    dict(key="custom", name="직접 입력", aggr=5,
         buff=("없음", "효과 없음"), debuff=("없음", "효과 없음"), fx={}),
]
# 지도자 분류 (선택 화면 탭)
LEADER_CATEGORIES = [
    ("founders", "나라의 문을 연 자들",
     ["dangun", "jumong", "onjo", "hyeokgeose", "suro", "daejoyeong", "wanggeon", "gungye", "gyeonhwon",
      "seonggye", "syngman", "kimilsung"]),
    ("footprints", "역사의 커다란 발자국",
     ["gwanggaeto", "geunchogo", "jinheung", "muryeong", "seondeok", "muyeol", "gongmin", "sejong", "gwanghae",
      "jeongjo", "parkcj", "kimdj"]),
    ("uncrowned", "왕이 되지 못한 자들",
     ["yeon", "jangbogo", "jungbu", "choiyoung", "yisunsin", "honggyeongrae", "dosan", "kimgu"]),
    ("invaders", "한반도를 넘본 외적들",
     ["yangdi", "taizong", "kublai", "hideyoshi", "hongtaiji", "terauchi"]),
]
_CAT_OF = {k: cid for cid, _, keys in LEADER_CATEGORIES for k in keys}
_ORDER = [k for _, _, keys in LEADER_CATEGORIES for k in keys] + ["custom"]
LEADERS.sort(key=lambda l: _ORDER.index(l["key"]))
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
    "ally_war_atk", "defense_small", "war_weary_rate", "war_start_weary", "def_coast",
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


def ai_pick_government(rng, aggression: float, factory_level: int, bank_level: int) -> str:
    """9절: 1 - |호전성 - 목표| / 10 + U(0, 0.1), 공장 >= 은행이면 사회주의 +0.2."""
    best, best_score = None, -1e9
    for g in GOVERNMENTS:
        if g["target"] is None:
            continue
        s = 1 - abs(aggression - g["target"]) / 10 + rng.random() * 0.1
        if g["key"] == "socialist" and factory_level >= bank_level:
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
