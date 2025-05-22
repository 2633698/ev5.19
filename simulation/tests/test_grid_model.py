import unittest
from datetime import datetime
import copy # For deepcopying config if needed

# Adjust import path based on how tests will be run.
# If run from project root with `python -m unittest simulation.tests.test_grid_model`:
from simulation.grid_model import GridModel 

class TestGridModel(unittest.TestCase):

    def setUp(self):
        """Set up a sample configuration and GridModel instance for tests."""
        self.sample_config = {
            'environment': {
                'region_count': 2, # Can also be derived if not explicitly set and grid keys are present
                'time_step_minutes': 15 # For total_steps calculation if used by GridModel directly
            },
            'grid': {
                'base_load': { # Regionalized
                    'region_0': [100] * 24, # 100kW constant base load for region_0
                    'region_1': [200] * 24  # 200kW constant base load for region_1
                },
                'solar_generation': { # Regionalized
                    'region_0': [10] * 24, # 10kW constant solar for region_0
                    'region_1': [20] * 24  # 20kW constant solar for region_1
                },
                'wind_generation': { # Regionalized
                    'region_0': [5] * 24,  # 5kW constant wind for region_0
                    'region_1': [15] * 24  # 15kW constant wind for region_1
                },
                'system_capacity_kw': { # Regionalized system_capacity_kw
                    'region_0': 1000,    # 1MW capacity for region_0
                    'region_1': 2000     # 2MW capacity for region_1
                },
                # Global settings remain
                'peak_hours': [8, 9, 17, 18], 
                'valley_hours': [0, 1, 2, 3],
                'normal_price': 0.85,
                'peak_price': 1.2,
                'valley_price': 0.4
            }
        }
        # Ensure a fresh GridModel instance for each test
        self.grid_model = GridModel(copy.deepcopy(self.sample_config))

    def test_initialization_regional(self):
        """Test correct initialization with regional configuration."""
        self.assertListEqual(sorted(self.grid_model.region_ids), sorted(['region_0', 'region_1']))
        
        # Check if profiles are correctly loaded into grid_status
        self.assertIn('base_load_profiles_regional', self.grid_model.grid_status)
        self.assertEqual(len(self.grid_model.grid_status['base_load_profiles_regional']['region_0']), 24)
        self.assertEqual(self.grid_model.grid_status['base_load_profiles_regional']['region_0'][0], 100)
        self.assertEqual(self.grid_model.grid_status['base_load_profiles_regional']['region_1'][5], 200)

        self.assertIn('system_capacity_regional', self.grid_model.grid_status)
        self.assertEqual(self.grid_model.grid_status['system_capacity_regional']['region_0'], 1000)
        self.assertEqual(self.grid_model.grid_status['system_capacity_regional']['region_1'], 2000)

        # Check initial current loads at hour 0 (after reset() call in GridModel.__init__)
        initial_hour = 0
        # Base loads
        self.assertEqual(self.grid_model.grid_status['current_base_load_regional']['region_0'], 
                         self.sample_config['grid']['base_load']['region_0'][initial_hour])
        self.assertEqual(self.grid_model.grid_status['current_base_load_regional']['region_1'], 
                         self.sample_config['grid']['base_load']['region_1'][initial_hour])
        # Solar generation
        self.assertEqual(self.grid_model.grid_status['current_solar_gen_regional']['region_0'],
                         self.sample_config['grid']['solar_generation']['region_0'][initial_hour])
        # Wind generation
        self.assertEqual(self.grid_model.grid_status['current_wind_gen_regional']['region_1'],
                         self.sample_config['grid']['wind_generation']['region_1'][initial_hour])
        
        # EV load should be zero initially for all regions
        self.assertEqual(self.grid_model.grid_status['current_ev_load_regional']['region_0'], 0)
        self.assertEqual(self.grid_model.grid_status['current_ev_load_regional']['region_1'], 0)

        # Total load initially should be base load (as EV load is 0)
        self.assertEqual(self.grid_model.grid_status['current_total_load_regional']['region_0'],
                         self.sample_config['grid']['base_load']['region_0'][initial_hour])
        self.assertEqual(self.grid_model.grid_status['current_total_load_regional']['region_1'],
                         self.sample_config['grid']['base_load']['region_1'][initial_hour])
        
        # Check initial load percentage
        expected_load_pct_r0 = (100 / 1000) * 100
        expected_load_pct_r1 = (200 / 2000) * 100
        self.assertAlmostEqual(self.grid_model.grid_status['grid_load_percentage_regional']['region_0'], expected_load_pct_r0)
        self.assertAlmostEqual(self.grid_model.grid_status['grid_load_percentage_regional']['region_1'], expected_load_pct_r1)

        # Check initial renewable ratio
        # R0: (10 solar + 5 wind) / 100 base = 15 / 100 = 15%
        # R1: (20 solar + 15 wind) / 200 base = 35 / 200 = 17.5%
        expected_renew_ratio_r0 = ((10 + 5) / 100) * 100
        expected_renew_ratio_r1 = ((20 + 15) / 200) * 100
        self.assertAlmostEqual(self.grid_model.grid_status['renewable_ratio_regional']['region_0'], expected_renew_ratio_r0)
        self.assertAlmostEqual(self.grid_model.grid_status['renewable_ratio_regional']['region_1'], expected_renew_ratio_r1)

    def test_update_step_regional_loads(self):
        """Test update_step with regional load distribution and calculations."""
        # Reset to ensure clean state (though setUp does this, explicit reset before update_step is good practice)
        self.grid_model.reset()

        # Simulate an update step, e.g., at hour 8 (peak hour in sample config)
        current_time = datetime(2023, 1, 1, 8, 0, 0) # Hour 8
        global_ev_load = 300  # Global EV load of 300 kW

        self.grid_model.update_step(current_time, global_ev_load)
        status = self.grid_model.get_status()

        # Verify EV Load Distribution (proportional to system_capacity_regional)
        # R0 capacity: 1000, R1 capacity: 2000. Total: 3000
        # R0 EV load: (1000/3000) * 300 = 100
        # R1 EV load: (2000/3000) * 300 = 200
        self.assertAlmostEqual(status['current_ev_load_regional']['region_0'], 100)
        self.assertAlmostEqual(status['current_ev_load_regional']['region_1'], 200)

        # Verify Total Load per Region (base load at hour 8 + regional EV load)
        # Base loads at hour 8: R0 = 100, R1 = 200
        expected_total_load_r0 = 100 + 100 # base_r0 + ev_r0
        expected_total_load_r1 = 200 + 200 # base_r1 + ev_r1
        self.assertAlmostEqual(status['current_total_load_regional']['region_0'], expected_total_load_r0)
        self.assertAlmostEqual(status['current_total_load_regional']['region_1'], expected_total_load_r1)

        # Verify Load Percentage per Region
        # R0: (200 / 1000) * 100 = 20%
        # R1: (400 / 2000) * 100 = 20%
        expected_load_pct_r0 = (expected_total_load_r0 / self.sample_config['grid']['system_capacity_kw']['region_0']) * 100
        expected_load_pct_r1 = (expected_total_load_r1 / self.sample_config['grid']['system_capacity_kw']['region_1']) * 100
        self.assertAlmostEqual(status['grid_load_percentage_regional']['region_0'], expected_load_pct_r0)
        self.assertAlmostEqual(status['grid_load_percentage_regional']['region_1'], expected_load_pct_r1)
        
        # Verify Renewable Ratio per Region
        # Solar/Wind at hour 8: R0_solar=10, R0_wind=5; R1_solar=20, R1_wind=15
        # R0: (10 + 5) / 200_total_load_r0 = 15 / 200 = 7.5%
        # R1: (20 + 15) / 400_total_load_r1 = 35 / 400 = 8.75%
        solar_r0_h8 = self.sample_config['grid']['solar_generation']['region_0'][8]
        wind_r0_h8 = self.sample_config['grid']['wind_generation']['region_0'][8]
        solar_r1_h8 = self.sample_config['grid']['solar_generation']['region_1'][8]
        wind_r1_h8 = self.sample_config['grid']['wind_generation']['region_1'][8]

        expected_renew_ratio_r0 = ((solar_r0_h8 + wind_r0_h8) / expected_total_load_r0) * 100 if expected_total_load_r0 > 0 else 0
        expected_renew_ratio_r1 = ((solar_r1_h8 + wind_r1_h8) / expected_total_load_r1) * 100 if expected_total_load_r1 > 0 else 0
        self.assertAlmostEqual(status['renewable_ratio_regional']['region_0'], expected_renew_ratio_r0)
        self.assertAlmostEqual(status['renewable_ratio_regional']['region_1'], expected_renew_ratio_r1)

        # Verify current price is peak price at hour 8
        self.assertEqual(status['current_price'], self.sample_config['grid']['peak_price'])

    def test_get_status_structure(self):
        """Test that get_status() returns a dictionary with the correct regionalized keys."""
        status = self.grid_model.get_status()
        
        # Check for presence of top-level regional keys
        self.assertIn('base_load_profiles_regional', status)
        self.assertIn('solar_generation_profiles_regional', status)
        self.assertIn('wind_generation_profiles_regional', status)
        self.assertIn('system_capacity_regional', status)
        
        self.assertIn('current_base_load_regional', status)
        self.assertIn('current_solar_gen_regional', status)
        self.assertIn('current_wind_gen_regional', status)
        self.assertIn('current_ev_load_regional', status)
        self.assertIn('current_total_load_regional', status)
        self.assertIn('grid_load_percentage_regional', status)
        self.assertIn('renewable_ratio_regional', status)

        # Check that these are dictionaries themselves, keyed by region_id
        for region_id in self.grid_model.region_ids:
            self.assertIn(region_id, status['current_base_load_regional'])
            self.assertIn(region_id, status['current_ev_load_regional'])
            # ... and so on for other regional current values
            self.assertIn(region_id, status['grid_load_percentage_regional'])
            self.assertIn(region_id, status['system_capacity_regional'])

    def test_missing_regional_config_fallback(self):
        """Test fallback behavior when a region is missing specific profile data."""
        config_missing_solar_r1 = copy.deepcopy(self.sample_config)
        # Remove solar generation data for region_1
        del config_missing_solar_r1['grid']['solar_generation']['region_1']
        
        grid_model_missing_data = GridModel(config_missing_solar_r1)
        status = grid_model_missing_data.get_status()

        # region_1 solar profile should fallback to default (e.g., list of 0s)
        self.assertIn('region_1', status['solar_generation_profiles_regional'])
        self.assertEqual(status['solar_generation_profiles_regional']['region_1'], [0] * 24)
        # Initial current solar gen for region_1 should be the first element of the default profile (0)
        self.assertEqual(status['current_solar_gen_regional']['region_1'], 0)

        # Check that region_0 solar data is still intact
        self.assertEqual(status['solar_generation_profiles_regional']['region_0'], 
                         self.sample_config['grid']['solar_generation']['region_0'])
        self.assertEqual(status['current_solar_gen_regional']['region_0'], 
                         self.sample_config['grid']['solar_generation']['region_0'][0])

        # Test missing system_capacity_kw for a region
        config_missing_capacity_r0 = copy.deepcopy(self.sample_config)
        del config_missing_capacity_r0['grid']['system_capacity_kw']['region_0']
        grid_model_missing_cap = GridModel(config_missing_capacity_r0)
        status_cap = grid_model_missing_cap.get_status()
        
        # region_0 system capacity should fallback to default (e.g., 10000 as per GridModel helper)
        self.assertEqual(status_cap['system_capacity_regional']['region_0'], 10000) 
        # region_1 should still be present
        self.assertEqual(status_cap['system_capacity_regional']['region_1'], 
                         self.sample_config['grid']['system_capacity_kw']['region_1'])


if __name__ == '__main__':
    unittest.main()
