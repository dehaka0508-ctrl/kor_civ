# 작업 규칙

- 사용자에게 하는 설명은 모두 한국어로 쓴다.
- 커밋 후 `main`과 `claude/vibrant-cerf-v4hlfl` 두 브랜치에 푸시한다.

## 버전 (korciv/version.py)

패치할 때마다 `VERSION`과 `RELEASE_DATE`(패치한 날짜)를 고치고, README 맨 위의 '현재 버전'도 맞춘다.
- 사용자가 "버전업"하라고 하기 전까지는 **세 번째 숫자만** 올린다(아직 사용자가 플레이하지 않은 개발 중 변경이므로,
  밸런스·지역 정보·규칙 수치 변경이어도 마찬가지). README 변경 기록은 지금 두 번째 숫자의 항목에 이어 적는다.
- 사용자가 버전업하라고 하면: 두 번째 숫자 +1, 세 번째는 0. (중대한 업데이트라고 하면 첫 번째 숫자 +1, 나머지 0)

## deploy 브랜치

- 평소에는 `main`(과 작업 브랜치)에만 올린다.
- 버전업으로 두 번째(또는 첫 번째) 숫자가 오를 때마다 `deploy` 브랜치를 `main`의 게임 실행 파일로 갱신한다.
  - 넣는 것: `korciv/`(코드·data·assets, `__pycache__` 제외), `requirements.txt`, `run.sh`, `게임실행.bat`, `.gitignore`
  - 빼는 것: `tests/`, `tools/`, `docs/`, `README.md`, `CLAUDE.md`
  - `deploy`는 main 과 따로 이어지는 기록이다. 갱신할 때는 deploy 위에 새 커밋 하나로 파일을 통째로 바꾼다(강제 푸시 없이).
