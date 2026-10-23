# laws — 법령 데이터 파이프라인

국가법령정보센터 OpenAPI에서 한국 법령 데이터를 수집하여 Markdown으로 변환하고 Git으로 관리하는 파이프라인입니다.

## 모듈

| 모듈 | 설명 |
|------|------|
| `config.py` | 법령 전용 설정 및 경로 (KR_DIR, CHILD_SUFFIXES 등) |
| `api_client.py` | law.go.kr OpenAPI 래퍼 (search, detail, history) |
| `cache.py` | 파일 기반 캐시 관리 (detail XML, history JSON) |
| `checkpoint.py` | 처리 상태 추적 (processed_msts, last_update) |
| `converter.py` | XML → Markdown + YAML frontmatter 변환 |
| `git_engine.py` | Git 커밋 (공포일자 기반 날짜 설정) |
| `fetch_cache.py` | API → 캐시 병렬 수집 |
| `import_laws.py` | 전체 법령 import (API/캐시/CSV 모드) |
| `audit_cache_vs_repo.py` | 캐시와 결과 저장소의 본문 누락/경로 drift 감사 |
| `update.py` | 증분 업데이트 (최근 N일) |
| `rebuild.py` | Git 히스토리 재구성 (시간순 커밋) |
| `generate_metadata.py` | metadata.json, stats.json 생성 |
| `validate.py` | 유효성 검증 (frontmatter, Unicode, 정합성) |

## CLI 사용법

모든 명령은 `python -m laws.*` 형식으로 실행합니다.

### 전체 import (최초 실행)

```bash
# 모든 법령
python -m laws.import_laws

# 특정 법령 유형만 (예: 법률)
python -m laws.import_laws --law-type 법률

# 미리보기
python -m laws.import_laws --limit 10 --dry-run

# CSV 파일에서 import (API 키 없이)
python -m laws.import_laws --csv /path/to/법령검색목록.csv
```

### API → 캐시 수집

```bash
# 모든 현행 법령 + 명시 seed 법령의 상세 XML + 개정 이력 캐시
python -m laws.fetch_cache --refresh-history --history-name-file laws/data/history_seed_names.txt

# 워커 수 조절
python -m laws.fetch_cache --refresh-history --history-name-file laws/data/history_seed_names.txt --workers 10

# 테스트용 (10건만)
python -m laws.fetch_cache --limit 10

# 개정 이력 건너뛰기
python -m laws.fetch_cache --skip-history
```

`--refresh-history`는 새 응답을 MST 기준으로 기존 캐시와 병합하므로, 상류가
일시적으로 생략한 기존 이력을 삭제하지 않습니다. 전체 법령명 조회가 비면
표기 정규화 또는 짧은 식별 질의로 재조회하되, 결과 행은 원래 전체 법령명과
일치하는 경우만 저장합니다.

### 캐시에서 import (오프라인)

```bash
# 캐시된 XML에서 Markdown 변환 (API 호출 없음)
python -m laws.import_laws --from-cache

# 미리보기
python -m laws.import_laws --from-cache --dry-run

# 특정 MST만 backfill
python -m laws.import_laws --from-cache --msts-list /path/to/msts.txt
```

### 캐시/저장소 감사

```bash
# .cache/history + .cache/detail 기준으로 결과 저장소 누락 확인
python -m laws.audit_cache_vs_repo

# 실제 본문 누락이 있으면 실패
python -m laws.audit_cache_vs_repo --fail-on-missing-content

# 기존 baseline에 없는 새 경로 drift가 있으면 실패
python -m laws.audit_cache_vs_repo --fail-on-new-path-drift

# 상세 JSON 출력
python -m laws.audit_cache_vs_repo --json
```

### 증분 업데이트 (일일 실행)

```bash
# 최근 14일
python -m laws.update

# 최근 30일
python -m laws.update --days 30

# history refresh 중 발견한 window 밖 누락 MST는 기본적으로 backfill
# 문제 분석 시에만 비활성화
python -m laws.update --no-backfill-discovered-history
```

### Git 히스토리 재구성

