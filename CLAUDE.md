# legalize-pipeline — Project Guidelines

## Repository

- **GitHub**: `legalize-kr/legalize-pipeline`
- **기본 브랜치**: `main`
- **Python**: 3.12+ (type hints: `str | None`, `list[str]`)
- **의존성**: `requests`, `pyyaml`, `python-dotenv`

### 관련 저장소

| 저장소 | 용도 |
|---|---|
| `legalize-kr/legalize-kr` | 법령 데이터 (`kr/{법령명}/*.md`, `metadata.json`) |
| `legalize-kr/legalize-pipeline` | 수집·변환·검증 파이프라인 (이 저장소) |
| `legalize-kr/legalize-web` | 웹사이트 (`legalize.kr`, GitHub Pages) |
| `legalize-kr/compiler` | rebuild용 네이티브 컴파일러 (Rust). `full-laws-import.yml`이 릴리즈 바이너리가 있으면 `laws.rebuild`보다 먼저 사용하고, 없을 때만 Python `rebuild.py`로 폴백 |
| `legalize-kr/precedent-kr` | 판례 데이터 (`{사건종류}/{법원등급}/{사건번호}.md`, `metadata.json`) |

## Directory Structure

```
core/                  # 파이프라인 공통 인프라
  __init__.py          # 패키지 마커
  config.py            # 경로, API 키, rate limit, BOT_AUTHOR
  http.py              # HTTP 요청 (retry, exponential backoff)
  atomic_io.py         # 원자적 파일 쓰기 (tempfile + rename)
  throttle.py          # 스레드 안전 rate limiter
  counter.py           # 스레드 안전 진행 카운터
laws/                  # 법령 파이프라인 (python -m laws.update)
  __init__.py          # 패키지 마커
  config.py            # 법령 전용 설정 (KR_DIR, CHILD_SUFFIXES 등)
  api_client.py        # law.go.kr OpenAPI 래퍼 (search, detail, history)
  cache.py             # 파일 기반 캐시 (detail XML, history JSON)
  checkpoint.py        # 처리 상태 관리 (processed_msts, last_update)
  converter.py         # XML → Markdown 변환 (frontmatter, 조문 파싱)
  git_engine.py        # Git 커밋 (공포일자 기반 historical date)
  fetch_cache.py       # 캐시 수집 (history + detail, 병렬)
  import_laws.py       # 전체 import (API/캐시/CSV 모드)
  rebuild.py           # Git 히스토리 재구성 (orphan branch)
  update.py            # 증분 업데이트 (최근 N일)
  generate_metadata.py # metadata.json, stats.json 생성
  validate.py          # 유효성 검증 (frontmatter, Unicode, 파일 일치)
precedents/            # 판례 파이프라인 (python -m precedents.fetch_cache)
  __init__.py          # 패키지 마커
  config.py            # 캐시 경로, API 설정 (LAW_OC 공유)
  cache.py             # .cache/precedent/{판례일련번호}.xml 캐시 (atomic write)
  api_client.py        # law.go.kr OpenAPI 래퍼 (target=prec)
  fetch_cache.py       # 전체 판례 목록 수집 + 상세 XML 병렬 캐시
  converter.py         # XML → Markdown 변환 (frontmatter, 경로 계산, 충돌 처리)
  import_precedents.py # 캐시 → Markdown 일괄 변환 (병렬 쓰기)
.github/workflows/     # CI/CD (daily-laws-update.yml, daily-precedent-update.yml, full-laws-import.yml)
```

### 런타임 워크스페이스

파이프라인은 `WORKSPACE_ROOT` 환경변수(기본값: 상위 디렉토리)를 법령 데이터 저장소 경로로 사용합니다.
CI에서는 `workspace/` 아래에 데이터 저장소를 체크아웃하고, `workspace/pipeline/`에 이 저장소를 배치합니다.

```
{WORKSPACE_ROOT}/              # legalize-kr/legalize-kr 체크아웃
  kr/{법령명}/                 # 법령 Markdown 파일
  metadata.json                # 법령 인덱스 (자동 생성)
  stats.json                   # 통계 (자동 생성 → legalize-web으로 복사)
  .cache/detail/{MST}.xml              # 법령 API 상세 응답 캐시
  .cache/history/{법령명}.json          # 법령 개정 이력 캐시
  .cache/precedent/{판례일련번호}.xml   # 판례 API 상세 응답 캐시
  .cache/precedent/precedent_ids.json  # 수집된 판례 ID 목록 (collected_at, total, ids)
  .checkpoint.json                     # 법령 처리 상태
```

