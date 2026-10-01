"""게임 밸런스 상수 (기획서 3~11절).

플레이테스트 중 조정할 수치는 모두 여기에 모은다. 금액 단위는 만원, 인구 단위는 만 명.
"""

# ---------------------------------------------------------------- 턴·날짜
START_YEAR = 2026
TURNS_PER_MONTH = 4
TURNS_PER_YEAR = 48

# ---------------------------------------------------------------- 경제 (4절)
MONEY_SCALE = 1            # 전체 금액 배수. 현실감 있는 숫자가 필요하면 키운다.
START_MONEY = 3000
TAX_DEFAULT = 0.10
TAX_MAX = 0.50

POP_OUTPUT = 30            # 인구 1만 명당 산출
FARM_OUTPUT = 150
FISH_OUTPUT = 150
FACTORY_OUTPUT = 1000
BANK_OUTPUT = 600
LANDMARK_OUTPUT = 9000
LEVEL_GROWTH = 0.2         # g(L) = L * (1 + r (L - 1))
FOOD_PER_G = 15            # 농장·어장 식량 15 * g(L)
FOOD_PER_POP = 1           # 인구 1만 명당 식량 소비/턴
START_FOOD_TURNS = 5       # 시작 식량 = 인구 * 5
COAST_FISH_BONUS = 0.20    # 해안선 점유(해역에 닿는 해안 지역 전부 보유) 시 바다 어장 식량·산출 +20%
COAST_NAVAL_DEF = 0.10     # 해안선 점유 시 그 해역 해전 방어 +10%
RIVER_FISH_MULT = 0.70     # 하천 어장(도하 경계를 가진 내륙 지역)은 바다 어장 생산력의 70%

FUEL_PHI = {"coal": 1.0, "oil": 1.1, "elec": 1.25, "none": 0.25}
FUEL_AUTO_ORDER = ("elec", "coal", "oil")   # 자동 연료: 석유는 군 생산용으로 아낀다

START_RESOURCES = {"oil": 5, "coal": 10, "elec": 0}   # 식량은 인구 * 5
RESOURCES = ("food", "oil", "coal", "elec")
RESOURCE_NAMES = {"food": "식량", "oil": "석유", "coal": "석탄", "elec": "전기"}
MARKET_BUY = {"food": 4, "oil": 40, "coal": 20, "elec": 30}
MARKET_SELL = {"food": 2, "oil": 20, "coal": 10, "elec": 15}
MARKET_STEP = 0.10         # 식량 제외 자원은 같은 턴 1개 살 때마다 +10%
OIL_RESERVE_FOR_LIQUEFY = 20   # 석유 비축이 이보다 적을 때만 석탄액화
SPECIALTY_VALUE = 20
SPECIALTY_MAX_TYPES = 5
SPECIALTY_HAPPY = 3

LANDMARK_COST_PER_TURN = 100_000
LANDMARK_TURNS = 15
LANDMARK_COST_GROWTH = 1.3     # 보유·건설 중인 랜드마크 1개마다 다음 랜드마크 비용 ×1.3 (8번째는 1.3^7 ≈ 6.3배)
CAPITAL_MOVE_TURNS = 4
CAPITAL_MOVE_COST_MULT = 20
CAPITAL_MOVE_HAPPY = -3
CAPITAL_LOST_HAPPY = -10
PROJECT_REFUND = 0.5
FOCUS_POP_BONUS = 0.15     # 생산 집중: 건설·병력 생산을 하지 않는 지역의 인구 산출(30P) +15%
DEBT_HAPPY = -1.0          # 보완안: 자금이 음수인 턴에는 전 지역 행복도 -1

