# surviving-busan-roads
A pre-trip route analysis service that evaluates driving difficulty and road hazards across Busan.


## 현재 실행 방법
Node.js와 Python 3.11 이상이 필요합니다.

1. `npm ci`
2. `.env.example`을 참고해 `.env.local`에 카카오 JavaScript 키를 설정합니다. SDK 도메인에 `http://localhost:5173`을 등록합니다.
3. Gemini 해설을 쓰려면 `.env.server`에 `LLM_PROVIDER=gemini`, `GEMINI_API_KEY`, `GEMINI_MODEL=gemini-3.5-flash-lite`, `ENABLE_LLM=true`를 설정합니다. 실제 키는 저장소에 포함하지 않습니다.
4. 도로 분석에는 별도로 확보한 통합 CSV 6개가 필요합니다. `integrated_roads/`에 road_nodes.csv, road_links.csv, road_transitions.csv, road_traffic.csv, view_t_groups.csv, hd_lane_link_matches.csv를 둡니다. 원본 데이터와 생성 DB는 이 저장소에 포함하지 않습니다.
5. `npm run prepare:data`로 로컬 DB를 생성한 뒤 `npm run dev`로 실행합니다. 기본 주소는 http://localhost:5173 입니다.
6. 검증은 `npm test`, 화면 빌드는 `npm run build`입니다. 테스트에도 통합 CSV 및 생성 DB가 필요합니다.

자체 길찾기는 방향 도로망 기반 실험 기능이며 회전 제한·실제 출입구의 누락으로 통행 허용을 보장하지 않습니다. 난이도는 임시 기준이며 과거 교통 통계를 사용합니다. Gemini는 평가 근거를 선택하고 서버가 검증된 내용으로 해설을 구성하며, 호출 실패 시 규칙 기반 안내임을 표시합니다.
상세 설정과 한계는 difficulty/README.md를 참고하세요.
