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
# 단계마다 15턴, 턴당 10만 × 1.1^단계(0부터, 예산 편성 포함 7단계): 10만 → 11만 → 12.1만 → … → 약 17.7만(합계 약 1,423만)
SCIENCE_COST_PER_TURN = 80_000
SCIENCE_TURNS = 15
SCIENCE_COST_GROWTH = 1.1
SCIENCE_STEPS = ("lab", "observatory", "budget", "pad", "booster", "module", "propellant")
SCIENCE = {
    "lab":        dict(name="항공우주연구소", unit=False, where="수도", tier=0),
    "observatory": dict(name="천체관측소", unit=False, where="산맥과 맞닿은 지역", tier=1),
    "budget":     dict(name="예산 편성", unit=False, where="은행 5단계 지역", tier=2, verb="진행"),
    "pad":        dict(name="로켓 발사대", unit=False, where="바다와 맞닿은 지역", tier=3),
    "booster":    dict(name="로켓 추진체", unit=True, where="공장 5단계 지역", tier=4),
    "module":     dict(name="탑승 모듈", unit=True, where="공장 5단계 지역", tier=5),
    "propellant": dict(name="발사체 연료", unit=True, where="석유 생산 지역", tier=6),
}
SCIENCE_UNITS = ("booster", "module", "propellant")
CAPITAL_MOVE_TURNS = 4
CAPITAL_MOVE_COST_MULT = 20
CAPITAL_MOVE_HAPPY = -3
CAPITAL_LOST_HAPPY = -10
CAPITAL_OUTPUT_BONUS = 0.10   # 모든 나라의 수도 산출 +10% (발해 선왕 '5경 분산'은 절반)
HAEDONG_STEP, HAEDONG_MAX = 20, 5   # 발해 선왕 '해동성국': 영토 20곳을 넘을 때마다 전 지역 산출 +2%, 최대 5번(+10%)
HAEDONG_OUTPUT = 0.02
PROVISIONAL_INF = 3            # 김구 '임시정부': 부활할 때 받는 보병
INF_WAVE_MIN = 10             # 마오쩌둥 '국공내전': 한 번의 돌격에 보병 10 이상
TRIBUTE_SPECIALTY = "공물"    # 야율융서 '전연의 맹약' 특산물
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
# 강화 성과: 그 전쟁에서 얻은 지역이 잃은 지역보다 많으면 강화 즉시 피로 −10,
# 처치한 유닛이 처치당한 유닛보다 많으면 또 −10(양쪽 각자 판정)
PEACE_WEARY_TERRITORY = 10.0
PEACE_WEARY_KILLS = 10.0
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
# 10배로 저장한다(보병 공격 10·체력 10). 화면에도 저장값 그대로 표시한다(v1.18.0부터, UNIT_STAT_SCALE은 기준값).
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

