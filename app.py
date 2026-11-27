"""
ReliefOps — Flask + SQLite Backend
===================================
Run:
    pip install flask flask-cors
    python app.py

Opens at: http://localhost:5000
"""

from flask import Flask, request, jsonify, send_from_directory, Response
import sqlite3, hashlib, os, datetime

app = Flask(__name__, static_folder='.')

# ── CORS — no flask-cors package needed ──
CORS_HEADERS = {
    'Access-Control-Allow-Origin':  '*',
    'Access-Control-Allow-Headers': 'Content-Type, X-Role, X-User-Id, X-Email, X-User-Name',
    'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
}

@app.after_request
def add_cors(response):
    for k, v in CORS_HEADERS.items():
        response.headers[k] = v
    return response

@app.before_request
def handle_preflight():
    if request.method == 'OPTIONS':
        return Response('', status=200, headers=CORS_HEADERS)
DB   = 'reliefops.db'


# ════════════════════════════════════════════════════
# DATABASE HELPERS
# ════════════════════════════════════════════════════

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    conn = get_db()
    with open('schema.sql', 'r', encoding='utf-8') as f:
        conn.executescript(f.read())
    conn.commit()
    conn.close()
    print("✅ Database initialized.")

def rows(cursor_result):
    return [dict(r) for r in cursor_result]

def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def today():
    return datetime.date.today().isoformat()

def now():
    return datetime.datetime.now().isoformat(sep=' ', timespec='seconds')

# Request helpers
def get_role():
    return request.headers.get('X-Role', '').lower()

def get_uid():
    uid = request.headers.get('X-User-Id', '')
    return int(uid) if uid.isdigit() else None

def admin_only():
    if get_role() != 'admin':
        return jsonify(error='Admin access required'), 403
    return None

def require_roles(*roles):
    if get_role() not in roles:
        return jsonify(error='Access denied'), 403
    return None


# ════════════════════════════════════════════════════
# SERVE STATIC HTML FILES
# ════════════════════════════════════════════════════

@app.before_request
def log_request():
    print(f"REQUEST: {request.method} {request.path}")
    if request.path.startswith('/api/donations') and request.method == 'PUT':
        print(f"  Headers: {dict(request.headers)}")

@app.route('/')
def index():
    return send_from_directory('.', 'dashboard.html')

@app.route('/<path:filename>')
def static_files(filename):
    return send_from_directory('.', filename)


# ════════════════════════════════════════════════════
# AUTH
# ════════════════════════════════════════════════════

@app.route('/api/auth/register', methods=['POST'])
def register():
    d = request.json or {}
    name  = (d.get('full_name') or d.get('name') or '').strip()
    email = (d.get('email') or '').strip().lower()
    pw    = d.get('password') or ''
    role  = d.get('role') or 'donor'
    phone = d.get('phone') or ''
    org   = d.get('organization') or ''

    if not name or not email or not pw:
        return jsonify(error='Name, email and password are required'), 400
    if role not in ('admin', 'donor', 'volunteer'):
        return jsonify(error='Invalid role'), 400

    conn = get_db()
    try:
        existing = conn.execute('SELECT user_id FROM users WHERE email=?', (email,)).fetchone()
        if existing:
            return jsonify(error='Email already registered'), 409
        conn.execute(
            'INSERT INTO users (full_name,email,password_hash,role,phone,organization) VALUES (?,?,?,?,?,?)',
            (name, email, hash_pw(pw), role, phone, org)
        )
        conn.commit()
        uid = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
        return jsonify(
            message='Registered successfully',
            id=uid, name=name, email=email, role=role
        ), 201
    finally:
        conn.close()


@app.route('/api/auth/login', methods=['POST'])
def login():
    d     = request.json or {}
    email = (d.get('email') or '').strip().lower()
    pw    = d.get('password') or ''

    if not email or not pw:
        return jsonify(error='Email and password required'), 400

    conn = get_db()
    try:
        user = conn.execute(
            'SELECT * FROM users WHERE email=? AND password_hash=?',
            (email, hash_pw(pw))
        ).fetchone()
        if not user:
            return jsonify(error='Invalid email or password'), 401

        # Get volunteer's camp if applicable
        camp_id = None
        if user['role'] == 'volunteer':
            vc = conn.execute(
                'SELECT camp_id FROM volunteer_camp WHERE user_id=?', (user['user_id'],)
            ).fetchone()
            if vc:
                camp_id = vc['camp_id']

        return jsonify(
            id=user['user_id'],
            name=user['full_name'],
            email=user['email'],
            role=user['role'],
            camp_id=camp_id
        )
    finally:
        conn.close()


