"""Read-only CSV input -> atomically replaced, local SQLite feature DB."""
import csv
import hashlib
import json
import math
import os
import sqlite3
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / 'difficulty_data' / 'roads.sqlite'
CONFIG = Path(__file__).with_name('config.json')
SOURCES = ROOT / 'integrated_roads'


def read(name):
    csv.field_size_limit(10_000_000)
    with (SOURCES / (name + '.csv')).open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def coordinates(wkt):
    return [list(map(float, p.strip().split()[:2]))
            for p in wkt.split('(', 1)[1].rstrip(') ').split(',')]


def distance(a, b):
    x = math.radians(a[0] - b[0]) * math.cos(math.radians((a[1] + b[1]) / 2))
    y = math.radians(a[1] - b[1])
    return 6371000 * math.hypot(x, y)


def bearing(a, b):
    return math.degrees(math.atan2((b[0] - a[0]) * math.cos(math.radians(a[1])), b[1] - a[1])) % 360


def arms(angles, tolerance):
    # Complete-span circular clusters avoid chaining many nearby directions into one arm.
    if not angles:
        return 0
    values = sorted(angles)
    counts = []
    for start in range(len(values)):
        ordered = values[start:] + [v + 360 for v in values[:start]]
        count, first = 1, ordered[0]
        for value in ordered[1:]:
            if value - first > tolerance:
                count += 1
                first = value
        counts.append(count)
    return min(counts)


def signature():
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(SOURCES.glob('*.csv'))}


