"""게임 밸런스 상수 (기획서 3~11절).

플레이테스트 중 조정할 수치는 모두 여기에 모은다. 금액 단위는 만원, 인구 단위는 만 명.
"""

# ---------------------------------------------------------------- 턴·날짜
START_YEAR = 2026
TURNS_PER_MONTH = 4
TURNS_PER_YEAR = 48
RANKING_WEEKS = (0, 24)    # 반기 랭킹 발표: 해마다 1주차·25주차(0부터 센 주차)

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
LEVEL_GROWTH = 0.2         # g(L) = L * (1 + r (L - 1))
FOOD_PER_G = 15            # 농장·바다 어장 식량 15 × 단계(단계에 비례), 산출은 그 10배
FOOD_BUILD_COST_TURN = (200, 400, 600, 800, 1000)   # 농장·어장 단계별 턴당 건설비
FOOD_PER_POP = 1           # 인구 1만 명당 식량 소비/턴
START_FOOD_TURNS = 5       # 시작 식량 = 인구 * 5
COAST_FISH_BONUS = 0.20    # 해안선 점유(해역에 닿는 해안 지역 전부 보유) 시 바다 어장 식량·산출 +20%
COAST_NAVAL_DEF = 0.10     # 해안선 점유 시 그 해역 해전 방어 +10%
RIVER_FISH_MULT = 0.80     # 하천 어장(도하 경계를 가진 내륙 지역): 식량 12×단계(바다 어장 15×단계의 80%)

# 에너지: 공장은 단계 L마다 연료 1개(석탄·석유·전기 무관)까지 받아, 1개당 단계별 산출
FACTORY_UNIT_OUTPUT = (1000, 1200, 1400, 1600, 2000)
POWER_ELEC = {"coal": 2, "oil": 4}   # 발전소: 단계 L마다 연료 1개/턴까지 → 전기
OIL_AS_COAL = 2                      # 석유 1 = 석탄 2 (군 생산 비용 대체 등)
ENERGY = ("oil", "coal", "elec")
UNBUYABLE = ("oil", "coal")          # 돈으로 살 수 없는 자원(판매는 가능). 전기는 시장에서 산다
AUTO_OIL_RESERVE = 6                 # 자동 배정은 군 생산용 석유를 이만큼 남긴다

START_RESOURCES = {"oil": 5, "coal": 10, "elec": 0}   # 식량은 인구 * 5
RESOURCES = ("food", "oil", "coal", "elec")
RESOURCE_NAMES = {"food": "식량", "oil": "석유", "coal": "석탄", "elec": "전기"}
MARKET_BUY = {"food": 4, "oil": 40, "coal": 20, "elec": 20}     # 석유·석탄은 구매 불가(UNBUYABLE)
MARKET_SELL = {"food": 3, "oil": 20, "coal": 10, "elec": 10}
MARKET_STEP = 0.10         # 식량 제외 자원은 같은 턴 1개 살 때마다 +10%
SPECIALTY_VALUE = 20
SPECIALTY_MAX_TYPES = 5
SPECIALTY_HAPPY_TURN = 0.1   # 공급받는 특산물 1종마다 그 지역 행복도 턴당 +0.1
SCENIC_HAPPY = 5             # 자연경관: 그 지역과 같은 나라의 인접 지역 행복도 +5