# ════════════════════════════════════════════════════
# ADMIN STATS & PENDING REQUESTS
# ════════════════════════════════════════════════════

@app.route('/api/stats')
def stats():
    conn = get_db()
    try:
        return jsonify(
            active_disasters  = conn.execute("SELECT COUNT(*) FROM disaster WHERE status='Active'").fetchone()[0],
            total_disasters   = conn.execute("SELECT COUNT(*) FROM disaster").fetchone()[0],
            active_camps      = conn.execute("SELECT COUNT(*) FROM relief_camp WHERE status IN ('Active','Full')").fetchone()[0],
            total_camps       = conn.execute("SELECT COUNT(*) FROM relief_camp").fetchone()[0],
            total_victims     = conn.execute("SELECT COALESCE(SUM(current_occupancy),0) FROM relief_camp").fetchone()[0],
            resource_types    = conn.execute("SELECT COUNT(*) FROM resource").fetchone()[0],
            low_stock_count   = conn.execute("SELECT COUNT(*) FROM resource WHERE quantity_available <= min_threshold").fetchone()[0],
            pending_shortages = conn.execute("SELECT COUNT(*) FROM resource_shortage WHERE status='Pending'").fetchone()[0],
            pending_donations = conn.execute("SELECT COUNT(*) FROM donation WHERE status='Pending'").fetchone()[0],
        )
    finally:
        conn.close()


@app.route('/api/admin/pending')
def admin_pending():
    """Admin activity panel — pending shortages + pending donations."""
    err = admin_only()
    if err: return err
    conn = get_db()
    try:
        shortages = rows(conn.execute('''
            SELECT rs.*, r.resource_name, r.unit, rc.camp_name,
                   u.full_name as reported_by_name
            FROM resource_shortage rs
            JOIN resource r       ON rs.resource_id = r.resource_id
            JOIN relief_camp rc   ON rs.camp_id     = rc.camp_id
            LEFT JOIN users u     ON rs.reported_by = u.user_id
            WHERE rs.status = 'Pending'
            ORDER BY rs.reported_at DESC
        ''').fetchall())

        donations = rows(conn.execute('''
            SELECT d.*, u.full_name as donor_name, r.resource_name, r.unit
            FROM donation d
            JOIN users u    ON d.donor_id    = u.user_id
            JOIN resource r ON d.resource_id = r.resource_id
            WHERE d.status = 'Pending'
            ORDER BY d.donation_date DESC
        ''').fetchall())

        return jsonify(shortages=shortages, donations=donations)
    finally:
        conn.close()


# ════════════════════════════════════════════════════
# DISASTERS
# ════════════════════════════════════════════════════

@app.route('/api/disasters', methods=['GET'])
def get_disasters():
    conn  = get_db()
    try:
        limit = request.args.get('limit')
        sql   = 'SELECT * FROM disaster ORDER BY start_date DESC'
        if limit:
            sql += f' LIMIT {int(limit)}'
        return jsonify(disasters=rows(conn.execute(sql).fetchall()))
    finally:
        conn.close()


@app.route('/api/disasters/<int:did>', methods=['GET'])
def get_disaster(did):
    conn = get_db()
    try:
        d = conn.execute('SELECT * FROM disaster WHERE disaster_id=?', (did,)).fetchone()
        if not d: return jsonify(error='Not found'), 404
        return jsonify(disaster=dict(d))
    finally:
        conn.close()


@app.route('/api/disasters', methods=['POST'])
def add_disaster():
    err = admin_only()
    if err: return err
    d = request.json or {}
    if not all(d.get(k) for k in ['disaster_name','disaster_type','location','severity_level','start_date','status']):
        return jsonify(error='Missing required fields'), 400
    conn = get_db()
    try:
        conn.execute(
            'INSERT INTO disaster (disaster_name,disaster_type,location,severity_level,start_date,end_date,status,lat,lng) VALUES (?,?,?,?,?,?,?,?,?)',
            (d['disaster_name'], d['disaster_type'], d['location'],
             d['severity_level'], d['start_date'], d.get('end_date'),
             d['status'], d.get('lat'), d.get('lng'))
        )
        conn.commit()
        new_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
        return jsonify(message='Disaster added', disaster_id=new_id), 201
    finally:
        conn.close()


