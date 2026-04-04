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
| `legalize-kr/compiler` | rebuild용 네이티브 컴파일러 (선택) |
| `legalize-kr/precedent-kr` | 판례 데이터 (예정) |

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
.github/workflows/     # CI/CD (daily-update.yml, full-import.yml)
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
  .cache/precedent/all_ids.txt         # 수집된 판례 ID 목록 (--skip-list 재사용)
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

### daily-update.yml (매일 13:00 KST)

1. `legalize-kr/legalize-kr` → `workspace/`
2. `legalize-kr/legalize-pipeline` → `workspace/pipeline/`
3. `legalize-kr/legalize-web` → `docs-repo/`
4. `python -m laws.update` 실행 (7일 lookback)
5. `python -m laws.validate` 실행
6. 데이터 저장소 push
7. `stats.json` → `docs-repo/` 복사 및 push

### full-import.yml (수동 실행)

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
- 경로 충돌 시 `시행규칙(부령).md` 형태로 법령구분 한정자 추가

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

# 이전에 수집한 all_ids.txt 재사용, 목록 재수집 생략
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

## API

- **데이터 출처**: [국가법령정보센터 OpenAPI](https://open.law.go.kr)
- **인증**: `LAW_OC` 환경변수 (GitHub Secrets: `LAW_OC`)

## Data Notes

- **다부처 법령**: `소관부처` 필드는 항상 YAML 리스트 형식
- **알려진 제한**: 6개 MST 파싱 불가, 2개 MST 메타데이터 누락 (GitHub Issues 참조)
