"""Temporary, deterministic rules. No routing and no lane-change-count inference."""
import json
import math
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from .build_db import DB, CONFIG, coordinates

PERIODS = ['4시~10시', '11시~17시', '18시~24시']
CATEGORIES = ['도로주행 능력', '연속 상황 대응', '교통 상황 대응']


def settings():
    cfg = json.loads(CONFIG.read_text(encoding='utf-8'))
    for key, value in cfg.items():
        if key != 'version' and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
            raise ValueError('임시 산식 설정이 올바르지 않습니다: ' + key)
    if not 0 <= cfg['straight_deg'] < cfg['turn_full_deg'] <= 180:
        raise ValueError('회전각 설정 범위를 확인하세요.')
    if cfg['score_half_saturation'] <= 0:
        raise ValueError('점수 완화 기준은 0보다 커야 합니다.')
    if cfg['continuous_distance_m'] <= 0 or cfg['intersection_full_arms'] <= 2:
        raise ValueError('거리·갈래 수 설정을 확인하세요.')
    if cfg['congestion_frequency_weight'] + cfg['congestion_time_weight'] <= 0:
        raise ValueError('혼잡 지표 가중치가 필요합니다.')
    return cfg


@contextmanager
def connection(path=DB):
    db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    try:
        yield db
    finally:
        db.close()


def catalog(path=DB):
    with connection(path) as db:
        return [{'id': r['id'], 'name': r['name'], 'link_ids': json.loads(r['link_ids'])}
                for r in db.execute('SELECT * FROM validation_routes ORDER BY rowid')]