@app.route('/api/disasters/<int:did>', methods=['PUT'])
def update_disaster(did):
    err = admin_only()
    if err: return err
    d = request.json or {}
    conn = get_db()
    try:
        conn.execute('''
            UPDATE disaster SET
                disaster_name=?, disaster_type=?, location=?,
                severity_level=?, start_date=?, end_date=?,
                status=?, lat=?, lng=?
            WHERE disaster_id=?
        ''', (d.get('disaster_name'), d.get('disaster_type'), d.get('location'),
              d.get('severity_level'), d.get('start_date'), d.get('end_date'),
              d.get('status'), d.get('lat'), d.get('lng'), did))
        conn.commit()
        return jsonify(message='Updated')
    finally:
        conn.close()


@app.route('/api/disasters/<int:did>', methods=['DELETE'])
def delete_disaster(did):
    err = admin_only()
    if err: return err
    conn = get_db()
    try:
        conn.execute('DELETE FROM disaster WHERE disaster_id=?', (did,))
        conn.commit()
        return jsonify(message='Deleted')
    finally:
        conn.close()


# ════════════════════════════════════════════════════
# CAMPS
# ════════════════════════════════════════════════════

@app.route('/api/camps', methods=['GET'])
def get_camps():
    conn = get_db()
    try:
        limit = request.args.get('limit')
        sql = '''
            SELECT rc.*, d.disaster_name, d.severity_level as disaster_severity
            FROM relief_camp rc
            LEFT JOIN disaster d ON rc.disaster_id = d.disaster_id
            ORDER BY rc.camp_id DESC
        '''
        if limit:
            sql += f' LIMIT {int(limit)}'
        return jsonify(camps=rows(conn.execute(sql).fetchall()))
    finally:
        conn.close()


@app.route('/api/camps/<int:cid>', methods=['GET'])
def get_camp(cid):
    conn = get_db()
    try:
        c = conn.execute('''
            SELECT rc.*, d.disaster_name, d.severity_level as disaster_severity
            FROM relief_camp rc
            LEFT JOIN disaster d ON rc.disaster_id = d.disaster_id
            WHERE rc.camp_id=?
        ''', (cid,)).fetchone()
        if not c: return jsonify(error='Camp not found'), 404
        return jsonify(camp=dict(c))
    finally:
        conn.close()


@app.route('/api/camps', methods=['POST'])
def add_camp():
    err = admin_only()
    if err: return err
    d = request.json or {}
    if not all(d.get(k) for k in ['camp_name','location','total_capacity','disaster_id']):
        return jsonify(error='Missing required fields'), 400
    conn = get_db()
    try:
        conn.execute(
            'INSERT INTO relief_camp (camp_name,location,total_capacity,current_occupancy,status,opened_date,disaster_id) VALUES (?,?,?,?,?,?,?)',
            (d['camp_name'], d['location'], int(d['total_capacity']),
             int(d.get('current_occupancy', 0)),
             d.get('status', 'Active'),
             d.get('opened_date'),
             int(d['disaster_id']))
        )
        conn.commit()
        new_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
        return jsonify(message='Camp added', camp_id=new_id), 201
    finally:
        conn.close()


@app.route('/api/camps/<int:cid>', methods=['PUT'])
def update_camp(cid):
    err = admin_only()
    if err: return err
    d = request.json or {}
    conn = get_db()
    try:
        conn.execute('''
            UPDATE relief_camp SET
                camp_name=?, location=?, total_capacity=?,
                current_occupancy=?, status=?, opened_date=?, disaster_id=?
            WHERE camp_id=?
        ''', (d.get('camp_name'), d.get('location'), d.get('total_capacity'),
              d.get('current_occupancy', 0), d.get('status'),
              d.get('opened_date'), d.get('disaster_id'), cid))
        conn.commit()
        return jsonify(message='Updated')
    finally:
        conn.close()


@app.route('/api/camps/<int:cid>', methods=['DELETE'])
def delete_camp(cid):
    err = admin_only()
    if err: return err
    conn = get_db()
    try:
        conn.execute('DELETE FROM relief_camp WHERE camp_id=?', (cid,))
        conn.commit()
        return jsonify(message='Deleted')
    finally:
        conn.close()


@app.route('/api/camps/<int:cid>/victims', methods=['PUT'])
def update_victims(cid):
    err = require_roles('admin', 'volunteer')
    if err: return err
    count = int((request.json or {}).get('count', 0))
    conn  = get_db()
    try:
        camp = conn.execute('SELECT total_capacity FROM relief_camp WHERE camp_id=?', (cid,)).fetchone()
        if not camp: return jsonify(error='Camp not found'), 404
        status = 'Full' if count >= camp['total_capacity'] else 'Active'
        conn.execute('UPDATE relief_camp SET current_occupancy=?, status=? WHERE camp_id=?',
                     (count, status, cid))
        conn.commit()
        return jsonify(message='Updated', status=status, current_occupancy=count)
    finally:
        conn.close()


