# core — 공유 인프라 패키지

모든 파이프라인(`laws`, `precedents`, `images`)에서 사용하는 공유 기능을 제공합니다.

## 모듈

### config.py
환경 설정 및 경로 관리

```python
# 환경 변수
LAW_OC              # 국가법령정보센터 OpenAPI 키 (필수)
WORKSPACE_ROOT      # 법령 데이터 저장소 경로 (기본: 상위 디렉토리)

# 설정값
REQUEST_DELAY_SECONDS = 0.2     # API 호출 간격
MAX_RETRIES = 3                 # 재시도 횟수
BACKOFF_BASE_SECONDS = 2.0      # 지수 백오프 베이스
CONCURRENT_WORKERS = 5          # 병렬 워커 수
BOT_AUTHOR = "legalize-kr-bot"  # 자동 커밋 작성자
```

### http.py
재시도 및 지수 백오프를 포함한 HTTP GET 요청

```python
from core.http import make_request
from core.throttle import Throttle

throttle = Throttle(0.2)
response = make_request(
    url="http://example.com/api",
    params={"key": "value"},
    throttle=throttle,
    api_key="YOUR_API_KEY",
    max_retries=3,
    backoff_base=2.0
)
```

- Rate limit (HTTP 429)에 자동 대응
- 요청 실패 시 지수 백오프로 재시도

### atomic_io.py
원자적 파일 쓰기 (tempfile → rename)

```python
from pathlib import Path
from core.atomic_io import atomic_write_text, atomic_write_bytes

# 텍스트 쓰기 (UTF-8)
atomic_write_text(Path("file.txt"), "내용")

# 바이너리 쓰기
atomic_write_bytes(Path("file.bin"), b"내용")
```

병렬 처리 환경에서 부분적인 쓰기로 인한 파일 손상을 방지합니다.

### throttle.py
Thread-safe rate limiter

```python
from core.throttle import Throttle

throttle = Throttle(delay_seconds=0.2)
throttle.wait()  # 필요시 대기 후 반환
```

각 파이프라인은 독립적인 Throttle 인스턴스를 사용하여 rate limit bucket을 분리합니다.

### counter.py
Thread-safe 진행 카운터

```python
from core.counter import Counter

counter = Counter()
counter.inc("cached")   # cached += 1
counter.inc("fetched")  # fetched += 1
counter.inc("errors")   # errors += 1

cached, fetched, errors = counter.snapshot()  # 스냅샷
```

병렬 작업의 진행 상황을 추적합니다.

## 사용 예시

이 패키지는 라이브러리로만 사용되며, CLI는 제공하지 않습니다.

```bash
# 파이썬 코드에서만 import
from core.config import WORKSPACE_ROOT, REQUEST_DELAY_SECONDS
from core.http import make_request
from core.throttle import Throttle
from core.atomic_io import atomic_write_text
from core.counter import Counter
```

## 환경 설정

`.env` 파일 또는 환경 변수 설정:

```bash
# 필수
LAW_OC=your-openapi-key

# 선택사항
WORKSPACE_ROOT=/path/to/legalize-kr
```
