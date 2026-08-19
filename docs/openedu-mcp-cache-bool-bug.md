# OpenEdu MCP `get_article_summary` 캐시 히트 시 Boolean 타입 오류

## 요약

`get_article_summary` 툴을 캐시된 항목(예: `title=Saltlux`/`솔트룩스`, `language=ko`)으로 호출하면 아래 에러가 100% 재현됩니다.

```
Error executing tool get_article_summary: Article summary retrieval failed:
API Error (wikipedia): Unexpected error: Invalid variable type: value should be str, int or float, got True of type <class 'bool'>
```

- 서버: `openedu-mcp-server` v1.29.0
- 영향받는 툴: `get_article_summary` (다른 캐시 사용 툴도 동일 패턴일 가능성 있음, 미확인)
- 재현 위치: Goover MCP Hub 경유(`https://dev-mcp.goover.ai/mcp/@OpenEduMcp`) 및 원본 포트 직접 호출(`http://k8s-aws-pri.goover.ai:35618/mcp`) 둘 다 동일

## 재현 절차 및 근거

### 1) 최초(캐시 없음) 호출 — 성공

원본 포트로 `title=Saltlux, language=ko, include_educational_analysis=true`를 처음 호출했을 때는 정상 성공했습니다. 이때 응답의 `created_at == updated_at`으로, 캐시가 새로 생성된 최초 호출임을 확인했습니다.

### 2) 같은 키를 Hub 경유로 재호출 — 실패 (재현)

캐시가 이미 존재하는 상태에서 Hub 네임스페이스 엔드포인트로 동일 파라미터(`title=Saltlux, language=ko, include_educational_analysis=true`)를 호출하면 위 에러가 발생합니다. 동일 요청을 반복해도 매번 동일하게 실패 — **일시적 오류가 아니라 결정적으로 재현되는 버그**입니다.

### 3) `include_educational_analysis` 파라미터를 아예 생략 — 여전히 실패

스키마 기본값이 `true`이므로 생략해도 서버 내부적으로는 결국 `True`가 적용됩니다. 생략한 요청도 동일한 에러로 실패했습니다.

→ **결론: 클라이언트가 boolean을 명시하는지 여부와 무관합니다.** 문제는 요청 파싱이 아니라, 캐시에 저장된 값을 다시 꺼내 처리하는 경로에 있습니다.

### 4) 캐시가 없는 새 title로 Hub 호출 — 성공

한 번도 조회된 적 없는 title(`세종대왕`, 위키백과 상 `세종`으로 리다이렉트됨)로 동일 Hub 엔드포인트를 호출하면 정상 성공합니다.

→ **캐시 미스(cache miss)일 때는 항상 성공, 캐시 히트(cache hit)일 때만 실패**한다는 패턴이 확정적으로 관찰되었습니다.

## 정정 — 실제 원인 (2026-08-19 조사 완료, 수정됨)

**아래 "근본 원인 추정" 이하는 조사 전 가설이며, 일부는 사실과 다릅니다.** 실제로는 서로 무관한 두 개의 버그가 겹쳐 "캐시 히트일 때만 실패"처럼 보였습니다.

### 원인 A — aiohttp 쿼리 파라미터의 Python `bool` (에러의 직접 원인)

`src/api/wikipedia.py`의 `get_article_summary`는 REST summary(`/api/rest_v1/page/summary/...`)를 먼저 호출하고, 응답이 falsy면 action API로 폴백합니다. `_make_request`가 HTTP 404에서 `{}`를 반환하므로 **REST summary가 404인 제목만** 폴백을 탑니다. 그 폴백 params에 `'exintro': True, 'explaintext': True`가 있었고, aiohttp가 넘긴 값을 yarl이 명시적으로 거부하며 문제의 메시지를 던집니다.

문제의 문자열은 `wikipedia` 패키지가 아니라 **yarl**(`yarl/_query.py`)의 것입니다:

```python
if cls is not bool and isinstance(v, SupportsInt):
    return str(int(v))
raise TypeError("Invalid variable type: value should be str, int or float, got {!r} of type {}"...)
```

따라서 트리거는 **캐시 히트 여부가 아니라 제목의 REST 응답 코드**입니다:

| 제목 | `ko.wikipedia.org` REST summary | 결과 |
|---|---|---|
| `Saltlux` | 404 | 폴백 → bool params → 크래시 |
| `솔트룩스` | 200 | 정상 |
| `세종대왕` | 200 (`세종`으로 리다이렉트) | 정상 |