# ════════════════════════════════════════════════════
# VOLUNTEER PROFILE & CAMP
# ════════════════════════════════════════════════════

@app.route('/api/volunteer/profile')
def volunteer_profile():
    err = require_roles('volunteer', 'admin')
    if err: return err
    uid  = get_uid()
    conn = get_db()
    try:
        user = conn.execute('SELECT user_id,full_name,email,phone,role,joined_date FROM users WHERE user_id=?', (uid,)).fetchone()
        if not user: return jsonify(error='User not found'), 404

        # Get assigned camp
        vc = conn.execute('''
            SELECT vc.camp_id, rc.camp_name, rc.location, rc.total_capacity,
                   rc.current_occupancy, rc.status, rc.opened_date,
                   d.disaster_name, vc.assigned_on
            FROM volunteer_camp vc
            JOIN relief_camp rc ON vc.camp_id = rc.camp_id
            LEFT JOIN disaster d ON rc.disaster_id = d.disaster_id
            WHERE vc.user_id=?
        ''', (uid,)).fetchone()

        return jsonify(
            user=dict(user),
            camp=dict(vc) if vc else None
        )
    finally:
        conn.close()


@app.route('/api/admin/assign-volunteer', methods=['POST'])
def assign_volunteer():
    """Admin assigns a volunteer to a camp."""
    err = admin_only()
    if err: return err
    d = request.json or {}
    conn = get_db()
    try:
        # Remove existing assignment if any
        conn.execute('DELETE FROM volunteer_camp WHERE user_id=?', (d['user_id'],))
        conn.execute(
            'INSERT INTO volunteer_camp (user_id, camp_id) VALUES (?,?)',
            (d['user_id'], d['camp_id'])
        )
        conn.commit()
        return jsonify(message='Volunteer assigned to camp')
    finally:
        conn.close()


@app.route('/api/volunteers')
def list_volunteers():
    err = admin_only()
    if err: return err
    conn = get_db()
    try:
        vols = rows(conn.execute('''
            SELECT u.user_id, u.full_name, u.email, u.phone, u.organization, u.joined_date,
                   vc.camp_id, rc.camp_name
            FROM users u
            LEFT JOIN volunteer_camp vc ON u.user_id = vc.user_id
            LEFT JOIN relief_camp rc    ON vc.camp_id = rc.camp_id
            WHERE u.role = 'volunteer'
            ORDER BY u.full_name
        ''').fetchall())
        return jsonify(volunteers=vols)
    finally:
        conn.close()

@app.route('/api/donors')
def list_donors():
    err = admin_only()
    if err: return err
    conn = get_db()
    try:
        donors = rows(conn.execute('''
            SELECT u.user_id, u.full_name, u.email, u.phone, u.organization, u.joined_date,
                   (SELECT COUNT(*) FROM donation WHERE donor_id = u.user_id) as total_donations,
                   (SELECT COALESCE(SUM(quantity),0) FROM donation WHERE donor_id = u.user_id AND status = 'Completed') as total_qty
            FROM users u
            WHERE u.role = 'donor'
            ORDER BY u.full_name
        ''').fetchall())
        return jsonify(donors=donors)
    finally:
        conn.close()

@app.route('/api/donors/<int:uid>')
def get_donor(uid):
    err = admin_only()
    if err: return err
    conn = get_db()
    try:
        donor = row(conn.execute('SELECT user_id, full_name, email, phone, organization, joined_date FROM users WHERE user_id = ? AND role = "donor"', (uid,)).fetchone())
        if not donor: return jsonify(error='Donor not found'), 404
        
        donations = rows(conn.execute('''
            SELECT d.donation_id, d.resource_id, r.resource_name, r.unit, d.quantity, d.donation_date, d.status, d.remarks
            FROM donation d
            JOIN resource r ON d.resource_id = r.resource_id
            WHERE d.donor_id = ?
            ORDER BY d.donation_date DESC
        ''', (uid,)).fetchall())
        
        return jsonify(donor=donor, donations=donations)
    finally:
        conn.close()


# ════════════════════════════════════════════════════
# RESOURCE SHORTAGES
# ════════════════════════════════════════════════════

