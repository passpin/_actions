# gmdtool JSON knowledge specification — draft v1

## 1. JSON 종류

gmdtool에서는 JSON을 세 범주로 구분한다.

### 1.1 Source Knowledge JSON

Geometry Dash에 대해 알고 있는 사실을 저장한다.

사람과 AI가 직접 수정할 수 있다.

### 1.2 Compiled Catalog JSON

source JSON을 compiler가 합치고 검증하여 runtime lookup에 최적화한 파일.

직접 수정하지 않는다.

### 1.3 Interchange JSON

level, patch, diff, explain 등의 데이터를 AI/외부 도구와 교환하기 위한 포맷.

knowledge DB와 별개다.

---

## 2. 권장 디렉터리

```text
data/
├─ manifest.json
├─ known_objects.json
├─ fragments.json
├─ enums.json
├─ references.json
├─ sources.json
├─ objects/
│  ├─ classic_triggers.json
│  ├─ camera.json
│  ├─ shaders.json
│  ├─ audio.json
│  ├─ gameplay_2_2.json
│  └─ ...
├─ schema/
│  └─ *.schema.json
└─ compiled/
   └─ catalog.json
```

reverse-engineering의 상세 evidence dump는 별도:

```text
tools/reverse/evidence/
```

knowledge DB에는 필요할 때 `evidence_refs`만 저장한다.

---

## 3. manifest.json

DB 전체 metadata와 source 목록.

예:

```json
{
  "$schema": "schema/manifest.schema.json",
  "schema_version": 1,
  "dataset": "gmdtool",
  "gd_version": "2.2081",
  "object_files": [
    "objects/classic_triggers.json",
    "objects/camera.json",
    "objects/shaders.json"
  ],
  "compiled": "compiled/catalog.json"
}
```

---

## 4. known_objects.json

알려진 모든 Object ID를 등록한다.

schema가 없어도 등록할 수 있다.

```json
{
  "schema_version": 1,
  "objects": [
    {
      "id": 1,
      "name": "Block",
      "confidence": "observed",
      "sources": ["fixture-object-ids"]
    },
    {
      "id": 901,
      "name": "Move Trigger",
      "confidence": "confirmed",
      "sources": ["geode-2.2081"]
    },
    {
      "id": 2743,
      "confidence": "observed",
      "sources": ["fixture-object-ids"]
    }
  ]
}
```

목적:

- 모든 known ID에 `OBJ_<ID>` 제공
- detailed schema coverage와 known ID coverage를 분리
- raw-only object도 정상적인 object로 취급

---

## 5. Object definition

권장 기본형:

```json
{
  "id": 901,
  "name": "Move Trigger",
  "aliases": ["Move"],
  "cpp_class": "EffectGameObject",
  "roles": ["trigger"],
  "schema_status": "partial",
  "confidence": "confirmed",
  "sources": ["geode-2.2081"],
  "fragments": [
    "object_base",
    "trigger_base"
  ],
  "properties": [
    {
      "key": 28,
      "name": "move_x",
      "wire_type": "real",
      "confidence": "confirmed",
      "sources": ["gd-2.2081-decompile"]
    },
    {
      "key": 51,
      "name": "target_group",
      "wire_type": "int",
      "semantic": {
        "kind": "reference",
        "namespace": "group"
      },
      "confidence": "confirmed",
      "sources": ["gd-2.2081-decompile"]
    }
  ]
}
```

---

## 6. Property definition

지원 가능한 필드의 기본 집합:

```json
{
  "key": 51,
  "name": "target_group",
  "aliases": ["target"],
  "wire_type": "int",

  "semantic": {
    "kind": "reference",
    "namespace": "group"
  },

  "default": 0,

  "constraints": {
    "min": 0
  },

  "confidence": "confirmed",
  "sources": ["geode-2.2081"],

  "evidence_refs": [
    "broma:EffectGameObject:m_targetGroupID"
  ],

  "notes": "optional human-readable note"
}
```

모든 필드를 채울 필요는 없다.

모르는 것을 억지로 추론하지 않는다.

---

## 7. wire_type과 semantic의 분리

### wire_type

실제 파일에서 어떻게 parse/serialize되는가.

초기 후보:

```text
int
real
bool
string
text
groups
particle
weighted_groups
sequence
group_remap
```

실제 raw representation이 다르지 않다면 의미 차이만으로 wire type을 늘리지 않는다.

### semantic

그 값이 무엇을 의미하는가.

예:

```json
{
  "kind": "reference",
  "namespace": "group"
}
```

또는:

```json
{
  "kind": "enum",
  "enum": "EasingType"
}
```

즉:

```text
wire_type = 어떻게 저장되는가
semantic  = 무엇을 뜻하는가
```

---

## 8. enums.json

```json
{
  "schema_version": 1,
  "enums": {
    "EasingType": {
      "wire_type": "int",
      "values": {
        "0": {"name": "none"},
        "1": {"name": "ease_in_out"},
        "2": {"name": "ease_in"}
      },
      "sources": ["geode-2.2081"]
    }
  }
}
```

property에서는:

```json
{
  "key": 30,
  "name": "easing",
  "wire_type": "int",
  "semantic": {
    "kind": "enum",
    "enum": "EasingType"
  }
}
```

---

## 9. references.json

