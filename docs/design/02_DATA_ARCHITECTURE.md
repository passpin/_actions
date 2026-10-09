# gmdtool data architecture

## 1. 전체 흐름

```text
.gmd file
  ↓
container decode
(plist / base64 / gzip 등)
  ↓
raw level string
  ↓
RawLevel
  ├─ raw metadata/header
  └─ RawObject[]
       └─ ordered raw pairs
  ↓
JSON knowledge catalog
  ↓
semantic view
  ├─ OBJ_<ID>
  ├─ typed properties
  ├─ references
  └─ provenance
  ↓
Python query / edit / generation
  ↓
same raw model is mutated
  ↓
serialize
  ↓
.gmd
```

중요한 점은 raw → semantic 변환으로 raw 데이터가 사라지는 것이 아니라는 것이다.

semantic layer는 raw model 위의 view다.

---

## 2. RawObject의 source of truth

object 내부의 진짜 상태는 일반 dict가 아니라 ordered pair sequence다.

```python
[
    (1, "901"),
    (2, "100"),
    (3, "200"),
    (28, "30"),
    (28, "40"),
    (51, "7"),
]
```

이 형태를 쓰는 이유:

- duplicate key 보존
- property 순서 보존
- unknown key 보존
- malformed-but-preservable raw value 보존

일반 JSON object:

```json
{
  "28": "30"
}
```

를 source of truth로 사용하면 duplicate key를 잃는다.

---

## 3. Raw API

raw 수정은 정식 escape hatch다.

권장 최소 API:

```python
obj.get_raw(key)
obj.get_all_raw(key)

obj.set_raw(key, value)
obj.append_raw(key, value)

obj.remove_raw(key)
obj.remove_raw(key, occurrence=0)

obj.raw_pairs
obj.replace_raw_pairs(pairs)
```

`set_raw()`는 catalog에 없는 key라도 동작해야 한다.

예:

```python
obj.set_raw(9999, "123456789")
```

schema에 정의되지 않았다는 이유만으로 실패시키지 않는다.

---

## 4. Semantic API

semantic property는 raw pair를 JSON catalog를 통해 해석한 view다.

예:

```python
obj.move_x
obj.target_group

obj["move_x"]
obj.get("move_x")
obj.set("move_x", 120)
```

semantic mutation은 즉시 raw state에 반영된다.

raw mutation도 가능한 경우 semantic view에서 즉시 보인다.

별도 typed-state cache를 source of truth로 두지 않는다.

---

## 5. duplicate key 정책

duplicate key는 실제 파일에 존재할 수 있으므로 손실 없이 다뤄야 한다.

필수 raw API:

```python
obj.get_all_raw(28)
```

일반 semantic getter가 duplicate 중 어떤 값을 의미하는지는 실제 GD parser behavior에 근거해 정의해야 한다.

그 behavior가 불확실한 경우 추측하지 않고 명시적 occurrence API를 제공한다.

예:

```python
obj.get_raw(28, occurrence="first")
obj.get_raw(28, occurrence="last")
```

---

## 6. 모든 known Object ID에 class 제공

known Object ID가 존재하면 schema의 상세 수준과 상관없이 Python class를 제공한다.

```python
OBJ_1
OBJ_901
OBJ_2743
```

사람이 class 수천 개를 직접 작성하지 않는다.

```text
JSON catalog
  ↓
class factory / registry
  ↓
OBJ_<ID>
```

schema가 풍부한 object:

```python
OBJ_901(
    move_x=120,
    target_group=42,
    duration=0.5,
)
```

schema가 거의 없는 object:

```python
OBJ_2743(
    x=100,
    y=200,
)
obj.set_raw(123, "456")
```

완전히 미등록인 미래 ID는 필요하다면 runtime에 generic `OBJ_<ID>`를 생성할 수 있다.

---

## 7. generated type stubs

runtime class는 동적으로 생성하더라도, AI/IDE/static tooling을 위해 catalog에서 `.pyi` stub을 생성하는 것을 권장한다.

```text
JSON catalog
  ├─ runtime classes
  └─ generated .pyi
```

JSON이 source of truth이며 `.pyi`는 generated artifact다.

---

## 8. exact numeric model

GD 숫자 처리에서 불필요한 float 손실을 피한다.

`GDReal` 같은 exact representation을 유지하는 것을 권장한다.

요구사항:

- `"1"`과 `"1.0"`은 numeric equality에서 같을 수 있음
- 가능한 경우 original lexical form 보존
- 정확한 rational arithmetic 지원
- non-terminating decimal을 몰래 근사하지 않음
- serialization 시 불필요한 값 변경 방지

---

## 9. structured values

다음처럼 하나의 raw string 안에 구조가 들어가는 값은 typed codec을 가질 수 있다.

- particle
- weighted groups
- sequence
- group remap
- group list
- text/base64 계열

원칙:

```text
structured decode 실패
  ≠ object load 실패
```

decode에 실패하더라도 raw string을 보존한다.

---

## 10. ID namespace

동일한 정수라도 의미를 구분한다.

```python
GroupId(42)
ItemId(42)
ControlId(42)
```

semantic catalog에는 raw integer라는 사실과 reference namespace를 별도로 기록한다.

ID remap도 namespace별로 독립 실행한다.

---

## 11. level identity와 runtime identity

GD 자체에 저장되지 않는 runtime object identity가 필요할 수 있다.

목적:

- diff
- query selection
- copy/delete tracking
- transaction
- object replacement

이 ID는 `.gmd`의 semantic property로 취급하지 않는다.

구현은 단순한 monotonic UID 등으로 충분하며 과도한 identity system은 만들지 않는다.

---

## 12. mutation model

기본은 Python다운 in-place mutation을 권장한다.

필요하면:

```python
with level.edit():
    ...
```

또는 snapshot/transaction API를 제공한다.

중첩 transaction이 level 전체를 반복 clone하지 않도록 outermost transaction만 snapshot을 가지게 한다.

---

## 13. serialization modes

최소 두 mode를 고려한다.

### preserve

기본값.

- 변경하지 않은 raw 정보 유지
- 원본 ordering 유지
- unknown data 유지
- 가능한 경우 clean roundtrip

### normalize

명시적으로 요청했을 때만.

- canonical numeric/string formatting
- 정규화된 property ordering 등

normalize behavior는 나중에 정확히 정의한다.
초기에는 `preserve`가 우선이다.

---

## 14. raw level JSON

AI나 외부 도구와 raw 데이터를 교환해야 할 때 사용하는 별도 포맷.

예:

```json
{
  "format": "gmdtool.raw-level",
  "version": 1,
  "objects": [
    {
      "pairs": [
        [1, "901"],
        [2, "100"],
        [3, "200"],
        [28, "30"],
        [28, "40"]
      ]
    }
  ]
}
```

이 JSON은 knowledge catalog가 아니다.

```text
knowledge JSON = GD에 대해 우리가 아는 것
raw level JSON = 이 level에 실제로 들어 있는 것
```

둘을 절대 혼동하지 않는다.