# ---- 과학승리: 7단계를 차례로 완료한 뒤 세 유닛을 발사대 지역에 모으고 턴을 마치면 승리
# 단계마다 턴당 12만 × 15턴, 비용 배수 ×1.2^tier (tier: 연구소 0 ~ 연료 5)
# 예외: '예산 편성'은 옛 랜드마크와 같은 턴당 10만 × 15턴(배수 없음)
SCIENCE_COST_PER_TURN = 120_000
SCIENCE_TURNS = 15
SCIENCE_COST_GROWTH = 1.2
SCIENCE_STEPS = ("lab", "observatory", "budget", "pad", "booster", "module", "propellant")
SCIENCE = {
    "lab":        dict(name="항공우주연구소", unit=False, where="수도", tier=0),
    "observatory": dict(name="천체관측소", unit=False, where="산맥과 맞닿은 지역", tier=1),
    "budget":     dict(name="예산 편성", unit=False, where="은행 5단계 지역", per_turn=100_000, verb="진행"),
    "pad":        dict(name="로켓 발사대", unit=False, where="바다와 맞닿은 지역", tier=2),
    "booster":    dict(name="로켓 추진체", unit=True, where="공장 5단계 지역", tier=3),
    "module":     dict(name="탑승 모듈", unit=True, where="공장 5단계 지역", tier=4),
    "propellant": dict(name="발사체 연료", unit=True, where="석유 생산 지역", tier=5),
}
SCIENCE_UNITS = ("booster", "module", "propellant")
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
    "specialty": {"name": "특산물 시설", "base": 600, "max": 3},
    "extract":   {"name": "정유·탄광 증설", "base": 2500, "max": 5},
}
PROD_TURNS_PER_LEVEL = 2
# 생산 건물 단계별 이름(행동 탭 '○○ 건설', 완공 알림, 지역 정보)
PROD_LEVEL_NAMES = {
    "farm":    ("텃밭", "경작지", "농장", "대농장", "플랜테이션 농장"),
    "fishery": ("낚시터", "나루터", "소형 포구", "어항", "대형 어항"),
    "factory": ("공방", "작업장", "공장", "대형 공장", "공업 단지"),
    "bank":    ("전당포", "환전소", "은행", "은행 본사", "금융 단지"),
}
POWER_SITE_DISCOUNT = 1.0  # 화력발전소 소재지: 건설비 할인 없음(대신 발전소 1단계로 시작)

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
POP_GROWTH_MIN_H = 5
POP_FOCUS_GROWTH = 0.0025    # 인구 성장 집중: 성장률 턴당 +0.25%p (성장 행복도 5 이상, 건설·생산 중이 아닐 때)
POP_FOCUS_MIN_H = 5
# 과밀: (시작 인구 상한(만), −2 시작 증가율, −4 시작 증가율). 시작 인구 대비 그만큼 늘면 그 지역 행복도 감소
CROWD_TIERS = ((10, 1.00, 1.50), (20, 0.75, 1.00), (40, 0.625, 0.75), (60, 0.50, 0.625), (None, 0.40, 0.50))
CROWD_HAPPY = (-2, -4)
FAMINE_POP = -0.005
MIGRATION_H = -30
MIGRATION_POP = -0.001

HAPPY_MIN, HAPPY_MAX = -100, 100
HAPPY_DECAY = 0.99
TAX_HAPPY_K = 0.1          # 0.1 * (10 - t%)
# 전쟁 피로: 전쟁은 행복도를 직접 깎지 않고, 국가 단위 '전쟁 피로도'(0~200)를 쌓는다.
# 실질 행복도 = 행복도 − 전쟁 피로도 (모든 지역에 고르게). 산출·반란·인구·전투력은 실질 행복도로 판정한다.
# 선전포고: 선포한 쪽 +15, 당한 쪽 +10. 전쟁 중 매 턴 양쪽 모두 +0.5. 전쟁이 없으면 턴당 1 회복.
WAR_WEARY_START = {"aggressor": 15.0, "defender": 10.0}
WAR_WEARY_TURN = {"aggressor": 0.5, "defender": 0.5}
WAR_WEARY_RECOVERY = 1.0
WAR_WEARY_MAX = 200.0
# 불행한 지역의 산출 감소: 행복도 H < 0 이면 산출 × (1 − 0.30 × (−H/100)²). −50에서 −7.5%, −100에서 −30%.
UNHAPPY_OUTPUT_MAX = 0.30
UNHAPPY_OUTPUT_EXP = 2.0
# 사기: 실질 평균 행복도가 −10 이하이면 군 전투력(공격·방어·폭격·해전)도 산출 감소와 같은 곡선으로 줄어든다.
MORALE_H = -10
# 징집 피로: 지역마다 최근 10턴 중 군 유닛 생산에 쓴 턴 수 n. n = 7·8·9·10이면 그 지역 행복도 −(1, 2, 4, 8)
# (6턴 이하는 감소 없음). 감소분은 n이 3 이하로 내려가면 턴당 3씩 빠르게 회복(4~6턴이면 유지).
CONSCRIPT_WINDOW = 10
CONSCRIPT_PENALTY = {7: 1.0, 8: 2.0, 9: 4.0, 10: 8.0}
CONSCRIPT_RECOVER_N = 3
CONSCRIPT_RECOVERY = 3.0
UNIT_START_HAPPY = {"light": -0.5, "heavy": -1.0}
UNIT_DISBAND_HAPPY = {"light": 0.5, "heavy": 1.0}
FAMINE_HAPPY = -5
BOMBED_HAPPY = -2
REBEL_ACCEPT_HAPPY = 20
REBEL_SUPPRESS_HAPPY = 5
REBEL_SUPPRESS_LOSS = 0.10
REBEL_ACCEPT_TURNS = 4     # 요구 수용: 산출 4턴분
REBEL_ACCEPT_TAX_CUT = 0.05
REBEL_THRESHOLD = -50
REBEL_WEARY_MULT = 1.2      # 반란 판정: (선포한 전쟁의) 전쟁 피로를 ×1.2로 반영
# 진압 실패 시 반란 지역이 그 지역을 수도로 하는 새 국가로 독립한다(건물·인구·산출·진행 중 공사 계승).
REBEL_MAX_PER_PARENT = 3   # 한 국가에서 분리독립한 반란 세력(생존) 최대 수. 넘으면 기존 반란 세력에 합류
REBEL_HAPPY_FLOOR_TURNS = 24   # 신생 국가는 이 기간 동안 행복도가 0 아래로 내려가지 않는다
REBEL_SIBLING_OPINION = 40     # 같은 국가에서 독립한 세력끼리: 체제 같거나 유사 +40, 다르면 -40
MAX_FACTIONS = 30          # 안전장치: 세력 수 상한. 넘으면 독립 지역은 중립이 된다

