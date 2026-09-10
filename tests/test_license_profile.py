import io
import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch


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
            conn.execute('DELETE FROM shared_data_events')
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

    def test_no_return_cargo_choice_is_saved_as_no(self):
        driver_id = self.db.create_driver('No Return Driver')
        response = self.client.post('/checkin', data={
            'driver_id': str(driver_id),
            'needs_return_cargo': '0',
            'scheduled_time': '18:00',
            'arrival_time': '18:00',
            'route': 'RIC',
        })

        checkin_id = int(response.headers['Location'].rstrip('/').split('/')[-1])
        self.assertEqual(self.db.get_checkin(checkin_id)['needs_return_cargo'], 0)
        self.assertIn('不需要回货'.encode('utf-8'), self.client.get(f'/print/{checkin_id}').data)

    def test_operational_day_changes_at_3am(self):
        self.assertEqual(
            self.db.get_operational_date(datetime(2026, 9, 10, 2, 59)),
            datetime(2026, 9, 9).date(),
        )
        self.assertEqual(
            self.db.get_operational_date(datetime(2026, 9, 10, 3, 0)),
            datetime(2026, 9, 10).date(),
        )

    def test_checkin_after_midnight_is_stored_on_previous_operational_day(self):
        driver_id = self.db.create_driver('After Midnight Driver')
        with patch.object(self.db, 'datetime') as mocked_datetime:
            mocked_datetime.now.return_value = datetime(2026, 9, 10, 1, 30)
            checkin_id = self.db.create_checkin(driver_id, arrival_time='01:30')

        self.assertEqual(self.db.get_checkin(checkin_id)['date'], '2026-09-09')

    def test_upload_page_allows_selecting_previous_date(self):
        response = self.client.get('/upload?date=2026-09-09')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'name="record_date" value="2026-09-09"', response.data)
        self.assertIn(b'/?date=2026-09-09', response.data)

    def test_bundled_history_imports_once_and_uses_operational_dates(self):
        first = self.db.import_historical_seed()
        second = self.db.import_historical_seed()

        self.assertEqual(first['inserted'], 282)
        self.assertEqual(second['inserted'], 0)
        self.assertEqual(first['updates_applied'], 121)
        self.assertEqual(second['updates_applied'], 0)
        with self.db.get_db() as conn:
            total = conn.execute('SELECT COUNT(*) FROM checkins').fetchone()[0]
            after_midnight = conn.execute('''
                SELECT date, score_given FROM checkins
                WHERE dms_task_id = 'MT2026091000325'
            ''').fetchone()
            chat_record = conn.execute('''
                SELECT ch.date, ch.scheduled_time, ch.arrival_time, ch.late_minutes,
                       ch.dms_task_id, ch.dms_match_confirmed, ch.score_given,
                       d.name, d.phone
                FROM checkins ch
                JOIN drivers d ON d.id = ch.driver_id
                WHERE ch.source_record_key = 'CHAT-20260910-IAD-1830-TEMEEKA-WILLIAMS'
            ''').fetchone()
        self.assertEqual(total, 284)
        self.assertEqual(after_midnight['date'], '2026-09-09')
        self.assertEqual(after_midnight['score_given'], 100.0)
        self.assertEqual(chat_record['date'], '2026-09-10')
        self.assertEqual(chat_record['scheduled_time'], '18:30')
        self.assertEqual(chat_record['arrival_time'], '18:30')
        self.assertEqual(chat_record['late_minutes'], 0)
        self.assertEqual(chat_record['dms_task_id'], '')
        self.assertEqual(chat_record['dms_match_confirmed'], 0)
        self.assertEqual(chat_record['score_given'], 100.0)
        self.assertEqual(chat_record['name'], 'Temeeka Williams')
        self.assertEqual(chat_record['phone'], '240-481-8722')

    def test_chat_evidence_updates_scores_once_and_preserves_later_edits(self):
        self.db.import_historical_seed()
        with self.db.get_db() as conn:
            luke = conn.execute('''
                SELECT id, scheduled_time, arrival_time, late_minutes, score_given
                FROM checkins WHERE dms_task_id = 'MT2026082500699'
            ''').fetchone()
            kevin = conn.execute('''
                SELECT score_given, manual_deduction, manual_deduction_category
                FROM checkins WHERE dms_task_id = 'MT2026090100732'
            ''').fetchone()
            joseph = conn.execute('''
                SELECT ch.score_given, ch.manual_deduction, d.status
                FROM checkins ch JOIN drivers d ON d.id = ch.driver_id
                WHERE ch.source_record_key = 'MAPCHAT-20260826-JOSEPH-BEHAVIOR'
            ''').fetchone()

        self.assertEqual(luke['scheduled_time'], '18:30')
        self.assertEqual(luke['arrival_time'], '19:00')
        self.assertEqual(luke['late_minutes'], 30)
        self.assertEqual(luke['score_given'], 55.0)
        self.assertEqual(kevin['score_given'], 0.0)
        self.assertEqual(kevin['manual_deduction'], 100.0)
        self.assertEqual(kevin['manual_deduction_category'], '影响操作')
        self.assertEqual(joseph['score_given'], 0.0)
        self.assertEqual(joseph['status'], '限制')

        with self.db.get_db() as conn:
            conn.execute('''
                UPDATE checkins SET arrival_time = '18:30', late_minutes = 0, score_given = 100
                WHERE id = ?
            ''', (luke['id'],))
        result = self.db.import_historical_seed()
        edited = self.db.get_checkin(luke['id'])
        self.assertEqual(result['updates_applied'], 0)
        self.assertEqual(edited['arrival_time'], '18:30')
        self.assertEqual(edited['score_given'], 100.0)

    def test_bundled_history_does_not_overwrite_existing_task_result(self):
        self.db.import_historical_seed()
        with self.db.get_db() as conn:
            task = conn.execute('''
                SELECT id FROM checkins WHERE dms_task_id = 'MT2026081500668'
            ''').fetchone()
            conn.execute('''
                UPDATE checkins
                SET score_given = 0, route_ok = 0, manual_deduction = 20,
                    manual_deduction_category = '影响操作'
                WHERE id = ?
            ''', (task['id'],))

        self.db.import_historical_seed()
        checkin = self.db.get_checkin(task['id'])
        self.assertEqual(checkin['score_given'], 0)
        self.assertEqual(checkin['route_ok'], 0)
        self.assertEqual(checkin['manual_deduction'], 20)


if __name__ == '__main__':
    unittest.main()
