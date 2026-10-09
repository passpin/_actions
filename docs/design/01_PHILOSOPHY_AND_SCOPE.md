# gmdtool philosophy and scope

## 1. 목적

gmdtool의 목적은 사람이 새로운 GD 전용 프로그래밍 언어를 배우게 하는 것이 아니다.

목적은 **AI가 Geometry Dash level data를 구조적으로 읽고, 기존 `.gmd`를 안전하게 수정하고, 필요하면 Python으로 반복적·절차적인 구조를 쉽게 생성하도록 돕는 것**이다.

주요 사용 흐름은 다음과 같다.

```text
사용자 지시
  ↓
AI가 level 분석 / Python 코드 작성
  ↓
gmdtool
  ↓
.gmd 생성 또는 수정
  ↓
검증 / diff / Geometry Dash 확인
  ↓
사용자 피드백
  ↓
AI가 재수정
```

일반 사용자용 GUI 도구나 독립 실행형 소비자 앱 배포는 핵심 목표가 아니다.

---

## 2. 핵심 철학

### 2.1 raw data가 진실이다

Python class나 JSON schema는 `.gmd`를 이해하기 위한 layer이지, 실제 데이터를 대체하지 않는다.

- unknown property를 버리지 않는다.
- unknown object를 버리지 않는다.
- duplicate property를 가능한 한 보존한다.
- property 순서를 가능한 한 보존한다.
- object 순서와 level layout을 가능한 한 보존한다.
- 변경하지 않은 정보는 변경하지 않는다.

### 2.2 schema는 whitelist가 아니다

schema에 정의되어 있지 않더라도 raw key/value를 읽고 수정할 수 있어야 한다.

즉 schema는:

> "수정 가능한 것의 목록"

이 아니라:

> "raw data를 더 정확하고 편하게 이해하기 위한 knowledge layer"

다.

### 2.3 아는 것과 모르는 것을 구분한다

GD에 대한 지식은 가능한 경우 다음 상태를 가진다.

- `confirmed`
- `observed`
- `inferred`
- `unknown`

또한 schema가 얼마나 많이 밝혀졌는지와 정보 자체의 신뢰도는 분리한다.

예:

```text
schema_status = partial
confidence = confirmed
```

이는 "현재 기록된 내용은 확실하지만 아직 모든 property를 찾은 것은 아니다"라는 뜻이다.

### 2.4 GD-specific knowledge는 JSON에 둔다

다음은 가능한 한 Python 코드가 아니라 JSON 지식 DB에 둔다.

- Object ID
- object 이름과 alias
- property key
- property semantic name
- raw wire type
- reference namespace
- enum
- object/property relation
- version
- provenance/source
- 단순한 context-dependent semantic rule

반면 다음은 Python이 담당한다.

- `for`, `if`, 함수
- 계산
- procedural generation
- query execution
- ID allocation algorithm
- file IO
- mutation
- diff / validation 실행
- context manager 등 실제 프로그래밍 동작

한 문장으로:

> **JSON에는 Geometry Dash에 대해 알고 있는 사실을 저장하고, Python에는 그 사실을 이용해 무엇을 할지 구현한다.**

### 2.5 semantic API와 raw API는 같은 데이터를 본다

다음 두 조작은 별도의 복사본을 수정하면 안 된다.

```python
obj.move_x = 120
obj.set_raw(28, "120")
```

둘 다 같은 ordered raw pair sequence를 바라보는 두 개의 view여야 한다.

그래야:

```python
obj.move_x = 120
assert obj.get_raw(28) == "120"
```

와 반대 방향도 즉시 일치한다.

### 2.6 Python 자체를 DSL로 사용한다

반복, 조건, 함수와 계산을 표현하기 위해 자체 scripting language를 만들지 않는다.

```python
for i in range(200):
    ...
```

면 충분하다.

JSON에 `loop`, `while`, `function` 같은 프로그래밍 언어 구조를 만들지 않는다.

---

## 3. 목표

### 3.1 이해

AI가 기존 level을 보고 다음을 빠르게 알 수 있어야 한다.

- object의 Object ID와 알려진 이름
- 각 property의 raw key와 semantic name
- raw value와 typed value
- Group / Item / Control 등 reference
- schema confidence / provenance
- unknown data

### 3.2 수정

다음과 같은 작업이 짧고 명시적이어야 한다.

```python
level.objects.filter(
    object_id=901,
    target_group=42,
).update(move_x=120)
```

### 3.3 생성

절차적인 대량 생성은 일반 Python으로 쉽게 표현할 수 있어야 한다.

```python
for i in range(200):
    level.add(
        OBJ_1(
            x=i * 30,
            y=300 + math.sin(i / 10) * 100,
        )
    )
```

### 3.4 검증

AI가 만든 결과에 대해 최소한 다음을 검사할 수 있어야 한다.

- malformed raw value
- invalid enum
- ID namespace 오류
- dangling reference
- known schema와의 불일치
- 예상하지 못한 unknown data
- 수정 전후 semantic diff

---

## 4. 비목표

초기 프로젝트 범위에 포함하지 않는다.

- SPWN clone
- G.js 전체 복제
- 별도의 GD scripting language
- Python control flow를 JSON으로 표현
- GUI editor 전체 구현
- GD gameplay engine의 Python simulation
- Object ID마다 사람이 직접 Python class 작성
- 불확실한 schema를 억지로 complete 처리
- 모든 사용자에게 standalone executable 배포

---

## 5. Python 선택

현재 목표에서는 C#의 주된 장점은 다음 정도다.

- 더 높은 실행 성능
- static typing / compile-time checking
- standalone executable 배포
- 비교적 예측 가능한 runtime behavior

하지만 gmdtool의 핵심 작업은 주로 문자열 parsing, list/dict lookup, filtering, JSON, gzip, file IO이고, 수만~십만 object 수준은 처음부터 C#을 요구하는 문제로 보지 않는다.

Python의 장점은 프로젝트 목표와 직접 연결된다.

- AI가 작성하기 쉬움
- procedural generation이 자연스러움
- engine과 scripting layer를 분리할 필요가 없음
- 개발 iteration이 빠름
- 데이터 처리 생태계가 큼

성능 문제가 실제로 측정될 때 특정 hot path만 최적화한다.

---

## 6. gmdbuilder / G.js 참고 원칙

이 프로젝트들과 경쟁하기 위해 기능을 억지로 구분하지 않는다.

좋은 API와 설계는 참고한다.

특히 다음을 살펴볼 가치가 있다.

- object creation
- typed wrappers
- Group/Item allocation
- batch object operations
- selection/edit/delete
- trigger helper
- context manager
- validation
- procedural scripting ergonomics

다만 가져올 때 다음 기준으로 분류한다.

- GD 자체에 대한 사실 → JSON
- 실행 방식 / scripting ergonomics → Python
- 과도한 hidden state / magic → 신중하게 채택
- AI가 추론하기 어려운 API → 피한다

gmdbuilder의 존재 때문에 gmdtool이 scripting을 포기할 필요는 없다.
gmdtool은 scripting을 지원하되, **풍부한 구조화 GD knowledge와 raw/semantic dual view를 핵심 기반으로 삼는다.**