START_MIN_DIST = 6         # 무작위 수도끼리(와 직접 고른 수도) 육상 최단 거리 최소 칸 수(5칸 안에 다른 수도 없음)
START_WIDE_DO8 = ("황해", "강원")   # 이 권역의 수도는 다른 수도와 한 칸 더 떨어진다(6칸 안에 다른 수도 없음)
START_PICK_TRIES = 40
# 무작위 시작에서 빼는 무연륙 섬(제주·서귀포·울릉): 플레이어가 직접 골라 도전할 때만 시작할 수 있다
START_NO_RANDOM_ISLAND = True
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
# 선물: 받는 나라의 턴당 세수 1턴분마다 우호도 +3(1회 최대 OP_GIFT_MAX, 소수 둘째 자리 아래 절사).
# 세수는 지난 턴 실제 세수와 GDP × 기준 세율(10%) 중 큰 값(세율을 0%로 내린 나라에 푼돈으로 우호도를 사지 못하게).
# 받는 나라의 호전성(지도자 + 정치체제, 최대 20)이 10보다 1 높을 때마다 −0.05, 낮을 때마다 +0.05.
GIFT_OP_PER_INCOME = 3.0
GIFT_AGGR_BASE = 10
GIFT_AGGR_STEP = 0.05
GIFT_GOV_AGGR_DEFAULT = 5.0   # 철인통치·체제 미정의 정치체제 호전성
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
AI_FRIEND_ENCIRCLE_W = 0.3  # 국경을 맞댄 나라와 우호 선언: 그 밖에 아직 우방이 아닌 이웃 1곳당 가점(포위 방지)
AI_FRIEND_ENCIRCLE_P = 0.1  # 국경을 맞댄 나라가 2곳 넘을 때 1곳당 우호 선언 확률 +10%(최대 +50%)
AI_TRIBUTE_FRIEND_AGGR = 2   # 야율융서: 우호 선언 확률은 호전성 2인 지도자만큼은 된다
AI_TRIBUTE_FRIEND_MULT = 1.5

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
# AI 해군·폭격 성향(v1.32.0: 해역이 잘게 나뉘어도 바다는 육로보다 빠르다)
AI_SEA_REACH = 2            # 상륙·함포 목표: 내 해안 해역에서 해역 두 칸까지(예전 한 칸)
AI_NAVY_P = 0.4             # 전쟁 중 적 해안이 닿으면 매 턴 40%(+ 해군 지도자 성향)는 해군을 원한다(예전 0, 불리·호전형만)
AI_LST_P = 0.4              # 육로로 닿아도 상륙함을 만들 확률(예전 0.15)
AI_LST_PER_REG = 25         # 상륙함 상한 1 + 지역 25곳당 1(예전 40곳)
AI_DD_PER_REG = 30          # 구축함 상한: 상륙함 + 1 + 지역 30곳당 1(적 항구가 없어도 바다로만 닿으면)
AI_BMB_BASE = 2             # 폭격기 상한 2 + 지역 25곳당 1(예전 1 + 40곳당 1)
AI_BMB_PER_REG = 25
AI_BMB_UTIL = 2.1           # 폭격기 생산 효용(예전 1.8), 전투기보다 적으면 폭격기부터
AI_COALITION_WAR_OP = 0     # 연합 회원의 선전포고에 동의: 대상에 대한 우호도가 이 이하(패권국·승리 근접국이면 우호도와 상관없이)
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
AI_WAR_LOSS_K = 3.0        # 선포 판단: 20턴 뒤 행복도로 본 산출·전투력 손실 × 3 감점(−45면 약 0.18)
AI_PEACE_LOSS_K = 3.0      # 강화 판단: 지금 행복도로 본 산출·전투력 손실 × 3 만큼 강화 욕구(−50이면 약 0.23)
AI_UNHAPPY_SHAKY = 2.0     # 적자이거나 군사력이 위협에 못 미치면(나라가 흔들림) 위 두 값 × 2
AI_FILL_SAVINGS = 0.5      # 노는 땅 채우기(2페이즈): 비상금 위 자금의 50%
AI_FILL_NET_TURNS = 12     #   + 남는 순수입 12턴분까지, 새 공사 총비용으로 쓴다(공사가 자금 부족으로 멈추지 않게)
# ---- AI 평시 방어 건설: 우호도가 이 값 이하인 이웃과 맞닿은 지역에, 재정에 따라 확률적으로 방어 건물(같은 단계면 방어선 우선)
AI_DEF_OP = -20
AI_DEF_MAX_LEVEL = 3
AI_DEF_BASE_P = 0.03       # 지역·턴당 기본 확률. 재정 여유(0~1.5)에 따라 최대 +0.09, 적대가 깊을수록 최대 ×2 (최대 0.24)
AI_DEF_WEALTH_P = 0.06
# ---- AI 승리 목표: 1년(48턴)마다 국내 상황·주변 정세로 추구할 승리 조건을 정한다(플레이어에게 보이지 않음)
AI_GOAL_WEIGHT = 0.25      # 목표에 맞는 전략 가중치에 더하는 값(맹목적이지 않도록 작게)
# ---- AI 1페이즈(확장기): 나라마다 맞닿은 빈 땅(중립)이 남아 있는 동안. 넘어가는 시점은 주변 상황으로 정한다
AI_P1_MIN_TURNS = 12          # 최소 체류 턴
AI_P1_MAX_TURN = 96           # 안전장치: 이 턴이 지나면 2페이즈
AI_P1_END_SHARE = 0.10        # 맞닿은 중립 ≤ max(2, 지역 수 × 10%)면 끝
AI_P1_FREE_SHARE = 0.2        # 빈 땅 여유 = 맞닿은 중립 / max(3, 지역 수 × 20%) (최대 1)
AI_P1_FREE_MIN = 3
AI_P1_WAR_PENALTY = 2.0       # 선전포고 점수에서 '빈 땅 여유 × 2.0'을 뺀다(빈 땅부터 먹는다)
AI_P1_PEACE = 0.3             # 전쟁 중이면 강화 욕구 + 빈 땅 여유 × 0.3(빨리 끝내고 확장으로)
AI_P1_DEFICIT_PROD = 2.0      # 이번 턴 예상 수지(세수 − 유지비 − 진행 중 공사비)가 적자면 생산 건물 가치 ×2
AI_P1_DEFICIT_ANNEX = 0.6     # 그동안 편입 가치 ×0.6
AI_P1_INTERIOR_PROD = 1.2     # 생산 건물은 편입할 곳이 없는 안쪽 지역 먼저(×1.2), 맞닿은 중립이 있는 지역은 ×0.8
AI_P1_FRONTIER_PROD = 0.8
PROD_PAYBACK_KEYS = ("farm", "fishery", "factory", "bank", "extract", "power", "port")   # 재정을 늘리는 건물
# ---- AI 2페이즈(경쟁기): 6턴마다 종합 판단으로 승리 방향을 고르고(관성), 매 턴 태세(위기·경계·평시)와 우방을 갱신
AI_P2_EVAL_TURNS = 6          # 승리 방향 재검토 주기(선전포고를 받거나 위기에 빠지면 바로)
AI_P2_MIN_DWELL = 24          # 방향을 바꾼 뒤 이 기간은 정기 재검토로 다시 바꾸지 않는다
AI_P2_SWITCH = 1.25           # 새 방향 점수가 지금 방향의 1.25배를 넘어야 바꾼다
AI_P2_MIN_SCORE = 0.05        # 지금 방향 점수가 이보다 낮으면(사실상 불가능) 바로 바꾼다
AI_P2_NOISE = 0.05            # 점수 흔들기 ±5%(같은 조건의 나라들이 모두 같은 길로 가지 않게)
AI_P2_LOG = 30
AI_P2_AGGR_MEMORY = 96        # 최근 이 턴 안에 선전포고한 나라는 '호전적'으로 본다(관측)
AI_P2_CRISIS_LOST = 0.20      # 위기: 한 전쟁에서 영토 20% 이상 상실
AI_P2_CRISIS_HAPPY = -45      # 위기: 실질 평균 행복도 −45 미만(반란 직전)
AI_P2_DEFEND_T = 1.2          # 경계: 위협도 1.2 이상인 이웃
AI_P2_ATTACKED_RATIO = 1.25    # 선전포고를 받았을 때 내 전력이 상대의 1.25배 미만이면 경계
AI_P2_MIL_OK = 0.8            # 경계 중 내 군사력이 국경 너머 위협 전력의 80% 이상이어야 과학·경제 단계를 새로 시작
AI_P2_SCI_GEO = 0.024        # 과학 조건: 해안·산맥 가점(거의 모든 나라에 있어 작게, 예전 0.12의 20%)
AI_P2_SCI_OIL = 0.125        # 과학 조건: 석유 보유 가점(석유가 흔해 v1.31.0에서 0.25의 절반)
AI_P2_ETA_W = 0.25           # 승리 방향 점수 × (1 + 0.25 × (300 − 남은 턴)/300), ×1.0~1.25: 빨리 끝낼 수 있는 길에 조금 더(감점은 없음, v1.33.0)
AI_P2_ETA_REF = 300
AI_P2_ETA_MIN = 1.0
AI_P2_ETA_MAX = 1.25
AI_P2_ECON_RANK_BASE = 0.3   # 경제 조건 × (0.3 + 1.0 × GDP 순위 계수): 돈만 있으면 된다. 반기 랭킹 1위 ×1.3 → 꼴찌 ×0.3
AI_P2_ECON_RANK_K = 1.0      #   (예전 '모아 둔 돈' 가점은 잔고 대신 이 순위 배수로)
AI_P2_ECON_BANK_CAP = 0.12   # 경제 조건: 수도 2칸 안에 은행 3단계 이상(v1.32.0: 4단계 0.10 → 3단계 0.12, 과학의 은행 가점 0.08보다 크게)
AI_P2_ECON_BANK_LV = 3
AI_P2_ECON_RICH = 1.25       # GDP 1~2위가 다음 경제 단계를 감당할 수 있으면 경제 점수 ×1.25
AI_P2_ECON_RICH_NET = 0.5    # 감당 가능: 순수입(세수 − 유지비)이 다음 단계 턴당 비용의 50% 이상
# 방향별 돈 쓰기: 과학·경제 단계는 그 방향일 때만 짓는다. 정복 방향은 여윳돈을 병력에, 외교 방향은 선물에 쓴다.
AI_P2_ECON_BEHIND_K = 0.5   # 나보다 GDP가 높고 경제 단계도 앞선 나라가 있으면 경제 점수 × exp(−0.5 × (단계 차 + GDP 배수 − 1))
AI_SCI_START_TURNS = 3      # 과학 방향: 잔고가 턴당 비용 3턴분이면 단계 착수(모자라면 멈췄다 이어서)
AI_P2_SCI_EARLY = 1.8       # 과학 조건 완비(산지·해안·석유·공장 4단계): 과학 점수 × 가중치, 착수 판단은 경계 중에도 군사력이
                            #   필요량의 1/가중치 이상이면, 잔고는 턴당 비용 2/가중치 턴분이면 시작(30판씩 돌려 맞추는 값)
