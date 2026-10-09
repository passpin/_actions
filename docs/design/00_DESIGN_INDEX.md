# gmdtool design index

이 문서 묶음은 gmdtool의 Python 재설계를 시작하기 전에 합의한 핵심 방향을 고정하기 위한 것이다.

## 프로젝트 한 줄 정의

> gmdtool은 Geometry Dash의 원본 데이터 구조를 숨기지 않으면서, AI가 레벨을 분석·수정·검증·생성하기 쉽게 만드는 데이터 중심 Python 툴킷이다.

핵심은 세 가지다.

1. **Python은 실행 언어다.**
   - 반복, 조건, 함수, 계산, 절차적 생성을 담당한다.
2. **JSON은 Geometry Dash 지식 DB다.**
   - Object ID, property, type, enum, reference, provenance 등 GD 자체에 대한 사실을 저장한다.
3. **raw `.gmd` 데이터가 최종 source of truth다.**
   - schema가 모르는 값, unknown object/property, duplicate key, 순서와 기타 원본 정보를 가능한 한 보존한다.

## 문서 구성

- `01_PHILOSOPHY_AND_SCOPE.md`
  - 목표, 비목표, 설계 원칙, 언어 선택, 외부 프로젝트 참고 원칙
- `02_DATA_ARCHITECTURE.md`
  - `.gmd` → raw → semantic → Python API 구조와 내부 데이터 모델
- `03_JSON_KNOWLEDGE_SPEC.md`
  - source JSON / compiled JSON / interchange JSON의 역할과 권장 명세
- `04_PYTHON_API_SPEC.md`
  - 공개 Python API의 1차 설계
- `05_IMPLEMENTATION_PLAN.md`
  - 구현 순서, 테스트 기준, 완료 조건, 보류 항목

## 설계 판단 기준

새 기능을 추가할 때 우선 다음을 묻는다.

> 이 기능이 AI가 `.gmd`를 더 적은 추측과 더 적은 코드로 정확하게 이해·수정·생성하게 하는가?

그렇지 않다면, 단순히 추상화가 가능하거나 다른 라이브러리에 존재한다는 이유만으로 추가하지 않는다.