ID namespace 정의.

```json
{
  "schema_version": 1,
  "namespaces": {
    "group": {
      "description": "Geometry Dash Group ID"
    },
    "item": {
      "description": "Geometry Dash Item ID"
    },
    "control": {
      "description": "Geometry Dash Control ID"
    }
  }
}
```

`GroupId`, `ItemId` 같은 Python class명은 knowledge DB에 넣지 않는다.

---

## 10. fragments.json

공통 property set을 재사용한다.

```json
{
  "schema_version": 1,
  "fragments": {
    "object_base": {
      "properties": [
        {
          "key": 2,
          "name": "x",
          "wire_type": "real"
        },
        {
          "key": 3,
          "name": "y",
          "wire_type": "real"
        }
      ]
    },
    "trigger_base": {
      "properties": [
        {
          "key": 62,
          "name": "spawn_triggered",
          "wire_type": "bool"
        }
      ]
    }
  }
}
```

### collision rule

여러 fragment가 같은 key를 다르게 정의하면 compiler가 임의로 하나를 고르지 않는다.

명시적인 object override가 없으면 compile error.

---

## 11. aliases

가능하면 별도 전역 `aliases.json`보다 정의 옆에 둔다.

```json
{
  "id": 901,
  "name": "Move Trigger",
  "aliases": ["Move"]
}
```

```json
{
  "key": 28,
  "name": "move_x",
  "aliases": ["x_offset"]
}
```

compiler가 runtime용 alias index를 만든다.

source of truth는 한 곳에만 둔다.

---

## 12. context-dependent meaning

property 의미가 다른 property의 값에 따라 바뀌는 것은 GD-specific knowledge이므로 제한된 declarative rule로 표현할 수 있다.

예:

```json
{
  "key": 51,
  "name": "target_id",
  "wire_type": "int",
  "variants": [
    {
      "when": {
        "property": "use_control_id",
        "equals": true
      },
      "semantic": {
        "kind": "reference",
        "namespace": "control"
      }
    },
    {
      "default": true,
      "semantic": {
        "kind": "reference",
        "namespace": "group"
      }
    }
  ]
}
```

허용 범위는 단순 comparison 중심으로 제한한다.

JSON 안에 arbitrary expression evaluator나 scripting language를 만들지 않는다.

---

## 13. sources.json

```json
{
  "schema_version": 1,
  "sources": {
    "geode-2.2081": {
      "kind": "binding",
      "gd_version": "2.2081",
      "title": "Geode GeometryDash.bro"
    },
    "gd-2.2081-decompile": {
      "kind": "decompile",
      "gd_version": "2.2081"
    },
    "fixture-2048": {
      "kind": "observed-fixture",
      "title": "2048 game preview"
    }
  }
}
```

object/property에는 source ID만 기록한다.

대형 decompile evidence는 외부에 둔다.

---

## 14. confidence와 schema_status

권장 confidence:

```text
unknown
inferred
observed
confirmed
```

권장 schema_status:

```text
raw_only
partial
complete
```

두 값은 서로 독립적이다.

---

## 15. Compiled catalog

source JSON은 읽기 쉽고 중복을 줄인다.

compiled catalog는 runtime lookup 성능을 위해 중복을 허용한다.

예:

```json
{
  "gd_version": "2.2081",
  "objects": {
    "901": {
      "id": 901,
      "name": "Move Trigger",
      "properties_by_key": {
        "28": {
          "name": "move_x",
          "wire_type": "real"
        }
      },
      "properties_by_name": {
        "move_x": 28,
        "x_offset": 28
      }
    }
  }
}
```

`data/compiled/catalog.json`은 generated artifact다.

---

## 16. Compiler validation requirements

compiler는 DB type checker 역할을 한다.

최소 검사 항목:

- duplicate Object ID
- duplicate canonical object name
- property key conflict
- canonical property name conflict
- alias collision
- missing fragment
- fragment cycle
- missing enum
- missing reference namespace
- missing source
- invalid `wire_type`
- invalid confidence/status
- variant가 존재하지 않는 property를 조건으로 참조
- unresolved fragment collision
- known object index와 detailed object definition 불일치
- compiled catalog stale 여부

---

## 17. Interchange formats

### Raw level

```json
{
  "format": "gmdtool.raw-level",
  "version": 1,
  "objects": [
    {
      "pairs": [
        [1, "901"],
        [28, "30"],
        [28, "40"]
      ]
    }
  ]
}
```

### Semantic explain

```json
{
  "object_id": 901,
  "name": "Move Trigger",
  "properties": [
    {
      "key": 28,
      "name": "move_x",
      "raw": "30",
      "value": 30,
      "wire_type": "real",
      "confidence": "confirmed"
    }
  ],
  "unknown": [
    [9999, "123456789"]
  ]
}
```

### Patch

```json
{
  "format": "gmdtool.patch",
  "version": 1,
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
}
```

Patch format에는 loop나 arbitrary code를 넣지 않는다.
절차적 작업은 Python이 담당한다.

### Diff

```json
{
  "format": "gmdtool.diff",
  "version": 1,
  "changed": [
    {
      "object": 382,
      "properties": {
        "move_x": {
          "before": 30,
          "after": 120
        }
      }
    }
  ],
  "added": [],
  "removed": []
}
```
