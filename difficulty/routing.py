"""Experimental local passenger-car routing. Unknown restrictions never become confirmed permission."""
import heapq
import math
import time
from collections import defaultdict
from .build_db import coordinates
from .evaluate import connection

COS = math.cos(math.radians(35))
SCALE = 6371000 * math.pi / 180
CELL = 200


def xy(point):
    return ((point[0]-129)*SCALE*COS, (point[1]-35)*SCALE)


def point_on_line(line, offset, source_length):
    points = [xy(p) for p in line]
    lengths = [math.dist(a, b) for a, b in zip(points, points[1:])]
    target = offset/source_length*sum(lengths)
    walked = 0
    for i, length in enumerate(lengths):
        if walked+length >= target or i == len(lengths)-1:
            fraction = min(1, max(0, (target-walked)/length)) if length else 0
            return [line[i][k]+fraction*(line[i+1][k]-line[i][k]) for k in [0, 1]]
        walked += length
    return line[-1]


def clip(line, start, end, source_length):
    points = [xy(p) for p in line]
    distances = [0.0]
    for a, b in zip(points, points[1:]):
        distances.append(distances[-1]+math.dist(a, b))
    return [point_on_line(line, start, source_length)] + [line[i] for i, d in enumerate(distances)
            if start < d/distances[-1]*source_length < end] + [point_on_line(line, end, source_length)]


