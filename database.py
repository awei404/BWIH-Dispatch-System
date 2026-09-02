import sqlite3
from datetime import datetime, date, timedelta
from contextlib import contextmanager

import config


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
    print(f"数据库已初始化: {config.DATABASE_PATH}")


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
    record_date = date.today()
    
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
