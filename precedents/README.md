# precedents — 판례 데이터 파이프라인

국가법령정보센터 OpenAPI에서 한국 법원 판례(판결문) 데이터를 수집하여 캐시하는 파이프라인입니다.

## 모듈

| 모듈 | 설명 |
|------|------|
| `config.py` | 판례 전용 설정 및 경로 (PREC_CACHE_DIR 등) |
| `api_client.py` | law.go.kr OpenAPI 판례 API 래퍼 (search, detail) |
| `cache.py` | 파일 기반 캐시 관리 (detail XML) |
| `fetch_cache.py` | API → 캐시 병렬 수집 |

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
python -m precedents.fetch_cache --skip-list
```

### 동작

1. `search_precedents()` 호출하여 판례 목록 페이지네이션 (또는 `--skip-list` 시 all_ids.txt 읽기)
2. 각 판례의 상세 XML을 병렬로 다운로드
3. 이미 캐시된 항목은 자동으로 건너뜀
4. 수집된 ID 목록을 `all_ids.txt`에 저장 (이후 `--skip-list` 재사용)

## 캐시 구조

```
WORKSPACE_ROOT/
  .cache/
    precedent/
      {판례일련번호}.xml        # 판례 상세 API 원본 XML
      all_ids.txt               # 수집된 판례 ID 목록
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