## Pipeline Architecture

```
law.go.kr OpenAPI
    ↓
laws/api_client.py ──→ laws/cache.py (atomic write via core/atomic_io)
    ↓
laws/converter.py (XML → Markdown + YAML frontmatter)
    ↓
laws/git_engine.py (공포일자 기반 커밋, MST 기반 중복 방지)
    ↓
laws/checkpoint.py (processed_msts 추적)
    ↓
laws/generate_metadata.py (metadata.json + stats.json)
```

#### 판례 변환 파이프라인

```
.cache/precedent/{id}.xml  (precedents/fetch_cache.py로 수집)
    ↓
precedents/converter.py (XML → Markdown + YAML frontmatter, 경로 충돌 처리)
    ↓
precedents/import_precedents.py (단일 스레드 파싱 → 병렬 쓰기)
    ↓
precedent-kr/{사건종류}/{법원등급}/{사건번호}.md
```

> 판례 통계(`precedent-stats.json`)는 저장소 내부에 생성하지 않고, 배포 시점에
> `legalize-web` 내부에서 `precedent-kr` 디렉토리 구조만 스캔하여 직접 생성합니다
> (`.github/workflows/daily-precedent-update.yml`의 `Regenerate precedent-stats.json` 스텝).
> Rust 재구현(`compiler-for-precedent`)과의 동작 일치를 위해 판례 저장소에는
> `metadata.json`/`stats.json`을 더 이상 만들지 않습니다.

### 실행 모드

| 모드 | 엔트리포인트 | 용도 |
|---|---|---|
| 전체 import | `python -m laws.import_laws` | 모든 법령 + 개정 이력 수집 |
| 증분 업데이트 | `python -m laws.update --days 7` | 최근 변경 법령만 |
| 캐시 수집 | `python -m laws.fetch_cache` | API → 로컬 캐시 (병렬) |
| 캐시 import | `python -m laws.import_laws --from-cache` | 캐시 → Markdown (오프라인) |
| CSV import | `python -m laws.import_laws --csv path` | CSV 폴백 (본문 없음) |
| 히스토리 재구성 | `python -m laws.rebuild` | orphan branch, 시간순 커밋 |
| 메타데이터 생성 | `python -m laws.generate_metadata` | `kr/` 스캔 → JSON |
| 유효성 검증 | `python -m laws.validate` | frontmatter, Unicode, 정합성 |
| 판례 캐시 수집 | `python -m precedents.fetch_cache` | API → .cache/precedent/ (병렬) |
| 판례 변환 | `python -m precedents.import_precedents` | 캐시 → Markdown 변환 |

## Configuration

### 환경변수

| 변수 | 용도 | 기본값 |
|---|---|---|
| `LAW_OC` | 국가법령정보센터 OpenAPI 키 | (필수) |
| `WORKSPACE_ROOT` | 법령 데이터 저장소 경로 | 상위 디렉토리 |

### core/config.py 주요 설정

- `REQUEST_DELAY_SECONDS = 0.2` — API 호출 간격 (thread-safe throttle)
- `MAX_RETRIES = 3` — 재시도 횟수 (exponential backoff)
- `CONCURRENT_WORKERS = 5` — 병렬 workers 수
- `BOT_AUTHOR = "legalize-kr-bot <bot@legalize.kr>"` — 자동 커밋 author

## CI/CD

### daily-laws-update.yml (매일 13:00 KST)

1. `legalize-kr/legalize-kr` → `workspace/`
2. `legalize-kr/legalize-pipeline` → `workspace/pipeline/`
3. `legalize-kr/legalize-web` → `docs-repo/`
4. `python -m laws.update` 실행 (7일 lookback)
5. `python -m laws.validate` 실행
6. 데이터 저장소 push
7. `stats.json` → `docs-repo/` 복사 및 push

### full-laws-import.yml (수동 실행)

동일 체크아웃 → 캐시 확인/수집 → compiler 또는 `python -m laws.rebuild` → validate → force push

## Commit Convention

### 법령 커밋 (legalize-kr 저장소, 공포일자를 커밋 날짜로 사용)