# ---------------------------------------------------------------- 군사 (6절)
# 전투력·체력은 '보병 하나가 아무 보정 없이 보병 하나를 공격할 때의 공격력 / 보병 하나의 체력'을 1/1로 둔 비율을
# 10배로 저장한다(보병 공격 10·체력 10). 화면에는 1/10로 표시한다(UNIT_STAT_SCALE).
# atk: 돌격·조우전 공격력(=방어력 df), bomb: 폭격 피해, hp: 체력. 비용은 턴당 비용 × 턴.
UNIT_STAT_SCALE = 10
UNITS = {
    #        이름      턴당비용 턴 석유 유지 공격 방어 폭격 체력 종류      수송칸
    "inf":  dict(name="보병", cost=250, turns=1, oil=0, upkeep=5, atk=10, df=10, bomb=0, hp=10, kind="land", cargo=1, weight="light"),
    "art":  dict(name="포병", cost=500, turns=2, oil=0, upkeep=20, atk=15, df=15, bomb=15, hp=10, kind="land", cargo=2, weight="light"),
    "tank": dict(name="전차", cost=750, turns=3, oil=1, upkeep=45, atk=20, df=20, bomb=0, hp=50, kind="land", cargo=4, weight="heavy"),
    "lst":  dict(name="상륙함", cost=500, turns=2, oil=1, upkeep=20, atk=0, df=0, bomb=0, hp=20, kind="naval", capacity=8, weight="heavy"),
    "dd":   dict(name="구축함", cost=1000, turns=3, oil=1, upkeep=60, atk=20, df=20, bomb=20, hp=50, kind="naval", weight="heavy"),
    "cv":   dict(name="항공모함", cost=1500, turns=4, oil=2, upkeep=120, atk=0, df=0, bomb=0, hp=100, kind="naval", air_capacity=4, weight="heavy"),
    # 전투기: 공격 불가. 돌격 방어와 폭격기 요격에만 쓰인다(방어 30)
    "ftr":  dict(name="전투기", cost=750, turns=3, oil=1, upkeep=45, atk=0, df=30, bomb=0, hp=30, kind="air", weight="heavy", intercept=30),
    "bmb":  dict(name="폭격기", cost=1000, turns=3, oil=1, upkeep=60, atk=0, df=0, bomb=40, hp=20, kind="air", weight="heavy"),
    # 과학승리 유닛: 전투력 없음, 자국(연합) 영토 안에서만 이동. 생산은 과학 단계(행동 탭 '특수')로만
    "booster":    dict(name="로켓 추진체", cost=0, turns=15, oil=0, upkeep=0, atk=0, df=1, bomb=0, hp=5, kind="land", cargo=4, weight="heavy", science=True),
    "module":     dict(name="탑승 모듈", cost=0, turns=15, oil=0, upkeep=0, atk=0, df=1, bomb=0, hp=5, kind="land", cargo=4, weight="heavy", science=True),
    "propellant": dict(name="발사체 연료", cost=0, turns=15, oil=0, upkeep=0, atk=0, df=1, bomb=0, hp=5, kind="land", cargo=4, weight="heavy", science=True),
}
# 유지비: 모든 유닛이 보병과 같은 (유지비 / 생산비) 비율. 보병 5 / 250 = 2%
UPKEEP_RATIO = UNITS["inf"]["upkeep"] / (UNITS["inf"]["cost"] * UNITS["inf"]["turns"])
for _k, _u in UNITS.items():
    if not _u.get("science"):
        _u["upkeep"] = round(_u["cost"] * _u["turns"] * UPKEEP_RATIO, 2)