```bash
# 미리보기
python -m laws.rebuild --infra-date "2026-03-30T12:00:00+09:00" --dry-run

# 실제 실행 (~3시간, orphan branch 생성)
python -m laws.rebuild --infra-date "2026-03-30T12:00:00+09:00"
```

### 메타데이터 재생성

```bash
# kr/ 아래 모든 .md 파일 스캔 → metadata.json + stats.json
python -m laws.generate_metadata
```

### 유효성 검증

```bash
# YAML frontmatter, Unicode, 정합성 검증
python -m laws.validate
```

## 캐시 구조

```
WORKSPACE_ROOT/
  .cache/
    detail/{MST}.xml              # 법령 상세 파서 입력 XML, 수리본 포함
    history/{법령명}.json         # 법령별 개정 이력
    .checkpoint.json              # 처리 상태 (processed_msts, last_update)
    .failed_msts.json             # 실패 ledger
  legalize-kr/
    kr/{법령명}/*.md              # 법령 Markdown
    metadata.json
    stats.json
```

캐시 모듈은 임시 파일을 쓴 뒤 rename으로 교체합니다.

`get_law_detail()`은 파싱과 메타데이터, 조문, 첨부파일 추출을 마친 XML을
캐시에 저장합니다. 반환값의 `raw_xml`도 이 파서 입력과 같습니다.
지원하는 오류를 수리했다면 두 값 모두 수리본이며 API 응답 원본을 별도로
보존하지 않습니다. compiler는 같은 `detail/` 파일을 직접 읽습니다.

캐시에서 읽은 XML을 수리한 경우에도 검증과 추출을 마친 뒤 수리본으로 교체합니다.
정상 캐시는 다시 쓰지 않으며 수리나 추출이 실패하면 기존 파일을 보존합니다.
수집기의 기존 캐시 건너뛰기 경로는 파일을 검증하지 않습니다.
이 계약은 새로 검증해서 저장한 파일에 적용되며 기존 캐시 전체의 검증을 뜻하지 않습니다.

법령 상세 파싱이 실패하면 `api_client.repair_law_xml()`이 미닫힌
`<조문참고자료>` 수리를 시도합니다. 실제 태그를 CDATA와 주석에서 구분하고,
조문단위 바로 아래의 참고자료에 CDATA와 XML 공백만 있을 때 수리합니다.
다음 형제 조문내용이나 참고자료, 부모 조문단위의 종료 태그 앞에만 닫는 태그를 삽입합니다.
불명확한 구조나 지원하지 않는 오류에는 최초 파싱 예외를 그대로 전달합니다.
수리 후 파싱과 내용 추출이 성공하면 수리본을 저장하므로 재임포트는 API 없이 동작합니다.

관련 회귀 테스트는 다음 명령으로 실행합니다. 테스트는 임시 캐시를 사용합니다.

```bash
python -m pytest tests/test_laws/test_repair_xml.py
```

## 법령명의 자식 법령

법령명에 특정 접미사가 붙으면 부모 법령과 같은 디렉토리에 저장됩니다:

```
민법 시행령       → kr/민법/시행령.md
민법 시행규칙     → kr/민법/시행규칙.md
(접미사 없음)     → kr/법령명/법률.md
```

경로 충돌 판정 기준은 **법령ID**입니다. 같은 법령ID를 가진 법령은 부처명이 달라도(부처 명칭 변경) 항상 같은 파일에 덮어씁니다. 진짜 다른 법령(다른 법령ID)이 같은 구조적 경로를 가질 때만 `시행규칙(총리령).md` 형태 한정자를 사용합니다.

### 정렬 키와 canonical 경로 선택 (compiler와의 동작 일치)

전체 캐시 import/rebuild와 Rust compiler는 먼저 같은 `법령ID`의 개정 이력을 묶고, 각 lineage의 **최신 개정 법령명**으로 최종 경로를 계획합니다. 그래서 `송유관사업법` → `송유관 안전관리법`처럼 법령명이 바뀐 경우에도 최종 저장소에는 최신명 경로(`kr/송유관안전관리법/법률.md`)가 남습니다.

