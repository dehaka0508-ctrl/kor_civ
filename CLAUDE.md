# 작업 규칙

- 사용자에게 하는 설명은 모두 한국어로 쓴다.
- 커밋 후 `main`에만 푸시한다(사용자 지시, 2026-10-24).

## 버전 (korciv/version.py)

패치할 때마다 `VERSION`과 `RELEASE_DATE`(패치한 날짜)를 고치고, README 맨 위의 '현재 버전'도 맞춘다.
- 사용자가 "버전업"하라고 하기 전까지는 **세 번째 숫자만** 올린다(아직 사용자가 플레이하지 않은 개발 중 변경이므로,
  밸런스·지역 정보·규칙 수치 변경이어도 마찬가지). README 변경 기록은 지금 두 번째 숫자의 항목에 이어 적는다.
- 사용자가 버전업하라고 하면: 두 번째 숫자 +1, 세 번째는 0. (중대한 업데이트라고 하면 첫 번째 숫자 +1, 나머지 0)
- 배포(deploy)할 때는 그동안의 개발 패치(x.y.1, x.y.2, …)를 x.y.0 하나로 묶어 `VERSION`을 x.y.0으로 맞추고
  README 변경 기록도 x.y.0 항목 하나로 정리한다. 배포 뒤 개발 패치는 다시 x.y.1부터.

## deploy 브랜치

- 평소에는 `main`(과 작업 브랜치)에만 올린다.
- 버전업으로 두 번째(또는 첫 번째) 숫자가 오를 때마다 `deploy` 브랜치를 `main`의 게임 실행 파일로 갱신한다.
  - 배포용이므로 게임 실행에 필요한 것만 넣는다.
  - 넣는 것: `korciv/`(코드·data·assets, `__pycache__` 제외), `requirements.txt`, `run.sh`, `게임실행.bat`.
    글꼴 라이선스(`korciv/assets/fonts/LICENSE-*`)와 `korciv/assets/CREDITS.md`는 글꼴·그림과 함께 배포해야 하므로 넣는다.
  - 빼는 것: `tests/`, `tools/`, `docs/`, `README.md`, `CLAUDE.md`, `.gitignore`, `korciv/assets/portraits/README.md` 등
    게임이 읽지 않는 파일
  - `deploy`는 main 과 따로 이어지는 기록이다. 갱신할 때는 deploy 위에 새 커밋 하나로 파일을 통째로 바꾼다(강제 푸시 없이).