def unit_weight(key):
    """대표 병종 고르기용 무게(전투력·생산비 큰 쪽)."""
    u = UNITS[key]
    return u["cost"] * u["turns"] + 1


UNIT_ORDER = ["inf", "art", "tank", "lst", "dd", "cv", "ftr", "bmb", "booster", "module", "propellant"]
BUILD_UNITS = [k for k in UNIT_ORDER if not UNITS[k].get("science")]   # 일반 생산 목록
NAVAL_AT_SEA_UPKEEP = 2.0
ASSAULT_UNITS = ("inf", "tank", "lst")
SURPRISE_UNITS = ("inf", "tank")
ART_RANGE = 2              # 포병 폭격: 육상 2칸(2차 인접)까지
NAVAL_BOMB_RANGE = 2       # 구축함 함포: 해역에서 2칸(해안 지역과 그 인접 지역)까지
BOMB_RANGE = 2             # 폭격기: 공항·항공모함에서 2칸까지
AIR_RANGE = 3              # 공군 재배치(공항 간 이동) 거리
AIR_REBASE_RANGE = 3
NAVAL_STEPS = 1            # 해군: 턴당 한 칸(항구→해역, 해역→해역, 해역→상륙·입항)
LAND_STEPS_OWN = 2

START_MIN_DIST = 6         # 무작위 수도끼리(와 직접 고른 수도) 육상 최단 거리 최소 칸 수
START_PICK_TRIES = 40
START_LINE_LEVEL = 1       # 시작 도시의 모든 경계 방어선 단계(반란국 제외)
LINE_BONUS = 0.30          # 방어선 돌격 방어 x(1 + 0.30L) (단계별 성능 원안 0.25의 1.2배)
# 지형 경계(도하·산악 돌파) 공격 배수는 data/terrain-borders.csv 의 공격배수 열(기본 0.9)을 쓴다.
BRIDGE_ATTACK_MULT = 1.0   # 연륙교는 기획서 2절대로 '육지처럼' 취급(지형 경계에 있으면 그 배수 적용)
FLANK_BONUS = 0.1          # n개 지역 동시 공격 x(1 + 0.1(n-1))
AMPHIBIOUS = 0.8
# 기습: 방어선이 없으면 성공 75%(공격 피해 ×1.2, 반격 ×0.9) / 실패 25%(×0.6, 반격 ×1.2) → 피해 기대값 돌격의 1.05배.
# 방어선 단계 L마다 성공률 −18%p, 실패 시 공격 피해 −6%p·반격 +6%p (돌격은 방어선이 방어력 ×(1 + 0.30L)).
# 방어선 단계별 성능은 3차(−15%p, ±5%p, 0.25L)의 1.2배.
SURPRISE_BASE = 0.75
SURPRISE_PER_LINE = 0.18
SURPRISE_WIN = (1.2, 0.9)      # (공격 피해, 반격)
SURPRISE_FAIL = (0.6, 1.2)
SURPRISE_FAIL_PER_LINE = 0.06
# 돌격에서 방어측이 입은 피해가 공격측보다 크면 25% 확률로 그 경계 방어선 −1단계
ASSAULT_LINE_BREAK = 0.25
DAMAGE_K = 0.5
RAND_LO, RAND_HI = 0.85, 1.15
SHELTER_K = 0.2
# 요격: 폭격당하는 지역의 대공포(단계당 10, 최대 5단계)와 그 지역·인접 지역의 전투기(대당 30)가
# 폭격기에 DAMAGE_K × r × 요격력 만큼 피해를 준다(폭격 전에). 전투기는 반격받지 않는다.
AA_PER_LEVEL = 10
AA_MAX_LEVEL = 5
# 전투기 지상전 지원(방어만): 전투 지역에서 2칸 이내(육상 인접) 자국 공항에 주둔한 전투기는 그 지역의
# 돌격 방어에 대당 30을 더한다. 공격 지원은 없다.
FTR_SUPPORT_RANGE = 2
FTR_SUPPORT_ATK = 0
FTR_SUPPORT_DEF = 30
# 돌격으로 방어측이 입는 피해는 이 순서로 먼저 채운다(전차 > 보병 > 포병 > 공군). 폭격 피해는 모든 부대에 무작위
ASSAULT_DAMAGE_ORDER = ("tank", "inf", "art", "ftr", "bmb")
# 폭격의 건물 피해: 포병(구축함 함포 포함)이 참여하면 30%, 폭격기 60%, 둘 다 90% 확률로
# 대상 지역의 생산·방어 건물(방어선 포함) 중 무작위 하나를 1단계 낮춘다.
BOMB_HIT_GUN = 0.30
BOMB_HIT_AIR = 0.60
BOMB_HIT_BOTH = 0.90
NAVAL_DD_POWER = 20       # 해전: 구축함 공격력
NAVAL_BMB_POWER = 40      # 해전: 항공모함에 실린 폭격기 공격력
CAPTURE_CHANCE = 0.05

