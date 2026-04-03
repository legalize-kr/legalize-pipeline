# legalize-pipeline

법령 수집·변환·검증 파이프라인입니다.

> 이 저장소는 [`legalize-kr/legalize-kr`](https://github.com/legalize-kr/legalize-kr)(법령 데이터)와 [`legalize-kr/legalize-web`](https://github.com/legalize-kr/legalize-web)(웹사이트)과 함께 사용됩니다.

## 사전 준비

```bash
pip install -r requirements.txt
```

환경 변수 `LAW_OC`에 [국가법령정보센터 OpenAPI](https://open.law.go.kr) 키를 설정합니다.

## 전체 import (최초 실행)

```bash
# 모든 법령
LAW_OC=your-law-openapi-key python import_laws.py

# 법률만
LAW_OC=your-law-openapi-key python import_laws.py --law-type 법률

# 대통령령만
LAW_OC=your-law-openapi-key python import_laws.py --law-type 대통령령

# 미리보기
LAW_OC=your-law-openapi-key python import_laws.py --limit 10 --dry-run
```

API 키 없이, 국가법령정보 사이트의 [법령목록지원](https://open.law.go.kr/LSO/lab/lawListSupport.do) 메뉴에서 CSV 파일을 내려받아 실행할 수도 있습니다:

```bash
python import_laws.py --csv /some/path/법령검색목록.csv
```

## API 응답 캐시

법령 상세 API (`lawService.do`) 응답을 `.cache/detail/{MST}.xml`에 Raw XML로 캐시합니다.
한번 캐시된 MST는 이후 API 호출 없이 즉시 로드됩니다.

### 캐시 다운로드

사전 수집된 캐시 데이터는 [`legalize-kr/legalize-kr` 릴리즈 페이지](https://github.com/legalize-kr/legalize-kr/releases)에서 다운로드할 수 있습니다.

```bash
# 법령 데이터 저장소
git clone https://github.com/legalize-kr/legalize-kr.git

# 파이프라인 저장소 (데이터 저장소 안에 체크아웃)
git clone https://github.com/legalize-kr/legalize-pipeline.git legalize-kr/pipeline

cd legalize-kr

# 캐시 압축 해제 (법령 데이터 저장소 루트에서)
unzip legalize-kr-cache.zip
# .cache/detail/*.xml, .cache/history/*.json 이 생성됩니다
```

> **참고**: 파이프라인은 상위 디렉토리를 `WORKSPACE_ROOT`(법령 데이터 저장소)로 사용합니다.
> 다른 경로에 체크아웃한 경우 `WORKSPACE_ROOT` 환경변수를 설정하세요.

### 캐시 수집

```bash
# 모든 현행 법령의 개정 이력 + 상세 XML 캐시 (기본 5 workers 병렬)
python fetch_cache.py

# workers 수 조절 (네트워크 환경에 따라)
python fetch_cache.py --workers 10

# 이력 없이 현행 상세만 캐시 (이전 동작)
python fetch_cache.py --skip-history

# 테스트용 (10건만)
python fetch_cache.py --limit 10
```

> **참고**: 병렬 처리 시 API rate limit은 전체 workers가 공유합니다 (thread-safe throttle).
> 캐시 파일은 atomic write (tempfile → rename)로 저장되어 병렬 실행에 안전합니다.

### 캐시에서 import

```bash
# 캐시된 XML에서 Markdown 변환 + Git Commit (API 호출 없음)
python import_laws.py --from-cache

# 미리보기
python import_laws.py --from-cache --dry-run
```

> **참고**: `--from-cache`는 `.cache/detail/`의 파일만 사용합니다.
> 일반 import (`import_laws.py`, `update.py`)는 search/history API를 호출하되,
> detail API는 캐시가 있으면 자동으로 캐시에서 읽습니다.

### 캐시에서 Git 히스토리 재구성

```bash
cd legalize-kr/pipeline
python rebuild.py --infra-date "2026-03-30T12:00:00+09:00" --dry-run  # 미리보기
python rebuild.py --infra-date "2026-03-30T12:00:00+09:00"            # 실제 실행 (~3시간)
```

rebuild 브랜치가 생성되며, 확인 후:
```bash
git branch -M rebuild main
```

### 캐시 구조

```
.cache/
  detail/{MST}.xml          # 법령 상세 API 원본 XML
  history/{법령명}.json      # 법령별 개정 이력
```

## 증분 업데이트 (일일 실행)

```bash
# 최근 7일 (기본값)
python update.py

# 최근 30일
python update.py --days 30
```

GitHub Actions에서 매일 13:00 KST에 자동 실행됩니다.

## 메타데이터 재생성

```bash
python generate_metadata.py
```

`kr/` 아래 모든 `.md` 파일을 스캔하여 `metadata.json`과 `stats.json`을 갱신합니다.

## 유효성 검증

```bash
python validate.py
```

검증 항목:
- YAML frontmatter 필수 필드
- `소관부처`가 YAML 리스트인지
- Unicode 가운뎃점 정규화 (U+00B7 → U+318D)
- `metadata.json`과 파일 시스템 일치

## XML 파싱 규칙

`api_client.py`가 국가법령정보센터 API의 XML 응답을 파싱하는 규칙입니다.

### 데이터 소스

| API 엔드포인트 | 용도 | 캐시 위치 |
|---|---|---|
| `lawSearch.do` (`target=law`) | 법령 목록 검색 | 캐시 없음 (매번 호출) |
| `lawService.do` (`MST={id}`) | 법령 상세 (본문 XML) | `.cache/detail/{MST}.xml` |
| `lawSearch.do` (`target=lsHistory`) | 개정 이력 (HTML 테이블) | `.cache/history/{법령명}.json` |

### XML 구조 → 파싱 계층

법령 상세 XML (`lawService.do`)의 파싱 계층:

```
<법령>
  ├── 메타데이터 (법령명_한글, 법령ID, 법종구분, 공포일자, …)
  ├── 조문단위[]
  │   ├── 조문번호, 조문제목, 조문내용
  │   └── 항[]
  │       ├── 항번호, 항내용
  │       └── 호[]
  │           ├── 호번호, 호내용
  │           └── 목[]
  │               ├── 목번호, 목내용
  │               └── (하위 구조 없음 — 반괄호 등은 목내용 텍스트에 포함)
  └── 부칙단위[]
      └── 부칙공포일자, 부칙공포번호, 부칙내용
```

> **제한**: API XML은 `목` 이하의 하위 항목(반괄호 `1)`, `2)` 등)을
> 별도 요소로 제공하지 않습니다. 해당 내용은 `목내용` 텍스트에 포함되어 있습니다.

### Markdown 변환 규칙 (`converter.py`)

| 법령 구조 | Markdown 출력 | 비고 |
|---|---|---|
| 편/장/절/관 | `#` ~ `####` 제목 | 조문내용에서 자동 감지 |
| 조 | `##### 제N조 (제목)` | 항상 h5 |
| 항 | `**N** 내용` | 원문 원문자(①②…) 제거 후 볼드 번호 |
| 호 | `  N\. 내용` (2칸 들여쓰기) | `\.`로 Markdown 순서목록 방지 |
| 목 | `    가\. 내용` (4칸 들여쓰기) | 동일하게 escape 처리 |
| 부칙 | `## 부칙` 아래 본문 | 별도 섹션, 공통 들여쓰기 dedent |

### 텍스트 정규화

- **Unicode 가운뎃점**: `·` (U+00B7), `・` (U+30FB), `･` (U+FF65) → `ㆍ` (U+318D)
- **호 접두사 제거**: `호내용`에서 `N.` 또는 `N의M.` 패턴 제거 (호번호와 중복 방지)
- **목 접두사 제거**: `목내용`에서 `가.` 등 한글 접두사 제거
- **공백 정규화**: 호/목 내용의 연속 공백·탭을 단일 공백으로 축소
- **공포일자 형식**: `YYYYMMDD` → `YYYY-MM-DD`

### 캐시 파일명

- 상세 XML: `.cache/detail/{MST}.xml` (MST는 숫자이므로 길이 문제 없음)
- 개정 이력: `.cache/history/{법령명}.json`
  - 법령명이 200바이트를 초과하면 `{접두사}_{SHA256해시16자리}.json`으로 축약

## 디렉토리 구조

```
kr/{법령명}/
  법률.md          # 국회에서 제정하는 법률
  시행령.md        # 법률의 시행령 (대통령령의 일종)
  시행규칙.md      # 법률의 시행규칙 (부령)
  대통령령.md      # 독립 대통령령 (규정, 직제 등 — 부모 법률 없음)
```

## 커밋 메시지 형식

각 법령 커밋은 law.go.kr 참조 URL과 메타데이터를 포함합니다:

```
법률: 민법 (일부개정)

법령 전문: https://www.law.go.kr/법령/민법
제개정문: https://www.law.go.kr/법령/제개정문/민법/(12345,20260317)
신구법비교: https://www.law.go.kr/법령/신구법비교/민법

공포일자: 2026-03-17
공포번호: 12345
소관부처: 법무부
법령분야: 민사
법령MST: 284415
```
