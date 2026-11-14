# legalize-pipeline

한국 법령 및 판례 데이터를 수집·변환·검증하는 파이프라인입니다.

> 이 저장소는 [`legalize-kr/legalize-kr`](https://github.com/legalize-kr/legalize-kr)(법령 데이터), [`legalize-kr/precedent-kr`](https://github.com/legalize-kr/precedent-kr)(판례 데이터), [`legalize-kr/legalize-web`](https://github.com/legalize-kr/legalize-web)(웹사이트), [`legalize-kr/compiler`](https://github.com/legalize-kr/compiler)(법령 컴파일러, Rust)와 함께 사용됩니다.

## 패키지 구조

| 패키지 | 설명 |
|--------|------|
| `core/` | 공유 인프라 (HTTP, 스로틀, 원자적 I/O, 카운터) |
| `laws/` | 법령 수집·변환·검증 파이프라인 |
| `precedents/` | 판례 수집 파이프라인 |
| `images/` | 법령 이미지 추출·다운로드 파이프라인 |

자세한 사용법은 각 패키지의 README를 참조하세요.

## 빠른 시작

### 1. 설정

```bash
pip install -r requirements.txt
```

환경 변수 `LAW_OC`에 [국가법령정보센터 OpenAPI](https://open.law.go.kr) 키를 설정합니다:

```bash
export LAW_OC=your-openapi-key
```

또는 `.env` 파일을 생성합니다:

```
LAW_OC=your-openapi-key
```

### 2. 법령 파이프라인

#### 전체 import (최초)

```bash
# 모든 법령
python -m laws.import_laws

# 특정 유형만 (예: 법률)
python -m laws.import_laws --law-type 법률

# 미리보기
python -m laws.import_laws --limit 10 --dry-run

# CSV 파일에서 (API 키 없이)
python -m laws.import_laws --csv /path/to/법령검색목록.csv
```

#### 캐시 수집 (병렬)

```bash
# 모든 현행 법령 + 명시 seed 법령의 상세 XML/개정 이력 캐시
python -m laws.fetch_cache --refresh-history --history-name-file laws/data/history_seed_names.txt

# 워커 수 조절
python -m laws.fetch_cache --refresh-history --history-name-file laws/data/history_seed_names.txt --workers 10

# 테스트 (10건)
python -m laws.fetch_cache --limit 10
```

#### 캐시에서 import (오프라인)

```bash
# API 호출 없이 캐시 사용
python -m laws.import_laws --from-cache
```

#### 증분 업데이트 (일일)

```bash
# 최근 14일
python -m laws.update

# 최근 30일
python -m laws.update --days 30
```

#### 메타데이터 재생성

```bash
# kr/ 스캔 → metadata.json + stats.json
python -m laws.generate_metadata
```

#### 검증

```bash
# YAML frontmatter, Unicode, 정합성 검증
python -m laws.validate
```

#### Git 히스토리 재구성

```bash
# 미리보기
python -m laws.rebuild --infra-date "2026-03-30T12:00:00+09:00" --dry-run

# 실행 (~3시간)
python -m laws.rebuild --infra-date "2026-03-30T12:00:00+09:00"
```

### 3. 판례 파이프라인

#### 판례 수집

```bash
# 전체 판례 수집
python -m precedents.fetch_cache

# 이전 목록 재사용
python -m precedents.fetch_cache --skip-list

# 테스트 (100건)
python -m precedents.fetch_cache --limit 100

# 워커 수 조절
python -m precedents.fetch_cache --workers 3
```

### 4. 이미지 파이프라인

```bash
# 이미지 추출
python -m images extract

# 이미지 다운로드
python -m images download

# 리포트 생성
python -m images report

# 자세한 내용은 images/README.md 참조
```

## 캐시 구조

```
LEGALIZE-KR-WORKSPACE-ROOT/
  legalize-pipeline/              # 이 저장소
  legalize-kr/
    kr/{법령명}/                  # 법령 Markdown 파일
    metadata.json                 # 법령 인덱스 (자동 생성)
    stats.json                    # 통계 (자동 생성)
  precedent-kr/                   # 판례 Markdown 저장소
  admrule-kr/                     # 행정규칙 Markdown 저장소
  ordinance-kr/                   # 자치법규 Markdown 저장소
  legalize-web/                   # 웹사이트 저장소
  .cache/
    detail/{MST}.xml              # 법령 상세 API XML
    history/{법령명}.json         # 법령 개정 이력
    precedent/{판례일련번호}.xml  # 판례 상세 API XML
    admrule/{행정규칙일련번호}.xml  # 행정규칙 연혁 상세 XML
    ordinance/{자치법규ID}.xml          # 기존 현행 자치법규 상세 XML
    ordinance/history/{자치법규일련번호}.xml  # 자치법규 연혁 상세 XML
    ordinance/ordinance_history_entries.json  # nw=2 전체 연혁 목록
    ordinance/_no_result_serials.txt    # 상세 API가 404를 반환한 연혁 일련번호
    images/                       # 이미지 캐시
    .checkpoint.json              # 법령 처리 상태
    .failed_msts.json             # 법령 실패 ledger
```

> **참고**: `WORKSPACE_ROOT`는 메타 워크스페이스 루트입니다. 법령 저장소는
> 기본적으로 `WORKSPACE_ROOT/legalize-kr`, 공유 캐시는 `WORKSPACE_ROOT/.cache`를
> 사용합니다. CI에서는 `LEGALIZE_CACHE_DIR` secret으로 주입된 영속 캐시 경로를
> `WORKSPACE_ROOT/.cache`에 심볼릭 링크합니다.

## 캐시 다운로드

사전 수집된 캐시 데이터는 [`legalize-kr/legalize-pipeline` 릴리즈 페이지](https://github.com/legalize-kr/legalize-pipeline/releases)에서
`cache-YYYYMMDD.tar.zst.part*` 형태의 분할 압축 파일로 배포됩니다.

```bash
# 메타 워크스페이스 루트에서 모든 part 파일을 받은 뒤
cat cache-YYYYMMDD.tar.zst.part* | zstd -d --long=27 -T0 | tar -xf -
# .cache/detail, .cache/history, .cache/precedent, .cache/admrule, .cache/ordinance, .cache/images가 생성됩니다
```

그 후 이 저장소를 체크아웃:

```bash
git clone https://github.com/legalize-kr/legalize-pipeline.git legalize-pipeline
```

## Markdown 변환 규칙

법령 상세 API XML은 다음과 같은 계층 구조를 가집니다:

```
<법령>
  ├── 메타데이터
  ├── 조문단위[]
  │   ├── 조문번호, 제목, 내용
  │   └── 항[]
  │       ├── 항번호, 항내용
  │       └── 호[]
  │           ├── 호번호, 호내용
  │           └── 목[] (하위 구조 없음)
  └── 부칙단위[]
```

Markdown 변환 규칙:

| 구조 | Markdown | 비고 |
|------|----------|------|
| 편/장/절/관 | `#` ~ `####` | 자동 감지 |
| 조 | `##### 제N조 (제목)` | 항상 h5 |
| 항 | `**N** 내용` | 원문자 제거 후 볼드 |
| 호 | `  N. 내용` (2칸) | 순서목록 방지 |
| 목 | `    가. 내용` (4칸) | 순서목록 방지 |
| 부칙 | `## 부칙` | 별도 섹션 |

### 텍스트 정규화

- **가운뎃점**: `·` (U+00B7), `・` (U+30FB), `･` (U+FF65) → `ㆍ` (U+318D)
- **공포일자**: `YYYYMMDD` → `YYYY-MM-DD`
- **공백**: 연속 공백·탭 → 단일 공백

## 중복 방지

같은 법령이 여러 번 처리되는 것을 방지합니다:

- **Git grep**: `git log --grep=법령MST:{id}` 검사
- **Checkpoint**: `.cache/.checkpoint.json` 추적
- **Update 모드**: checkpoint만 사용

## 병렬 처리

- Thread-safe throttle로 API rate limit 관리 (기본 0.2초 간격)
- 기본 5개 워커로 병렬 다운로드
- Atomic write (tempfile → rename)로 파일 안전성 보장
- 실패 재시도는 지수 백오프 (2, 4, 8초…)
- XML 요청에 HTTP 200 HTML 점검 페이지가 반환되어도 같은 백오프로 재시도합니다.
  재시도 후에도 복구되지 않으면 `HTML instead of XML (possible service maintenance)` 오류로
  수집을 실패 처리하며, 점검 페이지를 정상 데이터나 무결과 응답으로 저장하지 않습니다.
  일일 워크플로우 5개는 이전 실행의 성공 여부와 관계없이 다음 날 같은 예약 시각에
  다시 실행됩니다. 이는 24시간 동안 실행 중인 작업을 유지하는 방식이 아니며,
  실제 시작 시각은 GitHub 예약 지연과 공유 캐시 작업 대기열에 따라 늦어질 수 있습니다.

## 환경 설정

```bash
# 필수
LAW_OC=your-openapi-key

# 선택사항
WORKSPACE_ROOT=/path/to/LEGALIZE-KR-WORKSPACE-ROOT
LEGALIZE_CACHE_DIR=/path/to/cache
LEGALIZE_KR_REPO=/path/to/legalize-kr
PRECEDENT_KR_REPO=/path/to/precedent-kr
ADMRULE_KR_REPO=/path/to/admrule-kr
ORDINANCE_KR_REPO=/path/to/ordinance-kr
```

## CI/CD

### daily-laws-update.yml (매일 13:00 KST)

1. 저장소 체크아웃
2. `python -m laws.update --days 14` 실행 (최근 14일)
3. `python -m laws.validate` 검증
4. 변경사항 자동 push

## API

- **데이터 소스**: [국가법령정보센터 OpenAPI](https://open.law.go.kr)
- **인증**: `LAW_OC` 환경변수
- **Rate limit**: 기본 0.2초 간격 (thread-safe 스로틀)

## 주의사항

- 6개 MST는 파싱 불가능 (GitHub Issues 참조)
- 2개 MST는 메타데이터 누락 (GitHub Issues 참조)
- `소관부처` 필드는 항상 YAML 리스트 형식
- **판례 긴 파일명 capping**: 형사 병합/분리 판결은 `사건번호` 한 필드에 수십~수백 개 사건번호를 쉼표로 나열하는 경우가 있어, 그대로 파일명으로 쓰면 macOS APFS의 `NAME_MAX=255 bytes` 제한을 초과해 `git checkout`이 실패한다. `precedents/converter.py`의 `cap_filename_bytes`가 파일명 stem을 UTF-8 기준 180바이트로 cap하고, 잘린 경우 `_{판례일련번호}`를 접미사로 붙여 고유성을 보존한다. `compiler-for-precedent`(Rust 재구현)도 동일한 로직을 갖는다.

## 자치법규 업데이트 실패 처리

`python -m ordinances.update --commit`은 현재 HEAD 이력으로 수집 중복을 판단합니다.
보관 브랜치에만 있는 판본은 수집 대상에서 제외하지 않습니다.
처음 게시할 선택 판본은 유효한 XML 캐시가 있어도 공식 원문을 다시 조회합니다.
MST로 조회해도 응답의 법규 ID와 일련번호가 요청과 일치해야 캐시를 저장합니다.
연혁 캐시 `history/{MST}.xml`의 일련번호가 없거나 파일명과 다르면 Python import와 Rust 컴파일러 모두 해당 입력을 거부합니다. 기존 ID 기반 현행 캐시 형식은 유지합니다.
수집 오류가 있으면 기존 캐시로 파일을 쓰거나 커밋하지 않고 실패합니다.
이미 HEAD에 반영한 일반 판본은 중복 방지로 건너뜁니다. 같은 일련번호의 원문 정정은 원본 대조와 별도 정정 커밋으로 반영합니다.
변환 오류가 있거나 선택한 판본이 HEAD 이력에 남지 않으면 명령은 실패합니다.
원천의 404 또는 명시적 부재 응답이 `_no_result_serials.txt`에 기록된 판본은 미반영 검사에서 제외합니다.
다시 상세 캐시를 확보한 판본은 과거 부재 기록이 있어도 HEAD 반영을 검사합니다.
같은 조문 번호가 중복되거나 조문 시작 표기가 연달아 반복되면 `원문오류` 목록과 본문 경고를 추가합니다.
오류 판본은 조문 번호, 가지번호, 조문 여부, 제목, 내용 및 부칙의 날짜, 번호, 내용을 원천 XML의 필드 순서대로 표시합니다.
각 값은 코드 블록에 담으며 공백, 줄바꿈, 중복, 기호를 그대로 보존합니다. XML 표준에 따른 엔티티 해석과 줄바꿈 처리는 적용됩니다.
조문을 합치거나 번호를 고치거나 항을 다른 조문으로 옮기지 않습니다. 원본 XML 캐시도 수정하지 않습니다.
정상 판본의 형식은 유지합니다. Python import, 일일 갱신, Rust 컴파일러의 세 실행 모드에 같은 규칙을 적용합니다.
XML 문법 오류와 판본 식별번호 불일치는 여전히 실패합니다. 오류 표시가 없는 출력으로 대체하지 않습니다.

`ordinances/data/deferred_revisions.yaml`은 이전에 보류한 여섯 판본의 재조회 목록도 제공합니다.
아직 게시하지 않은 목록의 판본은 검색 기간 밖에서도 조회합니다. 중복 조문 원본은 이제 오류 표시와 함께 게시하므로 보류 해시나 만료일이 게시를 차단하지 않습니다.
재조회가 실패하면 기존 캐시로 게시하지 않습니다. 기존 이력에 반영한 동일 판본은 다시 커밋하지 않습니다.

이 기록은 영구 부재를 뜻하지 않습니다. 현행 캐시 갱신과 일일 업데이트는 복구된 판본을 다시 조회하며, 연혁 일괄 수집은 기존 부재 기록을 건너뜁니다.
일일 워크플로는 이 명령이 실패하면 게시 단계로 진행하지 않습니다.
오류를 수정하고 다시 실행하면 이미 커밋한 판본은 건너뛰고 남은 판본을 처리합니다.
`python -m ordinances.import_ordinances`도 변환 오류가 있으면 실패 종료합니다.

자치법규 import는 HEAD에 이미 반영한 판본을 파일 쓰기 전에 제외합니다.
과거 판본의 재시도가 최신 본문을 되돌리는 경우 업데이트를 중단합니다.
이 경우 기존 이력을 보존한 별도 저장소에서 개정 순서를 검증한 뒤 복구합니다.
기존 문서의 경로도 충돌 검사에 포함하므로 새 ID가 같은 이름의 기존 문서를 덮어쓰지 않습니다.

현행 캐시 갱신은 목록의 남은 페이지 수와 캐시에 없는 상세 수를 나누어 요청 예산을 검사합니다.
이미 캐시된 상세를 신규 요청으로 계산하지 않으며, 현행 목록도 지정한 워커 수로 수집합니다.
Rust 컴파일러는 이 수집 예산에 관여하지 않으며 기존 캐시 입력 형식을 유지합니다.

자치법규 목록의 공포일자 범위는 공식 API 인자 `ancYd`로 요청합니다.
`prmlYd`는 자치법규 목록에서 무시되어 전체 목록을 반환하므로 사용하지 않습니다.
반환된 항목의 공포일자도 다시 검사합니다. 이 변경은 캐시 XML과 Rust 변환 규약을 바꾸지 않습니다.
명세: https://open.law.go.kr/LSO/openApi/guideResult.do?htmlName=ordinListGuide

폐지 판본의 조문 구조에 오류가 있으면 현행 파일은 삭제하되, 삭제 커밋 본문에 경고와 원문 필드를 보존합니다. 파일이 없는 폐지 판본도 Git 이력에서 원문을 확인할 수 있습니다.

공포일자가 없거나 날짜로 해석할 수 없으면 Python과 Rust는 정렬 및 Git 커밋 날짜에 1970-01-01을 사용합니다. Markdown의 원문 날짜는 수정하지 않습니다. 유효한 1970년 이전 날짜는 실제 날짜 순서로 정렬하고 Git 타임스탬프만 1970-01-01로 보정합니다.
