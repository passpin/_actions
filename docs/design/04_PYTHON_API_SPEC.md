# gmdtool Python API specification — draft v1

이 문서는 공개 API의 방향을 정하기 위한 1차 설계다.
세부 이름은 구현하면서 조정할 수 있지만, API 계층 자체는 유지하는 것을 권장한다.

---

## 1. 기본 import

```python
from gmdtool import GMD, GDLevel
from gmdtool.objects import OBJ_1, OBJ_901
```

가능하면 자주 쓰는 핵심 타입은 top-level에서도 접근 가능하게 한다.

---

## 2. load / save

```python
gmd = GMD.load("input.gmd")
level = gmd.level

gmd.save("output.gmd")
```

또는 편의 API:

```python
level = GDLevel.load("input.gmd")
level.save("output.gmd")
```

둘 중 하나를 canonical path로 정하고 나머지는 얇은 convenience layer로 둔다.

기본 serialization mode는 `preserve`.

```python
level.save("out.gmd", mode="preserve")
```

---

## 3. object creation

### generated object class

```python
obj = OBJ_901(
    x=100,
    y=200,
    move_x=120,
    target_group=42,
)
```

### generic creation

```python
obj = level.new_object(
    901,
    x=100,
    y=200,
    move_x=120,
)
```

둘은 동일한 underlying object model을 사용한다.

---

## 4. add / extend

```python
level.add(obj)

level.extend([
    OBJ_1(x=0, y=0),
    OBJ_1(x=30, y=0),
])
```

절차적 생성:

```python
for i in range(200):
    level.add(
        OBJ_1(
            x=i * 30,
            y=300 + math.sin(i / 10) * 100,
        )
    )
```

---

## 5. semantic property access

```python
obj.move_x
obj.move_x = 120

obj["move_x"]
obj["move_x"] = 120

obj.get("move_x")
obj.set("move_x", 120)
```

어느 스타일을 canonical로 할지는 구현 초기에 결정한다.

권장 방향:

- attribute: 가장 편한 typed surface
- `get/set`: dynamic AI workflows
- raw: escape hatch

---

## 6. raw API

```python
obj.get_raw(28)
obj.get_all_raw(28)

obj.set_raw(28, "120")
obj.append_raw(9999, "123")

obj.remove_raw(28)
obj.remove_raw(28, occurrence=0)

pairs = obj.raw_pairs
obj.replace_raw_pairs(pairs)
```

raw mutation은 catalog validation을 요구하지 않는다.

필요하면 명시적 validation을 별도로 실행한다.

---

## 7. query

```python
q = level.objects.filter(
    object_id=901,
    target_group=42,
)
```

추가 후보:

```python
level.objects.exclude(...)
level.objects.where(...)
```

초기에는 지나치게 많은 query DSL을 만들지 않는다.

Python callable을 허용할 수도 있다.

```python
level.objects.where(lambda obj: obj.x > 1000)
```

---

## 8. batch edit

```python
q.update(move_x=120)
q.translate(x=30, y=0)
q.delete()
```

값 기반 update 외에 callable update를 지원하면 AI 반복 코드가 줄어든다.

```python
q.update(
    move_x=lambda value: value + 50
)
```

---

## 9. copy and isolation

기본 copy:

```python
copied = q.copy()
```

reference namespace를 새 ID로 remap하는 isolated copy:

```python
copied = q.copy_isolated()
```

정확한 isolation 정책은 초기 구현 이후 테스트를 통해 정한다.

---

## 10. ID allocation

Low-level allocation remains available:

```python
group_id = level.new_group()
item = level.new_item()
control = level.new_control()
```

For scripting, a level-scoped facade is preferred:

```python
group = level.new.group()
a, b, c = level.new.groups(3)
items = level.new.items(10)
```

`level.new.group()` returns a level-bound `GroupHandle`, which is also a
`GroupId`/`int`, so it can be used directly as a normal GD group ID.

```python
group.move(x=30, duration=0.5)
group.alpha(0.5, duration=0.2)
group.call(delay=0.1)
```

The handle stores no serialized state and there is no process-global current
level.

ID namespace를 명시적으로 분리한다.

---

## 11. remap

```python
level.remap_groups({1: 100, 2: 101})
level.remap_items({...})
level.remap_controls({...})
```

semantic catalog의 reference metadata를 사용한다.

unknown/raw property는 임의로 remap하지 않는다.

---

## 12. references

```python
level.references(group=42)
level.references(item=12)
level.references(control=3)
```

추후 후보:

```python
level.dependencies(obj)
```

reference graph는 AI가 기존 level을 안전하게 수정하는 데 중요한 기능으로 본다.

---

## 13. trigger convenience helpers

빈번한 작업에는 얇은 helper를 제공할 수 있다.

```python
level.move(
    target=group,
    x=100,
    y=0,
    duration=0.5,
)

level.spawn(...)
level.toggle(...)
level.alpha(...)
```

원칙:

- helper는 thin wrapper
- raw object를 숨기지 않음
- helper가 없더라도 `OBJ_<ID>`로 같은 결과 생성 가능
- 반복/조건 DSL은 추가하지 않음

gmdbuilder / G.js의 API를 참고하되 AI에게 불필요한 hidden context는 피한다.

---

## 14. explain / inspect

```python
obj.explain()
level.explain(...)
```

결과는 JSON serializable이어야 한다.

포함 후보:

- Object ID
- canonical name
- C++ class
- raw key
- property name
- raw value
- typed value
- wire type
- semantic
- confidence
- source
- unknown properties

---

## 15. validation

```python
issues = level.validate()
```

issue 예:

```python
{
    "severity": "warning",
    "object": 152,
    "property": "target_group",
    "code": "dangling-reference",
    "message": "...",
}
```

validation은 최소 두 계층으로 생각한다.

### wire/syntax validation

- malformed int/real/bool
- structured value parse failure

### semantic validation

- invalid enum
- invalid reference namespace
- dangling reference
- known constraint violation

raw preservation과 validation failure는 별개다.
invalid data를 읽었다고 자동 삭제하지 않는다.

---

## 16. diff

```python
diff = before.diff(after)
```

또는:

```python
from gmdtool import diff
result = diff(before, after)
```

semantic diff 결과는 JSON serializable이어야 한다.

목표는 AI가:

> 내가 의도한 것만 바뀌었나?

를 빠르게 검증하게 하는 것이다.

---

## 17. patch

단순 작업을 위한 declarative patch:

```python
level.apply_patch({
    "operations": [
        {
            "select": {
                "object_id": 901,
                "properties": {
                    "target_group": 42
                }
            },
            "set": {
                "move_x": 120
            }
        }
    ]
})
```

복잡한 반복 작업은 patch format을 확장하지 말고 Python을 사용한다.

---

## 18. transaction

```python
with level.edit():
    ...
```

실패하면 rollback 가능.

중첩 transaction은 전체 level을 반복 clone하지 않는다.

outermost edit만 snapshot을 갖는 방식이 우선 후보다.

---

## 19. API 원칙

### explicit over magic

AI가 숨은 상태를 추적해야 하는 API보다 명시적인 API를 선호한다.

### raw is always reachable

고수준 helper를 사용해도 underlying raw object에 접근할 수 있다.

### generated, not handwritten

`OBJ_<ID>`와 type stub은 JSON에서 생성한다.

### JSON serializable inspection

inspect, explain, validation, diff는 가능한 한 JSON으로 바로 전달 가능해야 한다.

### one underlying state

semantic/raw view가 별도 데이터 사본을 갖지 않는다.
