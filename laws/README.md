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
# 모든 현행 법령의 상세 XML + 개정 이력 캐시
python -m laws.fetch_cache

# 워커 수 조절
python -m laws.fetch_cache --workers 10

# 테스트용 (10건만)
python -m laws.fetch_cache --limit 10

# 개정 이력 건너뛰기
python -m laws.fetch_cache --skip-history
```

### 캐시에서 import (오프라인)

```bash
# 캐시된 XML에서 Markdown 변환 (API 호출 없음)
python -m laws.import_laws --from-cache

# 미리보기
python -m laws.import_laws --from-cache --dry-run
```

### 증분 업데이트 (일일 실행)

```bash
# 최근 7일
python -m laws.update

# 최근 30일
python -m laws.update --days 30
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
    detail/{MST}.xml              # 법령 상세 API 원본 XML
    history/{법령명}.json         # 법령별 개정 이력
  .checkpoint.json                # 처리 상태 (processed_msts, last_update)
```

캐시 파일은 원자적 쓰기(tempfile → rename)로 저장되어 병렬 실행에 안전합니다.

## 법령명의 자식 법령

법령명에 특정 접미사가 붙으면 부모 법령과 같은 디렉토리에 저장됩니다:

```
민법 시행령       → kr/민법/시행령.md
민법 시행규칙     → kr/민법/시행규칙.md
(접미사 없음)     → kr/법령명/법률.md
```

경로 충돌 시 `시행규칙(부령).md` 형태로 법령구분 한정자를 추가합니다.

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
- **Checkpoint**: `.checkpoint.json`의 `processed_msts` set 추적
- **Update 모드**: checkpoint만 사용 (skip_dedup=True)

## 환경 설정

```bash
# 필수
LAW_OC=your-openapi-key

# 선택사항
WORKSPACE_ROOT=/path/to/legalize-kr
```

> **참고**: 파이프라인은 `WORKSPACE_ROOT`(기본: 상위 디렉토리)를 법령 데이터 저장소로 사용합니다.
> 다른 경로에 체크아웃한 경우 환경변수를 설정하세요.

## API 엔드포인트

| 엔드포인트 | 용도 | 캐시 |
|---|---|---|
| `lawSearch.do` (target=law) | 법령 목록 검색 | 없음 |
| `lawService.do` (MST={id}) | 법령 상세 (본문 XML) | `detail/{MST}.xml` |
| `lawSearch.do` (target=lsHistory) | 개정 이력 | `history/{법령명}.json` |