```
{법령구분}: {법령명} ({제개정구분})

법령 전문: https://www.law.go.kr/법령/{법령명}
제개정문: https://www.law.go.kr/법령/제개정문/{법령명}/({공포번호},{공포일자})
신구법비교: https://www.law.go.kr/법령/신구법비교/{법령명}

공포일자: YYYY-MM-DD | 공포번호: NNNNN
소관부처: {부처명}
법령분야: {분야}
법령MST: {MST}
```

### 인프라 커밋 (이 저장소)

```
feat|fix|chore|docs|ci: 설명
```

## Key Implementation Details

### 파일 경로 규칙 (laws/converter.py)

- `{법률명} 시행령` → `kr/{법률명}/시행령.md`
- `{법률명} 시행규칙` → `kr/{법률명}/시행규칙.md`
- 접미사 없는 법률 → `kr/{법률명}/법률.md`
- 독립 대통령령 → `kr/{대통령령명}/대통령령.md`
- 경로 충돌 판정 기준: **법령ID** — 같은 법령ID는 부처명이 달라도 동일 법령으로 취급, 항상 같은 파일에 덮어씀
- 진짜 충돌(다른 법령ID가 같은 구조적 경로를 가질 때)만 `시행규칙(총리령).md` 형태 한정자 사용
- **부처명 변경은 경로에 영향 없음** — 경로는 `법령ID`로만 결정, 부처명은 frontmatter에만 기록

### 파편화 마이그레이션 (laws/migrate_ministry_paths.py)

기존 부처명 파편화 파일(예: `시행규칙(안전행정부령).md` + `시행규칙(행정안전부령).md`)을 통합:

```bash
# 현황 확인 (dry-run)
python -m laws.migrate_ministry_paths

# 실제 적용
python -m laws.migrate_ministry_paths --execute

# 본문 차이가 있는 쌍도 강제 통합
python -m laws.migrate_ministry_paths --execute --force-merge-lossy
```

- 같은 `법령ID`를 가진 같은 디렉토리 내 파일들을 `공포일자` 최신 기준으로 통합
- winner(최신)의 본문 분량이 loser의 30% 미만인 쌍은 `REQUIRES_MANUAL_REVIEW`로 표시하고 기본적으로 건너뜀 (개정으로 인한 정상적인 분량 변화는 통과)
- 법령명 변경(다른 디렉토리, 같은 법령ID)은 별도 보고만 함

### Markdown 변환 규칙 (laws/converter.py)

| 법령 구조 | Markdown | 비고 |
|---|---|---|
| 편/장/절/관 | `#` ~ `####` | 조문내용에서 자동 감지 |
| 조 | `##### 제N조 (제목)` | 항상 h5 |
| 항 | `**N** 내용` | 원문자(①②…) 제거 |
| 호 | `  N\. 내용` (2칸 들여쓰기) | escape 처리 |
| 목 | `    가\. 내용` (4칸 들여쓰기) | escape 처리 |
| 부칙 | `## 부칙` 아래 본문 | 공통 들여쓰기 dedent |

### Unicode 정규화

가운뎃점 `·` (U+00B7), `・` (U+30FB), `･` (U+FF65) → `ㆍ` (U+318D)

### 중복 방지

- 커밋 메시지의 `법령MST:` 로 `git log --grep` 검사 (laws/git_engine.py)
- `.checkpoint.json`의 `processed_msts` set (laws/checkpoint.py)
- `laws/update.py`는 checkpoint만 사용 (skip_dedup=True)

### 캐시 안전성

- Atomic write: `tempfile.mkstemp()` → `os.replace()` (core/atomic_io.py)
- Thread-safe throttle: `threading.Lock` (core/throttle.py)
- 긴 파일명: 200바이트 초과 시 SHA256 해시 접미사

### 날짜 처리

- 공포일자 `YYYYMMDD` → `YYYY-MM-DD` 변환 (laws/converter.py)
- 1970-01-01 이전 날짜는 Git epoch 제한으로 1970-01-01로 클램프
- 커밋 시 `+09:00` (KST) 타임존 사용

## 판례 파이프라인

`precedents/` 패키지는 법령과 동일한 국가법령정보센터 API에서 판례(판결문)를 수집하여 캐시합니다.