# 점령·편입
OCC_MAX_TURNS = 15         # 적 지역 점령 T(P) 상한
# 점령 저항: 다른 세력에게서 빼앗은 지역은 첫 4턴 '저항'(산출 0·생산 불가·행복도 −100 고정),
# 이어서 20턴 동안 점령 직전 행복도로 점차 회복. 점령 후 36턴 동안은 반란이 일어나지 않는다.
# 저항 중에는 그 지역의 원래 주인이 그 지역을 공격할 때 공격력 +10%(비어 있으면 들어서는 즉시 되찾는다).
RESIST_TURNS = 4
RESIST_RECOVER_TURNS = 20
RESIST_NO_REBEL_TURNS = 36
RESIST_HAPPY = -100.0
RESIST_RETAKE_ATK = 0.10
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
OP_HIJACK = -5             # 편입·점령하던 중립 지역을 다른 세력이 가로채면 빼앗긴 AI의 우호도 -5
# 전쟁광 평판: 선전포고하면 대상 외 모든 세력의 우호도 −10. 직전 전쟁(선포했거나, 그 전쟁이 끝난 지)
# 1년 안에 또 선포할 때마다 5씩 더 깎인다(−15, −20, ...).
OP_WARMONGER = -10
OP_WARMONGER_STEP = -5
WARMONGER_WINDOW = 48
OP_GIFT_MAX = 25
# 선물: 받는 나라의 턴당 세수 1턴분마다 우호도 +1(1회 최대 OP_GIFT_MAX).
# 세수는 지난 턴 실제 세수와 GDP × 기준 세율(10%) 중 큰 값(세율을 0%로 내린 나라에 푼돈으로 우호도를 사지 못하게).
GIFT_OP_PER_INCOME = 1.0
OP_DEMAND_ACCEPT = -15
OP_DEMAND_REJECT = -10
OP_TRADE_DONE = 2
OP_WAR_DECLARED = -100
OP_FRIEND_ATTACKED = -10
OP_NONAGGR_BROKEN = -30
OP_HEGEMON_FIGHTER = 0.3
OP_COALITION_LEAVE = -50

