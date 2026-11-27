"""Real-network routing contracts; no external directions or synthetic success routes."""
import json
import unittest
import threading
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer
from pathlib import Path
from .routing import Router, point_on_line
from .evaluate import evaluate, connection


class RoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.router = Router()
        cls.requests = [
            [(129.0422, 35.115), (129.1604, 35.1587)],
            [(129.0756, 35.1796), (129.0595, 35.1575)],
            [(129.0422, 35.115), (129.1187, 35.1532), (129.1604, 35.1587)],
            [(129.1604, 35.1587), (129.0422, 35.115)],
        ]
        cls.results = [cls.router.route({'places':[{'lon':x,'lat':y} for x,y in p]}) for p in cls.requests]

    def test_all_paths_follow_directed_active_nonprohibited_edges(self):
        with connection() as db:
            for result in self.results:
                ids = result['evaluation_request']['link_ids']
                for a,b in zip(ids,ids[1:]):
                    x,y = self.router.links[a],self.router.links[b]
                    self.assertEqual(x['to_node'],y['from_node'])
                    self.assertNotEqual(x['from_node'],y['to_node'])
                    t = db.execute('SELECT * FROM transitions WHERE in_id=? AND out_id=?',(a,b)).fetchone()
                    self.assertTrue(t['in_use'])
                    self.assertNotEqual(t['permission'],'prohibited_recorded')
                    self.assertLess(abs(t['angle']),150)
                self.assertFalse(result['legal_access_confirmed'])
                self.assertTrue(all(self.router.allowed(self.router.links[i],{'weight_kg':2000,'height_cm':180}) for i in ids))

    def test_via_is_same_position_and_visit_order_is_preserved(self):
        result = self.results[2]
        self.assertEqual(len(result['legs']),2)
        via = result['snaps'][1]
        passed = [t for t in result['traversals'] if t['link_id']==via['link_id'] and t['start_m']<=via['offset_m']<=t['end_m']]
        self.assertTrue(passed)
        self.assertAlmostEqual(sum(l['length_m'] for l in result['legs']),result['length_m'],places=2)

    def test_evaluation_differs_and_offsets_match_drawn_distance(self):
        scores=[]
        for result in self.results:
            evaluation=evaluate(result['evaluation_request'])
            self.assertAlmostEqual(evaluation['length_m'],result['length_m'],places=2)
            scores.append(tuple(c['score'] for c in evaluation['categories']))
        self.assertGreater(len(set(scores)),1)
        weekend=evaluate({**self.results[0]['evaluation_request'],'day_type':'weekend'})
        self.assertIsNone(weekend['categories'][2]['score'])

    def test_same_directed_link_partial_route_and_backward_not_shortcut(self):
        row=next(r for r in self.router.links.values() if not r['internal_junction'] and r['length_m']>100 and self.router.allowed(r,{'weight_kg':2000,'height_cm':180}))
        def snap(frac):
            return {'link_id':row['id'],'distance_m':0,'offset_m':row['length_m']*frac,'point':point_on_line(row['line'],row['length_m']*frac,row['length_m'])}
        forward=self.router.leg([snap(.2)],[snap(.7)],{'weight_kg':2000,'height_cm':180})
        self.assertEqual(forward['ids'],[row['id']])
        result=evaluate({'link_ids':[row['id']],'start_offset_m':row['length_m']*.2,'end_offset_m':row['length_m']*.7})
        self.assertAlmostEqual(result['length_m'],row['length_m']*.5,places=2)
        try:
            backward=self.router.leg([snap(.7)],[snap(.2)],{'weight_kg':2000,'height_cm':180})
            self.assertGreater(len(backward['ids']),1)
        except ValueError:
            pass  # No loop is preferable to illegally reversing a directed link.

    def test_restrictions_and_invalid_inputs(self):
        vehicle={'weight_kg':2000,'height_cm':180}
        base={'vehicle_code':'0','weight_kg':0,'height_cm':0}
        for change in [{'vehicle_code':'1'},{'vehicle_code':'6'},{'vehicle_code':''},{'weight_kg':1500},{'height_cm':170}]:
            self.assertFalse(Router.allowed({**base,**change},vehicle))
        self.assertTrue(Router.allowed(base,vehicle))
        for request in [{},{'places':[{'lon':float('nan'),'lat':35}]*2},{'places':[{'lon':127,'lat':37}]*2},{'places':[{'lon':129.04,'lat':35.11}]*2}]:
            with self.assertRaises(ValueError): self.router.route(request)
        # Airport-area coordinate cannot be connected within the documented 150m limit.
        with self.assertRaisesRegex(ValueError,'150m'):
            self.router.route({'places':[{'lon':128.9465,'lat':35.1701},{'lon':129.0422,'lat':35.115}]})

    def test_record_benchmarks(self):
        report={'cold_graph_load_ms':self.router.load_ms,'cases':[{'input_coordinates':p,'length_m':r['length_m'],'search_ms':r['search_ms'],'links':len(r['traversals']),'unknown_turns':r['unknown_turns'],'scores':[c['score'] for c in evaluate(r['evaluation_request'])['categories']]} for p,r in zip(self.requests,self.results)]}
        Path('difficulty_data/routing_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')

    def test_route_http_contract(self):
        from . import server
        previous=server.ROUTER
        server.ROUTER=self.router
        http=ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        worker=threading.Thread(target=http.serve_forever,daemon=True)
        worker.start()
        try:
            url=f'http://127.0.0.1:{http.server_port}/api/route'
            body={'places':[{'lon':x,'lat':y} for x,y in self.requests[1]]}
            def request(payload):
                return urllib.request.Request(url,json.dumps(payload).encode(),{'Content-Type':'application/json','Origin':'http://localhost:5173'})
            with urllib.request.urlopen(request(body)) as response:
                result=json.load(response)
            self.assertEqual(len(result['categories']),3)
            self.assertIn('explanation',result)
            self.assertEqual(result['routing']['evaluation_request']['link_ids'],result['link_ids'])
            self.assertEqual(len(result['route_geometry']),len(result['link_ids']))
            with self.assertRaises(urllib.error.HTTPError) as failure:
                urllib.request.urlopen(request({}))
            self.assertEqual(failure.exception.code,400)
        finally:
            http.shutdown(); http.server_close(); worker.join(); server.ROUTER=previous


if __name__=='__main__': unittest.main()