# 건물(생산·방어·단일) 건설 비용 배수. 재정이 빠듯해 원안의 50%로 낮췄다(랜드마크는 제외).
BUILD_COST_MULT = 0.5
# 생산 건물: 단계 L 비용 = base * L^1.5 * BUILD_COST_MULT, 소요 2L턴
PROD_BUILDINGS = {
    "farm":      {"name": "농장", "base": 400, "max": 5},
    "fishery":   {"name": "어장", "base": 400, "max": 5},
    "factory":   {"name": "공장", "base": 1500, "max": 5},
    "bank":      {"name": "은행", "base": 1200, "max": 5},
    "power":     {"name": "발전소", "base": 1500, "max": 5},
    "liquefy":   {"name": "석탄액화공장", "base": 2000, "max": 5},
    "specialty": {"name": "특산물 시설", "base": 600, "max": 3},
    "extract":   {"name": "정유·탄광 증설", "base": 2500, "max": 5},
}
PROD_TURNS_PER_LEVEL = 2
POWER_SITE_DISCOUNT = 0.5  # 기존 화력발전소 소재지 발전소 건설비

# 방어·군사 건물 (6절)
DEF_BUILDINGS = {
    "line":    {"name": "방어선", "base": 300, "max": 5},
    "shelter": {"name": "방공호", "base": 300, "max": 5},
    "aa":      {"name": "대공포", "base": 500, "max": 5},
}
DEF_TURNS = [1, 2, 4, 8, 15]
SINGLE_BUILDINGS = {
    "academy": {"name": "사관학교", "cost": 3000, "turns": 6},
    "airport": {"name": "공항", "cost": 4000, "turns": 8},
    "port":    {"name": "항구", "cost": 2500, "turns": 5},
}
ACADEMY_LOCAL = 0.25
ACADEMY_ADJ = 0.10
AIRPORT_CAPACITY = 20

# ---------------------------------------------------------------- 인구·행복도 (5절)
G_MAX = 0.0025             # 원안 값 0.01 도 가능
POP_GROWTH_MIN_H = 10
POP_CAP_START_MULT = 2
POP_CAP_PER_LEVEL = 5
FAMINE_POP = -0.005
MIGRATION_H = -30
MIGRATION_POP = -0.001

HAPPY_MIN, HAPPY_MAX = -100, 100
HAPPY_DECAY = 0.99
TAX_HAPPY_K = 0.1          # 0.1 * (10 - t%)
# 전쟁 피로: 전쟁은 행복도를 직접 깎지 않고, 국가 단위 '전쟁 피로도'(0~200)를 쌓는다.
# 실질 행복도 = 행복도 − 전쟁 피로도 (모든 지역에 고르게). 산출·반란·인구·전투력은 실질 행복도로 판정한다.
# 선전포고: 선포한 쪽 +20, 당한 쪽 +10. 전쟁 중 매 턴 선포한 쪽 +1, 당한 쪽 +0.5. 전쟁이 없으면 턴당 1 회복.
WAR_WEARY_START = {"aggressor": 20.0, "defender": 10.0}
WAR_WEARY_TURN = {"aggressor": 1.0, "defender": 0.5}
WAR_WEARY_RECOVERY = 1.0
WAR_WEARY_MAX = 200.0
# 불행한 지역의 산출 감소: 행복도 H < 0 이면 산출 × (1 − 0.30 × (−H/100)²). −50에서 −7.5%, −100에서 −30%.
UNHAPPY_OUTPUT_MAX = 0.30
UNHAPPY_OUTPUT_EXP = 2.0
# 사기: 실질 평균 행복도가 −10 이하이면 군 전투력(공격·방어·폭격·해전)도 산출 감소와 같은 곡선으로 줄어든다.
MORALE_H = -10
# 징집 피로: 지역마다 최근 10턴 중 군 유닛 생산에 쓴 턴 수 n. n ≥ 6이면 그 지역 행복도 −(1, 2, 4, 6, 10).
# 감소분은 n이 3 이하로 내려가면 턴당 3씩 빠르게 회복(4~5턴이면 유지).
CONSCRIPT_WINDOW = 10
CONSCRIPT_PENALTY = {6: 1.0, 7: 2.0, 8: 4.0, 9: 6.0, 10: 10.0}
CONSCRIPT_RECOVER_N = 3
CONSCRIPT_RECOVERY = 3.0
UNIT_START_HAPPY = {"light": -0.5, "heavy": -1.0}
UNIT_DISBAND_HAPPY = {"light": 0.5, "heavy": 1.0}
FAMINE_HAPPY = -5
BOMBED_HAPPY = -2
LANDMARK_HAPPY = 20
LANDMARK_ADJ_HAPPY = 5
REBEL_ACCEPT_HAPPY = 20
REBEL_SUPPRESS_HAPPY = 5
REBEL_SUPPRESS_LOSS = 0.10
REBEL_ACCEPT_TURNS = 4     # 요구 수용: 산출 4턴분
REBEL_ACCEPT_TAX_CUT = 0.05
REBEL_THRESHOLD = -50
# 진압 실패 시 반란 지역이 그 지역을 수도로 하는 새 국가로 독립한다(건물·인구·산출·진행 중 공사 계승).
REBEL_MAX_PER_PARENT = 3   # 한 국가에서 분리독립한 반란 세력(생존) 최대 수. 넘으면 기존 반란 세력에 합류
REBEL_HAPPY_FLOOR_TURNS = 24   # 신생 국가는 이 기간 동안 행복도가 0 아래로 내려가지 않는다
REBEL_SIBLING_OPINION = 40     # 같은 국가에서 독립한 세력끼리: 체제 같거나 유사 +40, 다르면 -40
MAX_FACTIONS = 30          # 안전장치: 세력 수 상한. 넘으면 독립 지역은 중립이 된다

