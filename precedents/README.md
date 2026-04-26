# precedents — 판례 데이터 파이프라인

국가법령정보센터 OpenAPI에서 한국 법원 판례(판결문) 데이터를 수집하여 캐시하는 파이프라인입니다.

## 모듈

| 모듈 | 설명 |
|------|------|
| `config.py` | 판례 전용 설정 및 경로 (PREC_CACHE_DIR 등) |
| `api_client.py` | law.go.kr OpenAPI 판례 API 래퍼 (search, detail) |
| `cache.py` | 파일 기반 캐시 관리 (detail XML) |
| `fetch_cache.py` | API → 캐시 병렬 수집 |
| `converter.py` | XML → Markdown + composite filename grammar |
| `import_precedents.py` | 캐시 → Markdown 일괄 변환 |
| `preflight_filename_audit.py` | 파일명 grammar 사전 측정 (N1/N2/SEP 결정) |
| `dump_oracle.py` | Python ↔ Rust byte-equality oracle (JSONL) |

## 파일명 Grammar (composite key)

판례 파일은 `{사건종류}/{법원등급}/{COURT}{SEP}{DATE}{SEP}{CASENO}.md` 로 저장됩니다.
하급심은 사건번호가 법원별로 발급되어 단일키로는 충돌하므로 합성 키만이 진정한
unique key 입니다.

| 슬롯 | 값 | 결측 시 |
|---|---|---|
| `COURT` | `normalize_court_name(법원명)` (NFC) | `미상법원` + CASENO 를 `serial` 로 강제 폴백 |
| `DATE` | `YYYY-MM-DD` (ISO 8601) | `0000-00-00` 센티넬 |
| `CASENO` | `sanitize_case_number(사건번호)` (NFC) | `serial` 폴백 |
| `SEP` | `--` (이중 hyphen) — preflight (`__` 18건 / `~` 2건 침입 → `--` 0건) 결정 | 추가 침입 검출 시 swap 후 lockstep PR |

상수는 `converter.py` 모듈 상단에 분리되어 있습니다 (`SEP`, `MISSING_DATE_SENTINEL`,
`MISSING_COURT_SENTINEL`, `MAX_FILENAME_STEM_BYTES`). `compiler-for-precedent` (Rust)
및 `cli-tools` 와 lockstep 으로 동기화해야 합니다 (3-repo PR 의무).

`sanitize_case_number` 는 `assert SEP not in result` runtime guard 를 둬서
미래 입력 변동으로 SEP 가 우연히 발생하면 즉시 fail-loud 합니다 (preflight 가
SEP swap 결정을 내릴 수 있도록).

## Preflight 측정 (필수 사전 게이트)

```bash
WORKSPACE_ROOT=/path/to/repo \
  python -m precedents.preflight_filename_audit \
    --report .omc/plans/preflight-report.json
```

10개 측정 결과를 stdout + JSON 으로 출력하고 `N1`/`N2`/`SEP` 를 결정합니다
(`exit 2` 시 모든 후보 SEP 가 데이터에 침입). `compiler-for-precedent` 의
`cargo test --test oracle` 입력으로 사용되는 oracle 도 함께 생성합니다:

```bash
WORKSPACE_ROOT=/path/to/repo \
  python -m precedents.dump_oracle --output /tmp/oracle.jsonl
```

## CLI 사용법

### 전체 판례 수집 (최초 실행)

```bash
# 전체 판례 목록 수집 및 상세 XML 캐시 (기본 5 workers 병렬)
python -m precedents.fetch_cache

# 워커 수 조절
python -m precedents.fetch_cache --workers 3

# 테스트용 (100건만)
python -m precedents.fetch_cache --limit 100
```

### 판례 목록 재사용 (이후 실행)

```bash
# all_ids.txt 재사용, 목록 수집 생략 (캐시 확인만 수행)
python -m precedents.fetch_cache --skip-list  # precedent_ids.json 재사용
```

### 동작

1. `search_precedents()` 호출하여 판례 목록 페이지네이션 (또는 `--skip-list` 시 precedent_ids.json 읽기)
2. 각 판례의 상세 XML을 병렬로 다운로드
3. 이미 캐시된 항목은 자동으로 건너뜀
4. 수집된 ID 목록을 `precedent_ids.json`에 저장 (수집일시 포함, 이후 `--skip-list` 재사용)

## 캐시 구조

```
WORKSPACE_ROOT/
  .cache/
    precedent/
      {판례일련번호}.xml        # 판례 상세 API 원본 XML
      precedent_ids.json        # 수집된 판례 ID 목록 (collected_at, total, ids)
```

캐시 파일은 원자적 쓰기(tempfile → rename)로 저장되어 병렬 실행에 안전합니다.

## API 엔드포인트

| 엔드포인트 | 용도 |
|---|---|
| `lawSearch.do` (target=prec) | 판례 목록 검색 (페이지네이션) |
| `lawService.do` (target=prec, ID={id}) | 판례 전문 XML |

## 환경 설정

```bash
# 필수
LAW_OC=your-openapi-key

# 선택사항
WORKSPACE_ROOT=/path/to/legalize-kr
```

## 병렬 처리

- 기본 5개 워커로 병렬 다운로드
- `--workers` 플래그로 조절 가능
- Thread-safe throttle로 API rate limit 관리
- 실패 항목은 로그되고 계속 진행