# 우호 선언·비난
DECL_COOLDOWN = 24          # 같은 상대에게 다시 쓰려면 24턴
DECL_FRIEND_MIN = -30       # 상대 우호도가 이 이상이면 우호 선언을 받아들인다
DECL_FRIEND_BONUS = 15      # 우호 선언: 서로 24턴 동안 우호도 +15
DECL_FRIEND_TURNS = 24
DECL_FRIEND_ENEMY = -5      # 선언 대상과 적대하는 세력의 선언국에 대한 우호도
DENOUNCE_TARGET = -15       # 비난: 대상의 비난국에 대한 우호도
DENOUNCE_OTHERS = -2        # 비난: 다른 모든 세력의 대상에 대한 우호도
DENOUNCE_WINDOW = 24        # 최근 24턴 안의 비난 횟수
DENOUNCE_SPAM_N = 3         # 그 안에서 3번째부터는 남발: 모든 세력의 비난국에 대한 우호도 −3
DENOUNCE_SPAM = -3
DENOUNCE_ALLY_BONUS = 5     # 2번째까지는 대상과 적대하던 세력의 비난국에 대한 우호도 +5
HOSTILE_OP = -30            # '적대': 전쟁 중이거나 우호도가 이 이하
AI_FRIEND_DECL_P = 0.05     # AI 우호 선언 기본 확률(호전성 0 기준, 호전성 10이면 0)
AI_DENOUNCE_P = 0.04        # AI 비난 기본 확률(호전성 10 기준)
AI_DENOUNCE_PLAYER = 0.5    # 플레이어를 비난할 때는 이 배율(낮은 확률)
AI_FRIEND_BACKLASH_W = 0.4  # 우호 선언 대상 고를 때 '대상과 적대하는 세력' 1곳당 감점

FRIEND_ON, FRIEND_OFF = 30, 20
TREATY_MIN = 45
NONAGGR_FEAR_DISCOUNT = 15  # 상대가 1/0.7배 이상 강해 보이면 불가침 문턱 -15
TREATY_RENEW_MIN = 35
ALLIANCE_MIN = 65
ALLIANCE_LEAVE = 30        # AI 는 우호도가 이 값 이하로 떨어지면 동맹을 파기한다(체결 문턱보다 낮게)
COALITION_MIN = 60         # 동맹 24턴 이상 + 우호도 60 이상이면 연합
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
# 경제승리: 전체 GDP 중 내 몫이 econ_share(시작 국가 수) 이상인 상태로 10턴.
# 8개국 50%, 6개국 60%(= 2위 이하 합의 1.5배): 몫 = 0.9 − 0.05 × 국가 수 (35%~80%)
ECON_SHARE_A, ECON_SHARE_B = 0.9, 0.05
ECON_SHARE_MIN, ECON_SHARE_MAX = 0.35, 0.80
ECON_VICTORY_TURNS = 10
# 정복승리: 전체 지역의 2/3 이상 + 반란이 일어날 수 있는 지역(반란 판정 행복도 −50 이하) 없음
CONQUEST_SHARE = 2 / 3
VICTORY_TYPES = {"conquest": "정복승리", "science": "과학승리", "economic": "경제승리",
                 "diplomatic": "외교승리", "time": "시간 종료 승리"}
# 시간 종료 승리: 정해진 턴(기본 480턴 = 10년, 시작 설정에서 최대 1200턴)이 되면 점수 1위가 승리.
# 점수 = (점유 지역 비율 + GDP 비율 + 인구 비율) / 3 × 100 (살아 있는 세력 전체 대비)
TIME_VICTORY_TURNS = 480
TIME_VICTORY_MIN, TIME_VICTORY_MAX, TIME_VICTORY_STEP = 120, 1200, 24

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

# 지도자 고유 디버프
AMBUSH_TURNS = 4            # 선덕여왕 '대야성 함락': 선전포고를 당한 뒤 방어력 감소 턴
CAPITAL_FALL_TURNS = 8     # 연개소문 '삼형제의 내분': 수도 함락 후 반란 확률 증가 턴
MINORITY_REGIONS = 40       # 홍타이지 '소수민족': 이 수를 넘는 지역마다 행복도 감소
HEAL_RATE = 0.10           # 한 턴 동안 아무것도 하지 않은 부대의 체력 회복(최대 체력 대비)
INDUSTRY_BUILDINGS = ("factory", "extract", "power")   # 공장·정유·탄광·발전소
