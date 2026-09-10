import json
import os
import sqlite3
from datetime import datetime, date, timedelta
from contextlib import contextmanager

import config


OPERATIONAL_DAY_CUTOFF_HOUR = 3


def get_operational_date(current_time=None):
    """Return the dispatch date; 00:00-02:59 belongs to the previous day."""
    current_time = current_time or datetime.now()
    if current_time.hour < OPERATIONAL_DAY_CUTOFF_HOUR:
        return (current_time - timedelta(days=1)).date()
    return current_time.date()


@contextmanager
def get_db():
    conn = sqlite3.connect(config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.executescript('''
            -- 供应商表
            CREATE TABLE IF NOT EXISTS carriers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                contact TEXT DEFAULT '',
                phone TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            -- 司机表
            CREATE TABLE IF NOT EXISTS drivers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                phone TEXT DEFAULT '',
                carrier_id INTEGER,
                usual_routes TEXT DEFAULT '',
                license_photo TEXT DEFAULT '',
                status TEXT DEFAULT '可用',
                score REAL DEFAULT 100.0,
                auto_score REAL DEFAULT 100.0,
                manual_score REAL,
                manual_score_reason TEXT DEFAULT '',
                manual_score_updated_at DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (carrier_id) REFERENCES carriers(id)
            );

            -- 司机总评分的人工调整历史
            CREATE TABLE IF NOT EXISTS driver_score_adjustments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                driver_id INTEGER NOT NULL,
                previous_score REAL NOT NULL,
                new_score REAL NOT NULL,
                action TEXT DEFAULT '手动设置',
                reason TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (driver_id) REFERENCES drivers(id)
            );

            -- Check-in 记录表
            CREATE TABLE IF NOT EXISTS checkins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date DATE NOT NULL,
                driver_id INTEGER NOT NULL,
                carrier_id INTEGER,
                
                -- Check-in 时填写
                scheduled_time TEXT DEFAULT '',
                arrival_time TEXT DEFAULT '',
                needs_return_cargo INTEGER DEFAULT 0,
                truck TEXT DEFAULT '',
                dock TEXT DEFAULT '',
                license_photo TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                
                -- 上传表格后自动填充
                dms_task_id TEXT DEFAULT '',
                source_record_key TEXT DEFAULT '',
                dms_match_confirmed INTEGER DEFAULT 0,
                route TEXT DEFAULT '',
                departure_time TEXT DEFAULT '',
                return_cargo_status TEXT DEFAULT '',
                route_ok INTEGER DEFAULT 1,
                manual_deduction REAL DEFAULT 0,
                manual_deduction_category TEXT DEFAULT '',
                manual_deduction_reason TEXT DEFAULT '',
                
                -- 自动计算
                wait_minutes INTEGER,
                late_minutes INTEGER,
                
                -- 评分
                score_given REAL,
                
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                
                FOREIGN KEY (driver_id) REFERENCES drivers(id),
                FOREIGN KEY (carrier_id) REFERENCES carriers(id)
            );

            CREATE INDEX IF NOT EXISTS idx_checkins_date ON checkins(date);
            CREATE INDEX IF NOT EXISTS idx_checkins_driver ON checkins(driver_id);
            CREATE INDEX IF NOT EXISTS idx_driver_score_adjustments_driver
                ON driver_score_adjustments(driver_id, created_at DESC);

            -- 共享数据更新的幂等记录。每条聊天证据只应用一次，避免应用每次
            -- 启动时覆盖调度员之后做出的人工修正。
            CREATE TABLE IF NOT EXISTS shared_data_events (
                event_key TEXT PRIMARY KEY,
                checkin_id INTEGER,
                applied_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (checkin_id) REFERENCES checkins(id)
            );
            
            -- 只保留 HHX 和 MAP
            INSERT OR IGNORE INTO carriers (name) VALUES ('HHX');
            INSERT OR IGNORE INTO carriers (name) VALUES ('MAP');
        ''')

        # 兼容已存在的数据库：SQLite 的 CREATE TABLE 不会自动补齐新字段。
        columns = {row['name'] for row in conn.execute('PRAGMA table_info(checkins)')}
        if 'return_cargo_status' not in columns:
            conn.execute("ALTER TABLE checkins ADD COLUMN return_cargo_status TEXT DEFAULT ''")
        if 'route_ok' not in columns:
            conn.execute('ALTER TABLE checkins ADD COLUMN route_ok INTEGER DEFAULT 1')
        if 'dms_match_confirmed' not in columns:
            conn.execute('ALTER TABLE checkins ADD COLUMN dms_match_confirmed INTEGER DEFAULT 0')
        if 'source_record_key' not in columns:
            conn.execute("ALTER TABLE checkins ADD COLUMN source_record_key TEXT DEFAULT ''")
        if 'manual_deduction' not in columns:
            conn.execute('ALTER TABLE checkins ADD COLUMN manual_deduction REAL DEFAULT 0')
        if 'manual_deduction_category' not in columns:
            conn.execute("ALTER TABLE checkins ADD COLUMN manual_deduction_category TEXT DEFAULT ''")
        if 'manual_deduction_reason' not in columns:
            conn.execute("ALTER TABLE checkins ADD COLUMN manual_deduction_reason TEXT DEFAULT ''")

        driver_columns = {row['name'] for row in conn.execute('PRAGMA table_info(drivers)')}
        if 'auto_score' not in driver_columns:
            conn.execute('ALTER TABLE drivers ADD COLUMN auto_score REAL')
        if 'manual_score' not in driver_columns:
            conn.execute('ALTER TABLE drivers ADD COLUMN manual_score REAL')
        if 'manual_score_reason' not in driver_columns:
            conn.execute("ALTER TABLE drivers ADD COLUMN manual_score_reason TEXT DEFAULT ''")
        if 'manual_score_updated_at' not in driver_columns:
            conn.execute('ALTER TABLE drivers ADD COLUMN manual_score_updated_at DATETIME')
        conn.execute('UPDATE drivers SET auto_score = score WHERE auto_score IS NULL')
        conn.execute('''
            CREATE UNIQUE INDEX IF NOT EXISTS idx_checkins_source_record_key
            ON checkins(source_record_key)
            WHERE source_record_key <> ''
        ''')
    import_historical_seed()
    print(f"数据库已初始化: {config.DATABASE_PATH}")


def normalize_driver_name(name):
    """Normalize punctuation, spaces and letter case for historical-name matching."""
    return ''.join(char.casefold() for char in str(name or '') if char.isalnum())


def import_historical_seed(seed_path=None):
    """Merge the bundled shared history without duplicating MT task IDs.

    Existing task scores, driver assignments and manually recorded outcomes are
    preserved. The supplied dispatch date is authoritative so the 03:00
    operational-day rule is applied consistently on every computer.
    """
    seed_path = seed_path or config.HISTORICAL_SEED_PATH
    if not os.path.exists(seed_path):
        return {'inserted': 0, 'existing': 0, 'total': 0}

    try:
        with open(seed_path, 'r', encoding='utf-8') as seed_file:
            seed = json.load(seed_file)
    except (OSError, ValueError, TypeError) as error:
        print(f"历史数据包无法读取: {error}")
        return {'inserted': 0, 'existing': 0, 'total': 0}

    records = seed.get('records') or []
    aliases = seed.get('driver_aliases') or {}
    updates_path = getattr(config, 'CHAT_UPDATES_PATH', '')
    chat_updates = []
    if updates_path and os.path.exists(updates_path):
        try:
            with open(updates_path, 'r', encoding='utf-8') as updates_file:
                chat_updates = (json.load(updates_file).get('updates') or [])
        except (OSError, ValueError, TypeError) as error:
            print(f"聊天更新数据包无法读取: {error}")
    inserted = 0
    existing = 0
    updates_applied = 0
    updates_existing = 0
    affected_driver_ids = set()

    with get_db() as conn:
        carrier_ids = {
            str(row['name']).strip().casefold(): row['id']
            for row in conn.execute('SELECT id, name FROM carriers')
        }
        drivers = [dict(row) for row in conn.execute(
            'SELECT id, name, phone, carrier_id, usual_routes FROM drivers'
        )]
        driver_ids = {normalize_driver_name(row['name']): row['id'] for row in drivers}
        driver_rows = {row['id']: row for row in drivers}

        for record in records:
            task_id = str(record.get('task_id') or '').strip()
            record_key = str(record.get('record_key') or '').strip()
            driver_name = str(record.get('driver') or '').strip()
            record_date = str(record.get('date') or '').strip()
            if not (task_id or record_key) or not driver_name or not record_date:
                continue

            carrier_name = str(record.get('carrier') or '').strip()
            carrier_id = carrier_ids.get(carrier_name.casefold()) if carrier_name else None
            if carrier_name and carrier_id is None:
                cursor = conn.execute('INSERT INTO carriers (name) VALUES (?)', (carrier_name,))
                carrier_id = cursor.lastrowid
                carrier_ids[carrier_name.casefold()] = carrier_id

            existing_task = None
            if task_id:
                existing_task = conn.execute(
                    'SELECT id, driver_id FROM checkins WHERE dms_task_id = ? LIMIT 1',
                    (task_id,),
                ).fetchone()
            if existing_task is None and record_key:
                existing_task = conn.execute(
                    'SELECT id, driver_id FROM checkins WHERE source_record_key = ? LIMIT 1',
                    (record_key,),
                ).fetchone()
            if existing_task:
                scheduled_time = str(record.get('scheduled_time') or '')
                arrival_time = str(record.get('arrival_time') or '')
                late_minutes = calculate_late_minutes(scheduled_time, arrival_time)
                conn.execute('''
                    UPDATE checkins
                    SET date = ?,
                        route = CASE WHEN COALESCE(route, '') = '' THEN ? ELSE route END,
                        departure_time = CASE WHEN COALESCE(departure_time, '') = '' THEN ? ELSE departure_time END,
                        truck = CASE WHEN COALESCE(truck, '') = '' THEN ? ELSE truck END,
                        dock = CASE WHEN COALESCE(dock, '') = '' THEN ? ELSE dock END,
                        scheduled_time = CASE WHEN COALESCE(scheduled_time, '') = '' THEN ? ELSE scheduled_time END,
                        arrival_time = CASE WHEN COALESCE(arrival_time, '') = '' THEN ? ELSE arrival_time END,
                        late_minutes = COALESCE(late_minutes, ?),
                        notes = CASE WHEN COALESCE(notes, '') = '' THEN ? ELSE notes END,
                        source_record_key = CASE WHEN COALESCE(source_record_key, '') = '' THEN ? ELSE source_record_key END,
                        needs_return_cargo = CASE WHEN ? = 1 THEN 1 ELSE needs_return_cargo END,
                        dms_match_confirmed = CASE WHEN ? = 1 THEN 1 ELSE dms_match_confirmed END,
                        score_given = COALESCE(score_given, ?)
                    WHERE id = ?
                ''', (
                    record_date,
                    str(record.get('route') or ''),
                    str(record.get('departure_time') or ''),
                    str(record.get('truck') or ''),
                    str(record.get('dock') or ''),
                    scheduled_time,
                    arrival_time,
                    late_minutes,
                    str(record.get('notes') or ''),
                    record_key,
                    int(bool(record.get('needs_return_cargo'))),
                    int(bool(task_id)),
                    float(record.get('score_given', 100.0)),
                    existing_task['id'],
                ))
                phone = str(record.get('phone') or '').strip()
                if phone:
                    conn.execute('''
                        UPDATE drivers
                        SET phone = CASE WHEN COALESCE(phone, '') = '' THEN ? ELSE phone END
                        WHERE id = ?
                    ''', (phone, existing_task['driver_id']))
                affected_driver_ids.add(existing_task['driver_id'])
                existing += 1
                continue

            lookup_names = [driver_name] + list(aliases.get(driver_name) or [])
            driver_id = next(
                (driver_ids.get(normalize_driver_name(name)) for name in lookup_names
                 if driver_ids.get(normalize_driver_name(name)) is not None),
                None,
            )
            route = str(record.get('route') or '').strip()

            if driver_id is None:
                phone = str(record.get('phone') or '').strip()
                cursor = conn.execute('''
                    INSERT INTO drivers (name, phone, carrier_id, usual_routes)
                    VALUES (?, ?, ?, ?)
                ''', (driver_name, phone, carrier_id, route))
                driver_id = cursor.lastrowid
                row = {
                    'id': driver_id,
                    'name': driver_name,
                    'phone': phone,
                    'carrier_id': carrier_id,
                    'usual_routes': route,
                }
                driver_ids[normalize_driver_name(driver_name)] = driver_id
                driver_rows[driver_id] = row
            else:
                driver = driver_rows[driver_id]
                updates = []
                values = []
                if driver['name'] != driver_name and driver['name'] in (aliases.get(driver_name) or []):
                    updates.append('name = ?')
                    values.append(driver_name)
                    driver_ids.pop(normalize_driver_name(driver['name']), None)
                    driver_ids[normalize_driver_name(driver_name)] = driver_id
                    driver['name'] = driver_name
                if carrier_id is not None and driver.get('carrier_id') is None:
                    updates.append('carrier_id = ?')
                    values.append(carrier_id)
                    driver['carrier_id'] = carrier_id
                phone = str(record.get('phone') or '').strip()
                if phone and not str(driver.get('phone') or '').strip():
                    updates.append('phone = ?')
                    values.append(phone)
                    driver['phone'] = phone
                routes = [value.strip() for value in (driver.get('usual_routes') or '').split(',') if value.strip()]
                if route and route not in routes:
                    routes.append(route)
                    updates.append('usual_routes = ?')
                    values.append(','.join(routes))
                    driver['usual_routes'] = ','.join(routes)
                if updates:
                    conn.execute(
                        f"UPDATE drivers SET {', '.join(updates)} WHERE id = ?",
                        values + [driver_id],
                    )

            conn.execute('''
                INSERT INTO checkins (
                    date, driver_id, carrier_id, dms_task_id, source_record_key,
                    dms_match_confirmed, route, scheduled_time, arrival_time,
                    departure_time, truck, dock, notes, needs_return_cargo,
                    route_ok, late_minutes, score_given
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                record_date,
                driver_id,
                carrier_id,
                task_id,
                record_key,
                int(bool(task_id)),
                route,
                str(record.get('scheduled_time') or ''),
                str(record.get('arrival_time') or ''),
                str(record.get('departure_time') or ''),
                str(record.get('truck') or ''),
                str(record.get('dock') or ''),
                str(record.get('notes') or ''),
                int(bool(record.get('needs_return_cargo'))),
                int(bool(record.get('route_ok', 1))),
                calculate_late_minutes(
                    str(record.get('scheduled_time') or ''),
                    str(record.get('arrival_time') or ''),
                ),
                float(record.get('score_given', 100.0)),
            ))
            affected_driver_ids.add(driver_id)
            inserted += 1

        for update in chat_updates:
            event_key = str(update.get('event_key') or '').strip()
            task_id = str(update.get('task_id') or '').strip()
            record_key = str(update.get('record_key') or '').strip()
            driver_name = str(update.get('driver') or '').strip()
            record_date = str(update.get('date') or '').strip()
            if not event_key or not driver_name or not record_date:
                continue

            already_applied = conn.execute(
                'SELECT checkin_id FROM shared_data_events WHERE event_key = ? LIMIT 1',
                (event_key,),
            ).fetchone()
            if already_applied:
                updates_existing += 1
                continue

            checkin = None
            if task_id:
                checkin = conn.execute(
                    'SELECT * FROM checkins WHERE dms_task_id = ? LIMIT 1',
                    (task_id,),
                ).fetchone()
            if checkin is None and record_key:
                checkin = conn.execute(
                    'SELECT * FROM checkins WHERE source_record_key = ? LIMIT 1',
                    (record_key,),
                ).fetchone()

            carrier_name = str(update.get('carrier') or '').strip()
            carrier_id = carrier_ids.get(carrier_name.casefold()) if carrier_name else None
            if carrier_name and carrier_id is None:
                cursor = conn.execute('INSERT INTO carriers (name) VALUES (?)', (carrier_name,))
                carrier_id = cursor.lastrowid
                carrier_ids[carrier_name.casefold()] = carrier_id

            if checkin is not None:
                checkin = dict(checkin)
                checkin_id = checkin['id']
                driver_id = checkin['driver_id']
                scheduled_time = str(update.get('scheduled_time') or '')
                arrival_time = str(update.get('arrival_time') or '')
                effective_scheduled = str(checkin.get('scheduled_time') or scheduled_time)
                effective_arrival = str(checkin.get('arrival_time') or arrival_time)
                late_minutes = calculate_late_minutes(effective_scheduled, effective_arrival)

                notes = str(update.get('notes') or '').strip()
                vehicle_parts = []
                if str(update.get('truck_number') or '').strip():
                    vehicle_parts.append(f"车号 {str(update.get('truck_number')).strip()}")
                if str(update.get('trailer') or '').strip():
                    vehicle_parts.append(f"拖车 {str(update.get('trailer')).strip()}")
                if vehicle_parts:
                    notes = f"{notes} 车辆信息：{'；'.join(vehicle_parts)}。".strip()
                old_notes = str(checkin.get('notes') or '').strip()
                merged_notes = old_notes
                if notes and notes not in old_notes:
                    merged_notes = f"{old_notes}\n{notes}".strip()

                had_manual_timing = bool(
                    str(checkin.get('scheduled_time') or '').strip()
                    or str(checkin.get('arrival_time') or '').strip()
                )
                can_apply_authoritative_score = (
                    not had_manual_timing
                    and float(checkin.get('manual_deduction') or 0) == 0
                    and int(checkin.get('route_ok', 1) or 0) == 1
                    and str(checkin.get('return_cargo_status') or '').strip() in ('', '待确认')
                )

                fields = {
                    'date': record_date,
                    'route': str(checkin.get('route') or update.get('route') or ''),
                    'scheduled_time': effective_scheduled,
                    'arrival_time': effective_arrival,
                    'late_minutes': late_minutes,
                    'notes': merged_notes,
                    'dms_match_confirmed': 1 if task_id else int(bool(checkin.get('dms_match_confirmed'))),
                    'updated_at': datetime.now().isoformat(),
                }
                if checkin.get('score_given') is None:
                    fields['score_given'] = float(update.get('score_given', 100.0))
                if update.get('authoritative_score') and can_apply_authoritative_score:
                    fields.update({
                        'score_given': float(update.get('score_given', 100.0)),
                        'manual_deduction': float(update.get('manual_deduction') or 0),
                        'manual_deduction_category': str(update.get('manual_deduction_category') or ''),
                        'manual_deduction_reason': str(update.get('manual_deduction_reason') or ''),
                    })
                assignments = ', '.join(f'{name} = ?' for name in fields)
                conn.execute(
                    f'UPDATE checkins SET {assignments} WHERE id = ?',
                    list(fields.values()) + [checkin_id],
                )
            else:
                lookup_names = [driver_name] + list(aliases.get(driver_name) or [])
                driver_id = next(
                    (driver_ids.get(normalize_driver_name(name)) for name in lookup_names
                     if driver_ids.get(normalize_driver_name(name)) is not None),
                    None,
                )
                route = str(update.get('route') or '').strip()
                phone = str(update.get('phone') or '').strip()
                if driver_id is None:
                    cursor = conn.execute('''
                        INSERT INTO drivers (name, phone, carrier_id, usual_routes)
                        VALUES (?, ?, ?, ?)
                    ''', (driver_name, phone, carrier_id, route))
                    driver_id = cursor.lastrowid
                    driver_ids[normalize_driver_name(driver_name)] = driver_id
                    driver_rows[driver_id] = {
                        'id': driver_id,
                        'name': driver_name,
                        'phone': phone,
                        'carrier_id': carrier_id,
                        'usual_routes': route,
                    }

                scheduled_time = str(update.get('scheduled_time') or '')
                arrival_time = str(update.get('arrival_time') or '')
                cursor = conn.execute('''
                    INSERT INTO checkins (
                        date, driver_id, carrier_id, dms_task_id, source_record_key,
                        dms_match_confirmed, route, scheduled_time, arrival_time,
                        notes, route_ok, late_minutes, manual_deduction,
                        manual_deduction_category, manual_deduction_reason, score_given
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    record_date,
                    driver_id,
                    carrier_id,
                    task_id,
                    record_key or event_key,
                    int(bool(task_id)),
                    route,
                    scheduled_time,
                    arrival_time,
                    str(update.get('notes') or ''),
                    int(bool(update.get('route_ok', 1))),
                    calculate_late_minutes(scheduled_time, arrival_time),
                    float(update.get('manual_deduction') or 0),
                    str(update.get('manual_deduction_category') or ''),
                    str(update.get('manual_deduction_reason') or ''),
                    float(update.get('score_given', 100.0)),
                ))
                checkin_id = cursor.lastrowid

            phone = str(update.get('phone') or '').strip()
            if phone:
                conn.execute('''
                    UPDATE drivers
                    SET phone = CASE WHEN COALESCE(phone, '') = '' THEN ? ELSE phone END
                    WHERE id = ?
                ''', (phone, driver_id))
            driver_status = str(update.get('driver_status') or '').strip()
            if driver_status:
                conn.execute('UPDATE drivers SET status = ? WHERE id = ?', (driver_status, driver_id))

            conn.execute(
                'INSERT INTO shared_data_events (event_key, checkin_id) VALUES (?, ?)',
                (event_key, checkin_id),
            )
            affected_driver_ids.add(driver_id)
            updates_applied += 1

    for driver_id in affected_driver_ids:
        recalculate_driver_score(driver_id)

    return {
        'inserted': inserted,
        'existing': existing,
        'total': len(records),
        'updates_applied': updates_applied,
        'updates_existing': updates_existing,
        'updates_total': len(chat_updates),
    }


# ========== 供应商 ==========

def get_carriers():
    with get_db() as conn:
        rows = conn.execute('SELECT * FROM carriers ORDER BY name').fetchall()
        return [dict(r) for r in rows]


def get_carrier(carrier_id):
    with get_db() as conn:
        row = conn.execute('SELECT * FROM carriers WHERE id = ?', (carrier_id,)).fetchone()
        return dict(row) if row else None


def create_carrier(name, contact='', phone='', notes=''):
    with get_db() as conn:
        cursor = conn.execute(
            'INSERT INTO carriers (name, contact, phone, notes) VALUES (?, ?, ?, ?)',
            (name, contact, phone, notes)
        )
        return cursor.lastrowid


def update_carrier(carrier_id, **kwargs):
    if not kwargs:
        return
    fields = ', '.join(f'{k} = ?' for k in kwargs.keys())
    with get_db() as conn:
        conn.execute(f'UPDATE carriers SET {fields} WHERE id = ?', list(kwargs.values()) + [carrier_id])


# ========== 司机 ==========

def get_drivers():
    with get_db() as conn:
        rows = conn.execute('''
            SELECT d.*, c.name as carrier_name 
            FROM drivers d 
            LEFT JOIN carriers c ON d.carrier_id = c.id 
            ORDER BY d.score DESC, d.name
        ''').fetchall()
        return [dict(r) for r in rows]


def get_driver(driver_id):
    with get_db() as conn:
        row = conn.execute('''
            SELECT d.*, c.name as carrier_name 
            FROM drivers d 
            LEFT JOIN carriers c ON d.carrier_id = c.id 
            WHERE d.id = ?
        ''', (driver_id,)).fetchone()
        return dict(row) if row else None


def create_driver(name, phone='', carrier_id=None, usual_routes='', license_photo=''):
    with get_db() as conn:
        cursor = conn.execute(
            'INSERT INTO drivers (name, phone, carrier_id, usual_routes, license_photo) VALUES (?, ?, ?, ?, ?)',
            (name, phone, carrier_id, usual_routes, license_photo)
        )
        return cursor.lastrowid


def update_driver(driver_id, **kwargs):
    if not kwargs:
        return
    fields = ', '.join(f'{k} = ?' for k in kwargs.keys())
    with get_db() as conn:
        conn.execute(f'UPDATE drivers SET {fields} WHERE id = ?', list(kwargs.values()) + [driver_id])


def set_driver_manual_score(driver_id, new_score, reason):
    """直接设置司机总评分，并保留原分数、原因和时间。"""
    new_score = min(100.0, max(0.0, float(new_score)))
    reason = (reason or '').strip()
    with get_db() as conn:
        driver = conn.execute('SELECT score FROM drivers WHERE id = ?', (driver_id,)).fetchone()
        if not driver:
            return False
        previous_score = float(driver['score'] if driver['score'] is not None else 100.0)
        now = datetime.now().isoformat(timespec='seconds')
        conn.execute('''
            UPDATE drivers
            SET score = ?, manual_score = ?, manual_score_reason = ?, manual_score_updated_at = ?
            WHERE id = ?
        ''', (new_score, new_score, reason, now, driver_id))
        conn.execute('''
            INSERT INTO driver_score_adjustments
                (driver_id, previous_score, new_score, action, reason, created_at)
            VALUES (?, ?, ?, '手动设置', ?, ?)
        ''', (driver_id, previous_score, new_score, reason, now))
    return True


def clear_driver_manual_score(driver_id, reason='恢复自动评分'):
    """取消人工覆盖，恢复当前近 30 天任务自动评分。"""
    reason = (reason or '').strip() or '恢复自动评分'
    with get_db() as conn:
        driver = conn.execute(
            'SELECT score, auto_score FROM drivers WHERE id = ?', (driver_id,)
        ).fetchone()
        if not driver:
            return False
        previous_score = float(driver['score'] if driver['score'] is not None else 100.0)
        auto_score = float(driver['auto_score'] if driver['auto_score'] is not None else 100.0)
        now = datetime.now().isoformat(timespec='seconds')
        conn.execute('''
            UPDATE drivers
            SET score = ?, manual_score = NULL, manual_score_reason = '', manual_score_updated_at = ?
            WHERE id = ?
        ''', (auto_score, now, driver_id))
        conn.execute('''
            INSERT INTO driver_score_adjustments
                (driver_id, previous_score, new_score, action, reason, created_at)
            VALUES (?, ?, ?, '恢复自动', ?, ?)
        ''', (driver_id, previous_score, auto_score, reason, now))
    recalculate_driver_score(driver_id)
    return True


def get_driver_score_adjustments(driver_id, limit=10):
    with get_db() as conn:
        rows = conn.execute('''
            SELECT * FROM driver_score_adjustments
            WHERE driver_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
        ''', (driver_id, int(limit))).fetchall()
        return [dict(row) for row in rows]


# ========== Check-in 记录 ==========

def get_checkins_by_date(record_date):
    with get_db() as conn:
        rows = conn.execute('''
            SELECT ch.*, d.name as driver_name, d.phone as driver_phone, c.name as carrier_name
            FROM checkins ch
            JOIN drivers d ON ch.driver_id = d.id
            LEFT JOIN carriers c ON ch.carrier_id = c.id
            WHERE ch.date = ?
            ORDER BY ch.arrival_time
        ''', (record_date.isoformat() if hasattr(record_date, 'isoformat') else record_date,)).fetchall()
        return [dict(r) for r in rows]


def get_checkins_by_driver(driver_id, days=30):
    cutoff = (datetime.now() - timedelta(days=days)).date().isoformat()
    with get_db() as conn:
        rows = conn.execute('''
            SELECT * FROM checkins 
            WHERE driver_id = ? AND date >= ?
            ORDER BY date DESC
        ''', (driver_id, cutoff)).fetchall()
        return [dict(r) for r in rows]


def get_checkin(checkin_id):
    with get_db() as conn:
        row = conn.execute('''
            SELECT ch.*, d.name as driver_name, c.name as carrier_name,
                   d.license_photo as driver_license_photo,
                   COALESCE(NULLIF(ch.license_photo, ''), d.license_photo, '') as effective_license_photo
            FROM checkins ch
            JOIN drivers d ON ch.driver_id = d.id
            LEFT JOIN carriers c ON ch.carrier_id = c.id
            WHERE ch.id = ?
        ''', (checkin_id,)).fetchone()
        return dict(row) if row else None


def create_checkin(driver_id, carrier_id=None, scheduled_time='', arrival_time='', 
                   needs_return_cargo=0, truck='', dock='', license_photo='', notes='', route=''):
    record_date = get_operational_date()
    
    # 计算迟到分钟数
    late_minutes = calculate_late_minutes(scheduled_time, arrival_time)
    
    with get_db() as conn:
        cursor = conn.execute('''
            INSERT INTO checkins (date, driver_id, carrier_id, scheduled_time, arrival_time,
                needs_return_cargo, truck, dock, license_photo, notes, late_minutes, route)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (record_date.isoformat(), driver_id, carrier_id, scheduled_time, arrival_time,
              needs_return_cargo, truck, dock, license_photo, notes, late_minutes, route))
        
        checkin_id = cursor.lastrowid
        
        # 新 Check-in 先按到达情况计分；回货结果补录后会再次重算。
        score = calculate_checkin_score({
            'late_minutes': late_minutes,
            'needs_return_cargo': needs_return_cargo,
            'return_cargo_status': '',
        })
        conn.execute('UPDATE checkins SET score_given = ? WHERE id = ?', (score, checkin_id))
        
        return checkin_id


def delete_checkin(checkin_id):
    with get_db() as conn:
        cursor = conn.execute('DELETE FROM checkins WHERE id = ?', (checkin_id,))
        return cursor.rowcount > 0


def update_checkin(checkin_id, **kwargs):
    if not kwargs:
        return
    
    # 如果更新了时间，重新计算迟到
    if 'scheduled_time' in kwargs or 'arrival_time' in kwargs:
        checkin = get_checkin(checkin_id)
        scheduled = kwargs.get('scheduled_time', checkin.get('scheduled_time', ''))
        arrival = kwargs.get('arrival_time', checkin.get('arrival_time', ''))
        late = calculate_late_minutes(scheduled, arrival)
        if late is not None:
            kwargs['late_minutes'] = late
    
    kwargs['updated_at'] = datetime.now().isoformat()
    fields = ', '.join(f'{k} = ?' for k in kwargs.keys())
    with get_db() as conn:
        conn.execute(f'UPDATE checkins SET {fields} WHERE id = ?', list(kwargs.values()) + [checkin_id])


def calculate_late_minutes(scheduled_time, arrival_time):
    """计算迟到分钟数（负数表示提前）"""
    if not scheduled_time or not arrival_time:
        return None
    try:
        # 解析 HH:MM 格式
        s_parts = scheduled_time.split(':')
        a_parts = arrival_time.split(':')
        
        s_hour, s_min = int(s_parts[0]), int(s_parts[1])
        a_hour, a_min = int(a_parts[0]), int(a_parts[1])
        
        s_total = s_hour * 60 + s_min
        a_total = a_hour * 60 + a_min
        
        # 处理跨午夜情况（如约定23:00，到达01:00）
        diff = a_total - s_total
        if diff < -720:  # 超过12小时的负数，说明跨天了
            diff += 1440
        elif diff > 720:  # 超过12小时的正数，说明是前一天
            diff -= 1440
            
        return diff
    except:
        return None


def calculate_late_score(late_minutes):
    """根据迟到分钟数计算评分"""
    if late_minutes is None:
        return None
    
    # 提前或准时：100分
    # 迟到1-15分钟：90分
    # 迟到16-30分钟：80分
    # 迟到31-60分钟：60分
    # 迟到超过60分钟：40分
    
    if late_minutes <= 0:
        return 100.0
    elif late_minutes <= 15:
        return 90.0
    elif late_minutes <= 30:
        return 80.0
    elif late_minutes <= 60:
        return 60.0
    else:
        return 40.0


def calculate_checkin_score(checkin):
    """单次 Check-in 评分：自动规则加上调度员可填写的人工扣分。"""
    # 跑错线路属于重大事故，本次任务直接记 0 分。
    if not checkin.get('route_ok', 1):
        return 0.0

    score = 100.0

    # 迟到只区分“迟到”与“未迟到”。45 分来自既定的准时到达 35 分
    # 加上过晚到达 10 分；不再使用 15/30/60 分钟的分档。
    if (checkin.get('late_minutes') or 0) > 0:
        score -= 45

    if checkin.get('needs_return_cargo'):
        return_status = (checkin.get('return_cargo_status') or '').strip()
        if return_status in ('未完成', '未带回'):
            score -= 25
        elif return_status == '部分完成':
            score -= 10

    # 人工扣分是独立记录的可追溯项，只接受正数；最终分数不会低于 0。
    try:
        manual_deduction = max(0.0, float(checkin.get('manual_deduction') or 0))
    except (TypeError, ValueError):
        manual_deduction = 0.0
    score -= manual_deduction

    return max(0.0, score)


def recalculate_all_checkin_scores():
    """用于规则更新后同步历史 Check-in 和司机近 30 天平均分。"""
    with get_db() as conn:
        records = [dict(row) for row in conn.execute('SELECT * FROM checkins').fetchall()]
        driver_ids = set()
        for record in records:
            conn.execute(
                'UPDATE checkins SET score_given = ?, updated_at = ? WHERE id = ?',
                (calculate_checkin_score(record), datetime.now().isoformat(), record['id'])
            )
            driver_ids.add(record['driver_id'])

    for driver_id in driver_ids:
        recalculate_driver_score(driver_id)


def calculate_wait_time(arrival_time, departure_time):
    """计算等待时间（分钟）"""
    if not arrival_time or not departure_time:
        return None
    try:
        a_parts = arrival_time.split(':')
        d_parts = departure_time.split(':')
        
        a_hour, a_min = int(a_parts[0]), int(a_parts[1])
        d_hour, d_min = int(d_parts[0]), int(d_parts[1])
        
        a_total = a_hour * 60 + a_min
        d_total = d_hour * 60 + d_min
        
        diff = d_total - a_total
        if diff < 0:
            diff += 1440  # 跨天
            
        return diff
    except:
        return None


def recalculate_driver_score(driver_id):
    """重算近 30 天自动评分；存在人工评分时继续显示人工评分。"""
    checkins = get_checkins_by_driver(driver_id, days=30)
    scores = [ch['score_given'] for ch in checkins if ch.get('score_given') is not None]
    auto_score = round(sum(scores) / len(scores), 1) if scores else 100.0

    driver = get_driver(driver_id)
    if not driver:
        return auto_score
    displayed_score = (
        float(driver['manual_score'])
        if driver.get('manual_score') is not None
        else auto_score
    )
    update_driver(driver_id, auto_score=auto_score, score=displayed_score)
    return displayed_score


if __name__ == '__main__':
    init_db()
