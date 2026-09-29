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
COAST_FISH_BONUS = 0.25    # 해안선 점유 시 어장 식량·산출 +25%
COAST_NAVAL_DEF = 0.25     # 해안선 점유 시 그 해역 해전 방어 +25%

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
CAPITAL_MOVE_TURNS = 4
CAPITAL_MOVE_COST_MULT = 20
CAPITAL_MOVE_HAPPY = -3
CAPITAL_LOST_HAPPY = -10
PROJECT_REFUND = 0.5
FOCUS_POP_BONUS = 0.5      # 생산 집중: 건설·병력 생산을 하지 않는 지역의 인구 산출(30P) +50%
DEBT_HAPPY = -1.0          # 보완안: 자금이 음수인 턴에는 전 지역 행복도 -1

# 생산 건물: 단계 L 비용 = base * L^1.5, 소요 2L턴
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
WAR_START_HAPPY = -10
WAR_ONGOING_PERIOD = 5
WAR_ONGOING_HAPPY = -1
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
SURPRISE_BASE = 0.90
SURPRISE_PER_LINE = 0.15   # 원안 '0%까지'는 0.18
SURPRISE_WIN = (1.75, 0.5)     # (공격 피해, 반격)
SURPRISE_FAIL = (0.4, 1.25)
DAMAGE_K = 0.5
RAND_LO, RAND_HI = 0.85, 1.15
SHELTER_K = 0.2
AA_DMG_K = 0.1
AA_SHOOT_K = 0.05
STEALTH_AA_SHOOT = 0.10
STEALTH_AA_DMG = 0.8
INTERCEPT_PER_FIGHTER = 0.3
FIGHTER_LOSS = 0.2
BUILDING_HIT_ART = 0.01
BUILDING_HIT_BMB = 0.03
BUILDING_HIT_MAX = 0.25
NAVAL_DD_POWER = 30
NAVAL_BMB_POWER = 40
CAPTURE_CHANCE = 0.05

# 점령·편입
OCC_MAX_TURNS = 15
INSTANT_ANNEX_H = -50
ANNEX_BASE_COST = 100
ANNEX_COST_PER_POP = 20

# ---------------------------------------------------------------- 외교 (7절)
OPINION_DECAY = 0.99
OP_SAME_ENEMY = 0.5
OP_SAME_FRIEND = 0.3
OP_WAR_WITH_FRIEND = -0.5
OP_FRIEND_OF_ENEMY = -0.3
OP_BORDER_K = 0.2
OP_BORDER_MAX = 2.0
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
TREATY_RENEW_MIN = 35
ALLIANCE_MIN = 65
ALLIANCE_LEAVE = 55
COALITION_MIN = 85
COALITION_ALLIANCE_TURNS = 24
TREATY_TURNS = 24
PEACE_TREATY_TURNS = 24
PEACE_WAR_TURNS = 20
PEACE_VICTORY_TURNS = 24
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

# ---------------------------------------------------------------- 승리 (10절)
ECON_VICTORY_RATIO = 2.0
ECON_VICTORY_TURNS = 10
VICTORY_TYPES = {"conquest": "정복승리", "economic": "경제승리", "peace": "평화승리", "landmark": "랜드마크승리"}

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
AI_UTILITY_HORIZON = 24

# ---------------------------------------------------------------- 표시
FACTION_COLORS = ["#2F6FDE", "#D9480F", "#2B8A3E", "#862E9C", "#C2255C",
                  "#E67700", "#0B7285", "#5C940D", "#495057", "#A61E4D"]
REBEL_COLORS = ["#7C5E10", "#5F3DC4", "#1864AB", "#087F5B", "#9C36B5", "#E8590C"]