문서의 4번 관찰("캐시 없는 새 title은 성공")에서 쓰인 `세종대왕`이 마침 REST 200이었기 때문에 캐시 상태와 상관관계가 있는 것처럼 보였습니다. 참고로 캐시 히트 분기(`base_tool.py`)는 저장된 JSON을 반환할 뿐 Wikipedia 클라이언트를 아예 호출하지 않으므로 구조적으로 `APIError`를 낼 수 없습니다.

### 원인 B — 캐시 키가 파라미터를 전혀 포함하지 않음 (관찰을 왜곡한 진짜 캐시 버그)

`BaseTool.execute_with_monitoring`은 캐시 키를 `*args`/`**kwargs`로 만드는데, **19개 툴 메서드 전부**가 인자 없는 클로저와 `user_session`만 넘겼습니다. `title`/`language`/`include_educational_analysis`는 클로저 안에 갇혀 키에 반영되지 않았고, 결과적으로 `get_article_summary`의 캐시 키는 항상 `"wikipedia|get_article_summary"` 하나였습니다.

즉 **TTL 1시간 동안 어떤 제목으로 물어도 맨 처음 캐시된 문서가 반환**되었습니다. 수정 전 실측:

```
세종대왕/ko        -> title='솔트룩스'   ← 잘못된 문서
Photosynthesis/en  -> title='솔트룩스'   ← 잘못된 문서
```

`get_article_content`, `get_word_definition`, `get_paper_summary` 등 19개 메서드 전부 같은 문제가 있었습니다. 히트 여부가 파드/TTL에 따라 사실상 무작위여서 성공·실패가 캐시와 상관있어 보인 것도 이 때문입니다. 데이터 정확성 면에서는 원인 A보다 심각합니다.

### 원인 C — action API가 항상 영어 위키

`self.action_api_url`이 `https://en.wikipedia.org/w/api.php`로 하드코딩되어 `lang`이 무시되었습니다. 원인 A만 고치면 ko 폴백이 en 위키를 조회하므로 함께 수정했습니다.

### 수정 내용

- `src/api/wikipedia.py`: 폴백 params의 `True` → `'1'`; `_make_request`에 `_normalize_params` 가드 추가(bool → `'1'`, `False`/`None` → 제외)로 재발 방지; action API를 `lang` 기반으로 생성; `APIError` 이중 포장 제거.
- `src/tools/base_tool.py`: `execute_with_monitoring`에 `cache_params` 인자 추가(캐시 키·사용량 기록에만 사용). 누락 시 캐시를 비활성화하는 fail-safe. 캐시 키에 버전 접두사(`v2`)를 넣어 기존 오염 엔트리 무효화. 프로세스마다 달라지는 내장 `hash()`를 sha256으로 교체.
- `src/tools/{wikipedia,openlibrary,arxiv,dictionary}_tools.py`: 19개 호출부 전부에 `cache_params` 전달.
- 회귀 테스트: `tests/test_tools/test_base_tool.py`(신규), `tests/test_tools/test_wikipedia_tools.py::TestWikipediaClientQueryParams`.

### 수정 후 실측

```
Saltlux/ko         -> ToolError: Article not found: Saltlux (ko)   ← 크래시 대신 명확한 실패
솔트룩스/ko (2회)   -> 동일 내용 (캐시 히트 정상)
세종대왕/ko        -> title='세종'          ← 더 이상 오염되지 않음
Photosynthesis/en  -> title='Photosynthesis'
```

---

## 근본 원인 추정

1. 최초 호출(캐시 미스) 시점에는 정상적으로 응답을 만들고 캐시에 저장함.
2. 이후 같은 키로 재조회(캐시 히트)할 때, 캐시에서 값을 꺼내 다시 검증/직렬화하는 코드 경로를 타는 것으로 보임.
3. 이 경로의 어딘가에서 `include_educational_analysis` 값(Python `bool`)을 `str`, `int`, `float`만 허용하는 엄격한 타입 체크(`type(x) in (str, int, float)` 형태로 추정)에 통과시키다가 실패.
   - Python에서 `bool`은 `int`의 서브클래스지만, `isinstance(x, int)`가 아니라 `type(x) is int` 같은 엄격 비교를 쓰면 `bool` 값이 걸러지지 않고 예외가 발생하는 전형적인 패턴입니다.
4. 이 체크가 "API 파라미터 검증"이 아니라 "wikipedia API 호출/캐시 데이터 파라미터 바인딩" 쪽 코드에 있는 것으로 보이는 이유: 에러 메시지가 `API Error (wikipedia): ...`로 wikipedia 클라이언트 레이어에서 발생함을 시사합니다. 캐시에서 복원한 파라미터(혹은 캐시 자체에 저장된 메타데이터 값)를 다시 wikipedia API 호출 함수에 넘길 때, 이 값이 `bool`이라서 걸리는 것으로 추정됩니다.