```bash
# 전체 판례 목록 수집 및 상세 XML 캐시 (최초 실행)
python -m precedents.fetch_cache

# 이전에 수집한 precedent_ids.json 재사용, 목록 재수집 생략
python -m precedents.fetch_cache --skip-list

# 테스트용 (N건만)
python -m precedents.fetch_cache --limit 100

# 병렬 workers 수 조정 (기본값: 5)
python -m precedents.fetch_cache --workers 3
```

> **참고**: 이미 캐시된 항목은 자동으로 건너뜁니다 (모든 실행에서 자동 재개).
> `--skip-list`는 목록 재수집(API 페이지네이션)을 생략할 뿐이며, 상세 XML 캐시 여부와 무관합니다.

**API 엔드포인트**
- 목록: `lawSearch.do?target=prec` (판례 검색, 페이지네이션)
- 본문: `lawService.do?target=prec&ID={판례일련번호}` (판례 전문 XML)

**환경변수**: `LAW_OC` (법령과 동일한 키)

### 판례 파일명 composite grammar (issue #4)

판례 파일은 `{사건종류}/{법원등급}/{COURT}{SEP}{DATE}{SEP}{CASENO}.md` 로 저장됩니다.
하급심 사건번호는 법원별로 발급되어 단일키로는 진정한 unique 가 아니기 때문에
법원명·선고일자·사건번호 합성 키만이 충돌 없이 분리합니다. 단일 진실 원본은
`legalize-pipeline/precedents/converter.py:compose_filename_stem` 입니다.

- 모듈 상단 상수: `SEP = "_"` (single underscore, 가독성 우선),
  `MISSING_DATE_SENTINEL = "0000-00-00"`, `MISSING_COURT_SENTINEL = "미상법원"`,
  `MAX_FILENAME_STEM_BYTES = 180`. `compiler-for-precedent/src/render.rs` 및
  `cli-tools/src/legalize_cli/SEP.py` 와 lockstep 으로 동기화 (3-repo PR 의무).
- `sanitize_case_number` 의 출력에는 `_` 가 정상적으로 포함됩니다 (병합 사건
  `2000나10828_10835_병합` 등). 파일명 파싱은 좌측 anchor 의 `split(SEP, 2)` 로
  수행 — 법원명에는 `_` 가 없고 선고일자는 고정 `YYYY-MM-DD` 포맷이므로 처음 두
  번의 `_` split 이 항상 (법원명, 선고일자) 슬롯을 분리합니다. 이후 잔여 문자열
  전체가 사건번호 슬롯이 됩니다.
- 결측치 정책: 선고일자 누락 → `0000-00-00` (frontmatter 키는 omit 유지),
  법원명 누락 → `미상법원` + CASENO 를 `serial` 로 강제 폴백, 사건번호 누락 → `serial`.
- `cap_caseno_slot` 은 stem byte 길이 초과 시 CASENO 슬롯만 잘라내고 `_{serial}`
  접미사를 붙입니다 — SEP 슬롯은 항상 살아남습니다.
- 사전 게이트: `python -m precedents.preflight_filename_audit --report ...` 로
  N1 (composite collision)·N2 (single-key collision)·SEP 결정·NFC mismatch
  ·cap firing·`판례일련번호` 건전성을 측정. `python -m precedents.dump_oracle
  --output /tmp/oracle.jsonl` 로 Rust 측 byte-equality 검증용 oracle 생성.

### 판례 파일명 capping (`NAME_MAX` 대응)

형사 병합(병합)/분리(분리) 판결은 하나의 판결에 여러 연관 사건이 묶일 때 법원이 모든 사건번호를 쉼표로 연결하여 `사건번호` 단일 필드에 기록한다 (예: `2011고합669, 743, 746, ..., 985-1 (병합) (분리)`). 수십~수백 건이 누적되면 변환된 파일명이 500바이트+가 되어 macOS APFS의 `NAME_MAX=255 bytes` 제한을 넘고, `git checkout` 시 `File name too long` 오류로 작업 트리 체크아웃이 실패한다.