def evaluate(request, path=DB):
    if not isinstance(request, dict):
        raise ValueError('경로 입력은 JSON 객체여야 합니다.')
    ids = request.get('link_ids')
    if not isinstance(ids, list) or not 1 <= len(ids) <= 1000 or any(not isinstance(i, str) or not i.isdigit() or len(i) > 30 for i in ids):
        raise ValueError('주행 순서의 도로 ID 문자열을 1~1000개 전달하세요.')
    period = request.get('period', PERIODS[1])
    day = request.get('day_type', 'weekday')
    if period not in PERIODS or day not in ['weekday', 'weekend']:
        raise ValueError('지원 기간 또는 요일을 확인하세요.')
    cfg = settings()
    # Monotonic soft scale: preserves zero/ordering, avoids hard clipping and reserves headroom.
    def scale(raw):
        return round(100 * raw / (raw + cfg['score_half_saturation']), 2)

    with connection(path) as db:
        built = json.loads(db.execute("SELECT value FROM meta WHERE key='build_config'").fetchone()[0])
        if any(built[k] != cfg[k] for k in ['junction_edge_m', 'junction_diameter_m', 'arm_angle_deg']):
            raise ValueError('교차로 추정 설정이 변경되었습니다. npm run prepare:data로 DB를 다시 만드세요.')
        links = []
        for i in ids:
            row = db.execute('SELECT * FROM links WHERE id=?', (i,)).fetchone()
            if row is None or not row['in_use']:
                raise ValueError('없는 도로 또는 미사용 도로입니다: ' + i)
            links.append(dict(row))
        trans = []
        for a, b in zip(ids, ids[1:]):
            t = db.execute('SELECT * FROM transitions WHERE in_id=? AND out_id=?', (a, b)).fetchone()
            if t is None or not t['in_use']:
                raise ValueError('연결되지 않은 도로 순서입니다: ' + a + ' → ' + b)
            if t['permission'] == 'prohibited_recorded':
                raise ValueError('기록된 금지 전환은 평가할 수 없습니다: ' + a + ' → ' + b)
            trans.append(dict(t))
        offsets = [request.get('start_offset_m', 0), request.get('end_offset_m', links[-1]['length_m'])]
        for value, limit in zip(offsets, [links[0]['length_m'], links[-1]['length_m']]):
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= limit:
                raise ValueError('시작·종료 링크의 통과 위치가 범위를 벗어났습니다.')
        lengths = [r['length_m'] for r in links]
        lengths[0] -= offsets[0]
        lengths[-1] = offsets[1]
        if len(links) == 1:
            lengths[0] = offsets[1] - offsets[0]
        if lengths[0] <= 0 or lengths[-1] <= 0:
            raise ValueError('양 끝 링크의 실제 통과 길이는 0보다 커야 합니다.')
        prefix = [0.0]
        for length in lengths:
            prefix.append(prefix[-1] + length)
        traffic = []
        for index, link in enumerate(links):
            state = {'index': index, 'link_id': link['id'], 'score': None, 'speed': None,
                     'frequency': None, 'congestion_time': None, 'group_id': None,
                     'status': 'missing' if day == 'weekday' else 'not_applicable_weekend'}
            if day == 'weekday':
                rows = db.execute("SELECT * FROM traffic WHERE link_id=? AND source='view_t' AND year='2025' AND day_type='weekday' AND period=? AND status='exact_its_reference'", (link['id'], period)).fetchall()
                if len(rows) == 1:
                    selected = rows[0]
                    state.update(speed=selected['speed'], group_id=selected['group_id'])
                    congestion = db.execute("SELECT * FROM traffic WHERE link_id=? AND source='view_t' AND group_id=? AND year='2025' AND day_type='weekday' AND period='weekday_all' AND status='exact_its_reference'", (link['id'], selected['group_id'])).fetchall()
                    if len(congestion) == 1:
                        c = congestion[0]
                        state.update(frequency=c['frequency'], congestion_time=c['congestion_time'])
                        values = [(c['frequency'], cfg['congestion_frequency_weight']),
                                  (c['congestion_time'], cfg['congestion_time_weight'])]
                        available = [(v, w) for v, w in values if v is not None and w > 0]
                        if available:
                            base = sum(v*w for v, w in available) / sum(w for _, w in available)
                            speeds = [r[0] for r in db.execute("SELECT speed FROM traffic WHERE link_id=? AND group_id=? AND source='view_t' AND year='2025' AND day_type='weekday' AND status='exact_its_reference' AND speed>0", (link['id'], selected['group_id']))]
                            decline = max(0, 1-selected['speed']/max(speeds)) if len(speeds) >= 2 and selected['speed'] is not None and selected['speed'] > 0 else None
                            state.update(score=scale(base*(1+cfg['speed_decline_weight']*(decline or 0))),
                                         speed_decline=decline, status='historical_proxy')
                    if state['score'] is None and state['speed'] is not None:
                        state['status'] = 'speed_only_unrated'
            traffic.append(state)
        nodes = {t['node_id']: dict(db.execute('SELECT * FROM nodes WHERE id=?', (t['node_id'],)).fetchone()) for t in trans}
        junctions = {n['junction_id']: dict(db.execute('SELECT * FROM junctions WHERE id=?', (n['junction_id'],)).fetchone())
                     for n in nodes.values() if n['junction_id']}
        runs = []
        for index, t in enumerate(trans):
            group = nodes[t['node_id']]['junction_id']
            if runs and group and runs[-1]['junction_id'] == group:
                runs[-1]['end'] = index
            else:
                runs.append({'start': index, 'end': index, 'junction_id': group})
        details, events = [], []

        def detail(category, item, base_score, location, evidence, link_index, position, **extra):
            context = traffic[link_index]
            adjusted = base_score
            if category != CATEGORIES[2] and base_score is not None and context['score'] is not None:
                adjusted = base_score*(1+cfg['traffic_amplification']*context['score']/100)
            row = {'id': 'e' + str(len(details)), 'category': category, 'item': item,
                   'base_score': round(base_score, 2) if base_score is not None else None,
                   'unmodified_score': scale(base_score) if base_score is not None and category != CATEGORIES[2] else base_score,
                   'score': (scale(adjusted) if category != CATEGORIES[2] else adjusted) if adjusted is not None else None,
                   'location': location, 'evidence': evidence, 'position_m': round(position, 3),
                   'link_id': ids[link_index], 'traffic_status': context['status'],
                   'traffic_modifier': context['score'] if category != CATEGORIES[2] else None, **extra}
            details.append(row)
            return row

        for run in runs:
            first, last = run['start'], run['end']
            group = run['junction_id']
            node = nodes[trans[first]['node_id']]
            location = junctions[group]['name'] if group else node['name'] or node['id']
            angle = (trans[last]['departure'] - trans[first]['approach'] + 180) % 360 - 180
            turn_score = max(0, abs(angle)-cfg['straight_deg'])/(cfg['turn_full_deg']-cfg['straight_deg'])*100
            position = prefix[first+1]
            event_rows = []
            selected_drop = max(trans[first:last+1], key=lambda t: t['drop_ratio'])
            drop_index = first + trans[first:last+1].index(selected_drop)
            ratio = selected_drop['drop_ratio']
            event_rows.append(detail(CATEGORIES[0], '차로 수 감소', 100*ratio, location,
                f"선택 전환 {selected_drop['in_id']} → {selected_drop['out_id']}: 차로 감소 비율 {ratio:.1%}. 실제 종단·변경 횟수 아님.", drop_index, prefix[drop_index+1], ratio=ratio,
                node_id=selected_drop['node_id'], in_link_id=selected_drop['in_id'], out_link_id=selected_drop['out_id']))
            event_rows.append(detail(CATEGORIES[0], '회전', turn_score, location,
                f"진입 {ids[first]} → 최종 진출 {ids[last+1]}: 회전각 {angle:.2f}°. 교차로 내부 {last-first+1}개 전환을 한 이동으로 계산.", first, position, angle_deg=round(angle, 4)))
            arm_count = junctions[group]['arms'] if group else None
            complexity = max(0, arm_count-2)/(cfg['intersection_full_arms']-2)*100 if arm_count is not None else None
            event_rows.append(detail(CATEGORIES[0], '교차로 갈래 수', complexity, location,
                f"자동 추정 {arm_count}갈래. 위치·연결·외부 도로 방향 기반, 진입·진출 중복 제거." if group else '실제 교차로 묶음 미확인: 갈래 수 미평가.', first, position, arms=arm_count, status='estimated' if group else 'unrated'))
            candidates = [nodes[t['node_id']] for t in trans[first:last+1]]
            merge = any(n['merge_candidate'] for n in candidates)
            diverge = any(n['diverge_candidate'] for n in candidates)
            event_rows.append(detail(CATEGORIES[0], '합류·분기', cfg['merge_score'] if merge or diverge else 0, location,
                f"원천 연결 위상: 합류 후보 {'있음' if merge else '없음'}, 분기 후보 {'있음' if diverge else '없음'}. 시설 확정 아님.", first, position, merge=merge, diverge=diverge))
            events.append({**run, 'location': location, 'angle': angle, 'drop': ratio,
                           'direction': 'left' if angle < -cfg['straight_deg'] else 'right' if angle > cfg['straight_deg'] else 'straight',
                           'hard': max(r['base_score'] or 0 for r in event_rows) > 0,
                           'peak': max(r['base_score'] or 0 for r in event_rows),
                           'position': position, 'evidence_ids': [r['id'] for r in event_rows]})
        junction_events = [(i, e) for i, e in enumerate(events) if e['junction_id']]
        blocks = []
        for (ia, a), (ib, b) in zip(junction_events, junction_events[1:]):
            start_link, end_link = a['end']+1, b['start']
            segment = ids[start_link:end_link+1]
            length = prefix[end_link+1]-prefix[start_link]
            status = 'estimated' if a['junction_id'] != b['junction_id'] else 'returns_to_same_junction'
            blocks.append({'start': a['location'], 'end': b['location'], 'link_ids': segment,
                           'length_m': round(length, 3), 'status': status,
                           'start_event': ia, 'end_event': ib})
            if status != 'estimated':
                continue
            local = [e for e in events[ia:ib+1] if e['hard']]
            for before, after in zip(local, local[1:]):
                gap = max(0, after['position']-prefix[before['end']+1])
                if gap > cfg['continuous_distance_m'] or length > cfg['continuous_distance_m']:
                    continue
                kinds = []
                if (before['direction'], after['direction']) == ('left', 'right'):
                    kinds.append('좌회전 후 우회전')
                if (before['direction'], after['direction']) == ('right', 'left'):
                    kinds.append('우회전 후 좌회전')
                if before['drop'] > 0 and after['direction'] != 'straight':
                    kinds.append('차로 수 감소 후 회전')
                if before['direction'] != 'straight' and after['drop'] > 0:
                    kinds.append('회전 후 차로 수 감소')
                if not kinds:
                    kinds.append('기타 어려운 상황 연속')
                proximity = 1-max(gap, length)/cfg['continuous_distance_m']
                base_score = min(100, cfg['continuous_base'] + cfg['continuous_proximity']*proximity)
                # One pair contributes once even when multiple labels apply.
                detail(CATEGORIES[1], ' · '.join(kinds), base_score,
                    before['location'] + ' → ' + after['location'],
                    f"추정 블록 {length:.2f}m, 상황 사이 거리 {gap:.2f}m. 실제 차로변경 위치·횟수는 평가하지 않음.",
                    before['end']+1, before['position'], block_length_m=round(length, 3),
                    gap_m=round(gap, 3), kinds=kinds, source_events=before['evidence_ids']+after['evidence_ids'])
        if not any(r['category'] == CATEGORIES[1] for r in details):
            complete = any(b['status'] == 'estimated' for b in blocks)
            detail(CATEGORIES[1], '연속 상황', 0 if complete else None, '검증용 경로',
                   '완전한 추정 블록에서 임시 조건에 해당하는 연속 상황 없음.' if complete else '서로 다른 교차로 사이의 완전한 블록이 없어 미평가.', 0, 0)
        seen_groups = set()
        for state in traffic:
            i = state['index']
            key = state['group_id'] if state['score'] is not None else ('unrated', i)
            if key in seen_groups:
                continue
            seen_groups.add(key)
            detail(CATEGORIES[2], '과거 교통 상황', state['score'], links[i]['name'] or ids[i],
                   f"2025 평일 {period}: 평균속도 {state['speed']}km/h, 평일 전체 혼잡빈도 {state['frequency']}%, 혼잡시간 {state['congestion_time']}%. 같은 그룹 내 기간별 속도와 비교." if state['score'] is not None else
                   ('주말 통계 미확보: 미평가.' if day == 'weekend' else '동일 그룹의 유효 혼잡 통계 미확보: 미평가. 낮은 속도만으로 혼잡 판정하지 않음.'),
                   i, prefix[i], group_id=state['group_id'], status=state['status'])
        detail(CATEGORIES[1], '실제 차로 변경 후 회전', None, '검증용 경로',
               '확정된 차로 변경 위치·횟수·가용거리 미확보.', 0, 0, status='unavailable')
        categories = []
        for category in CATEGORIES:
            valid = [r for r in details if r['category'] == category and r['score'] is not None]
            peak = max(valid, key=lambda r: r['score']) if valid else None
            categories.append({'name': category, 'score': peak['score'] if peak else None,
                               'peak_evidence_id': peak['id'] if peak else None,
                               'status': 'partial_provisional' if peak else 'unrated'})
        covered_length = sum(lengths[i] for i, t in enumerate(traffic) if t['score'] is not None)
        speed_length = sum(lengths[i] for i, t in enumerate(traffic) if t['speed'] is not None)
        fingerprint = json.loads(db.execute("SELECT value FROM meta WHERE key='input_hashes'").fetchone()[0])
        return {'mode': 'topology_validation', 'warning': '실제 연결 도로 기반 검증용 경로 · 합법적 자동차 경로 미확인 · 임시 점수',
                'criteria_version': cfg['version'], 'criteria': cfg, 'dataset_hashes': fingerprint,
                'period': period, 'day_type': day, 'reference_year': 2025,
                'link_ids': ids, 'length_m': round(prefix[-1], 3), 'offsets_m': offsets,
                'categories': categories, 'details': details, 'blocks': blocks,
                'events': events, 'traffic': traffic,
                'coverage': {'traffic_length_pct': round(100*covered_length/prefix[-1], 2),
                             'speed_length_pct': round(100*speed_length/prefix[-1], 2),
                             'junctions_estimated': len(junction_events),
                             'legal_turns_confirmed': False},
                'route_geometry': [coordinates(l['geometry']) for l in links]}