AI_SCI_UNIT_BOMB = 6           # 폭격 대상 가치: 보이는 적 과학 유닛(추진체·탑승 모듈·발사체 연료) 1개당 +6(병력 공격력 합·건물 단계×2와 비교, 낮은 적극성)
AI_ECON_TOP_PROD = 1.5      # GDP 1위 경제 방향: 공장·은행 가치 ×1.5 더(턴당 수입을 빨리 늘린다)
AI_P2_CONQ_RICH_TURNS = 20   # 정복 여윳돈 계수 = (잔고 − 비상금) / (세수 20턴분 + 비상금 4배), 0~1
AI_P2_CONQ_MIL = 0.3         # 바라는 병력 × (1 + 0.3 × 여윳돈 계수)
AI_P2_CONQ_TANK = 0.5        # 전차 확률 × (1 + 0.5 × 여윳돈 계수)
AI_P2_CONQ_UPKEEP = 0.3      # 정복 방향 군비: 군 유지비가 세수의 30%가 될 때까지 턴마다 전차·포병을 더 뽑는다
AI_P2_CONQ_EXTRA = 2         #   한 턴에 2 + 지역 30곳당 1개까지(여윳돈 계수가 0보다 클 때)
AI_P2_CONQ_AIR = 0.5         # 여윳돈 계수 0.5 이상이면 평시에도 공항·전투기·폭격기를 갖춘다
AI_P2_POOR_SCI = 0.15       # GDP 하위권(하위 절반, 꼴찌 1): 과학·경제 점수 × (1 − 0.15 × 하위 정도)
AI_P2_POOR_DIP = 0.5        #   외교 점수 × (1 + 0.5 × 하위 정도)
AI_POOR_FRIEND = 0.3        #   우호 선언 확률 × (1 + 0.3 × 하위 정도)
AI_P2_ANCHOR_BORDERS = 2      # 국경을 맞댄 나라가 2곳 이상이면(강약·위협과 상관없이) 우방을 둔다: 적에게 둘러싸이지 않는 것 자체가 이득
AI_P2_ANCHOR_OP = 0.5         # 우방으로 정한 나라에 대한 내 우호도 +0.5/턴(관계를 맺기로 한 결정)
AI_P2_ANCHOR_MIN_OP = -50     # 나를 이보다 싫어하는 이웃은 다른 후보가 있으면 우방으로 고르지 않는다
AI_P2_GIFT_EVERY = 4          # 우방 선물 간격(턴)
AI_P2_GIFT_SHARE = 0.4        # 선물은 비상금 위 자금의 40%와 순수입 6턴분 중 작은 값까지
AI_P2_GIFT_NET = 6
AI_P2_GIFT_MARGIN = 5         # 우방의 나에 대한 우호도를 불가침 문턱 + 5까지 올린다
AI_P2_TWO_FRONT_T = 0.8       # 새 전쟁 금지: 상대 말고 위협도 0.8 이상이고 불가침·동맹이 없는 이웃이 있으면
AI_P2_TWO_FRONT_RATIO = 2.5   # (상대보다 2.5배 이상 강하면 예외)
AI_P2_MASS = 1.3              # 새 전쟁 금지: 상대가 국경에 내 국경 병력의 1.3배 넘게 모았으면
AI_P2_MASS_RATIO = 2.0        # (전체 전력이 2배 이상이면 예외)
AI_P2_PATH_WAR = 0.3          # 정복 방향이면 선전포고 점수 +0.3, 다른 방향이면 −0.4
AI_P2_OTHER_WAR = -0.4
AI_P2_CRISIS_PEACE = 0.5      # 위기면 강화 욕구 +0.5
AI_P2_NONCONQ_PEACE = 0.15    # 정복 방향이 아니면 강화 욕구 +0.15
AI_P2_CRISIS_PROD = 0.3       # 위기: 생산 건물 가치 ×0.3, 편입 ×0.5(돈은 군사로), 과학·경제 단계 착수 중지
AI_P2_CRISIS_ANNEX = 0.5
AI_P2_DEFEND_PROD = 0.8       # 경계: 생산 건물 가치 ×0.8
# 어느 쪽도 유리하지 않은 나라(외교를 뺀 세 방향 최고점 < 0.18(v1.23.0, 점수식 변경에 맞춰 0.25에서 조정), 판단의 하위 약 10%)는 자포자기하지 않고 외교승리를 노린다:
# 만나 본 나라 중 군사적으로 가장 강한 나라(전쟁 중이 아닌, 동맹이 가능한)를 '의지할 강국'으로 정해
# 우호 선언 → 조약 → 동맹 → 연합까지 우호도를 끌어올린다(내 우호도 +0.8/턴, 선물). 최소 48턴 뒤, 최고점이 0.18×1.25를 넘으면 벗어난다.
AI_P2_HOPELESS = 0.18
AI_P2_HOPELESS_EXIT = 1.25
AI_P2_PATRON_OP = 0.8
AI_P2_PATRON_GIFT_SHARE = 0.5   # 강국 선물은 비상금 위 자금의 50%와 순수입 8턴분 중 작은 값까지. 위기면 선물하지 않고,
AI_P2_PATRON_GIFT_NET = 8       # 경계면 군사력이 충분할 때만(살아남는 게 먼저)
AI_P2_HOPELESS_MIN = 48       # 강국에 기대기로 했으면 최소 48턴은 외교에 전념(관계를 쌓을 시간)
AI_P2_POSTURE_W = {"crisis": {"military": 1.0, "defense": 1.0, "economy": -0.6, "expansion": -0.5},
                   "defend": {"military": 0.5, "defense": 0.5, "economy": -0.2}}
