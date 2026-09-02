import io
import os
import tempfile
import unittest


class DriverLicenseProfileTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()

        import config
        config.DATA_DIR = cls.temp_dir.name
        config.DATABASE_PATH = os.path.join(cls.temp_dir.name, 'test.db')

        import database
        import app as app_module

        cls.db = database
        cls.app_module = app_module
        cls.app_module.app.config.update(
            TESTING=True,
            UPLOAD_FOLDER=os.path.join(cls.temp_dir.name, 'uploads')
        )
        os.makedirs(cls.app_module.app.config['UPLOAD_FOLDER'], exist_ok=True)
        cls.client = cls.app_module.app.test_client()

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def setUp(self):
        with self.db.get_db() as conn:
            conn.execute('DELETE FROM checkins')
            conn.execute('DELETE FROM drivers')

    def test_existing_driver_photo_is_reused_for_checkin_and_print(self):
        driver_id = self.db.create_driver('Profile Photo Driver', license_photo='stored-license.jpg')

        response = self.client.post('/checkin', data={
            'driver_id': str(driver_id),
            'scheduled_time': '18:00',
            'arrival_time': '17:45',
            'route': 'RIC',
        })

        self.assertEqual(response.status_code, 302)
        checkin_id = int(response.headers['Location'].rstrip('/').split('/')[-1])
        checkin = self.db.get_checkin(checkin_id)
        self.assertEqual(checkin['license_photo'], 'stored-license.jpg')
        self.assertEqual(checkin['effective_license_photo'], 'stored-license.jpg')

        print_page = self.client.get(f'/print/{checkin_id}')
        self.assertIn(b'/uploads/stored-license.jpg', print_page.data)

    def test_checkin_upload_updates_driver_profile(self):
        driver_id = self.db.create_driver('Photo Update Driver')

        response = self.client.post('/checkin', data={
            'driver_id': str(driver_id),
            'scheduled_time': '18:00',
            'arrival_time': '18:00',
            'route': 'DCA',
            'license_photo': (io.BytesIO(b'fake-image'), 'driver-license.jpg'),
        }, content_type='multipart/form-data')

        self.assertEqual(response.status_code, 302)
        driver = self.db.get_driver(driver_id)
        self.assertTrue(driver['license_photo'].endswith('_driver-license.jpg'))
        self.assertTrue(os.path.exists(os.path.join(
            self.app_module.app.config['UPLOAD_FOLDER'], driver['license_photo']
        )))

        checkin_id = int(response.headers['Location'].rstrip('/').split('/')[-1])
        self.assertEqual(self.db.get_checkin(checkin_id)['license_photo'], driver['license_photo'])

    def test_driver_form_accepts_profile_photo(self):
        response = self.client.get('/driver/new')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'enctype="multipart/form-data"', response.data)
        self.assertIn(b'name="license_photo"', response.data)


if __name__ == '__main__':
    unittest.main()