def build(destination=DB):
    cfg = json.loads(CONFIG.read_text(encoding='utf-8'))
    original = signature()
    nodes, links, transitions = read('road_nodes'), read('road_links'), read('road_transitions')
    nd = {r['node_id']: r for r in nodes}
    ld = {r['link_id']: r for r in links}
    assert len(nd) == len(nodes) and len(ld) == len(links)
    used = [r for r in links if r['road_in_use'] == 'True']
    adj, rev = defaultdict(list), defaultdict(list)
    for row in used:
        assert row['from_node_id'] in nd and row['to_node_id'] in nd
        adj[row['from_node_id']].append(row)
        rev[row['to_node_id']].append(row)
    points = {n: [float(r['lon']), float(r['lat'])] for n, r in nd.items()}
    members = {n: {n} for n, r in nd.items() if r['node_type_code'] == '101'}
    owner = {n: n for n in members}
    # shortcut: planar compact connected clusters are estimates; elevation/parallel-road review is still needed.
    for row in sorted(used, key=lambda r: (float(r['length_m']), r['link_id'])):
        a, b = row['from_node_id'], row['to_node_id']
        if a not in owner or b not in owner or float(row['length_m']) > cfg['junction_edge_m']:
            continue
        ga, gb = owner[a], owner[b]
        if ga == gb:
            continue
        joined = members[ga] | members[gb]
        if any(distance(points[x], points[y]) > cfg['junction_diameter_m'] for x in joined for y in joined):
            continue
        key, old = sorted((ga, gb))
        members[key] = joined
        del members[old]
        for node in joined:
            owner[node] = key
    junctions = []
    for key, group in sorted(members.items()):
        outside = [r for n in group for r in adj[n] + rev[n]
                   if (r['from_node_id'] in group) != (r['to_node_id'] in group)]
        headings = []
        for row in outside:
            pp = coordinates(row['geometry_wkt'])
            pp = pp if row['from_node_id'] in group else list(reversed(pp))
            end = next((p for p in pp[1:] if distance(pp[0], p) > .1), None)
            if end:
                headings.append(bearing(pp[0], end))
        names = sorted({nd[n]['node_name'] for n in group} - {'', '-'})
        name = ' / '.join(names[:2]) or ('교차 지점 ' + key)
        count = arms(headings, cfg['arm_angle_deg'])
        junctions.append((key, name, json.dumps(sorted(group)), count, 'estimated',
                          sum(points[n][0] for n in group) / len(group),
                          sum(points[n][1] for n in group) / len(group)))
    transition_map = {}
    tr_rows = []
    for r in transitions:
        a, b = ld[r['in_link_id']], ld[r['out_link_id']]
        assert a['to_node_id'] == r['node_id'] == b['from_node_id']
        assert int(r['lane_delta']) == int(r['lanes_out']) - int(r['lanes_in'])
        ratio = max(0, -int(r['lane_delta'])) / int(r['lanes_in'])
        tr_rows.append((r['node_id'], r['in_link_id'], r['out_link_id'], ratio,
                        float(r['turn_angle_deg']) if r['turn_angle_deg'] else None,
                        float(r['approach_bearing_deg']), float(r['departure_bearing_deg']),
                        r['turn_permission_status'], int(r['transition_in_use'] == 'True')))
        if r['transition_in_use'] == 'True' and r['turn_permission_status'] != 'prohibited_recorded':
            transition_map[r['in_link_id'], r['out_link_id']] = r
    blocks = []
    for row in used:
        start = owner.get(row['from_node_id'])
        if start is None or owner.get(row['to_node_id']) == start:
            continue
        path, seen, last = [row['link_id']], {row['from_node_id']}, row
        status = 'unresolved'
        while last['to_node_id'] not in seen:
            end = last['to_node_id']
            if end in owner:
                status = 'estimated' if owner[end] != start else 'returns_to_same_junction'
                break
            seen.add(end)
            options = [x for x in adj[end] if x['to_node_id'] not in seen and
                       (last['link_id'], x['link_id']) in transition_map]
            if len(options) != 1:
                break
            last = options[0]
            path.append(last['link_id'])
        end = owner.get(last['to_node_id'])
        block_id = hashlib.sha256('|'.join(path).encode()).hexdigest()[:24]
        blocks.append((block_id, start, end, json.dumps(path),
                       sum(float(ld[i]['length_m']) for i in path), status))
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix('.building.sqlite')
    if temporary.exists():
        temporary.unlink()
    db = sqlite3.connect(temporary)
    try:
        db.executescript('''
        CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE junctions(id TEXT PRIMARY KEY,name TEXT,node_ids TEXT,arms INTEGER,status TEXT,lon REAL,lat REAL);
        CREATE TABLE nodes(id TEXT PRIMARY KEY,name TEXT,lon REAL,lat REAL,junction_id TEXT,in_count INTEGER,out_count INTEGER,merge_candidate INTEGER,diverge_candidate INTEGER);
        CREATE TABLE links(id TEXT PRIMARY KEY,from_node TEXT,to_node TEXT,name TEXT,lanes INTEGER,length_m REAL,in_use INTEGER,internal_junction TEXT,geometry TEXT,hd_status TEXT);
        CREATE TABLE transitions(node_id TEXT,in_id TEXT,out_id TEXT,drop_ratio REAL,angle REAL,approach REAL,departure REAL,permission TEXT,in_use INTEGER,PRIMARY KEY(in_id,out_id));
        CREATE TABLE blocks(id TEXT PRIMARY KEY,start_junction TEXT,end_junction TEXT,link_ids TEXT,length_m REAL,status TEXT);
        CREATE TABLE traffic(link_id TEXT,source TEXT,group_id TEXT,year TEXT,day_type TEXT,period TEXT,observed_at TEXT,speed REAL,frequency REAL,congestion_time REAL,status TEXT,raw_speed REAL,feature_status TEXT);
        CREATE INDEX traffic_link_period ON traffic(link_id,period);
        CREATE TABLE source_groups(group_id TEXT,year TEXT,day_type TEXT,period TEXT,its_ids TEXT,feature_status TEXT,PRIMARY KEY(group_id,year,day_type,period));
        CREATE TABLE hd_matches(id TEXT PRIMARY KEY,link_id TEXT,status TEXT);
        CREATE TABLE validation_routes(id TEXT PRIMARY KEY,name TEXT,link_ids TEXT);
        CREATE TABLE routing_attributes(link_id TEXT PRIMARY KEY,vehicle_code TEXT,weight_kg REAL,height_cm REAL,speed_limit REAL);
        ''')
        db.executemany('INSERT INTO junctions VALUES(?,?,?,?,?,?,?)', junctions)
        db.executemany('INSERT INTO nodes VALUES(?,?,?,?,?,?,?,?,?)', [
            (n, r['node_name'], *points[n], owner.get(n), len(rev[n]), len(adj[n]),
             int(r['merge_topology_candidate'] == 'True'), int(r['diverge_topology_candidate'] == 'True'))
            for n, r in nd.items()])
        db.executemany('INSERT INTO links VALUES(?,?,?,?,?,?,?,?,?,?)', [
            (r['link_id'], r['from_node_id'], r['to_node_id'], r['road_name'], int(r['lane_count']),
             float(r['length_m']), int(r['road_in_use'] == 'True'),
             owner.get(r['from_node_id']) if owner.get(r['from_node_id']) is not None and
             owner.get(r['from_node_id']) == owner.get(r['to_node_id']) else None,
             r['geometry_wkt'], r['hd_match_status']) for r in links])
        db.executemany('INSERT INTO transitions VALUES(?,?,?,?,?,?,?,?,?)', tr_rows)
        db.executemany('INSERT INTO routing_attributes VALUES(?,?,?,?,?)', [
            (r['link_id'], r['restriction_vehicle_code'], float(r['weight_limit_raw']),
             float(r['height_limit_raw']), float(r['speed_limit_kmh'])) for r in links])
        db.executemany('INSERT INTO blocks VALUES(?,?,?,?,?,?)', blocks)
        traffic = read('road_traffic')
        num = lambda r, k: float(r[k]) if r[k] != '' else None
        db.executemany('INSERT INTO traffic VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)', [
            (r['link_id'], r['source'], r['source_group_id'], r['reference_year'], r['day_type'], r['period'],
             r['observed_at'], num(r, 'mean_speed_kmh'), num(r, 'congestion_frequency'),
             num(r, 'congestion_time'), r['match_status'], num(r, 'observed_speed_raw'), r['feature_status_json']) for r in traffic])
        db.executemany('INSERT INTO source_groups VALUES(?,?,?,?,?,?)', [
            (r['source_group_id'], r['reference_year'], r['day_type'], r['period'], r['its_link_ids_json'], r['feature_status_json'])
            for r in read('view_t_groups')])
        db.executemany('INSERT INTO hd_matches VALUES(?,?,?)', [
            (r['match_id'], r['link_id'] or None, r['match_status']) for r in read('hd_lane_link_matches')])
        routes = [
            ('drop', '차로 수 감소 · 부평교차로', ['1300004601', '1310022800']),
            ('complex', '복합 교차로 · 연산 내부 통과', ['1420013600', '1420013601', '1420000605', '1420003507', '1420013700']),
            ('continuous', '연속 좌→우 · 전포 일대', ['1340319001', '1340018102', '1340022900']),
            ('right_left', '연속 우→좌 · 대천 일대', ['1360012306', '1360016700', '1360016701']),
            ('drop_turn', '감소→회전 · 남항 일대', ['1330014601', '1330012600', '1330012300']),
            ('turn_drop', '회전→감소 · 사하 일대', ['1390037400', '1390034201', '1390034202'])]
        # Select real connected examples; do not manufacture geometry or assume legal routing.
        next_rows = defaultdict(list)
        arm_counts = {j[0]: j[3] for j in junctions}
        for (a, b), r in transition_map.items():
            next_rows[a].append(r)
        for (a, b), r in transition_map.items():
            if abs(float(r['turn_angle_deg'])) > 5 or int(r['lane_delta']) != 0:
                continue
            for t in next_rows[b]:
                c = t['out_link_id']
                simple_nodes = [r['node_id'], t['node_id']]
                simple_context = all(nd[n]['merge_topology_candidate'] == 'False' and
                    nd[n]['diverge_topology_candidate'] == 'False' and
                    arm_counts.get(owner.get(n), 0) <= 2 for n in simple_nodes)
                separate = owner.get(simple_nodes[0]) is not None and owner.get(simple_nodes[0]) != owner.get(simple_nodes[1])
                if c != a and abs(float(t['turn_angle_deg'])) < 5 and int(t['lane_delta']) == 0 and simple_context and separate:
                    routes.insert(0, ('simple', '비교적 단순한 연결 도로', [a, b, c]))
                    break
            if routes[0][0] == 'simple':
                break
        for label, name, present in [('traffic', '과거 교통정보 수록 경로', True), ('no_traffic', '교통정보 미수록 경로', False)]:
            for a, b in transition_map:
                has = [db.execute("SELECT 1 FROM traffic WHERE link_id=? AND source='view_t' AND status='exact_its_reference' AND congestion_time IS NOT NULL", (i,)).fetchone() is not None for i in [a, b]]
                if (all(has) if present else not any(has)):
                    routes.append((label, name, [a, b]))
                    break
        for _, _, path in routes:
            assert all((a, b) in transition_map for a, b in zip(path, path[1:]))
        db.executemany('INSERT INTO validation_routes VALUES(?,?,?)', [(i, n, json.dumps(p)) for i, n, p in routes])
        assert original == signature(), 'Source changed during build'
        meta = {'input_hashes': original, 'build_config': cfg,
                'counts': {'links': len(links), 'transitions': len(transitions), 'junctions': len(junctions), 'blocks': len(blocks)},
                'warning': '자동 추정 · 법적 통행 가능성 미검증'}
        db.executemany('INSERT INTO meta VALUES(?,?)', [(k, json.dumps(v, ensure_ascii=False)) for k, v in meta.items()])
        db.commit()
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    finally:
        db.close()
    os.replace(temporary, destination)
    print('DB ready:', destination.name, meta['counts'], flush=True)


if __name__ == '__main__':
    build()