AI_P1_STACK = 3               # 빈 땅 무력 점령 부대: 보병 3개 이상 모이면 출발(중립 수비대는 보병 1)
# ---- AI 3페이즈(결승기): 노리는 승리 조건이 눈앞에 보이면
AI_P3_CONQ_K = 2.0            # 정복: 전체 지역의 2/시작 국가 수(8개국 25%) 이상
AI_P3_SCI_STEPS = 3           # 과학: 3단계 완료
AI_P3_ECON_STAGE = 2          # 경제: 2단계 완료(금융 권역 + 증권거래소 3곳)
AI_P3_EXIT = 0.8              # 정복 3페이즈는 지역이 문턱의 80% 아래로 줄면 2페이즈로
AI_P3_EVAL_TURNS = 6          # 6턴마다 승리까지 남은 턴(ETA)을 다시 비교
AI_P3_NET_RATE = 0.05         # ETA 어림: 순수입 ≈ GDP × 5%
AI_P3_CLUSTER_TURNS = 30      # 경제 ETA: 금융 권역이 아직 없으면 +30턴
AI_P3_MIN_RATE = 0.05         # 정복 ETA: 턴당 지역 증가가 이보다 느리면 '가망 없음'
AI_P3_TOL = 0.2               # 내 ETA 가 다른 나라 가장 빠른 ETA 의 1.2배 안이면 '가장 유리' → 질주
AI_P3_SPRINT_WAR = 0.5        # 정복 질주: 선포 점수 +0.5
AI_P3_SPRINT_NEED = 0.2       # 정복 질주: 필요 전력비 −0.2
AI_P3_SPRINT_PEACE = 0.3      # 정복 질주: 강화 욕구 −0.3(위기가 아니면)
AI_P3_SITE_WAR = 0.6          # 과학 질주: 다음 단계 땅(산맥·해안·석유)을 가진 이웃에 선포 점수 +0.6
AI_P3_SPRINT_MIL = 1.3        # 질주(과학·경제): 원하는 병력 ×1.3(지키기)
AI_P3_SPRINT_MIL_CONQ = 1.5   # 정복 질주: 원하는 병력 ×1.5
AI_P3_SPRINT_START = 2.0      # 질주: 승리 조건 단계는 턴당 비용 2턴분만 있어도 착수(멈추면 다음에 이어서)
AI_P3_SPRINT_KEEP = 6         # 질주: 노는 땅 채우기 예산에서 승리 조건 공사 6턴분은 남긴다
AI_P3_SPRINT_DEF_LV = 4       # 질주: 국경·해안 방어 시설 4단계까지
AI_P3_SPRINT_GARRISON = 2     # 질주: 수도 최소 방위군 +2
AI_P3_URGENT_ETA = 150       # 견제 위급도: 나보다 앞선 나라의 ETA 가 150턴 → 0, 0턴 → 1(6턴마다 다시 계산)
AI_P3_HARASS_MIN = 0.2        # 위급도 0.2 이상이면 그 나라를 견제
AI_P3_HARASS_WAR = 1.0        # 견제: 이웃이면 선포 점수 + 1.0 × 위급도, 필요 전력비 − 0.3 × 위급도
AI_P3_HARASS_NEED = 0.3
AI_P3_HARASS_RATIO = 0.6      # 견제 선포: 그 나라와 이미 싸우는 나라들 힘(×0.5)을 합쳐 상대의 0.6배 이상이면(이길 필요는 없다)
AI_P3_HARASS_RATIO_FAR = 0.3  # 국경이 닿지 않고 바다·하늘로만 닿으면 0.3배(반격이 어렵다)
AI_P3_HARASS_BREAK = 0.6      # 위급도 0.6 이상이면 불가침을 깨고서라도 견제(강화 직후 불가침은 못 깬다)
AI_P3_HARASS_PEACE = 0.2      # 견제 전쟁: 강화 욕구 − 0.2 × 위급도(위기가 아니면)
AI_P3_HARASS_MIL = 0.5        # 견제: 군사 가중치 + 0.5 × 위급도(내정은 그대로 병행)
AI_P3_HARASS_CV = 1.5         # 항공모함은 낮은 가중치(효용 1.5 × 위급도, v1.32.0: 1.0 → 1.5)
AI_P3_HARASS_OP_K = 0.4       # 견제 위급도 × (1 − 0.4 × 우호도/100): 좋아하는 나라는 덜, 싫어하는 나라는 더(v1.33.0)
AI_P3_HARASS_P_K = 1.3        # 견제 선포 확률 = 위급도 × 1.3(최대 1). 선포 점수·군사 가중치는 위급도 × (1 + 위급도)로 가파르게
AI_P3_HARASS_RATIO_URG = 0.4  # 견제 선포에 필요한 합산 전력비 × (1 − 0.4 × 위급도): 임박할수록 덜 따진다
AI_P3_LEAD_GUARD = 2          # 우세한 나라(질주 중): 승리 거점 수비대 + 2 × 수비 강도
AI_P3_LEAD_PATROL = 0.3       # 수비 강도 0.3 이상이면 해안 거점 앞바다에 구축함을 띄운다
AI_P3_PATRON_CONQ = 0.5       # 외교: 의지할 강국은 정복을 노리는 나라를 ×1.5로 친다
AI_P3_PATRON_SWITCH = 0.7     # 외교 3페이즈: 지금 강국이 정복을 노리지 않고, 정복을 노리는 나라가 그 0.7배 이상 강하면 바꾼다(같은 연합이면 그대로)
AI_P3_RECRUIT_MIN_OP = -10    # 연합에 끌어들일 나라: 강국이 그 나라를 이보다 싫어하면 제외
AI_P3_RECRUIT_OP = 0.4        # 끌어들일 나라에 대한 내 우호도 +0.4/턴(선물은 강국 다음)
AI_P3_DYING_REGIONS = 10      # 편승 참전: 강국에게 땅을 잃고 있거나 지역 10곳 이하로 줄어든 이웃
AI_P3_DRAG_P = 0.5            # 강국 끌어들이기: 6턴마다 50%
AI_P3_DRAG_RATIO = 0.6        # 강국 끌어들이기: 강국 군사력의 0.6배 이하인 나라
AI_P3_CONQ_CONSENT = 1.2      # 연합 동의: 정복을 노리는 나라는 맞닿은 나라가 자기보다 1.2배 이상 약하면 동의
AI_P3_SPOILS = 1.5            # 편승: 강국과 싸우는 나라의 땅을 빼앗는 공격 가치 ×1.5
AI_P3_PATRON_WARM = 1.0       # 정복을 노리는 강국은 자기에게 기대는 나라에 대한 우호도 +1.0/턴(받아준다)
AI_P3_KEY_ATK = 1500          # 견제 전쟁 지상 공격: 승리 거점(가치 v, 거리 d) 쪽 지역을 빼앗는 공격 가치 + 1500 × v / (1 + d)
AI_KEY_GUARD = 2              # 승리 거점(발사대·경제 시설·공사 중) 최소 수비대(위협 0.5 이상 +2, 견제를 받으면 +1)
AI_KEY_SHELTER = 2            # 승리 거점 방공호 목표 단계(전쟁 중·견제를 받으면 +1, 방공호 2단계부터 대공포 2단계까지)