@app.route('/api/camps/<int:cid>/shortages', methods=['GET'])
def get_camp_shortages(cid):
    conn = get_db()
    try:
        result = rows(conn.execute('''
            SELECT rs.*, r.resource_name, r.unit,
                   u.full_name as reported_by_name
            FROM resource_shortage rs
            JOIN resource r    ON rs.resource_id = r.resource_id
            LEFT JOIN users u  ON rs.reported_by  = u.user_id
            WHERE rs.camp_id=?
            ORDER BY rs.reported_at DESC
        ''', (cid,)).fetchall())
        return jsonify(shortages=result)
    finally:
        conn.close()


@app.route('/api/camps/<int:cid>/shortages', methods=['POST'])
def report_shortage(cid):
    err = require_roles('volunteer', 'admin')
    if err: return err
    d   = request.json or {}
    uid = get_uid()
    if not d.get('resource_id') or not d.get('quantity_needed'):
        return jsonify(error='resource_id and quantity_needed required'), 400
    conn = get_db()
    try:
        conn.execute(
            'INSERT INTO resource_shortage (camp_id,resource_id,reported_by,quantity_needed,remarks,status) VALUES (?,?,?,?,?,?)',
            (cid, d['resource_id'], uid, int(d['quantity_needed']), d.get('remarks',''), 'Pending')
        )
        conn.commit()
        return jsonify(message='Shortage reported'), 201
    finally:
        conn.close()


@app.route('/api/shortages', methods=['GET'])
def get_all_shortages():
    """Admin: view all shortages, optionally filter by status."""
    conn   = get_db()
    status = request.args.get('status')
    try:
        sql = '''
            SELECT rs.*, r.resource_name, r.unit, rc.camp_name,
                   u.full_name as reported_by_name
            FROM resource_shortage rs
            JOIN resource r    ON rs.resource_id = r.resource_id
            JOIN relief_camp rc ON rs.camp_id    = rc.camp_id
            LEFT JOIN users u   ON rs.reported_by = u.user_id
        '''
        params = []
        if status:
            sql += ' WHERE rs.status=?'
            params.append(status)
        sql += ' ORDER BY rs.reported_at DESC'
        return jsonify(shortages=rows(conn.execute(sql, params).fetchall()))
    finally:
        conn.close()


@app.route('/api/shortages/<int:sid>/received', methods=['PUT'])
def mark_shortage_received(sid):
    """Volunteer marks shortage as received after resource delivered."""
    err = require_roles('volunteer', 'admin')
    if err: return err
    conn = get_db()
    try:
        # Also mark linked allocation as Received
        shortage = conn.execute('SELECT * FROM resource_shortage WHERE shortage_id=?', (sid,)).fetchone()
        if not shortage: return jsonify(error='Shortage not found'), 404
        conn.execute("UPDATE resource_shortage SET status='Received' WHERE shortage_id=?", (sid,))
        conn.execute("UPDATE resource_allocation SET status='Received' WHERE shortage_id=?", (sid,))
        conn.commit()
        return jsonify(message='Marked as received')
    finally:
        conn.close()


# ════════════════════════════════════════════════════
# RESOURCES
# ════════════════════════════════════════════════════

@app.route('/api/resources', methods=['GET'])
def get_resources():
    conn = get_db()
    try:
        return jsonify(resources=rows(conn.execute(
            'SELECT * FROM resource ORDER BY resource_name'
        ).fetchall()))
    finally:
        conn.close()


@app.route('/api/resources', methods=['POST'])
def add_resource():
    err = admin_only()
    if err: return err
    d = request.json or {}
    if not all(d.get(k) for k in ['resource_name','category','unit']):
        return jsonify(error='Missing required fields'), 400
    conn = get_db()
    try:
        conn.execute(
            'INSERT INTO resource (resource_name,category,unit,quantity_available,min_threshold) VALUES (?,?,?,?,?)',
            (d['resource_name'], d['category'], d['unit'],
             int(d.get('quantity_available', 0)),
             int(d.get('min_threshold', 0)))
        )
        conn.commit()
        new_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
        return jsonify(message='Resource added', resource_id=new_id), 201
    finally:
        conn.close()


@app.route('/api/resources/<int:rid>', methods=['PUT'])
def update_resource(rid):
    err = admin_only()
    if err: return err
    d = request.json or {}
    conn = get_db()
    try:
        conn.execute('''
            UPDATE resource SET
                resource_name=?, category=?, unit=?,
                quantity_available=?, min_threshold=?
            WHERE resource_id=?
        ''', (d.get('resource_name'), d.get('category'), d.get('unit'),
              d.get('quantity_available'), d.get('min_threshold'), rid))
        conn.commit()
        return jsonify(message='Updated')
    finally:
        conn.close()


