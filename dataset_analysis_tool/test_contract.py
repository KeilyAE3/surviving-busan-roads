"""Small regression checks for geometry decisions that can silently misjoin roads."""
import unittest
from shapely.geometry import LineString
from hd_map import evaluate
from traffic import number

class ContractTests(unittest.TestCase):
    def test_same_direction_offset_lane_is_a_candidate(self):
        result=evaluate(LineString([(2,0),(2,50),(2,100)]),LineString([(0,0),(0,100)]))
        self.assertTrue(result['geometry_supported'])
        self.assertEqual(result['direction_difference_deg'],0)

    def test_opposite_direction_parallel_lane_is_rejected(self):
        result=evaluate(LineString([(2,100),(2,0)]),LineString([(0,0),(0,100)]))
        self.assertFalse(result['geometry_supported'])
        self.assertEqual(result['direction_difference_deg'],180)

    def test_crossing_road_is_not_a_parallel_match(self):
        result=evaluate(LineString([(-40,50),(40,50)]),LineString([(0,0),(0,100)]))
        self.assertFalse(result['geometry_supported'])

    def test_zero_and_missing_remain_distinct(self):
        self.assertEqual(number('0'),0)
        self.assertIsNone(number('-'))
        self.assertIsNone(number(None))
        with self.assertRaises(ValueError):number('-1')

if __name__=='__main__':unittest.main()
