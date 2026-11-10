"""Regression checks for the classification mistakes found by the whole-map audit."""
import unittest
from temperature_policy import profile_for_mesh


class TemperaturePolicyTests(unittest.TestCase):
    def test_barriers_do_not_inherit_road_residual_heat(self):
        for name in ('SM_RoadBlock01','SM_TrafficBarrel01'):
            with self.subTest(name=name):
                self.assertEqual(profile_for_mesh(name,289.15)['temperature_k'],289.15)
        self.assertEqual(profile_for_mesh('SM_MergedRoad4',289.15)['temperature_k'],292.15)

    def test_pickups_are_vehicles(self):
        self.assertEqual(profile_for_mesh('SM_Pickup',289.15)['category'],'vehicle')

    def test_constructed_ivy_has_vegetation_profile(self):
        for name in ('SM_Ivy1_02','SM_Ivy2_01'):
            with self.subTest(name=name):
                p=profile_for_mesh(name,289.15)
                self.assertEqual(p['temperature_k'],289.15)
                self.assertEqual(p['emissivity'],.97)

    def test_street_lights_are_not_asphalt(self):
        self.assertEqual(profile_for_mesh('SM_StreetLamp',289.15)['category'],'painted_metal')

    def test_decorative_water_and_camera_helpers_are_excluded(self):
        for name in ('SM_WaterPlane01','PlanarReflectionPlane','MatineeCam_SM','SM_CineCam'):
            with self.subTest(name=name):
                self.assertTrue(profile_for_mesh(name,289.15)['ignored'])
        self.assertFalse(profile_for_mesh('WaterTank',289.15)['ignored'])

    def test_imported_equipment_is_explicit(self):
        self.assertEqual(profile_for_mesh('SM_Kenney_detail_tank',289.15)['category'],'process_or_storage_equipment')
        self.assertEqual(profile_for_mesh('SM_Kenney_solar_panel_landscape',289.15)['category'],'solar_equipment')


if __name__=='__main__':unittest.main()