@app.route('/api/resources/<int:rid>', methods=['DELETE'])
def delete_resource(rid):
    err = admin_only()
    if err: return err
    conn = get_db()
    try:
        conn.execute('DELETE FROM resource WHERE resource_id=?', (rid,))
        conn.commit()
        return jsonify(message='Deleted')
    finally:
        conn.close()


# ════════════════════════════════════════════════════
# RESOURCE ALLOCATIONS
# Admin allocates resource → qty decreases → shortage updated
# ════════════════════════════════════════════════════

@app.route('/api/allocations', methods=['GET'])
def get_allocations():
    conn     = get_db()
    camp_id  = request.args.get('camp_id')
    try:
        sql = '''
            SELECT ra.*, r.resource_name, r.unit, rc.camp_name, rc.location,
                   u.full_name as allocated_by_name
            FROM resource_allocation ra
            JOIN resource r     ON ra.resource_id = r.resource_id
            JOIN relief_camp rc ON ra.camp_id     = rc.camp_id
            LEFT JOIN users u   ON ra.allocated_by = u.user_id
        '''
        params = []
        if camp_id:
            sql += ' WHERE ra.camp_id=?'
            params.append(int(camp_id))
        sql += ' ORDER BY ra.allocation_date DESC'
        return jsonify(allocations=rows(conn.execute(sql, params).fetchall()))
    finally:
        conn.close()


@app.route('/api/allocations', methods=['POST'])
def allocate_resource():
    """
    Admin allocates resource to a camp.
    - Checks available stock first.
    - Reduces resource quantity.
    - Updates matching shortage status to Allocated.
    """
    err = admin_only()
    if err: return err
    d   = request.json or {}
    uid = get_uid()

    required = ['resource_id','camp_id','quantity_dispatched','allocation_date']
    if not all(d.get(k) for k in required):
        return jsonify(error='Missing required fields'), 400

    qty = int(d['quantity_dispatched'])
    conn = get_db()
    try:
        # Check available stock
        res = conn.execute(
            'SELECT quantity_available FROM resource WHERE resource_id=?', (d['resource_id'],)
        ).fetchone()
        if not res:
            return jsonify(error='Resource not found'), 404
        if qty > res['quantity_available']:
            return jsonify(error=f"Not enough stock. Available: {res['quantity_available']}"), 400

        # Reduce resource quantity
        conn.execute(
            'UPDATE resource SET quantity_available = quantity_available - ? WHERE resource_id=?',
            (qty, d['resource_id'])
        )

        # Create allocation record
        conn.execute(
            'INSERT INTO resource_allocation (resource_id,camp_id,shortage_id,quantity_dispatched,allocation_date,allocated_by,status) VALUES (?,?,?,?,?,?,?)',
            (d['resource_id'], d['camp_id'], d.get('shortage_id'),
             qty, d['allocation_date'], uid, 'Dispatched')
        )

        alloc_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]

        # Update shortage status to Allocated
        # NOTE: use explicit None check — shortage_id=0 is falsy in Python but valid
        shortage_id = d.get('shortage_id')
        if shortage_id is not None and str(shortage_id).strip() not in ('', 'null', 'None', '0'):
            sid_int = int(shortage_id)
            conn.execute(
                "UPDATE resource_shortage SET status='Allocated' WHERE shortage_id=?",
                (sid_int,)
            )
        else:
            # Fallback: match latest Pending shortage for same camp + resource
            conn.execute('''
                UPDATE resource_shortage SET status='Allocated'
                WHERE shortage_id = (
                    SELECT shortage_id FROM resource_shortage
                    WHERE camp_id=? AND resource_id=? AND status='Pending'
                    ORDER BY reported_at DESC LIMIT 1
                )
            ''', (d['camp_id'], d['resource_id']))

        conn.commit()
        return jsonify(message='Resource allocated successfully', allocation_id=alloc_id), 201
    finally:
        conn.close()


# ════════════════════════════════════════════════════
# DONATIONS
# Donor donates → Pending → Admin accepts/rejects
# On accept: resource qty increases automatically
# ════════════════════════════════════════════════════