# ---------------------------------------------------------------- 군사 (6절)
UNITS = {
    #        이름      턴당비용 턴 석유 유지 공격 방어 폭격 체력 종류      수송칸
    "inf":  dict(name="보병", cost=300, turns=1, oil=0, upkeep=5, atk=10, df=12, bomb=0, hp=10, kind="land", cargo=1, weight="light"),
    "art":  dict(name="포병", cost=900, turns=2, oil=0, upkeep=15, atk=4, df=6, bomb=25, hp=8, kind="land", cargo=2, weight="light"),
    "tank": dict(name="전차", cost=2500, turns=3, oil=2, upkeep=40, atk=40, df=30, bomb=0, hp=30, kind="land", cargo=4, weight="heavy"),
    "lst":  dict(name="상륙함", cost=3000, turns=4, oil=3, upkeep=50, atk=5, df=10, bomb=0, hp=20, kind="naval", capacity=12, weight="heavy"),
    "dd":   dict(name="구축함", cost=5000, turns=5, oil=4, upkeep=80, atk=0, naval=30, df=25, bomb=30, hp=30, kind="naval", weight="heavy"),
    "cv":   dict(name="항공모함", cost=25000, turns=15, oil=15, upkeep=400, atk=0, df=20, bomb=0, hp=60, kind="naval", air_capacity=8, weight="heavy"),
    "ftr":  dict(name="전투기", cost=3500, turns=3, oil=2, upkeep=60, atk=0, air=30, df=20, bomb=0, hp=15, kind="air", weight="heavy"),
    "bmb":  dict(name="폭격기", cost=7000, turns=5, oil=4, upkeep=110, atk=0, df=5, bomb=60, hp=20, kind="air", weight="heavy"),
    "stl":  dict(name="스텔스폭격기", cost=20000, turns=10, oil=8, upkeep=300, atk=0, df=5, bomb=60, hp=20, kind="air", weight="heavy", stealth=True),
}
UNIT_ORDER = ["inf", "art", "tank", "lst", "dd", "cv", "ftr", "bmb", "stl"]
NAVAL_AT_SEA_UPKEEP = 2.0
ASSAULT_UNITS = ("inf", "tank", "lst")
SURPRISE_UNITS = ("inf", "tank")
ART_RANGE = 1
AIR_RANGE = 3
AIR_REBASE_RANGE = 3
NAVAL_STEPS = 2
LAND_STEPS_OWN = 2