- `precedents/converter.py:cap_filename_bytes(filename, serial)`이 파일명 stem을 UTF-8 기준 **180바이트**로 cap하고, truncation이 일어난 경우 `_{판례일련번호}`를 접미사로 붙인다. UTF-8 문자 경계에서 잘라 깨진 문자를 만들지 않는다.
- `MAX_FILENAME_STEM_BYTES = 180`은 `.md` 확장자와 충돌 해소용 `_{serial}` 접미사(최악의 경우)까지 포함했을 때 255바이트 안에 들어가도록 여유를 둔 값이다.
- `compiler-for-precedent`(Rust 재구현)의 `render.rs:cap_filename_bytes`도 동일 상수·동일 규약을 쓴다. 두 구현의 동등성이 깨지면 재컴파일된 `precedent-kr` 저장소가 API/프론트엔드와 어긋날 수 있으므로 한쪽을 바꿀 때는 양쪽을 같이 바꿔야 한다.
- 업스트림 API가 지나치게 긴 사건번호 나열을 끝에서 `....`로 잘라 보내는 케이스가 있으며(예: `..._초기3461 ....md`), 현재 파이프라인은 이 잘림 흔적을 별도로 정리하지 않고 파일명에 그대로 남긴다.

## API

- **데이터 출처**: [국가법령정보센터 OpenAPI](https://open.law.go.kr)
- **인증**: `LAW_OC` 환경변수 (GitHub Secrets: `LAW_OC`)

## Data Notes

- **다부처 법령**: `소관부처` 필드는 항상 YAML 리스트 형식
- **알려진 제한**: 6개 MST 파싱 불가, 2개 MST 메타데이터 누락 (GitHub Issues 참조)
- **판례 목록/상세 API 불일치 (업스트림)**: `lawSearch.do?target=prec`이 반환하는
  `판례일련번호` 중 약 48,214건(2026-04-09, 전체 171,701건의 약 28%)이
  `lawService.do?target=prec&ID=...`에서 `<Law>일치하는 판례가 없습니다...</Law>`
  응답을 돌려준다. 결정적 업스트림 이슈이며 수집 버그가 아니다. `precedents/api_client.py`
  의 `NoResultError`와 `.cache/precedent/_no_result_ids.txt` 네거티브 캐시로
  격리한다. 기존 잘못된 캐시는 `python -m precedents.cleanup_no_result`로 이관
  가능. 자세한 내용은 루트 `KNOWN_ISSUES.md` §10 참조.

## History Allowlist & Failure Baseline

### full-laws-import.yml 불변성 실패 대응

- 에러 메시지의 stem 이름을 검사합니다.
- Unicode/긴 이름 클래스면 `laws/known_empty_history.yaml`에 추가 (추적 이슈, 3~9개월 만료 설정).
- 회귀 클래스면 pagination/fetch 경로 진단 후 추가합니다.

### daily-laws-update.yml 델타 게이트 실패 (exit 1)

- `::error::` 출력에서 `(mst, reason)` 튜플을 읽습니다.
- 기존 MST의 reason이 변경되면 근본원인 진단 필요 (의미 변경).
- 수정 후: `cp workspace/.failed_msts.json workspace/pipeline/.failure-baseline.json` → pipeline 저장소에 커밋 (legalize-kr 아님).

### 일시적 경고 (::warning::, api_error 24h 내)

- 다음 날까지 지속되지 않으면 조치 불필요.
- law.go.kr 일시적 오류는 예상 잡음입니다.

### allowlist 항목 expiry 임박

- 다음 `fetch_cache` 실행 시 불변성 위반.
- 버그 수정됨 → 항목 제거 또는 만료일 연장 (코드 변경 없는 bump는 안티패턴).

### ::notice::allowlist_orphan

- allowlist stem의 캐시 파일이 없음 → 다음 PR에서 allowlist 항목 제거.

### 기본 규칙

- **기존 실패 분류 후 baseline 갱신**: 현재 실패가 모두 예상 범주에 속함을 확인한 후에만 갱신.
- **파일 위치**: `.failure-baseline.json` → `legalize-pipeline/`; `known_empty_history.yaml` → `legalize-pipeline/laws/`.
- **hash-truncated stem 원래 이름 복구**: `.omc/logs/history-recovery-{date}.txt` 또는 `laws.api_client.search_laws(stem_prefix)`.
- **초기 baseline 시드**: 청정 복구 후 `python -m laws.update --days 7 --dry-run` → `.failed_msts.json` 검사 → `cp` → commit.
- **금지 사항**: 레드 실행에서 baseline 갱신 금지.
