# legalize-pipeline

한국 법령 및 판례 데이터를 수집·변환·검증하는 파이프라인입니다.

> 이 저장소는 [`legalize-kr/legalize-kr`](https://github.com/legalize-kr/legalize-kr)(법령 데이터)과 [`legalize-kr/legalize-web`](https://github.com/legalize-kr/legalize-web)(웹사이트)과 함께 사용됩니다.

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
# 모든 현행 법령 캐시
python -m laws.fetch_cache

# 워커 수 조절
python -m laws.fetch_cache --workers 10

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
# 최근 7일
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
WORKSPACE_ROOT/
  kr/{법령명}/
    법률.md                       # 법령 Markdown 파일
    시행령.md
    시행규칙.md
  metadata.json                   # 법령 인덱스 (자동 생성)
  stats.json                      # 통계 (자동 생성)
  .cache/
    detail/{MST}.xml              # 법령 상세 API XML
    history/{법령명}.json         # 법령 개정 이력
    precedent/{판례일련번호}.xml  # 판례 상세 API XML
    images/                       # 이미지 캐시
  .checkpoint.json                # 처리 상태
```

> **참고**: 파이프라인은 `WORKSPACE_ROOT` 환경변수(기본: 상위 디렉토리)를 법령 데이터 저장소로 사용합니다.
> 다른 경로에 체크아웃한 경우 환경변수를 설정하세요.

## 캐시 다운로드

사전 수집된 캐시 데이터는 [`legalize-kr/legalize-kr` 릴리즈 페이지](https://github.com/legalize-kr/legalize-kr/releases)에서 다운로드할 수 있습니다:

```bash
# 법령 데이터 저장소
git clone https://github.com/legalize-kr/legalize-kr.git

cd legalize-kr

# 캐시 압축 해제
unzip legalize-kr-cache.zip
# .cache/detail/*.xml, .cache/history/*.json이 생성됩니다
```

그 후 이 저장소를 체크아웃:

```bash
git clone https://github.com/legalize-kr/legalize-pipeline.git pipeline
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
- **Checkpoint**: `.checkpoint.json` 추적
- **Update 모드**: checkpoint만 사용

## 병렬 처리

- Thread-safe throttle로 API rate limit 관리 (기본 0.2초 간격)
- 기본 5개 워커로 병렬 다운로드
- Atomic write (tempfile → rename)로 파일 안전성 보장
- 실패 재시도는 지수 백오프 (2, 4, 8초…)

## 환경 설정

```bash
# 필수
LAW_OC=your-openapi-key

# 선택사항
WORKSPACE_ROOT=/path/to/legalize-kr
```

## CI/CD

### daily-update.yml (매일 13:00 KST)

1. 저장소 체크아웃
2. `python -m laws.update` 실행 (최근 7일)
3. `python -m laws.validate` 검증
4. 변경사항 자동 push

### full-import.yml (수동 실행)

1. 캐시 확인/수집
2. `python -m laws.rebuild` 실행
3. 검증 후 force push

## API

- **데이터 소스**: [국가법령정보센터 OpenAPI](https://open.law.go.kr)
- **인증**: `LAW_OC` 환경변수
- **Rate limit**: 기본 0.2초 간격 (thread-safe 스로틀)

## 주의사항

- 6개 MST는 파싱 불가능 (GitHub Issues 참조)
- 2개 MST는 메타데이터 누락 (GitHub Issues 참조)
- `소관부처` 필드는 항상 YAML 리스트 형식