LINE_BONUS = 0.25          # 방어선 돌격 방어 x(1 + 0.25L)
# 지형 경계(도하·산악 돌파) 공격 배수는 data/terrain-borders.csv 의 공격배수 열(기본 0.9)을 쓴다.
BRIDGE_ATTACK_MULT = 1.0   # 연륙교는 기획서 2절대로 '육지처럼' 취급(지형 경계에 있으면 그 배수 적용)
FLANK_BONUS = 0.1          # n개 지역 동시 공격 x(1 + 0.1(n-1))
AMPHIBIOUS = 0.8
# 기습: 방어선이 없으면 성공 75%(공격 피해 ×1.2, 반격 ×0.9) / 실패 25%(×0.6, 반격 ×1.2) → 피해 기대값 돌격의 1.05배.
# 방어선 단계 L마다 성공률 −15%p, 실패 시 공격 피해 −5%p·반격 +5%p (돌격은 방어선이 방어력 ×(1 + 0.25L)).
SURPRISE_BASE = 0.75
SURPRISE_PER_LINE = 0.15
SURPRISE_WIN = (1.2, 0.9)      # (공격 피해, 반격)
SURPRISE_FAIL = (0.6, 1.2)
SURPRISE_FAIL_PER_LINE = 0.05
# 돌격에서 방어측이 입은 피해가 공격측보다 크면 25% 확률로 그 경계 방어선 −1단계
ASSAULT_LINE_BREAK = 0.25
DAMAGE_K = 0.5
RAND_LO, RAND_HI = 0.85, 1.15
SHELTER_K = 0.2
AA_DMG_K = 0.1
AA_SHOOT_K = 0.05
STEALTH_AA_SHOOT = 0.10
STEALTH_AA_DMG = 0.8
INTERCEPT_PER_FIGHTER = 0.3
FIGHTER_LOSS = 0.2
# 폭격의 건물 피해: 포병(구축함 함포 포함)이 참여하면 30%, 폭격기·스텔스폭격기 60%, 둘 다 90% 확률로
# 대상 지역의 생산·방어 건물(방어선 포함) 중 무작위 하나를 1단계 낮춘다.
BOMB_HIT_GUN = 0.30
BOMB_HIT_AIR = 0.60
BOMB_HIT_BOTH = 0.90
NAVAL_DD_POWER = 30
NAVAL_BMB_POWER = 40
CAPTURE_CHANCE = 0.05

# 점령·편입
OCC_MAX_TURNS = 15         # 적 지역 점령 T(P) 상한
INSTANT_ANNEX_H = -50
# 점령 저항: 다른 세력에게서 빼앗은 지역은 첫 6턴 '저항'(산출 0·생산 불가·행복도 −100 고정),
# 이어서 24턴 동안 점령 직전 행복도로 점차 회복. 점령 후 36턴 동안은 반란이 일어나지 않는다.
# 저항 중에는 그 지역의 원래 주인이 그 지역을 공격할 때 공격력 +20%.
RESIST_TURNS = 6
RESIST_RECOVER_TURNS = 24
RESIST_NO_REBEL_TURNS = 36
RESIST_HAPPY = -100.0
RESIST_RETAKE_ATK = 0.20
# 중립 지역: 인구·건물·산출·자원·특산물을 합친 점수로 '지역 가치' 1~10을 매기고, 가치별로 편입·점령 턴이 정해진다.
# 점수 = log2(산출/200) + 0.8 log2(1 + 인구/5) + 건물(단계당 0.3, 항구·공항·사관학교 0.5, 최대 3)
#        + 자원(정유 1.5, 탄광 1.0, 자체발전 0.7, 화력발전소 소재지 0.5, 증설 단계당 0.5, 최대 3) + 특산물 0.8/종
# 가치 = 1 + (아래 문턱을 넘은 수). 문턱은 시작 지도에서 가치 1~10이 약 10/15/17/17/13/10/7/5/3.5/2.5%가 되도록 정했다.
VALUE_THRESHOLDS = (2.3, 3.8, 5.0, 6.0, 6.9, 7.8, 8.6, 9.6, 10.5)
VALUE_TURNS = (1, 2, 3, 4, 6, 8, 10, 13, 16, 20)
# 편입 비용 = (100 + 1.0 × 대상 산출) × (1 + 0.01 × 보유 지역 수) — 넓어질수록 행정 부담으로 비싸진다
ANNEX_BASE_COST = 100
ANNEX_COST_OUTPUT = 1.0
ANNEX_COST_PER_REGION = 0.01
# 공동 편입: 같은 중립 지역을 인접한 내 지역 여러 곳에서 동시에 편입하면 소요 시간 감소(2곳 33%, 3곳 50%, 4곳 60%, 5곳 이상 70%).
# 각 지역은 자기 몫의 편입 비용을 따로 내고, 진행도는 함께 쌓인다(턴당 1 / (1 − 감소율)).
JOINT_ANNEX_REDUCTION = {1: 0.0, 2: 0.33, 3: 0.50, 4: 0.60, 5: 0.70}

