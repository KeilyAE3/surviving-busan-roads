import io
import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from .build_db import DB, build, signature
from .evaluate import CATEGORIES, catalog, connection, evaluate, settings
from .server import Handler, explain


class DifficultyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not DB.exists():
            build()
        cls.routes = {r['id']: r for r in catalog()}
        cls.results = {key: evaluate({'link_ids': r['link_ids']}) for key, r in cls.routes.items()}

    def request(self, name, **extra):
        return {'link_ids': self.routes[name]['link_ids'], **extra}

    def test_sources_unchanged_and_db_integrity(self):
        with connection() as db:
            baseline = json.loads(db.execute("SELECT value FROM meta WHERE key='input_hashes'").fetchone()[0])
            self.assertEqual(baseline, signature())
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(db.execute('SELECT count(*) FROM links').fetchone()[0], 74967)

    def test_named_intersections_and_duplicate_direction_dedup(self):
        with connection() as db:
            for name, count in [('연산교차로', 6), ('서면교차로', 5), ('동래교차로', 4)]:
                rows = db.execute('SELECT * FROM junctions WHERE name=?', (name,)).fetchall()
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]['arms'], count)
            self.assertGreater(db.execute("SELECT count(*) FROM junctions WHERE name='1번신호등교차로'").fetchone()[0], 1)

    def test_internal_links_do_not_become_blocks_or_alternating_turns(self):
        result = self.results['complex']
        self.assertEqual(len(result['events']), 1)
        self.assertEqual(result['blocks'], [])
        self.assertIsNone(result['categories'][1]['score'])
        self.assertFalse(any('좌회전 후 우회전' in r['item'] for r in result['details']))

    def test_multilink_block_and_distance(self):
        with connection() as db:
            row = db.execute('SELECT * FROM blocks WHERE link_ids=?', (json.dumps(['1330019500', '1330019701']),)).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row['status'], 'estimated')
            self.assertAlmostEqual(row['length_m'], 890.985, places=2)

    def test_scenarios_are_real_connected_and_scores_differ(self):
        self.assertTrue({'simple', 'drop', 'complex', 'continuous', 'traffic', 'no_traffic'} <= set(self.results))
        values = []
        with connection() as db:
            for result in self.results.values():
                self.assertEqual([c['name'] for c in result['categories']], CATEGORIES)
                self.assertFalse(result['coverage']['legal_turns_confirmed'])
                for a, b in zip(result['link_ids'], result['link_ids'][1:]):
                    row = db.execute('SELECT * FROM transitions WHERE in_id=? AND out_id=?', (a, b)).fetchone()
                    self.assertTrue(row['in_use'])
                    self.assertNotEqual(row['permission'], 'prohibited_recorded')
                for category in result['categories']:
                    scores = [r['score'] for r in result['details'] if r['category'] == category['name'] and r['score'] is not None]
                    self.assertEqual(category['score'], max(scores) if scores else None)
                    if category['score'] is not None:
                        self.assertTrue(0 <= category['score'] <= 100)
                values.append(tuple(c['score'] for c in result['categories']))
        self.assertGreater(len(set(values)), 5)
        self.assertLess(self.results['simple']['categories'][0]['score'], self.results['complex']['categories'][0]['score'])

    def test_lane_drop_is_ratio_not_lane_change_count(self):
        rows = [r for r in self.results['drop']['details'] if r['item'] == '차로 수 감소']
        self.assertEqual(rows[0]['ratio'], .5)
        self.assertEqual(rows[0]['base_score'], 50)
        self.assertIn('횟수 아님', rows[0]['evidence'])
        for result in self.results.values():
            for row in result['details']:
                if row['item'] == '차로 수 감소':
                    self.assertEqual(row['link_id'], row['in_link_id'])

    def test_all_consecutive_patterns(self):
        for name, kind in [('continuous', '좌회전 후 우회전'), ('right_left', '우회전 후 좌회전'),
                           ('drop_turn', '차로 수 감소 후 회전'), ('turn_drop', '회전 후 차로 수 감소')]:
            rows = [r for r in self.results[name]['details'] if kind in r.get('kinds', [])]
            self.assertTrue(rows, name)
            self.assertGreater(rows[0]['block_length_m'], 0)
            self.assertGreater(rows[0]['gap_m'], 0)

    def test_missing_and_weekend_are_null_not_zero(self):
        result = self.results['no_traffic']
        self.assertIsNone(result['categories'][2]['score'])
        self.assertEqual(result['coverage']['traffic_length_pct'], 0)
        weekend = evaluate(self.request('traffic', day_type='weekend'))
        self.assertIsNone(weekend['categories'][2]['score'])
        self.assertTrue(all(t['status'] == 'not_applicable_weekend' for t in weekend['traffic']))

    def test_soft_scale_avoids_saturation_and_remains_configurable(self):
        for result in self.results.values():
            for row in result['details']:
                if row['score'] is not None:
                    self.assertGreaterEqual(row['score'], 0)
                    self.assertLess(row['score'], 100)
        cfg=settings()
        with patch('difficulty.evaluate.settings', return_value={**cfg, 'score_half_saturation':cfg['score_half_saturation']*2}):
            softer=evaluate(self.request('complex'))
        self.assertLess(softer['categories'][0]['score'],self.results['complex']['categories'][0]['score'])

    def test_real_zero_is_retained(self):
        self.assertEqual(self.results['simple']['categories'][1]['score'], 0)
        self.assertTrue(any(r['base_score'] == 0 for r in self.results['simple']['details']))

    def test_traffic_is_independent_and_amplifies_structure_and_sequence(self):
        for name, category in [('drop', CATEGORIES[0]), ('continuous', CATEGORIES[1])]:
            rows = [r for r in self.results[name]['details'] if r['category'] == category and
                    r['base_score'] and r['traffic_modifier'] is not None and r['traffic_modifier'] > 0]
            self.assertTrue(rows)
            self.assertTrue(any(r['score'] > r['unmodified_score'] for r in rows))
        self.assertIsNotNone(self.results['traffic']['categories'][2]['score'])

    def test_group_values_are_not_summed_and_missing_not_low_speed_scored(self):
        for result in self.results.values():
            rows = [r for r in result['details'] if r['category'] == CATEGORIES[2] and r['score'] is not None]
            groups = [r['group_id'] for r in rows]
            self.assertEqual(len(groups), len(set(groups)))
            for t in result['traffic']:
                if t['frequency'] is None and t['congestion_time'] is None:
                    self.assertIsNone(t['score'])

    def test_time_period_comparison_and_config_changes(self):
        morning = evaluate(self.request('traffic', period='4시~10시'))
        evening = evaluate(self.request('traffic', period='18시~24시'))
        self.assertNotEqual(morning['traffic'], evening['traffic'])
        cfg = settings()
        cfg['traffic_amplification'] = 0
        cfg['continuous_distance_m'] = 10
        with patch('difficulty.evaluate.settings', return_value=cfg):
            changed = evaluate(self.request('continuous'))
        self.assertEqual(changed['categories'][1]['score'], 0)
        self.assertNotEqual(changed['categories'], self.results['continuous']['categories'])

    def test_invalid_ids_disconnects_prohibitions_and_offsets(self):
        for request in [None, {'link_ids': []}, {'link_ids': [1, 2]}, {'link_ids': ['9999999999', '1300004601']},
                        {'link_ids': ['1300004601', '1420013700']},
                        {'link_ids': ['1300004208', '1300003900']},
                        self.request('drop', start_offset_m=float('nan')),
                        self.request('drop', day_type='holiday'), self.request('drop', period='01시')]:
            with self.subTest(request=request), self.assertRaises(ValueError):
                evaluate(request)

    def test_partial_endpoints_change_only_traversed_length(self):
        original = self.results['drop']
        changed = evaluate(self.request('drop', start_offset_m=1, end_offset_m=1))
        self.assertLess(changed['length_m'], original['length_m'])

    def test_rule_explanation_changes_and_never_claims_llm(self):
        a, b = explain(self.results['simple']), explain(self.results['complex'])
        self.assertEqual(a['source'], 'rule')
        self.assertIn('아닙니다', a['message'])
        self.assertNotEqual(a['situations'], b['situations'])

    def test_llm_prompt_and_response_validation_without_network(self):
        result = self.results['complex']
        best = max((r for r in result['details'] if r['score'] is not None), key=lambda r: r['score'])
        def response(ids):
            return io.BytesIO(json.dumps({'output': [{'content': [{'type': 'output_text', 'text': json.dumps({'event_ids': ids, 'preparation_ids': ['direction']})}]}]}).encode())
        with patch.dict('os.environ', {'OPENAI_API_KEY': 'test-only', 'OPENAI_MODEL': 'test-model', 'ENABLE_LLM': 'true'}):
            def valid(request, timeout):
                body = json.loads(request.data)
                self.assertFalse(body['store'])
                self.assertNotIn('geometry', body['input'])
                self.assertNotIn('API_KEY', body['input'])
                return response([best['id']])
            generated = explain(result, True, valid)
            self.assertEqual(generated['source'], 'llm_grounded')
            rejected = explain(result, True, lambda *a, **k: response(['invented-evidence']))
            self.assertEqual(rejected['source'], 'rule')
            self.assertIn('실패', rejected['message'])
        with patch.dict('os.environ', {'ENABLE_LLM': 'false'}), self.assertRaises(ValueError):
            explain(result, True)

    def test_gemini_structured_explanation_without_network(self):
        result=self.results['continuous']
        best=max((r for r in result['details'] if r['score'] is not None),key=lambda r:r['score'])
        def respond(request, timeout):
            self.assertEqual(request.full_url,'https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent')
            self.assertNotIn('key=',request.full_url)
            body=json.loads(request.data)
            facts=json.loads(body['contents'][0]['parts'][0]['text'])
            self.assertEqual(facts['highest_score_event_id'],best['id'])
            self.assertNotIn('route_geometry',facts)
            self.assertEqual(body['generationConfig']['responseMimeType'],'application/json')
            selection={'event_ids':[best['id']],'preparation_ids':['direction']}
            return io.BytesIO(json.dumps({'candidates':[{'content':{'parts':[{'text':json.dumps(selection)}]}}]}).encode())
        with patch.dict('os.environ',{'LLM_PROVIDER':'gemini','GEMINI_API_KEY':'test-only','GEMINI_MODEL':'gemini-3.5-flash-lite','ENABLE_LLM':'true'}):
            generated=explain(result,True,respond)
        self.assertEqual(generated['source'],'llm_grounded')

    def test_http_contract_and_origin_guard(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = 'http://127.0.0.1:' + str(server.server_port)
        try:
            with urllib.request.urlopen(url+'/api/routes') as response:
                self.assertGreaterEqual(len(json.load(response)['routes']), 6)
            req = urllib.request.Request(url+'/api/evaluate', json.dumps(self.request('drop')).encode(), {'Content-Type': 'application/json'})
            with urllib.request.urlopen(req) as response:
                self.assertEqual(len(json.load(response)['categories']), 3)
            req.add_header('Origin', 'https://untrusted.example')
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(req)
            self.assertEqual(error.exception.code, 403)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == '__main__':
    unittest.main()