class Router:
    def __init__(self, path=None):
        started = time.perf_counter()
        with connection() if path is None else connection(path) as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='routing_attributes'").fetchone():
                raise ValueError('길찾기 DB를 준비하세요: npm run prepare:data')
            self.links = {r['id']: dict(r) for r in db.execute('SELECT l.*,a.vehicle_code,a.weight_kg,a.height_cm,a.speed_limit FROM links l JOIN routing_attributes a ON a.link_id=l.id WHERE l.in_use=1')}
            self.turns = defaultdict(list)
            self.end_bearing, self.start_bearing = {}, {}
            for r in db.execute('SELECT * FROM transitions WHERE in_use=1'):
                self.end_bearing[r['in_id']] = r['approach']
                self.start_bearing[r['out_id']] = r['departure']
                if r['permission'] != 'prohibited_recorded' and r['angle'] is not None and abs(r['angle']) < 150:
                    self.turns[r['in_id']].append(dict(r))
        self.grid = defaultdict(set)
        self.max_length = max(r['length_m'] for r in self.links.values())
        for link_id, row in self.links.items():
            row['line'] = coordinates(row.pop('geometry'))
            row['xy'] = [xy(p) for p in row['line']]
            cumulative = [0.0]
            for a, b in zip(row['xy'], row['xy'][1:]):
                cumulative.append(cumulative[-1]+math.dist(a, b))
            row['cumulative'] = cumulative
            xs, ys = zip(*row['xy'])
            for ix in range(math.floor(min(xs)/CELL), math.floor(max(xs)/CELL)+1):
                for iy in range(math.floor(min(ys)/CELL), math.floor(max(ys)/CELL)+1):
                    self.grid[ix, iy].add(link_id)
        self.load_ms = round((time.perf_counter()-started)*1000, 2)

    @staticmethod
    def allowed(row, vehicle):
        # Official older code table: 1 passenger, 2 van, 3 bus, 4 truck, 5 motorcycle, 6 other.
        # Current source marks the code unverified: block passenger/other/unknown codes conservatively;
        # the remaining codes and zero do NOT certify legal access or complete restriction coverage.
        code = row['vehicle_code']
        if not code or any(c not in '02345' for c in code):
            return False
        return not ((row['weight_kg'] > 0 and vehicle['weight_kg'] > row['weight_kg']) or
                    (row['height_cm'] > 0 and vehicle['height_cm'] > row['height_cm']))

    def snap(self, point, vehicle):
        px, py = xy(point)
        ix, iy = math.floor(px/CELL), math.floor(py/CELL)
        nearby = set().union(*(self.grid[x, y] for x in range(ix-1, ix+2) for y in range(iy-1, iy+2)))
        hits = []
        for link_id in nearby:
            row = self.links[link_id]
            if row['internal_junction'] or not self.allowed(row, vehicle):
                continue
            best = None
            for i, (a, b) in enumerate(zip(row['xy'], row['xy'][1:])):
                vx, vy = b[0]-a[0], b[1]-a[1]
                length_sq = vx*vx+vy*vy
                if length_sq == 0:
                    continue
                t = min(1, max(0, ((px-a[0])*vx+(py-a[1])*vy)/length_sq))
                d = math.hypot(px-a[0]-t*vx, py-a[1]-t*vy)
                if best is None or d < best[0]:
                    progress = row['cumulative'][i]+t*math.sqrt(length_sq)
                    best = (d, progress/row['cumulative'][-1]*row['length_m'])
            if best and best[0] <= 150:
                hits.append({'link_id': link_id, 'distance_m': best[0], 'offset_m': best[1],
                             'point': point_on_line(row['line'], best[1], row['length_m'])})
        hits.sort(key=lambda s: (s['distance_m'], s['link_id']))
        if not hits:
            raise ValueError('선택 장소에서 150m 안에 연결할 수 있는 도로가 없습니다. 도로 쪽 출입구에 가까운 장소를 선택하세요.')
        # shortcut: up to six local candidates, not driveway/vertical-level certainty; replace with verified access points when available.
        return [s for s in hits if s['distance_m'] <= hits[0]['distance_m']+25][:6]

    def leg(self, starts, goals, vehicle):
        queue, costs, parent, roots = [], {}, {}, {}
        best = None
        goal_links = defaultdict(list)
        for goal in goals:
            goal_links[goal['link_id']].append(goal)

        def path_to(state):
            result = []
            while state is not None:
                result.append(state[0])
                state = parent[state]
            return list(reversed(result))

        def accept(cost, path, source, goal):
            nonlocal best
            total = cost+goal['distance_m']*4
            if best is None or total < best['cost']:
                best = {'cost': total, 'ids': path, 'start': source, 'end': goal}

        for start in starts:
            link_id = start['link_id']
            row = self.links[link_id]
            state = (link_id, '')
            cost = row['length_m']-start['offset_m']+4*start['distance_m']
            if cost < costs.get(state, math.inf):
                costs[state], parent[state], roots[state] = cost, None, start
                heapq.heappush(queue, (cost, state))
            for goal in goal_links[link_id]:
                if goal['offset_m'] > start['offset_m']:
                    accept(goal['offset_m']-start['offset_m']+4*start['distance_m'], [link_id], start, goal)
        expanded = 0
        deadline = time.perf_counter()+8
        while queue:
            cost, state = heapq.heappop(queue)
            if cost != costs.get(state):
                continue
            if best and cost > best['cost']+self.max_length:
                break
            if expanded % 256 == 0 and time.perf_counter() > deadline:
                raise ValueError('길찾기 시간이 초과되었습니다. 장소를 도로에 더 가까이 지정해 다시 시도하세요.')
            expanded += 1
            current_id, entry = state
            current = self.links[current_id]
            for turn in self.turns[current_id]:
                next_id = turn['out_id']
                nxt = self.links.get(next_id)
                if not nxt or not self.allowed(nxt, vehicle) or nxt['to_node'] == current['from_node']:
                    continue
                entry_id = entry or current_id
                if nxt['internal_junction']:
                    next_entry = entry_id if current['internal_junction'] == nxt['internal_junction'] else current_id
                else:
                    next_entry = ''
                    approach = self.end_bearing.get(entry_id)
                    departure = self.start_bearing.get(next_id)
                    if approach is not None and departure is not None and abs((departure-approach+180)%360-180) >= 150:
                        continue
                full_cost = cost+nxt['length_m']
                for goal in goal_links[next_id]:
                    accept(cost+goal['offset_m'], path_to(state)+[next_id], roots[state], goal)
                next_state = (next_id, next_entry)
                if full_cost < costs.get(next_state, math.inf):
                    costs[next_state], parent[next_state], roots[next_state] = full_cost, state, roots[state]
                    heapq.heappush(queue, (full_cost, next_state))
        if best is None:
            raise ValueError('현재 도로망과 제한 조건으로 연결 경로를 찾지 못했습니다. 반대편 도로·고가도로 연결이나 누락 구간을 확인해야 합니다.')
        best['expanded'] = expanded
        return best

    def route(self, request):
        if not isinstance(request, dict):
            raise ValueError('방문지 좌표가 필요합니다.')
        places = request.get('places')
        if not isinstance(places, list) or not 2 <= len(places) <= 6:
            raise ValueError('방문지를 순서대로 2~6개 선택하세요.')
        for place in places:
            if not isinstance(place, dict) or any(type(place.get(k)) not in (int, float) or not math.isfinite(place[k]) for k in ['lon', 'lat']):
                raise ValueError('유효한 장소 좌표가 필요합니다.')
            if not 128.75 <= place['lon'] <= 129.4 or not 34.98 <= place['lat'] <= 35.5:
                raise ValueError('현재 제공된 부산 주변 도로망 범위를 벗어났습니다.')
            if not isinstance(place.get('name', ''), str) or len(place.get('name', '')) > 150:
                raise ValueError('장소 이름을 확인하세요.')
        vehicle = request.get('vehicle', {'weight_kg': 2000, 'height_cm': 180})
        if not isinstance(vehicle, dict) or any(type(vehicle.get(k)) not in (int, float) or not math.isfinite(vehicle[k]) or vehicle[k] <= 0 for k in ['weight_kg', 'height_cm']):
            raise ValueError('승용차 중량(kg)과 높이(cm)가 필요합니다.')
        started = time.perf_counter()
        candidates = [self.snap([p['lon'], p['lat']], vehicle) for p in places]
        legs, chosen, traversals = [], [], []
        starts = candidates[0]
        for index in range(len(places)-1):
            if math.dist(xy([places[index]['lon'], places[index]['lat']]), xy([places[index+1]['lon'], places[index+1]['lat']])) < 1:
                raise ValueError('연속한 방문지가 같습니다. 중복 장소를 삭제하세요.')
            leg = self.leg(starts, candidates[index+1], vehicle)
            if not chosen:
                chosen.append(leg['start'])
            chosen.append(leg['end'])
            local = []
            for j, link_id in enumerate(leg['ids']):
                a = leg['start']['offset_m'] if j == 0 else 0
                b = leg['end']['offset_m'] if j == len(leg['ids'])-1 else self.links[link_id]['length_m']
                if b-a > 1e-6:
                    local.append({'link_id': link_id, 'start_m': a, 'end_m': b})
            if not local:
                raise ValueError('장소가 같거나 도로상 이동 거리가 없습니다.')
            length = sum(t['end_m']-t['start_m'] for t in local)
            legs.append({'from': places[index].get('name', ''), 'to': places[index+1].get('name', ''),
                         'length_m': round(length, 3), 'expanded_states': leg['expanded']})
            for traversal in local:
                if traversals and traversals[-1]['link_id'] == traversal['link_id'] and abs(traversals[-1]['end_m']-traversal['start_m']) < .001:
                    traversals[-1]['end_m'] = traversal['end_m']
                else:
                    traversals.append(traversal)
            starts = [leg['end']]
        ids = [t['link_id'] for t in traversals]
        if len(ids) > 1000:
            raise ValueError('평가 가능한 경로 길이를 초과했습니다. 방문지를 나누어 분석하세요.')
        evaluation = {'link_ids': ids, 'start_offset_m': traversals[0]['start_m'],
                      'end_offset_m': traversals[-1]['end_m'], 'period': request.get('period', '11시~17시'),
                      'day_type': request.get('day_type', 'weekday')}
        # Via points stay on the same directed link; no teleport across a median or disconnected road.
        for a, b in zip(traversals, traversals[1:]):
            if self.links[a['link_id']]['to_node'] != self.links[b['link_id']]['from_node']:
                raise ValueError('경유지 앞뒤 도로 연결을 확인하지 못했습니다.')
        geometry = [clip(self.links[t['link_id']]['line'], t['start_m'], t['end_m'], self.links[t['link_id']]['length_m']) for t in traversals]
        return {'evaluation_request': evaluation, 'geometry': geometry, 'traversals': traversals,
                'places': [{'name': p.get('name', ''), 'lon': p['lon'], 'lat': p['lat']} for p in places],
                'snaps': chosen, 'legs': legs, 'length_m': round(sum(l['length_m'] for l in legs), 3),
                'search_ms': round((time.perf_counter()-started)*1000, 2), 'legal_access_confirmed': False,
                'unknown_turns': sum(1 for a, b in zip(ids, ids[1:])
                    if any(t['out_id'] == b and t['permission'] != 'prohibited_recorded' for t in self.turns[a])),
                'warnings': ['자체 도로망 탐색 결과입니다. 회전·차량 제한의 누락이 있어 실제 통행 허용을 보장하지 않습니다.',
                    f"승용차 {vehicle['weight_kg']:,.0f}kg·높이 {vehicle['height_cm']:g}cm 기준입니다. 장소 좌표와 도로 사이의 실제 차량 출입구·고도·중앙분리대 접근은 확인되지 않았습니다.",
                    '현재 거리 기준으로 탐색하며, 난이도·소요시간별 대체 경로 최적화는 지원하지 않습니다.']}