# ---------------------------------------------------------------- 외교 (7절)
OPINION_DECAY = 0.99
OP_SAME_ENEMY = 0.5
OP_SAME_FRIEND = 0.3
OP_WAR_WITH_FRIEND = -0.5
OP_FRIEND_OF_ENEMY = -0.3
# 국경 긴장: 상대가 우리 쪽 국경에 우리보다 많은 병력을 모아 두면 매 턴 우호도 감소.
# 비율 = 상대 국경 병력 / (우리 국경 병력 + 20), 감소 = min(MAX, K × (비율 − FREE)). 수렴값은 감소 × 약 100.
OP_BORDER_K = 0.15
OP_BORDER_FREE = 0.75
OP_BORDER_MAX = 0.35
OP_TREATY_TURN = 0.1       # 불가침·통행권을 유지하는 동안 매 턴 우호도 +0.1 (수렴 +10)
OP_LAND_GRAB = -2          # 우리와도 맞닿은 중립 지역을 먼저 차지하면(영토 경쟁) 우리 쪽 우호도 -2
OP_HIJACK = -15            # 편입·점령하던 중립 지역을 다른 세력이 가로채면 빼앗긴 AI의 우호도 -15
# 전쟁광 평판: 선전포고하면 대상 외 모든 세력의 우호도 −10. 직전 전쟁(선포했거나, 그 전쟁이 끝난 지)
# 1년 안에 또 선포할 때마다 5씩 더 깎인다(−15, −20, ...).
OP_WARMONGER = -10
OP_WARMONGER_STEP = -5
WARMONGER_WINDOW = 48
OP_GIFT_MAX = 25
OP_DEMAND_ACCEPT = -15
OP_DEMAND_REJECT = -10
OP_TRADE_DONE = 2
OP_WAR_DECLARED = -100
OP_FRIEND_ATTACKED = -10
OP_NONAGGR_BROKEN = -30
OP_HEGEMON_FIGHTER = 0.3
OP_COALITION_LEAVE = -50

FRIEND_ON, FRIEND_OFF = 30, 20
TREATY_MIN = 45
NONAGGR_FEAR_DISCOUNT = 15  # 상대가 1/0.7배 이상 강해 보이면 불가침 문턱 -15
TREATY_RENEW_MIN = 35
ALLIANCE_MIN = 65
ALLIANCE_LEAVE = 55
COALITION_MIN = 85
COALITION_ALLIANCE_TURNS = 24
TREATY_TURNS = 24
PEACE_TREATY_TURNS = 24
PASSAGE_FREE_OPINION = 45
PASSAGE_VALUE = 500
TERRITORY_TURNS = 40
TERRITORY_WEIGHT = 3
TRADE_M_BASE = 1.1
TRADE_M_DIV = 250
FRIEND_M = 0.05
COUNTER_RATIO = 0.8

