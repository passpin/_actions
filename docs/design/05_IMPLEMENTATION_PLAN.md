# gmdtool implementation plan

## 0. 구현 전에 고정할 사항

이 문서 묶음의 설계를 baseline으로 삼는다.

초기 구현 중 바꿔도 되는 것:

- 일부 method 이름
- 파일 분할
- 작은 convenience API

쉽게 바꾸면 안 되는 것:

- raw data가 source of truth라는 원칙
- JSON knowledge DB 중심 구조
- semantic/raw dual view
- source/compiled JSON 분리
- Python이 control flow를 담당한다는 원칙
- 모든 known Object ID에 generated class 제공
- unknown data preservation

---

## 1. 기존 자산에서 가져올 것

C# runtime 자체는 유지할 필요가 없지만 다음은 reference/specification으로 활용한다.

- JSON catalog
- known Object ID 목록
- reverse-engineering 결과
- property/class mapping
- fixtures
- validation 사례
- 기존 test expectations
- exact numeric behavior
- structured value behavior
- lossless roundtrip behavior

C# 코드를 Python으로 기계 번역하는 것이 목표가 아니다.

현재 동작 중 가치 있는 behavior를 Python 구조로 다시 구현한다.

---

## 2. Phase 1 — JSON DB 정리

목표:

- source JSON schema 확정
- manifest
- known objects
- object definitions
- fragments
- enums
- references
- sources
- confidence/status
- compiler

완료 기준:

- 모든 source JSON이 JSON Schema validation 통과
- compiler가 충돌/누락을 잡음
- compiled catalog 생성
- known Object ID 전체가 compiled catalog에 존재
- detailed schema coverage 통계 출력 가능

---

## 3. Phase 2 — raw `.gmd` engine

목표:

- plist/container read
- level string decode
- RawLevel
- RawObject ordered pair representation
- exact raw preservation
- save

완료 기준:

- 실제 fixture load/save
- 변경 없는 파일에서 가능한 경우 byte-identical 또는 의미적으로 동일한 clean roundtrip
- duplicate key 보존
- unknown key 보존
- unknown object 보존
- malformed-but-preservable data 보존

실제 fixture를 synthetic fixture보다 우선한다.

---

## 4. Phase 3 — primitive codecs

구현:

- int
- bool
- string
- exact real
- text/base64
- group list
- structured value types

완료 기준:

- typed decode/encode roundtrip
- malformed typed value는 raw fallback
- exact number regression 통과

---

## 5. Phase 4 — semantic catalog layer

구현:

- object schema lookup
- property lookup by key/name/alias
- enum
- reference namespace
- fragment resolution
- variant semantic
- provenance/confidence access

완료 기준:

```python
obj.move_x
obj.target_group
obj.explain()
```

등이 catalog 기반으로 동작.

---

## 6. Phase 5 — generated object classes

구현:

```text
known_objects
  ↓
OBJ_<ID> registry
```

추가:

- generated `.pyi`

완료 기준:

- 모든 known Object ID에 class 존재
- schema가 없는 object도 생성/수정 가능
- schema 추가만으로 Python runtime 기능이 자동 확장

---

## 7. Phase 6 — query/edit API

구현:

- `level.objects`
- `filter`
- `exclude` 또는 최소 대체
- `update`
- `translate`
- `delete`
- transaction

완료 기준:

실제 대형 fixture에서 반복 수정이 자연스럽게 가능.

---

## 8. Phase 7 — ID/reference system

구현:

- GroupId
- ItemId
- ControlId
- allocation
- remap
- reference lookup
- copy isolation

완료 기준:

- namespace별 remap 독립
- known references 자동 추적
- raw unknown 값을 함부로 remap하지 않음

---

## 9. Phase 8 — generation ergonomics

gmdbuilder/G.js를 source/API 수준에서 검토한다.

특히:

- object creation
- trigger wrappers
- group allocation
- context management
- batch generation
- autoappend 계열
- validation ergonomics

가져오는 기준:

