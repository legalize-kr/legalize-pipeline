# (WIP) images — 법령 이미지 파이프라인

법령 Markdown 파일에 포함된 `<img>` 태그를 추출하고, 원본 이미지를 다운로드하며, 텍스트 변환 후 원본 문서에 반영하는 파이프라인입니다.

최신 버전의 법령에 남아있는 이미지를 처리하기 위해 법령 Markdown 파일을 기준으로 이미지를 찾습니다.

## 파이프라인 흐름

```
extract → download → (변환) → approve → replace
```

| 단계 | 설명 | 상태 변화 |
|------|------|-----------|
| **extract** | 한국어 법령 Markdown 파일에서 `<img>` 태그 추출 | → `extracted` |
| **download** | law.go.kr에서 이미지 병렬 다운로드 + SHA256 검증 | → `downloaded` / `not_found` / `error` |
| *(변환)* | VLM 또는 수작업으로 이미지를 텍스트로 변환 | (외부 처리) |
| **approve** | 변환된 텍스트를 검토·승인 | → `approved` |
| **replace** | 승인된 텍스트로 원본 문서의 `<img>` 태그 교체 | → `replaced` |

## 이미지 태그 형식

두 가지 형식을 처리합니다. 모두 동일한 URL(`flDownload.do?flSeq={ID}`)로 다운로드됩니다.

```html
<!-- src 형식 (95,523건) -->
<img src="https://www.law.go.kr/LSW/flDownload.do?flSeq=46807799" alt="img46807799"></img>

<!-- id-only 형식 (1,173건) -->
<img id="13403924"></img>
```

## CLI 사용법

```bash
python -m images [전역 옵션] <서브커맨드> [서브커맨드 옵션]
```

### 전역 옵션

| 옵션 | 설명 | 기본값 |
|------|------|--------|
| `--cache-dir DIR` | 이미지 캐시 디렉토리 | `LEGALIZE_CACHE_DIR/images` 또는 `WORKSPACE_ROOT/.cache/images` |
| `--kr-dir DIR` | 법령 문서(*.md) 소스 디렉토리 | `LEGALIZE_KR_REPO/kr` 또는 `WORKSPACE_ROOT/legalize-kr/kr` |
| `--output-dir DIR` | 리포트 등 출력 디렉토리 | (stdout) |

### 서브커맨드

#### extract — 이미지 태그 추출

```bash
python -m images extract
python -m images --kr-dir /path/to/kr extract
```

`kr/` 아래 모든 `*.md` 파일을 스캔하여 `<img>` 태그를 manifest에 기록합니다.
기존 manifest가 있으면 병합하여 진행 상태를 보존합니다.

#### download — 이미지 다운로드

```bash
python -m images download
python -m images download --workers 3
python -m images download --verify
```

| 옵션 | 설명 |
|------|------|
| `--workers N` | 병렬 다운로드 워커 수 (기본: 5) |
| `--verify` | 다운로드 대신 기존 캐시의 SHA256 체크섬 검증 |

- 이미 캐시된 이미지는 자동 건너뜀
- 연속 20회 실패 시 서킷 브레이커 작동
- `checksums.json`에 SHA256 해시 저장

#### report — 리포트 생성

```bash
python -m images report                          # 통계 요약 (stdout)
python -m images report --format tsv             # TSV 전체 목록
python -m images report --status downloaded       # 상태 필터
python -m images report --doc-path "kr/민법/*"    # 문서 경로 필터
python -m images report --output result.tsv       # 파일 출력
python -m images --output-dir ./out report --format tsv  # 디렉토리 지정 시 out/report.tsv
```

| 옵션 | 설명 |
|------|------|
| `--format tsv\|stats` | 출력 형식 (기본: stats) |
| `--status STATUS` | 상태 필터 |
| `--doc-path GLOB` | 문서 경로 glob 필터 |
| `--output FILE` | 출력 파일 경로 |

#### approve — 변환 승인

```bash
python -m images approve --ids 46807799,13403924
python -m images approve --doc-path "kr/민법/*"
```

| 옵션 | 설명 |
|------|------|
| `--ids ID,ID,...` | 이미지 ID 지정 승인 |
| `--doc-path GLOB` | 문서 경로 glob으로 일괄 승인 |

#### replace — 태그 교체

```bash
python -m images replace
python -m images replace --dry-run
```

| 옵션 | 설명 |
|------|------|
| `--dry-run` | 실제 파일 수정 없이 변경 내역만 출력 |

#### stats — 요약 통계

```bash
python -m images stats
```

#### viewer — 로컬 리뷰 뷰어

```bash
python -m images viewer
python -m images viewer --port 9000
```

브라우저에서 이미지와 문서 컨텍스트를 보며 텍스트 변환을 입력할 수 있는 웹 UI를 제공합니다.

## 모듈 구성

```
images/
├── __init__.py      # 패키지 마커
├── __main__.py      # CLI 엔트리포인트 (argparse)
├── config.py        # 경로 설정 + 런타임 오버라이드 (set_cache_dir, set_kr_dir)
├── manifest.py      # ImageEntry 데이터클래스 + Manifest (JSON 읽기/쓰기/조회)
├── extract.py       # *.md 파일 스캔, <img> 태그 정규식 매칭, manifest 생성
├── download.py      # 병렬 HTTP 다운로드, SHA256 체크섬, 서킷 브레이커
├── replace.py       # 승인된 텍스트로 원본 문서 교체 + approve_images()
├── report.py        # TSV/통계 리포트 생성
├── viewer.py        # 로컬 HTTP 리뷰 뷰어 (stdlib http.server)
└── README.md        # 이 문서
```

## Manifest 구조

`manifest.json`은 모든 이미지 참조의 상태를 추적합니다.

```json
{
  "version": 1,
  "updated_at": "2025-04-04T18:00:00+09:00",
  "stats": { "total": 96696, "extracted": 90000, "downloaded": 6000, ... },
  "entries": [
    {
      "doc_path": "kr/민법/법률.md",
      "image_id": "46807799",
      "image_url": "https://www.law.go.kr/LSW/flDownload.do?flSeq=46807799",
      "tag_format": "src",
      "original_tag": "<img src=\"...\" alt=\"img46807799\"></img>",
      "line_number": 142,
      "status": "downloaded",
      "sha256": "a1b2c3...",
      "image_size": null,
      "converted_text": "",
      "priority": 365
    }
  ]
}
```

### 상태 흐름

```
extracted ──→ downloaded ──→ approved ──→ replaced
    │              │
    └→ error       ├→ not_found
                   └→ skipped
```

### 우선순위 (priority)

공포일자(promulgation date) 기준으로 산출됩니다. 값이 낮을수록 최근 법령이므로 먼저 처리합니다.

## 무결성 검증

- 다운로드 시 각 이미지의 SHA256 해시를 `checksums.json`에 기록
- `python -m images download --verify`로 캐시 파일과 기록된 해시 대조 가능
- 파일 쓰기는 atomic write (tempfile + rename)로 중간 실패에 안전

## 의존성

- `requests` — HTTP 다운로드
- `core/` 패키지: `atomic_io`, `throttle`, `counter`, `config`