서로 다른 `법령ID`가 같은 최신 structural path를 공유할 때만, 먼저 계획되는 lineage가 canonical(`법률.md`)이 되고 늦게 오는 lineage가 qualified(`법률(법률).md`)가 됩니다. Streaming helper인 `get_law_path()` 자체는 여전히 first-write-wins 동작을 유지하므로, 전체 입력을 알고 있는 경로에서는 `plan_current_law_paths()`를 먼저 사용해야 합니다.

이 파이프라인과 Rust 재구현(`legalize-kr/compiler`)은 동일한 4-튜플 정렬 키를 사용합니다:

1. `공포일자` (문자열 오름차순)
2. `법령명한글`
3. `공포번호` (numeric)
4. `법령MST` (numeric)

공통 헬퍼는 `laws.converter.entry_sort_key`에 있으며, 정렬이 일어나는 호출 지점(`rebuild.py`, `import_laws.py` cache 모드, `update.py`)에서 같은 키를 사용합니다. Rust 쪽은 `compiler/src/main.rs`의 `plan_and_diagnose`에 동일 순서가 구현돼 있으며, 한쪽을 바꾸면 양쪽이 갈라져 canonical 파일이 뒤집힙니다.

### 부처명 변경과 파편화 방지

```
# 같은 법령ID → 같은 파일 (부처명 변경 무관)
집회및시위에관한법률 시행규칙 (법령ID: 008397)
  - 안전행정부령 시절 → kr/집회및시위에관한법률/시행규칙.md
  - 행정안전부령 이후 → kr/집회및시위에관한법률/시행규칙.md (덮어씀)
```

기존 파편화된 파일 통합: `python -m laws.migrate_ministry_paths`

## Markdown 변환 규칙

| 법령 구조 | Markdown 출력 | 비고 |
|---|---|---|
| 편/장/절/관 | `#` ~ `####` 제목 | 조문내용에서 자동 감지 |
| 조 | `##### 제N조 (제목)` | 항상 h5 |
| 항 | `**N** 내용` | 원문자(①②…) 제거 후 볼드 번호 |
| 호 | `  N. 내용` (2칸 들여쓰기) | Markdown 순서목록 방지 |
| 목 | `    가. 내용` (4칸 들여쓰기) | Markdown 순서목록 방지 |
| 부칙 | `## 부칙` 아래 본문 | 별도 섹션 |

### 텍스트 정규화

- **가운뎃점**: `·` (U+00B7), `・` (U+30FB), `･` (U+FF65) → `ㆍ` (U+318D)
- **공포일자 형식**: `YYYYMMDD` → `YYYY-MM-DD`
- **호/목 접두사**: 중복 제거
- **공백**: 연속 공백·탭을 단일 공백으로 축소

## 중복 방지 메커니즘

같은 법령의 중복 처리를 방지합니다:

- **Git grep**: `git log --grep=법령MST:{id}` 검사
- **Checkpoint**: `.cache/.checkpoint.json`의 `processed_msts` set 추적
- **Update 모드**: checkpoint만 사용 (skip_dedup=True)

## 환경 설정

```bash
# 필수
LAW_OC=your-openapi-key

# 선택사항
WORKSPACE_ROOT=/path/to/LEGALIZE-KR-WORKSPACE-ROOT
LEGALIZE_CACHE_DIR=/path/to/cache
LEGALIZE_KR_REPO=/path/to/legalize-kr
```

> **참고**: 파이프라인은 `WORKSPACE_ROOT`(기본: 상위 디렉토리)를 메타 워크스페이스 루트로 사용합니다.
> 법령 저장소 기본값은 `WORKSPACE_ROOT/legalize-kr`, 공유 캐시 기본값은 `WORKSPACE_ROOT/.cache`입니다.

## API 엔드포인트

| 엔드포인트 | 용도 | 캐시 |
|---|---|---|
| `lawSearch.do` (target=law) | 법령 목록 검색 | 없음 |
| `lawService.do` (MST={id}) | 법령 상세 (본문 XML) | `detail/{MST}.xml` |
| `lawSearch.do` (target=lsHistory) | 개정 이력 | `history/{법령명}.json` |