- AI code가 실제로 짧아지는가
- hidden state가 과하지 않은가
- raw object와의 관계가 명확한가

이 단계에서 convenience helper를 추가한다.

---

## 10. Phase 9 — AI workflow

구현:

- explain/inspect
- semantic diff
- validation
- patch format
- raw level JSON export/import

완료 기준:

AI가 다음 루프를 안정적으로 수행 가능.

```text
inspect
  ↓
edit/generate
  ↓
validate
  ↓
diff
  ↓
save
```

이 단계까지 완료되면 프로젝트를 실질적인 AI-first toolkit으로 본다.

---

## 11. Phase 10 — reverse knowledge expansion

runtime과 별도로 진행.

```text
tools/reverse/
```

에서:

- Broma parser
- decompile extraction
- schema comparison
- missing/conflict reports

결과는 source knowledge JSON에 반영.

runtime이 reverse tool 구현 세부사항을 알 필요는 없다.

---

## 12. Phase 11 — optional Geode oracle

장기 옵션.

실제 Geometry Dash / Geode 환경을 통해:

- object roundtrip
- serializer behavior
- parser behavior
- ambiguous property meaning

을 검증한다.

v1 blocker로 두지 않는다.

---

## 13. 권장 초기 패키지 구조

```text
gmdtool/
├─ gmdtool/
│  ├─ __init__.py
│  ├─ gmd.py
│  ├─ level.py
│  ├─ object.py
│  ├─ catalog.py
│  ├─ registry.py
│  ├─ numeric.py
│  ├─ structured.py
│  ├─ ids.py
│  ├─ query.py
│  ├─ references.py
│  ├─ validation.py
│  ├─ diff.py
│  ├─ patch.py
│  └─ builders.py
├─ data/
├─ tools/
│  ├─ build_catalog.py
│  └─ reverse/
├─ tests/
├─ fixtures/
└─ docs/
```

초기부터 모든 모듈을 잘게 쪼갤 필요는 없다.
기능이 실제로 커질 때 분리한다.

---

## 14. 테스트 원칙

### real fixture first

실제 GD가 만든 파일을 regression 기준으로 사용한다.

### roundtrip

수정하지 않은 데이터가 예상치 않게 바뀌지 않는지 확인한다.

### dual-view invariant

```python
obj.move_x = 120
assert obj.get_raw(28) == "120"
```

반대 방향도 검사한다.

### unknown preservation

unknown key/object가 semantic 작업 후에도 살아있는지 확인한다.

### catalog compiler test

AI가 잘못 수정한 JSON을 compiler가 가능한 한 빠르게 잡게 한다.

### performance

성능은 실제 문제가 측정될 때 최적화한다.

초기에는 수만~십만 object의 parse/filter/save benchmark 정도만 기록하고,
언어/구조를 성능 추측 때문에 복잡하게 만들지 않는다.

---

## 15. 초기 버전 완료 기준

첫 usable version:

- JSON catalog
- raw `.gmd` parsing/saving
- semantic property access
- raw property access
- 모든 known `OBJ_<ID>`
- object generation
- query/edit
- Group/Item/Control semantics

AI-first version:

위 기능 +
- explain
- references
- validation
- semantic diff
- patch
- procedural generation ergonomics 정리

---

## 16. 지금 일부러 보류할 것

다음은 필요성이 확인되기 전까지 만들지 않는다.

- GUI
- standalone exe
- 자체 scripting DSL
- arbitrary JSON expression language
- GD physics/gameplay simulator
- generic plugin architecture
- DI / service / repository 계층
- 복잡한 event system
- 고급 normalization policy
- 모든 trigger의 handcrafted helper

---

## 17. 최종 우선순위

```text
1. 데이터 정확성 / 보존
2. 구조화된 GD knowledge
3. AI가 이해하기 쉬운 API
4. 기존 level 수정 능력
5. procedural generation 편의
6. 검증 / diff / reference 분석
7. 개발 편의
8. 배포 편의
9. 성능 최적화
```

성능이 실제 병목으로 확인되면 그때 재평가한다.
