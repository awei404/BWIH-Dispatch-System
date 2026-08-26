from flask import Flask, render_template, request, redirect, url_for, jsonify
from datetime import datetime, date
from werkzeug.utils import secure_filename
from werkzeug.exceptions import RequestEntityTooLarge
import os
import re
import pandas as pd

import config
import database as db

app = Flask(
    __name__,
    template_folder=os.path.join(config.RESOURCE_DIR, 'templates'),
    static_folder=os.path.join(config.RESOURCE_DIR, 'static')
)
app.secret_key = config.SECRET_KEY
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.jinja_env.auto_reload = True
app.config['UPLOAD_FOLDER'] = os.path.join(config.DATA_DIR, 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB：兼容手机原图的驾照照片

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# 初始化新数据库，并为已有数据库补齐新增字段。
db.init_db()


@app.errorhandler(RequestEntityTooLarge)
def handle_large_upload(error):
    return render_template(
        'error.html',
        title='照片文件过大',
        message='照片超过 50MB，无法上传。请使用较小的照片后重试。',
        back_url=url_for('checkin'),
        back_label='返回 Check-in'
    ), 413


# ========== 首页：今日 Check-in ==========

@app.route('/')
def index():
    selected = request.args.get('date', date.today().isoformat())
    try:
        selected_date = datetime.fromisoformat(selected).date()
    except ValueError:
        selected_date = date.today()
    
    checkins = db.get_checkins_by_date(selected_date)
    drivers = db.get_drivers()
    carriers = db.get_carriers()
    
    return render_template('index.html', 
                           checkins=checkins, 
                           drivers=drivers,
                           carriers=carriers,
                           selected_date=selected_date,
                           today=date.today())


# ========== Check-in ==========

@app.route('/checkin', methods=['GET', 'POST'])
def checkin():
    if request.method == 'POST':
        driver_id = request.form.get('driver_id')
        
        # 如果是新司机
        if request.form.get('new_driver_name'):
            carrier_id = request.form.get('carrier_id') or None
            if carrier_id:
                carrier_id = int(carrier_id)
            driver_id = db.create_driver(
                name=request.form['new_driver_name'],
                phone=request.form.get('new_driver_phone', ''),
                carrier_id=carrier_id
            )
        
        if not driver_id:
            return redirect(url_for('checkin'))
        
        # 处理驾照图片
        license_photo = ''
        if 'license_photo' in request.files:
            file = request.files['license_photo']
            if file and file.filename:
                filename = secure_filename(f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}")
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                license_photo = filename
        
        carrier_id = request.form.get('carrier_id') or None
        if carrier_id:
            carrier_id = int(carrier_id)
        
        checkin_id = db.create_checkin(
            driver_id=int(driver_id),
            carrier_id=carrier_id,
            scheduled_time=request.form.get('scheduled_time', ''),
            arrival_time=request.form.get('arrival_time', ''),
            needs_return_cargo=1 if request.form.get('needs_return_cargo') else 0,
            truck=request.form.get('truck', ''),
            dock=request.form.get('dock', ''),
            license_photo=license_photo,
            notes=request.form.get('notes', ''),
            route=request.form.get('route', '')
        )
        return redirect(url_for('print_checkin', checkin_id=checkin_id))
    
    drivers = db.get_drivers()
    carriers = db.get_carriers()
    
    # 生成时间选项
    time_options = []
    for h in range(15, 24):  # 15:00 - 23:59
        for m in [0, 15, 30, 45]:
            time_options.append(f"{h:02d}:{m:02d}")
    for h in range(0, 8):  # 00:00 - 07:59
        for m in [0, 15, 30, 45]:
            time_options.append(f"{h:02d}:{m:02d}")
    
    return render_template('checkin.html', 
                           drivers=drivers, 
                           carriers=carriers,
                           time_options=time_options)


# ========== 记录详情 ==========

@app.route('/print/<int:checkin_id>')
def print_checkin(checkin_id):
    checkin = db.get_checkin(checkin_id)
    if not checkin:
        return redirect(url_for('index'))
    return render_template('print.html', checkin=checkin)


@app.route('/record/<int:checkin_id>/delete', methods=['POST'])
def delete_record(checkin_id):
    db.delete_checkin(checkin_id)
    return redirect(url_for('index'))


@app.route('/record/<int:checkin_id>', methods=['GET', 'POST'])
def record_detail(checkin_id):
    checkin = db.get_checkin(checkin_id)
    if not checkin:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        updates = {}
        
        for field in ['dock', 'truck', 'dms_task_id', 'route', 'notes', 
                      'scheduled_time', 'arrival_time', 'departure_time', 'return_cargo_status']:
            if field in request.form:
                updates[field] = request.form[field]
        
        updates['needs_return_cargo'] = int(request.form.get('needs_return_cargo', 0))
        updates['route_ok'] = int(request.form.get('route_ok', 1))
        updates['dms_match_confirmed'] = 1 if request.form.get('dms_match_confirmed') else 0
        try:
            updates['manual_deduction'] = min(100.0, max(0.0, float(request.form.get('manual_deduction', 0) or 0)))
        except ValueError:
            updates['manual_deduction'] = 0.0
        category = request.form.get('manual_deduction_category', '')
        updates['manual_deduction_category'] = category if category in ('行为异常', '影响操作', '其他') else ''
        updates['manual_deduction_reason'] = request.form.get('manual_deduction_reason', '').strip()
        
        # 计算等待时间
        arrival = request.form.get('arrival_time') or checkin.get('arrival_time')
        departure = request.form.get('departure_time') or checkin.get('departure_time')
        if arrival and departure:
            wait = db.calculate_wait_time(arrival, departure)
            if wait is not None:
                updates['wait_minutes'] = wait
        
        db.update_checkin(checkin_id, **updates)
        
        # 每次保存都重算：回货结果会立即反映在本次及司机评分中。
        checkin = db.get_checkin(checkin_id)
        if checkin:
            score = db.calculate_checkin_score(checkin)
            db.update_checkin(checkin_id, score_given=score)
            db.recalculate_driver_score(checkin['driver_id'])
        
        return redirect(url_for('record_detail', checkin_id=checkin_id))
    
    return render_template('record_detail.html', checkin=checkin)


# ========== 上传表格 ==========

ROUTE_CODES = ('IAD', 'DCA', 'RIC', 'ORF')


def normalize_match_value(value):
    return re.sub(r'[^A-Z0-9]', '', str(value or '').upper())


def extract_route_code(value):
    value = str(value or '').upper()
    return next((code for code in ROUTE_CODES if code in value), '')


def clean_cell(value):
    if value is None or pd.isna(value):
        return ''
    return str(value).strip()


def extract_route_label(value):
    """Keep the station suffix when present, e.g. ORF01 instead of only ORF."""
    match = re.search(r'\b(IAD|DCA|RIC|ORF)(01)?\b', clean_cell(value).upper())
    return match.group(0) if match else ''


def task_destination(row, destination_col, route_name_col, task_name_col):
    # The DMS destination can be BWI.H for a return trip; the line/task name still
    # carries the actual branch station, which is more useful for dispatch review.
    raw_destination = clean_cell(row.get(destination_col, '')) if destination_col else ''
    if raw_destination and raw_destination.upper() != 'BWI.H':
        return raw_destination
    for column in (route_name_col, task_name_col, destination_col):
        if column:
            label = extract_route_label(row.get(column, ''))
            if label:
                return label
    return raw_destination or '-'


def extract_time(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ''
    if hasattr(value, 'strftime'):
        return value.strftime('%H:%M')
    match = re.search(r'(?<!\d)([01]\d|2[0-3]):([0-5]\d)', str(value))
    return match.group(0) if match else ''


def time_difference_minutes(first, second):
    if not first or not second:
        return None
    first_minutes = int(first[:2]) * 60 + int(first[3:5])
    second_minutes = int(second[:2]) * 60 + int(second[3:5])
    return min(abs(first_minutes - second_minutes), 1440 - abs(first_minutes - second_minutes))


def find_unique_checkin_match(row, checkins, carrier_col, route_col, arrival_col):
    """只在供应商、线路、到达时间中至少两项吻合且无并列候选时自动匹配。"""
    source_carrier = normalize_match_value(row.get(carrier_col, '')) if carrier_col else ''
    source_route = extract_route_code(row.get(route_col, '')) if route_col else ''
    source_arrival = extract_time(row.get(arrival_col, '')) if arrival_col else ''
    candidates = []

    for checkin in checkins:
        signals = []
        if source_carrier and source_carrier == normalize_match_value(checkin.get('carrier_name')):
            signals.append('供应商')
        if source_route and source_route == extract_route_code(checkin.get('route')):
            signals.append('线路')
        if source_arrival and checkin.get('arrival_time'):
            difference = time_difference_minutes(source_arrival, checkin['arrival_time'])
            if difference is not None and difference <= 30:
                signals.append('到达时间')
        if len(signals) >= 2:
            candidates.append((checkin, signals))

    if len(candidates) == 1:
        return candidates[0], ''
    if not candidates:
        return None, '缺少至少两项一致信息（供应商、线路、到达时间）'
    return None, '存在多个相同候选记录，需人工确认'

@app.route('/upload', methods=['GET', 'POST'])
def upload_excel():
    if request.method == 'POST':
        results = {
            'tasks': [],
            # 已经人工确认的记录无需再次出现在弹窗中；待确认和未填 MT 的记录需要处理。
            'pending_checkins': [
                checkin for checkin in db.get_checkins_by_date(date.today())
                if not checkin.get('dms_match_confirmed')
            ],
        }
        
        if 'file' not in request.files:
            return render_template('upload.html', error='请选择文件')
        
        file = request.files['file']
        if not file.filename:
            return render_template('upload.html', error='请选择文件')
        
        try:
            df = pd.read_excel(file)
            
            # 识别关键列
            task_col = None
            arrival_col = None
            departure_col = None
            carrier_col = None
            destination_col = None
            route_name_col = None
            task_name_col = None
            truck_col = None
            trailer_col = None
            
            for col in df.columns:
                col_lower = str(col).lower()
                if '任务编码' in col:
                    task_col = col
                elif '实际抵达始发' in col or '人工抵达始发' in col:
                    arrival_col = col
                elif '实际发车' in col or '人工发车' in col:
                    departure_col = col
                elif '供应商' in col:
                    carrier_col = col
                elif str(col) == '目的地':
                    destination_col = col
                elif '线路名称' in col:
                    route_name_col = col
                elif '任务名称' in col:
                    task_name_col = col
                elif '车牌' in col:
                    truck_col = col
                elif '挂箱' in col:
                    trailer_col = col
            
            if not task_col:
                return render_template('upload.html', error='找不到任务编码列')
            
            # 获取今日 Check-in 记录
            today_checkins = db.get_checkins_by_date(date.today())
            
            for _, row in df.iterrows():
                task_id = str(row.get(task_col, '')).strip()
                if not task_id or task_id == 'nan':
                    continue
                
                departure_time = extract_time(row.get(departure_col, '')) if departure_col else ''
                results['tasks'].append({
                    'task_id': task_id,
                    'destination': task_destination(row, destination_col, route_name_col, task_name_col),
                    'carrier': clean_cell(row.get(carrier_col, '')) if carrier_col else '-',
                    'arrival_time': extract_time(row.get(arrival_col, '')) if arrival_col else '-',
                    'departure_time': departure_time or '-',
                    'truck': clean_cell(row.get(truck_col, '')) if truck_col else '',
                    'trailer': clean_cell(row.get(trailer_col, '')) if trailer_col else '',
                })
            
            return render_template('upload.html', results=results)
            
        except Exception as e:
            return render_template('upload.html', error=f'处理文件时出错: {str(e)}')
    
    return render_template('upload.html')


@app.route('/upload/confirm', methods=['POST'])
def confirm_upload_match():
    """Only a dispatcher can bind a DMS task ID to a Check-in record."""
    try:
        checkin_id = int(request.form.get('checkin_id', ''))
    except ValueError:
        return redirect(url_for('upload_excel'))

    task_id = request.form.get('task_id', '').strip()
    checkin = db.get_checkin(checkin_id)
    if not task_id or not checkin:
        return redirect(url_for('upload_excel'))

    updates = {'dms_task_id': task_id, 'dms_match_confirmed': 1}
    departure_time = request.form.get('departure_time', '').strip()
    if departure_time and departure_time != '-':
        updates['departure_time'] = departure_time
        if checkin.get('arrival_time'):
            wait = db.calculate_wait_time(checkin['arrival_time'], departure_time)
            if wait is not None:
                updates['wait_minutes'] = wait
    db.update_checkin(checkin_id, **updates)
    return redirect(url_for('record_detail', checkin_id=checkin_id))


@app.route('/upload/confirm-bulk', methods=['POST'])
def confirm_upload_matches_bulk():
    """Apply only the dispatcher-selected DMS task mappings from the upload modal."""
    selected_task_ids = set()
    for key, value in request.form.items():
        if not key.startswith('task_') or not value:
            continue
        try:
            checkin_id = int(key.removeprefix('task_'))
            task_id, departure_time = value.split('||', 1)
        except (ValueError, AttributeError):
            continue

        # 同一个 MT 任务只能确认给一位司机。
        if task_id in selected_task_ids:
            continue
        checkin = db.get_checkin(checkin_id)
        if not checkin:
            continue

        updates = {'dms_task_id': task_id, 'dms_match_confirmed': 1}
        if departure_time and departure_time != '-':
            updates['departure_time'] = departure_time
            if checkin.get('arrival_time'):
                wait = db.calculate_wait_time(checkin['arrival_time'], departure_time)
                if wait is not None:
                    updates['wait_minutes'] = wait
        db.update_checkin(checkin_id, **updates)
        selected_task_ids.add(task_id)

    return redirect(url_for('index'))


# ========== 司机管理 ==========

@app.route('/drivers')
def drivers():
    all_drivers = db.get_drivers()
    return render_template('drivers.html', drivers=all_drivers)


@app.route('/driver/new', methods=['GET', 'POST'])
def new_driver():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            return render_template('driver_form.html', error='姓名不能为空', carriers=db.get_carriers())
        
        carrier_id = request.form.get('carrier_id') or None
        if carrier_id:
            carrier_id = int(carrier_id)
        
        # 处理驾照图片
        license_photo = ''
        if 'license_photo' in request.files:
            file = request.files['license_photo']
            if file and file.filename:
                filename = secure_filename(f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}")
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                license_photo = filename
        
        driver_id = db.create_driver(
            name=name,
            phone=request.form.get('phone', ''),
            carrier_id=carrier_id,
            usual_routes=request.form.get('usual_routes', ''),
            license_photo=license_photo
        )
        return redirect(url_for('driver_detail', driver_id=driver_id))
    
    return render_template('driver_form.html', driver=None, carriers=db.get_carriers())


@app.route('/driver/<int:driver_id>', methods=['GET', 'POST'])
def driver_detail(driver_id):
    driver = db.get_driver(driver_id)
    if not driver:
        return redirect(url_for('drivers'))
    
    if request.method == 'POST':
        updates = {}
        for field in ['name', 'phone', 'usual_routes', 'status']:
            if field in request.form:
                updates[field] = request.form[field]
        
        carrier_id = request.form.get('carrier_id') or None
        if carrier_id:
            updates['carrier_id'] = int(carrier_id)
        else:
            updates['carrier_id'] = None
        
        # 处理驾照图片
        if 'license_photo' in request.files:
            file = request.files['license_photo']
            if file and file.filename:
                filename = secure_filename(f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}")
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                updates['license_photo'] = filename
        
        db.update_driver(driver_id, **updates)
        return redirect(url_for('driver_detail', driver_id=driver_id))
    
    checkins = db.get_checkins_by_driver(driver_id, days=30)
    db.recalculate_driver_score(driver_id)
    driver = db.get_driver(driver_id)
    
    return render_template('driver_detail.html', 
                           driver=driver, 
                           checkins=checkins,
                           carriers=db.get_carriers())


# ========== 供应商管理 ==========

@app.route('/carriers')
def carriers():
    all_carriers = db.get_carriers()
    return render_template('carriers.html', carriers=all_carriers)


@app.route('/carrier/new', methods=['GET', 'POST'])
def new_carrier():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            return render_template('carrier_form.html', error='名称不能为空')
        
        carrier_id = db.create_carrier(
            name=name,
            contact=request.form.get('contact', ''),
            phone=request.form.get('phone', ''),
            notes=request.form.get('notes', '')
        )
        return redirect(url_for('carriers'))
    
    return render_template('carrier_form.html', carrier=None)


@app.route('/carrier/<int:carrier_id>', methods=['GET', 'POST'])
def carrier_detail(carrier_id):
    carrier = db.get_carrier(carrier_id)
    if not carrier:
        return redirect(url_for('carriers'))
    
    if request.method == 'POST':
        updates = {}
        for field in ['name', 'contact', 'phone', 'notes']:
            if field in request.form:
                updates[field] = request.form[field]
        db.update_carrier(carrier_id, **updates)
        return redirect(url_for('carrier_detail', carrier_id=carrier_id))
    
    return render_template('carrier_form.html', carrier=carrier)


# ========== 静态文件：上传的图片 ==========

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    from flask import send_from_directory
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


if __name__ == '__main__':
    app.run(host=config.HOST, port=config.PORT, debug=config.DEBUG)