@app.route('/api/donations', methods=['GET'])
def get_all_donations():
    """Admin: see all donations."""
    err = admin_only()
    if err: return err
    conn = get_db()
    try:
        status = request.args.get('status')
        sql = '''
            SELECT d.*, u.full_name as donor_name, u.email as donor_email,
                   r.resource_name, r.unit,
                   a.full_name as accepted_by_name
            FROM donation d
            JOIN users u    ON d.donor_id    = u.user_id
            JOIN resource r ON d.resource_id = r.resource_id
            LEFT JOIN users a ON d.accepted_by = a.user_id
        '''
        params = []
        if status:
            sql += ' WHERE d.status=?'
            params.append(status)
        sql += ' ORDER BY d.donation_date DESC'
        return jsonify(donations=rows(conn.execute(sql, params).fetchall()))
    finally:
        conn.close()


@app.route('/api/donations/mine', methods=['GET'])
def my_donations():
    """Donor: see their own donation history."""
    err = require_roles('donor', 'admin')
    if err: return err
    uid  = get_uid()
    conn = get_db()
    try:
        result = rows(conn.execute('''
            SELECT d.*, r.resource_name, r.unit,
                   a.full_name as accepted_by_name
            FROM donation d
            JOIN resource r  ON d.resource_id = r.resource_id
            LEFT JOIN users a ON d.accepted_by = a.user_id
            WHERE d.donor_id=?
            ORDER BY d.donation_date DESC
        ''', (uid,)).fetchall())
        return jsonify(donations=result)
    finally:
        conn.close()


@app.route('/api/donations', methods=['POST'])
def submit_donation():
    """Donor submits a donation request (status = Pending)."""
    err = require_roles('donor', 'admin')
    if err: return err
    uid = get_uid()
    d   = request.json or {}

    if not d.get('resource_id') or not d.get('quantity'):
        return jsonify(error='resource_id and quantity required'), 400

    conn = get_db()
    try:
        conn.execute(
            'INSERT INTO donation (donor_id,resource_id,quantity,donation_date,status,remarks) VALUES (?,?,?,?,?,?)',
            (uid, d['resource_id'], int(d['quantity']),
             today(), 'Pending', d.get('remarks',''))
        )
        conn.commit()
        return jsonify(message='Donation submitted. Waiting for admin acceptance.'), 201
    finally:
        conn.close()


@app.route('/api/donations/<int:did>/accept', methods=['PUT'])
def accept_donation(did):
    """
    Admin accepts a donation.
    Resource quantity increases automatically.
    """
    # Force debug info to see headers
    print(f"DEBUG: Headers: {dict(request.headers)}")
    role = get_role()
    uid = get_uid()
    print(f"DEBUG: accept_donation did={did}, role={role}, uid={uid}")
    
    err = admin_only()
    if err: 
        print(f"DEBUG: admin_only check failed: {err.get_json() if hasattr(err, 'get_json') else err}")
        return err
    
    conn = get_db()
    try:
        dn = conn.execute('SELECT * FROM donation WHERE donation_id=?', (did,)).fetchone()
        if not dn:
            print(f"DEBUG: Donation {did} not found")
            return jsonify(error='Donation not found'), 404
        if dn['status'] != 'Pending':
            print(f"DEBUG: Donation {did} already processed: {dn['status']}")
            return jsonify(error='Donation already processed'), 400

        # Increase resource quantity
        print(f"DEBUG: Updating resource {dn['resource_id']} by +{dn['quantity']}")
        conn.execute(
            'UPDATE resource SET quantity_available = quantity_available + ? WHERE resource_id=?',
            (dn['quantity'], dn['resource_id'])
        )

        # Mark donation accepted
        print(f"DEBUG: Updating donation {did} status to Completed")
        conn.execute(
            "UPDATE donation SET status='Completed', accepted_by=?, accepted_at=? WHERE donation_id=?",
            (uid, now(), did)
        )
        conn.commit()
        print(f"DEBUG: Donation {did} accepted successfully")
        return jsonify(message='Donation accepted. Resource inventory updated.')
    except Exception as e:
        print(f"DEBUG: Error in accept_donation: {e}")
        return jsonify(error=str(e)), 500
    finally:
        conn.close()