## Claude Code로 확인/수정할 때 체크리스트

1. `openedu-mcp-server` 저장소에서 `get_article_summary` 구현을 찾는다. 캐시 조회(cache lookup/cache hit) 분기와 캐시 미스(신규 조회) 분기가 분리되어 있는지 확인한다.
2. 캐시 히트 분기에서 `include_educational_analysis` (혹은 캐시에 저장된 다른 boolean/optional 파라미터)를 다시 wikipedia API 클라이언트 함수에 전달하는 코드를 찾는다.
3. 에러 메시지 `"Invalid variable type: value should be str, int or float"`로 전체 코드베이스를 검색한다 (`grep -rn "should be str, int or float"` 또는 `grep -rn "Invalid variable type"`). 이 메시지는 `wikipedia`/`wikipedia-api` 파이썬 패키지 자체의 에러 문자열일 가능성이 높으므로, 해당 패키지에 어떤 값이 넘어가는지 호출부를 역추적한다.
4. 의심되는 타입 체크 패턴을 찾는다:
   ```python
   if type(value) not in (str, int, float):
       raise ...
   ```
   이런 코드가 있다면 `isinstance(value, (str, int, float)) and not isinstance(value, bool)` 조건과 정확히 반대로 동작하는 셈이라, `bool`이 걸러지지 않고 통과된 뒤 다른 곳(혹은 이 체크 자체)에서 예외가 남을 확인한다. 실제로는 캐시 히트 시에만 이 코드 경로를 타므로, **캐시 미스 분기와 캐시 히트 분기에서 같은 파라미터를 서로 다른 함수/다른 타입으로 넘기고 있을 가능성**이 높다 (예: 신규 조회 시엔 `bool`을 wikipedia API에 안 넘기지만, 캐시 히트 시엔 캐시에 저장된 JSON 값을 그대로 다시 넘기면서 타입이 바뀌는 경우 등).
5. 수정 방향(택1 또는 병행):
   - 캐시 히트 분기에서 wikipedia API 클라이언트에 boolean 파라미터를 넘기지 않도록 수정 (애초에 그 값이 wikipedia API 호출에 필요 없다면 캐시된 응답만 반환하고 끝내야 함).
   - 부득이하게 넘겨야 한다면 호출 직전에 `str(value)` 또는 `int(value)`로 명시 변환.
   - 근본적으로는 "캐시 히트 시 원본 API를 다시 호출하지 않아야 하는데 호출하고 있다"는 설계 문제일 가능성도 배제하지 말고 확인.
6. 수정 후 회귀 테스트:
   - 캐시 미스 상태의 새 title (`get_article_summary`, 처음 보는 title) → 성공 확인
   - 같은 title 재호출 (캐시 히트) → 성공 확인 (기존엔 여기서 실패)
   - `include_educational_analysis` 명시 `true`/`false`/생략 3가지 케이스 모두 캐시 히트 상태에서 성공 확인
   - 다른 캐시 사용 툴(`get_article_content` 등)도 동일 패턴(캐시 히트 시 boolean 파라미터로 실패)이 있는지 동일 방식으로 점검 권장

## 참고: 재현용 curl 명령어

```bash
# 1. 캐시 미스 확인용 새 title (매번 다른 제목 사용 권장)
curl -s -X POST https://dev-mcp.goover.ai/mcp/@OpenEduMcp \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -H "x-user-id: UID_c308d24f-99a0-4294-b599-d77411e55ebd" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"get_article_summary","arguments":{"title":"<새로운_제목>","language":"ko"}}}'

# 2. 같은 title 재호출 (캐시 히트) - 버그 재현
curl -s -X POST https://dev-mcp.goover.ai/mcp/@OpenEduMcp \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -H "x-user-id: UID_c308d24f-99a0-4294-b599-d77411e55ebd" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"get_article_summary","arguments":{"title":"<위와_동일한_제목>","language":"ko"}}}'
```

## 영향도

- 사용자가 같은 주제를 두 번째 물어보는 순간(캐시가 이미 생성된 이후) 실패하는 구조라, 실사용 시나리오에서 매우 자주 발생할 것으로 예상됨.
- Hub 로그 상 `[MCP RESPONSE]` 라인에 응답 바디/에러 여부가 기록되지 않아, 이런 이슈를 사후에 로그만으로 확인하기 어려움 (별도 개선 필요 사항, 본 문서 범위 밖).
