# OpenEdu MCP

K-12부터 대학 수준까지 대응하는 교육 자료 검색 MCP 서버입니다. Open Library, Wikipedia, Dictionary API, arXiv 4개의 공개 API를 결합해 도서 추천, 위키 문서 요약, 어휘 분석, 학술 논문 검색까지 22개 도구로 제공합니다.

> 이 저장소는 [Cicatriiz/openedu-mcp](https://github.com/Cicatriiz/openedu-mcp)를 **Goover MCP Hub** 배포용으로 포크·수정한 버전입니다. 원본은 stdio transport 전용이었으며, 이 저장소에서 streamable HTTP transport 지원을 추가하고 기동 자체가 불가능했던 치명적 버그를 수정했습니다.

## 기본 정보

| 항목 | 내용 |
|---|---|
| MCP 명칭 | OpenEdu MCP |
| 원본 저장소 | https://github.com/Cicatriiz/openedu-mcp |
| 언어/런타임 | Python 3.9+, `mcp.server.fastmcp.FastMCP` |
| Transport | stdio(원본) + **streamable HTTP(신규 브릿지)** |
| 인증 | 없음 — 4개 데이터 소스 전부 공개 API, 키 불필요 |
| 로컬 상태 | SQLite(`/data/cache.db`, 캐시+사용량 통계 겸용) → **PVC 필요** |
| 도구 수 | 22개 |

## 소개

**English**

> OpenEdu MCP provides curated educational resources for K-12 through college-level learning by combining four public APIs: Open Library, Wikipedia, Dictionary API, and arXiv. It offers 22 tools covering educational book search and recommendations by grade level, Wikipedia article search with grade-appropriate summaries and featured articles, dictionary lookups with vocabulary complexity analysis and pronunciation guides, and academic paper search with research trend analysis by subject and academic level. Every tool tags results with grade-level appropriateness (K-2 through College) and curriculum alignment (e.g., Common Core). Responses are cached locally to reduce redundant API calls. No API keys or authentication are required for any of the underlying data sources.

**한글**

> OpenEdu MCP는 Open Library, Wikipedia, Dictionary API, arXiv 등 4개의 공개 API를 결합해 K-12부터 대학 수준까지 교육 자료를 제공하는 MCP입니다. 총 22개 도구로 학년별 교육 도서 검색·추천, 학년 수준에 맞춘 위키피디아 문서 검색·요약·오늘의 추천 문서, 어휘 난이도 분석과 발음 가이드를 포함한 사전 조회, 주제·학업 수준별 학술 논문 검색과 연구 동향 분석을 지원합니다. 모든 결과에 학년 적합도(K-2~College)와 교육과정 연계 정보(Common Core 등)가 태그로 붙습니다. 응답은 로컬 캐시로 저장되어 중복 호출을 줄이며, 별도의 API 키나 인증 없이 사용 가능합니다.

## 제공 도구 (22개)

| 카테고리 | 개수 | 도구명 |
|---|---|---|
| Open Library (도서) | 4 | `search_educational_books`, `get_book_details_by_isbn`, `search_books_by_subject`, `get_book_recommendations` |
| Wikipedia (문서) | 5 | `search_educational_articles`, `get_article_summary`, `get_article_content`, `get_featured_article`, `get_articles_by_subject` |
| Dictionary (사전/어휘) | 6 | `get_word_definition`, `get_vocabulary_analysis`, `get_word_examples`, `get_pronunciation_guide`, `get_related_vocabulary` |
| arXiv (학술논문) | 6 | `search_academic_papers`, `get_paper_summary`, `get_recent_research`, `get_research_by_level`, `analyze_research_trends` |
| 기타 | 2 | `handle_stdio_input`, `get_server_status` |

프롬프트/리소스는 제공하지 않는 순수 tool 기반 MCP입니다.

## 원본 대비 변경 사항

### 버그 수정

**1. import 시점 크래시 — 서버 자체가 기동 불가능했던 치명적 결함**

원본 `src/main.py` 하단에 미완성 SSE 실험 코드가 남아 있었습니다.

```python
@mcp.tool(route="/events", methods=["GET"])  # Assuming a route decorator might exist or be added to FastMCP
async def stream_events(request: Request) -> StreamingResponse:
```

`@mcp.tool()`은 `route`/`methods` 인자를 지원하지 않아 `TypeError`로 즉시 크래시가 발생했고, 이 때문에 stdio 모드로도 서버 실행 자체가 불가능한 상태였습니다. `sse_event_generator`와 `stream_events` 함수 전체(약 34줄)를 제거했습니다.

**2. `mcp` 패키지가 직접 의존성 목록에 없음**

`requirements.txt`/`pyproject.toml`에는 `fastmcp>=0.1.0`만 명시되어 있었지만, 실제 코드는 이와 별개인 `mcp.server.fastmcp`를 임포트하고 있었습니다. `fastmcp` 패키지의 전이 의존성으로 우연히 동작하던 상태라, 향후 `fastmcp` 의존성이 바뀌면 깨질 수 있는 취약한 구조였습니다. `mcp>=1.9.0,<2.0.0`을 직접 의존성으로 추가했습니다.

**3. HTTP transport 설정 누락**

```python
# 변경 전
mcp = FastMCP("openedu-mcp-server")

# 변경 후
mcp = FastMCP(
    "openedu-mcp-server",
    host=os.getenv("OPENEDU_MCP_HOST", "0.0.0.0"),
    port=int(os.getenv("OPENEDU_MCP_PORT", "8000")),
    stateless_http=True,
)
```

`import os` 누락도 함께 추가했습니다.

### 참고 — 코드 수정 없이 배포로 해결한 항목

`src/config.py`의 `load_config()`가 `config/default.yaml`을 프로세스 cwd 기준 상대경로로 탐색하는 구조라, Dockerfile의 `WORKDIR`을 레포 루트로 맞춰서 해결했습니다(코드 변경 불필요).

### HTTP 브릿지 추가

기존 `main()`(stdio 경로)은 전혀 건드리지 않고, `src/main.py`에 `main_http()` 함수를 신설했습니다.

```python
def main_http():
    """HTTP entry point for the OpenEdu MCP Server (streamable-http transport).

    Added for Goover MCP Hub deployment; the original stdio path via main()
    is untouched.
    """
    try:
        asyncio.run(initialize_services())

        import atexit
        atexit.register(lambda: asyncio.run(cleanup_services()))

        logger.info("Starting OpenEdu MCP Server (HTTP)...")

        mcp.run(transport="streamable-http")

    except KeyboardInterrupt:
        logger.info("Server shutdown requested")
    except Exception as e:
        logger.error(f"Server startup failed:{e}")
        sys.exit(1)
    finally:
        logger.info("OpenEdu MCP Server stopped")
```

신규 파일 `src/http_entrypoint.py`:

```python
"""
HTTP entrypoint for OpenEdu MCP Server (Goover MCP Hub deployment).

Runs the server over streamable-http transport by invoking main_http()
from main.py. The original stdio entrypoint (main.py's main(), run via
`python src/main.py`) is left completely untouched.

Must be run with the repository root as the working directory, since
config.py resolves "config/default.yaml" relative to the process cwd.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import main

if __name__ == "__main__":
    main.main_http()
```

`pyproject.toml`에 추가된 항목:

```toml
dependencies = [..., "mcp>=1.9.0,<2.0.0", ...]

[project.scripts]
openedu-mcp-server = "src.main:main"
openedu-mcp-server-http = "src.main:main_http"
```

trailing-slash 테스트 결과: bare `/mcp`는 200, `/mcp/`는 307을 반환하여, 별도 ASGI 래퍼 없이 정상 동작함을 확인했습니다.

## 실행 방법

### stdio (원본 방식, 그대로 유지)

```bash
python src/main.py
```

### streamable HTTP (신규, Goover MCP Hub 배포용)

```bash
python src/http_entrypoint.py
```

## Docker

### Dockerfile

```dockerfile
FROM python:3.11-slim-bookworm

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV OPENEDU_MCP_HOST=0.0.0.0
ENV OPENEDU_MCP_PORT=8000
ENV OPENEDU_MCP_CACHE_PATH=/data/cache.db

EXPOSE 8000

CMD ["python", "src/http_entrypoint.py"]
```

### 로컬 빌드 및 스모크 테스트

```bash
docker build --no-cache --platform linux/amd64 -t openedu-mcp:latest .
docker run -d --name openedu-mcp-test -p 8069:8000 openedu-mcp:latest
```

검증 완료 항목:
- `initialize` — 세션 ID 없음, stateless 정상 동작
- `tools/list` — 22개 도구 정상 반환
- `tools/call`(`get_word_definition`, `"photosynthesis"`) — dictionaryapi.dev 실제 호출 성공, 정의·발음·교육 메타데이터까지 정상 반환

## 이 포크만의 특징적인 사항

- 원본 저장소는 stdio 전용으로만 검증되어 있었고, 미완성 HTTP/SSE 코드가 import 시점에 서버 전체를 크래시시키는 상태로 방치되어 있었습니다. 단순 설정 누락 수준이 아니라 **실행 자체가 불가능한 수준의 결함**이었습니다.
- `mcp` 패키지가 직접 의존성이 아니라 `fastmcp` 패키지의 전이 의존성으로만 존재해 패키징이 취약했습니다. 직접 의존성으로 명시해 향후 breaking change에 대비했습니다.
- config 로더가 상대경로에 의존하는 구조라, 코드 수정 대신 Dockerfile `WORKDIR`로 우회 해결했습니다.
- 캐시 서비스와 사용량 통계 서비스가 동일한 SQLite 파일을 공유합니다.
- 4개 외부 API(Open Library, Wikipedia, Dictionary API, arXiv) 모두 인증/API 키가 필요 없어 자격증명 관리 이슈가 없습니다.

## 라이선스

원본 저장소([Cicatriiz/openedu-mcp](https://github.com/Cicatriiz/openedu-mcp))의 라이선스를 따릅니다. 재배포·상업적 사용 전 원본 LICENSE 파일을 반드시 확인하시기 바랍니다.