@app.route('/api/donations/<int:did>/reject', methods=['PUT'])
def reject_donation(did):
    """Admin rejects a donation (resource quantity NOT changed)."""
    print(f"DEBUG: reject_donation did={did}, role={get_role()}, uid={get_uid()}")
    err = admin_only()
    if err: 
        print(f"DEBUG: admin_only check failed: {err.get_json() if hasattr(err, 'get_json') else err}")
        return err
    uid  = get_uid()
    conn = get_db()
    try:
        dn = conn.execute('SELECT * FROM donation WHERE donation_id=?', (did,)).fetchone()
        if not dn: return jsonify(error='Donation not found'), 404
        conn.execute(
            "UPDATE donation SET status='Rejected', accepted_by=?, accepted_at=? WHERE donation_id=?",
            (uid, now(), did)
        )
        conn.commit()
        return jsonify(message='Donation rejected.')
    except Exception as e:
        print(f"DEBUG: Error in reject_donation: {e}")
        return jsonify(error=str(e)), 500
    finally:
        conn.close()


@app.route('/api/donations/<int:did>', methods=['DELETE'])
def delete_donation(did):
    """Admin deletes a donation record (reverses resource if Accepted)."""
    err = admin_only()
    if err: return err
    conn = get_db()
    try:
        dn = conn.execute('SELECT * FROM donation WHERE donation_id=?', (did,)).fetchone()
        if not dn: return jsonify(error='Not found'), 404
        # Reverse quantity only if already accepted
        if dn['status'] == 'Completed':
            conn.execute(
                'UPDATE resource SET quantity_available = MAX(0, quantity_available-?) WHERE resource_id=?',
                (dn['quantity'], dn['resource_id'])
            )
        conn.execute('DELETE FROM donation WHERE donation_id=?', (did,))
        conn.commit()
        return jsonify(message='Donation deleted')
    finally:
        conn.close()


# ════════════════════════════════════════════════════
# PROFILE (shared — all roles)
# ════════════════════════════════════════════════════

@app.route('/api/profile', methods=['GET'])
def get_profile():
    uid   = get_uid()
    role  = get_role()
    email = request.headers.get('X-Email', '')

    conn = get_db()
    try:
        # Try by ID first, then by email header
        user = None
        if uid:
            user = conn.execute(
                'SELECT user_id,full_name,email,phone,organization,role,joined_date FROM users WHERE user_id=?', (uid,)
            ).fetchone()
        if not user and email:
            user = conn.execute(
                'SELECT user_id,full_name,email,phone,organization,role,joined_date FROM users WHERE email=?', (email,)
            ).fetchone()
        if not user:
            return jsonify(error='User not found. Please log in again.'), 404

        result = {'user': dict(user)}

        if user['role'] == 'donor':
            result['total_donated']   = conn.execute(
                "SELECT COALESCE(SUM(quantity),0) FROM donation WHERE donor_id=? AND status='Completed'", (user['user_id'],)
            ).fetchone()[0]
            result['total_donations'] = conn.execute(
                "SELECT COUNT(*) FROM donation WHERE donor_id=?", (user['user_id'],)
            ).fetchone()[0]
            result['pending'] = conn.execute(
                "SELECT COUNT(*) FROM donation WHERE donor_id=? AND status='Pending'", (user['user_id'],)
            ).fetchone()[0]

        return jsonify(**result)
    finally:
        conn.close()


@app.route('/api/profile', methods=['PUT'])
def update_profile():
    uid   = get_uid()
    email = request.headers.get('X-Email', '')
    d     = request.json or {}
    conn  = get_db()
    try:
        # Find user by ID or email
        user = None
        if uid:
            user = conn.execute('SELECT user_id FROM users WHERE user_id=?', (uid,)).fetchone()
        if not user and email:
            user = conn.execute('SELECT user_id FROM users WHERE email=?', (email,)).fetchone()
        if not user:
            return jsonify(error='User not found'), 404

        real_uid = user['user_id']
        if d.get('password'):
            conn.execute(
                'UPDATE users SET full_name=?, phone=?, organization=?, password_hash=? WHERE user_id=?',
                (d.get('full_name'), d.get('phone',''), d.get('organization',''), hash_pw(d['password']), real_uid)
            )
        else:
            conn.execute(
                'UPDATE users SET full_name=?, phone=?, organization=? WHERE user_id=?',
                (d.get('full_name'), d.get('phone',''), d.get('organization',''), real_uid)
            )
        conn.commit()
        return jsonify(message='Profile updated')
    finally:
        conn.close()




# ════════════════════════════════════════════════════
# RUN
# ════════════════════════════════════════════════════

if __name__ == '__main__':
    # Always run schema to create any missing tables (safe — uses CREATE TABLE IF NOT EXISTS)
    init_db()
    print("\n🛡️  ReliefOps server starting...")
    print("   URL: http://localhost:5001\n")
    app.run(debug=True, port=5001)