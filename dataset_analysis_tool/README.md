# 도로 데이터셋 통합 재현 도구

네 원천 폴더만 읽어 전체 국가표준 기준망과 교통·정밀지도 관계를 재생성합니다. 네트워크 요청, API 수집, 환경변수·인증정보 읽기, 서비스 구현, 난이도 산정은 포함하지 않습니다.

## 실행

저장소 루트, Python 3.11 이상에서 실행합니다. 검증 환경은 Windows / Python 3.13.2이며 직접 의존성 버전은 `requirements.txt`에 고정했습니다.

```powershell
$env:PYTHONIOENCODING = 'utf-8'
.\.venv\Scripts\python.exe -m pip install -r dataset_analysis_tool/requirements.txt
.\.venv\Scripts\python.exe dataset_analysis_tool/test_contract.py
.\.venv\Scripts\python.exe dataset_analysis_tool/integrate.py --validate-only
```

다시 생성할 때는 **비어 있는 별도 출력 폴더**를 지정합니다. 기존 통합본을 덮어쓰지 않습니다.

```powershell
.\.venv\Scripts\python.exe dataset_analysis_tool/integrate.py --output .rebuild/processed --report .rebuild/validation.json
```

입력 해시 → 기준망 → View-T/API → HD → UTF-8 BOM CSV → 저장본 재읽기 검증 순으로 실행합니다. 검증 실패는 비정상 종료이며 자동 배치·정리하지 않습니다. 이미 실행한 `.rebuild/processed`에는 새 경로를 지정하세요. 배포된 `data/processed/`에는 최종 CSV 여섯 개만 둡니다.

## 입력 및 출력

- `data/raw/national_node_link/`: CSV·GPKG 및 원천/참조 manifest. GPKG 정밀 좌표를 사용합니다.
- `data/raw/hd_map/`: 사전 중복 제거된 51개 SHP 레이어. 압축 해제·신규 다운로드 없음.
- `data/raw/view_t/`: 2025 부산 평일 XLSX 세 개. 병합 헤더, 그룹, 원본 ITS 목록을 확인합니다.
- `data/raw/busan_link_traffic/`: `ADOPTION_MANIFEST.json` 및 링크 API 원문 93페이지. 원래 `SOURCE_MANIFEST.json`은 준비 당시 기록으로 보존합니다.

기본 테이블: `road_nodes.csv`, `road_links.csv`, `road_transitions.csv`, `road_traffic.csv`.
추가 관계: `view_t_groups.csv`(다중 참조·충돌 그룹 원시 통계), `hd_lane_link_matches.csv`(차로·기준 링크 후보와 원문 증거).

전체 컬럼, 키, 단위, 결측 규칙, 커버리지, 배포 한계는 `docs/도로_데이터셋_통합_인수인계.md`에 있습니다. 기계 검증 결과는 `docs/도로_데이터셋_통합_검증.json`입니다.

## 모듈

| 파일 | 역할 |
|---|---|
| `integrate.py` | 단일 오프라인 진입점. 생성/검증 모드 |
| `common.py` | 원천 SHA-256, 안전한 manifest 경로, CSV/JSON |
| `network.py` | 기준망, 연결·전환 후보, 회전 코드 |
| `traffic.py` | View-T 다단 헤더/그룹, API 원문, 충돌 차단 |
| `hd_map.py` | 구·신 모델 로더, 객체 충돌, 평면·방향·위상 후보 |
| `validate.py` | 저장본 PK/FK·형상·수치·출처 검증 및 커버리지 |
| `test_contract.py` | 역방향·교차 도로 오매칭 및 0/결측 회귀 검사 |

`assert` 검증을 사용하므로 Python의 `-O` 최적화 옵션으로 실행하지 마세요. 현재 원천 계약의 건수를 의도적으로 검사하므로 다른 버전 원천으로 교체할 때는 manifest와 명세를 함께 검토해야 합니다.

ID와 코드는 `dtype=str, keep_default_na=False, encoding='utf-8-sig'`로 읽습니다. 숫자형이 필요한 컬럼만 명시적으로 변환합니다. 통행망은 `road_in_use == 'True'`, 전환망은 `transition_in_use == 'True'`를 먼저 적용합니다. 전환 후보는 법적 허용 목록이 아닙니다.

HD는 전부 검토 후보이며 확정 대응은 없습니다. 원천 코드표 미확인·고도/버전 미검증을 근거로 차로별 진행 의미, 실제 차로 종단, 차로변경 거리를 보류했습니다. View-T 복수 그룹 충돌은 통합 수치를 NULL로 두고 그룹 원값을 남깁니다. 시간대 교통량 집계 단위와 공간평균 속도 정의가 확인되지 않아 밀집도는 계산하지 않습니다. API 속도는 단위 미확인 원시값만 제공합니다.

일부 SHP에 M좌표 또는 닫히지 않은 링 경고가 있으며 레이어별로 검증 JSON에 기록됩니다. 거리 계산은 XY/EPSG:5179만 사용하고 원본 SHP·SHX·DBF·PRJ·CPG는 변경하지 않습니다.