# ---------------------------------------------------------------- 승리 (10절)
# 경제승리(기축통화): ① 수도를 포함해 서로 맞닿은 한 덩어리의 금융 단지(은행 5단계) 5곳 →
# ② 금융 권역에 증권거래소(수도 포함 3곳) → ③ 수도에 경제특구 → ④ 경제특구 + 우호 선언 이상 관계 2개국이면
# 증권거래소가 있는 지역에 국제금융센터 → ⑤ 국제금융센터 + 우호 선언 이상 3개국(그중 동맹 1곳 이상)이면
# 수도에서 기축통화 지정. 완공하면 승리. 건물은 유닛 없이 지역에 남고, 점령당하면 사라진다.
ECON_CLUSTER = 5
ECON_EXCHANGES = 3
ECON_IFC_FRIENDS = 2
ECON_CURRENCY_FRIENDS = 3
ECON_CURRENCY_ALLIES = 1
ECON_STEPS = ("exchange", "sez", "ifc", "currency")
ECON = {
    "exchange": dict(name="증권거래소", where="금융 권역", per_turn=150_000, turns=10),
    "sez":      dict(name="경제특구", where="수도", per_turn=200_000, turns=15),
    "ifc":      dict(name="국제금융센터", where="증권거래소가 있는 지역", per_turn=300_000, turns=15),
    "currency": dict(name="기축통화 지정", where="수도", per_turn=400_000, turns=20),
}
ECON_STAGES = 5                # 진척도 n/5: 금융 권역, 증권거래소 3곳, 경제특구, 국제금융센터, 기축통화
EXCHANGE_BANK_BONUS = 0.10     # 증권거래소: 그 지역 은행 산출 +10%
IFC_GIFT_BONUS = 0.10          # 국제금융센터: 내 선물이 올리는 우호도 +10%
ECON_PAUSE_REFUND = 0.5        # 건설 중 조건이 깨지면 중단하고 낸 돈의 50% 환급(진행도는 사라져 처음부터 다시)
LOST_PROJECT_REFUND = 0.5      # 점령으로 멈춘 과학·경제 공사: 저항·회복 기간 안에 되찾으면 이어서, 못 되찾으면 낸 돈의 50% 환급
# 승리에 가까워지는 나라 견제(패권 견제와 같은 방식): 과학·경제 진척이 절반을 넘으면 0 → 완성 직전 1.
# 우호 선언·조약·동맹 관계가 없는 AI는 그 나라에 대한 우호도가 매 턴 최대 −0.3, 선전포고 문턱이 최대 +15 쉬워진다.
VICTORY_THREAT_FROM = 0.5
VICTORY_THREAT_OP = 0.3
VICTORY_THREAT_WAR = 15
VICTORY_THREAT_SCORE = 0.3     # 전쟁 대상 고를 때 점수 가산(최대)
# AI가 경제승리를 목표로 삼으면: 생산 건물(공장·은행) 증축 가치 ×1.3, 연료(광산·유전·발전소) ×1.5,
# 다음 경제 단계 비용을 모을 때까지 다른 공사에는 순수입의 절반만 쓰고(비축을 헐지 않음), 세율 상한 +2%p
AI_ECON_PROD_MULT = 1.3
AI_ECON_FUEL_MULT = 1.5
AI_ECON_SAVE_SPEND = 0.5
AI_ECON_TAX_BONUS = 0.02
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