HEGEMON_SHARE = 0.35
HEGEMON_LEAD = 1.5
HEGEMON_OP_BASE = 0.2
HEGEMON_OP_K = 2.0
HEGEMON_OP_MAX = 0.6
HEGEMON_WAR_K = 1.5
HEGEMON_WAR_MAX = 0.5
HEGEMON_TRADE_M = 0.2
# 7절 "한 세력이 독주하면 나머지 AI가 서로 가까워진다": 패권 세력이 아닌 AI끼리
# 견제 강도(0.2 + 2(s-0.35), 최대 0.6)에 이 배수를 곱한 만큼 매 턴 우호도 상승
HEGEMON_BALANCE_K = 1.5
# 공동의 패권 세력이 있는 두 비패권 세력은 조약·동맹 우호도 문턱이 이만큼 낮아진다
HEGEMON_TREATY_DISCOUNT = 20
# 패권 세력에 대한 선전포고 점수에서, 이미 패권 세력과 싸우는 세력의 전력을 이 비율만큼 내 전력에 더한다(공동 전선)
HEGEMON_JOINT_FRONT = 0.5
AI_MAX_WARS = 2
# ---- AI 전쟁 판단 (안개 안에서 보이는 병력 기준)
AI_WAR_OP_BASE = -85       # 선전포고 가능 우호도 상한 = -85 + 11 × 호전성 (호전성 9 → +14, 5 → -30, 2 → -63)
AI_WAR_OP_PER_AGGR = 11
AI_WAR_OP_HEGEMON = 25     # 패권 세력 상대로는 이만큼 더 쉽게
AI_WAR_OP_TEMPT_MAX = 12   # 보이는 전력이 압도적이면 유혹: 문턱 + min(12, 호전성 × log2(전력비))
AI_WAR_OP_NEED = 5         # 평화적으로 넓힐 중립 땅이 없으면(호전성 4 이상) 문턱 +5
AI_INTEL_DECAY = 0.97      # 한 번 본 적 병력의 기억이 턴마다 줄어드는 비율
AI_HIDDEN_GARRISON = 7     # 시야 밖 적 지역 하나당 추정 전력(보병 약 0.7개)
AI_PEACE_SEEK = 1.0        # 강화 욕구가 이 값 이상이면 강화를 제안
AI_PEACE_ACCEPT = 0.6      # 상대가 제안하면 이 값 이상에서 수락
# ---- AI 평시 방어 건설: 우호도가 이 값 이하인 이웃과 맞닿은 지역에, 재정에 따라 확률적으로 방어 건물(같은 단계면 방어선 우선)
AI_DEF_OP = -20
AI_DEF_MAX_LEVEL = 3
AI_DEF_BASE_P = 0.03       # 지역·턴당 기본 확률. 재정 여유(0~1.5)에 따라 최대 +0.09, 적대가 깊을수록 최대 ×2 (최대 0.24)
AI_DEF_WEALTH_P = 0.06
# ---- AI 승리 목표: 1년(48턴)마다 국내 상황·주변 정세로 추구할 승리 조건을 정한다(플레이어에게 보이지 않음)
AI_GOAL_WEIGHT = 0.25      # 목표에 맞는 전략 가중치에 더하는 값(맹목적이지 않도록 작게)

# ---------------------------------------------------------------- 승리 (10절)
ECON_VICTORY_RATIO = 2.0
ECON_VICTORY_TURNS = 10
VICTORY_TYPES = {"conquest": "정복승리", "economic": "경제승리", "landmark": "랜드마크승리"}

# ---------------------------------------------------------------- 난이도 (11절, AI에만 적용)
DIFFICULTIES = [
    ("매우 쉬움", 0.70, 0.60),
    ("쉬움", 0.85, 0.80),
    ("중간", 1.00, 1.00),
    ("어려움", 1.15, 1.25),
    ("매우 어려움", 1.30, 1.50),
    ("불가능", 1.50, 2.00),
]
FOG_MODES = ["없음", "지도 공개", "미탐색"]

# ---------------------------------------------------------------- AI
AI_STRATEGY_PERIOD = 12
AI_WAR_GRACE_TURNS = 12
AI_UTILITY_HORIZON = 24    # 건물: 완공 뒤 (24 - 소요 턴) 동안의 이득으로 평가
AI_ANNEX_HORIZON = 36      # 편입: 영구 영토라 더 길게 본다. 가치가 높을수록 오래 걸려 이득 기간이 줄어든다

SAVE_SLOTS = 3             # 저장 슬롯 수

# ---------------------------------------------------------------- 표시
FACTION_COLORS = ["#2F6FDE", "#D9480F", "#2B8A3E", "#862E9C", "#C2255C",
                  "#E67700", "#0B7285", "#5C940D", "#495057", "#A61E4D"]
REBEL_COLORS = ["#7C5E10", "#5F3DC4", "#1864AB", "#087F5B", "#9C36B5", "#E8590C"]
