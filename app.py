from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_file
from werkzeug.security import check_password_hash, generate_password_hash
from functools import wraps
from datetime import datetime, timedelta
import io
import uuid
import random
import string
import qrcode

from db import init_db, query_one, query_all, execute_query

app = Flask(__name__)
app.secret_key = 'qr-attendance-super-secret-key-12345'

# Initialize database tables
init_db()

# ----------------- HOME PORTAL -----------------
@app.route('/')
def index():
    return render_template('index.html')

# ----------------- TEACHER ROUTES -----------------
@app.route('/teacher/login', methods=['GET', 'POST'])
def teacher_login():
    if request.method == 'POST':
        teacher_id = request.form.get('teacher_id')
        password = request.form.get('password')

        teacher = query_one("SELECT * FROM faculty WHERE faculty_id = ? OR email = ?", (teacher_id, teacher_id))
        if teacher and check_password_hash(teacher['password'], password):
            session['teacher_id'] = teacher['faculty_id']
            session['teacher_name'] = teacher['name']
            session['role'] = 'teacher'
            return redirect(url_for('teacher_dashboard'))
        flash('Invalid Faculty ID or password.', 'danger')

    return render_template('teacher/login.html')

@app.route('/teacher/logout')
def teacher_logout():
    session.clear()
    flash('Logged out successfully.', 'success')
    return redirect(url_for('index'))

@app.route('/teacher/dashboard')
def teacher_dashboard():
    if session.get('role') != 'teacher':
        return redirect(url_for('teacher_login'))

    teacher_id = session['teacher_id']
    # Get active and recent sessions
    sessions = query_all(
        """
        SELECT s.*, COUNT(r.record_id) as attendee_count
        FROM attendance_sessions s
        LEFT JOIN attendance_records r ON s.session_id = r.session_id
        WHERE s.faculty_id = ? OR s.teacher_id = ?
        GROUP BY s.session_id
        ORDER BY s.created_at DESC
        """,
        (teacher_id, teacher_id)
    )

    return render_template('teacher/dashboard.html', sessions=sessions)

@app.route('/teacher/create_session', methods=['GET', 'POST'])
def create_session():
    if session.get('role') != 'teacher':
        return redirect(url_for('teacher_login'))

    if request.method == 'POST':
        subject = request.form.get('subject')
        course = request.form.get('course')
        duration_minutes = int(request.form.get('duration', 10))

        token = uuid.uuid4().hex[:16]
        # 6-character clean PIN for manual entry (e.g. 783421)
        code = ''.join(random.choices(string.digits, k=6))

        now = datetime.now()
        expires_at = now + timedelta(minutes=duration_minutes)

        session_id = execute_query(
            """
            INSERT INTO attendance_sessions (session_token, session_code, subject, course, faculty_id, teacher_id, created_at, expires_at, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (token, code, subject, course, session['teacher_id'], session['teacher_id'], now.strftime('%Y-%m-%d %H:%M:%S'), expires_at.strftime('%Y-%m-%d %H:%M:%S'))
        )

        flash('New QR Attendance session created!', 'success')
        return redirect(url_for('teacher_session_view', session_id=session_id))

    return render_template('teacher/create_session.html')

@app.route('/teacher/session/<int:session_id>')
def teacher_session_view(session_id):
    if session.get('role') not in ('teacher', 'admin'):
        return redirect(url_for('teacher_login'))

    if session.get('role') == 'admin':
        s = query_one("SELECT * FROM attendance_sessions WHERE id = ?", (session_id,))
    else:
        s = query_one("SELECT * FROM attendance_sessions WHERE id = ? AND (faculty_id = ? OR teacher_id = ?)", (session_id, session['teacher_id'], session['teacher_id']))

    if not s:
        flash('Session not found.', 'danger')
        if session.get('role') == 'admin':
            return redirect(url_for('admin_sessions'))
        return redirect(url_for('teacher_dashboard'))

    # Mark URL
    mark_url = request.host_url.rstrip('/') + url_for('mark_qr', token=s['session_token'])

    # Current attendees
    attendees = query_all(
        "SELECT student_id, student_name, marked_at FROM attendance_records WHERE session_id = ? ORDER BY marked_at DESC",
        (session_id,)
    )

    return render_template('teacher/session_view.html', session_data=s, mark_url=mark_url, attendees=attendees)

@app.route('/teacher/session/<int:session_id>/end', methods=['POST'])
def end_session(session_id):
    if session.get('role') != 'teacher':
        return redirect(url_for('teacher_login'))

    execute_query("UPDATE attendance_sessions SET is_active = 0 WHERE id = ? AND (faculty_id = ? OR teacher_id = ?)", (session_id, session['teacher_id'], session['teacher_id']))
    flash('Attendance session ended.', 'warning')
    return redirect(url_for('teacher_session_view', session_id=session_id))

@app.route('/qr_image/<token>')
def qr_image(token):
    target_url = request.host_url.rstrip('/') + url_for('mark_qr', token=token)
    img = qrcode.make(target_url)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return send_file(buf, mimetype='image/png')

@app.route('/api/session/<int:session_id>/live')
def live_session_data(session_id):
    s = query_one("SELECT * FROM attendance_sessions WHERE id = ?", (session_id,))
    if not s:
        return jsonify({'error': 'Session not found'}), 404

    # Check expiration
    expires = datetime.strptime(s['expires_at'], '%Y-%m-%d %H:%M:%S')
    now = datetime.now()
    seconds_remaining = max(0, int((expires - now).total_seconds()))
    is_expired = seconds_remaining <= 0

    if is_expired and s['is_active']:
        execute_query("UPDATE attendance_sessions SET is_active = 0 WHERE id = ?", (session_id,))
        s['is_active'] = 0

    attendees = query_all(
        "SELECT student_id, student_name, marked_at FROM attendance_records WHERE session_id = ? ORDER BY marked_at DESC",
        (session_id,)
    )

    return jsonify({
        'is_active': bool(s['is_active']),
        'is_expired': is_expired,
        'seconds_remaining': seconds_remaining,
        'attendee_count': len(attendees),
        'attendees': attendees
    })

# ----------------- STUDENT ROUTES -----------------
@app.route('/student/login', methods=['GET', 'POST'])
def student_login():
    next_url = request.args.get('next', '')
    if request.method == 'POST':
        student_id = request.form.get('student_id')
        password = request.form.get('password')

        student = query_one("SELECT * FROM students WHERE student_id = ?", (student_id,))
        if student and check_password_hash(student['password'], password):
            session['student_id'] = student['student_id']
            session['student_name'] = student['name']
            session['role'] = 'student'
            if next_url:
                return redirect(next_url)
            return redirect(url_for('student_scan'))
        flash('Invalid Student ID or password.', 'danger')

    return render_template('student/login.html', next=next_url)

@app.route('/student/logout')
def student_logout():
    session.clear()
    flash('Logged out successfully.', 'success')
    return redirect(url_for('index'))

@app.route('/student/scan')
def student_scan():
    if session.get('role') != 'student':
        return redirect(url_for('student_login', next=url_for('student_scan')))

    # Student's past records
    history = query_all(
        """
        SELECT r.marked_at, s.subject, s.course, t.name as teacher_name
        FROM attendance_records r
        JOIN attendance_sessions s ON r.session_id = s.session_id
        LEFT JOIN faculty t ON s.faculty_id = t.faculty_id
        WHERE r.student_id = ?
        ORDER BY r.marked_at DESC
        """,
        (session['student_id'],)
    )

    return render_template('student/scan.html', history=history)

@app.route('/student/enter_code', methods=['POST'])
def enter_code():
    if session.get('role') != 'student':
        return redirect(url_for('student_login'))

    code = request.form.get('session_code', '').strip()
    s = query_one("SELECT * FROM attendance_sessions WHERE session_code = ?", (code,))
    if not s:
        flash('Invalid Session Code.', 'danger')
        return redirect(url_for('student_scan'))

    return redirect(url_for('mark_qr', token=s['session_token']))

@app.route('/mark/<token>', methods=['GET', 'POST'])
def mark_qr(token):
    s = query_one("SELECT * FROM attendance_sessions WHERE session_token = ?", (token,))
    if not s:
        return render_template('student/mark_confirm.html', status='error', message='Invalid or non-existent attendance QR code.')

    # Check expiration
    expires = datetime.strptime(s['expires_at'], '%Y-%m-%d %H:%M:%S')
    if datetime.now() > expires or not s['is_active']:
        return render_template('student/mark_confirm.html', status='expired', session_data=s, message='This attendance QR code has expired or was ended by the teacher.')

    # If student is not logged in, prompt quick verification or redirect to login
    if session.get('role') != 'student':
        if request.method == 'POST':
            student_id = request.form.get('student_id')
            password = request.form.get('password')
            student = query_one("SELECT * FROM students WHERE student_id = ?", (student_id,))
            if not student or not check_password_hash(student['password'], password):
                flash('Invalid Student ID or password.', 'danger')
                return render_template('student/mark_confirm.html', status='login_required', session_data=s)
            session['student_id'] = student['student_id']
            session['student_name'] = student['name']
            session['role'] = 'student'
        else:
            return render_template('student/mark_confirm.html', status='login_required', session_data=s)

    student_id = session['student_id']
    student_name = session['student_name']

    # Check if already marked
    existing = query_one("SELECT * FROM attendance_records WHERE session_id = ? AND student_id = ?", (s['id'], student_id))
    if existing:
        return render_template(
            'student/mark_confirm.html',
            status='already_marked',
            session_data=s,
            student_id=student_id,
            student_name=student_name,
            marked_at=existing['marked_at']
        )

    # Record attendance
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    execute_query(
        "INSERT INTO attendance_records (session_id, student_id, student_name, marked_at, status) VALUES (?, ?, ?, ?, 'Present')",
        (s['id'], student_id, student_name, now_str)
    )

    return render_template(
        'student/mark_confirm.html',
        status='success',
        session_data=s,
        student_id=student_id,
        student_name=student_name,
        marked_at=now_str
    )

# ----------------- ADMIN ROUTES -----------------
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('role') != 'admin':
            flash('Admin authentication required.', 'danger')
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if session.get('role') == 'admin':
        return redirect(url_for('admin_dashboard'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        admin = query_one("SELECT * FROM admins WHERE username = ?", (username,))
        if admin and check_password_hash(admin['password'], password):
            session['admin_id'] = admin['id']
            session['admin_username'] = admin['username']
            session['admin_name'] = admin['name']
            session['role'] = 'admin'
            flash(f'Welcome back, {admin["name"]}!', 'success')
            return redirect(url_for('admin_dashboard'))
        flash('Invalid Admin username or password.', 'danger')

    return render_template('admin/login.html')

@app.route('/admin/logout')
def admin_logout():
    session.clear()
    flash('Admin logged out successfully.', 'success')
    return redirect(url_for('index'))

@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    total_teachers = query_one("SELECT COUNT(*) as c FROM faculty")['c']
    total_students = query_one("SELECT COUNT(*) as c FROM students")['c']
    total_sessions = query_one("SELECT COUNT(*) as c FROM attendance_sessions")['c']
    active_sessions = query_one("SELECT COUNT(*) as c FROM attendance_sessions WHERE is_active = 1")['c']
    total_records = query_one("SELECT COUNT(*) as c FROM attendance_records")['c']

    stats = {
        'total_teachers': total_teachers,
        'total_students': total_students,
        'total_sessions': total_sessions,
        'active_sessions': active_sessions,
        'total_records': total_records
    }

    recent_sessions = query_all("""
        SELECT s.*, t.name as teacher_name, COUNT(r.record_id) as attendee_count
        FROM attendance_sessions s
        LEFT JOIN faculty t ON s.faculty_id = t.faculty_id
        LEFT JOIN attendance_records r ON s.session_id = r.session_id
        GROUP BY s.session_id
        ORDER BY s.created_at DESC
        LIMIT 5
    """)

    recent_records = query_all("""
        SELECT r.marked_at, r.status, s.subject, s.course, st.name as student_name, st.student_id, t.name as teacher_name
        FROM attendance_records r
        JOIN attendance_sessions s ON r.session_id = s.session_id
        JOIN students st ON r.student_id = st.student_id
        LEFT JOIN faculty t ON s.faculty_id = t.faculty_id
        ORDER BY r.marked_at DESC
        LIMIT 6
    """)

    return render_template('admin/dashboard.html', stats=stats, recent_sessions=recent_sessions, recent_records=recent_records)

# --- Faculty Management ---
@app.route('/admin/teachers')
@admin_required
def admin_teachers():
    teachers = query_all("""
        SELECT f.*, COUNT(s.session_id) as session_count
        FROM faculty f
        LEFT JOIN attendance_sessions s ON f.faculty_id = s.faculty_id
        GROUP BY f.id, f.faculty_id
        ORDER BY f.name ASC
    """)
    return render_template('admin/teachers.html', teachers=teachers)

@app.route('/admin/teachers/create', methods=['GET', 'POST'])
@admin_required
def admin_teacher_create():
    if request.method == 'POST':
        teacher_id = request.form.get('teacher_id', '').strip()
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()

        if not teacher_id or not name or not email or not password:
            flash('All fields are required.', 'danger')
            return render_template('admin/teacher_form.html', action='create')

        if query_one("SELECT id FROM faculty WHERE faculty_id = ?", (teacher_id,)):
            flash(f'Faculty ID "{teacher_id}" is already registered.', 'danger')
            return render_template('admin/teacher_form.html', action='create')

        if query_one("SELECT id FROM faculty WHERE email = ?", (email,)):
            flash(f'Email "{email}" is already registered to another user.', 'danger')
            return render_template('admin/teacher_form.html', action='create')

        execute_query(
            "INSERT INTO faculty (faculty_id, name, email, password) VALUES (?, ?, ?, ?)",
            (teacher_id, name, email, generate_password_hash(password))
        )

        flash(f'Faculty member "{name}" ({teacher_id}) registered successfully.', 'success')
        return redirect(url_for('admin_teachers'))

    return render_template('admin/teacher_form.html', action='create')

@app.route('/admin/teachers/<int:teacher_id>/edit', methods=['GET', 'POST'])
@admin_required
def admin_teacher_edit(teacher_id):
    teacher = query_one("SELECT * FROM faculty WHERE id = ?", (teacher_id,))
    if not teacher:
        flash('Faculty member not found.', 'danger')
        return redirect(url_for('admin_teachers'))

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()

        if not name or not email:
            flash('Name and Email are required.', 'danger')
            return render_template('admin/teacher_form.html', action='edit', teacher=teacher)

        existing_email = query_one("SELECT id FROM faculty WHERE email = ? AND id != ?", (email, teacher_id))
        if existing_email:
            flash(f'Email "{email}" is already used by another faculty member.', 'danger')
            return render_template('admin/teacher_form.html', action='edit', teacher=teacher)

        if password:
            hashed_pw = generate_password_hash(password)
            execute_query(
                "UPDATE faculty SET name = ?, email = ?, password = ? WHERE id = ?",
                (name, email, hashed_pw, teacher_id)
            )
        else:
            execute_query(
                "UPDATE faculty SET name = ?, email = ? WHERE id = ?",
                (name, email, teacher_id)
            )

        flash(f'Faculty profile for "{name}" updated successfully.', 'success')
        return redirect(url_for('admin_teachers'))

    return render_template('admin/teacher_form.html', action='edit', teacher=teacher)

@app.route('/admin/teachers/<int:teacher_id>/delete', methods=['POST'])
@admin_required
def admin_teacher_delete(teacher_id):
    teacher = query_one("SELECT * FROM faculty WHERE id = ?", (teacher_id,))
    if not teacher:
        flash('Faculty member not found.', 'danger')
        return redirect(url_for('admin_teachers'))

    # Clean up attendance records for this teacher's sessions
    sessions = query_all("SELECT session_id, id FROM attendance_sessions WHERE faculty_id = ?", (teacher['faculty_id'],))
    for s in sessions:
        sid = s.get('session_id') or s.get('id')
        execute_query("DELETE FROM attendance_records WHERE session_id = ?", (sid,))
    execute_query("DELETE FROM attendance_sessions WHERE faculty_id = ?", (teacher['faculty_id'],))
    execute_query("DELETE FROM faculty WHERE id = ?", (teacher_id,))

    flash(f'Faculty member "{teacher["name"]}" and all their sessions have been deleted.', 'success')
    return redirect(url_for('admin_teachers'))

# --- Student Management ---
@app.route('/admin/students')
@admin_required
def admin_students():
    students = query_all("""
        SELECT st.*, COUNT(r.id) as attendance_count
        FROM students st
        LEFT JOIN attendance_records r ON st.student_id = r.student_id
        GROUP BY st.id
        ORDER BY st.student_id ASC
    """)
    return render_template('admin/students.html', students=students)

@app.route('/admin/students/create', methods=['GET', 'POST'])
@admin_required
def admin_student_create():
    if request.method == 'POST':
        student_id = request.form.get('student_id', '').strip()
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        course = request.form.get('course', '').strip()
        password = request.form.get('password', '').strip()

        if not student_id or not name or not email or not course or not password:
            flash('All fields are required.', 'danger')
            return render_template('admin/student_form.html', action='create')

        if query_one("SELECT id FROM students WHERE student_id = ?", (student_id,)):
            flash(f'Student ID "{student_id}" is already registered.', 'danger')
            return render_template('admin/student_form.html', action='create')

        if query_one("SELECT id FROM students WHERE email = ?", (email,)):
            flash(f'Email "{email}" is already registered to another user.', 'danger')
            return render_template('admin/student_form.html', action='create')

        execute_query(
            "INSERT INTO students (student_id, name, email, password, course) VALUES (?, ?, ?, ?, ?)",
            (student_id, name, email, generate_password_hash(password), course)
        )
        flash(f'Student "{name}" ({student_id}) enrolled successfully.', 'success')
        return redirect(url_for('admin_students'))

    return render_template('admin/student_form.html', action='create')

@app.route('/admin/students/<int:student_id>/edit', methods=['GET', 'POST'])
@admin_required
def admin_student_edit(student_id):
    student = query_one("SELECT * FROM students WHERE id = ?", (student_id,))
    if not student:
        flash('Student not found.', 'danger')
        return redirect(url_for('admin_students'))

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        course = request.form.get('course', '').strip()
        password = request.form.get('password', '').strip()

        if not name or not email or not course:
            flash('Name, Email, and Course are required.', 'danger')
            return render_template('admin/student_form.html', action='edit', student=student)

        existing_email = query_one("SELECT id FROM students WHERE email = ? AND id != ?", (email, student_id))
        if existing_email:
            flash(f'Email "{email}" is already used by another student.', 'danger')
            return render_template('admin/student_form.html', action='edit', student=student)

        if password:
            execute_query(
                "UPDATE students SET name = ?, email = ?, course = ?, password = ? WHERE id = ?",
                (name, email, course, generate_password_hash(password), student_id)
            )
        else:
            execute_query(
                "UPDATE students SET name = ?, email = ?, course = ? WHERE id = ?",
                (name, email, course, student_id)
            )

        flash(f'Student profile for "{name}" updated successfully.', 'success')
        return redirect(url_for('admin_students'))

    return render_template('admin/student_form.html', action='edit', student=student)

@app.route('/admin/students/<int:student_id>/delete', methods=['POST'])
@admin_required
def admin_student_delete(student_id):
    student = query_one("SELECT * FROM students WHERE id = ?", (student_id,))
    if not student:
        flash('Student not found.', 'danger')
        return redirect(url_for('admin_students'))

    execute_query("DELETE FROM attendance_records WHERE student_id = ?", (student['student_id'],))
    execute_query("DELETE FROM students WHERE id = ?", (student_id,))

    flash(f'Student "{student["name"]}" ({student["student_id"]}) and their attendance history have been deleted.', 'success')
    return redirect(url_for('admin_students'))

@app.route('/admin/students/<int:student_id>/history')
@admin_required
def admin_student_history(student_id):
    student = query_one("SELECT * FROM students WHERE id = ?", (student_id,))
    if not student:
        flash('Student not found.', 'danger')
        return redirect(url_for('admin_students'))

    records = query_all("""
        SELECT r.marked_at, r.status, s.subject, s.course, t.name as teacher_name
        FROM attendance_records r
        JOIN attendance_sessions s ON r.session_id = s.session_id
        LEFT JOIN faculty t ON s.faculty_id = t.faculty_id
        WHERE r.student_id = ?
        ORDER BY r.marked_at DESC
    """, (student['student_id'],))

    return render_template('admin/student_history.html', student=student, records=records)

# --- Sessions Oversight ---
@app.route('/admin/sessions')
@admin_required
def admin_sessions():
    sessions = query_all("""
        SELECT s.*, t.name as teacher_name, COUNT(r.record_id) as attendee_count
        FROM attendance_sessions s
        LEFT JOIN faculty t ON s.faculty_id = t.faculty_id
        LEFT JOIN attendance_records r ON s.session_id = r.session_id
        GROUP BY s.session_id
        ORDER BY s.created_at DESC
    """)
    return render_template('admin/sessions.html', sessions=sessions)

@app.route('/admin/sessions/<int:session_id>/end', methods=['POST'])
@admin_required
def admin_session_end(session_id):
    execute_query("UPDATE attendance_sessions SET is_active = 0 WHERE id = ?", (session_id,))
    flash('Attendance session ended successfully.', 'warning')
    return redirect(url_for('admin_sessions'))

@app.route('/admin/sessions/<int:session_id>/delete', methods=['POST'])
@admin_required
def admin_session_delete(session_id):
    execute_query("DELETE FROM attendance_records WHERE session_id = ?", (session_id,))
    execute_query("DELETE FROM attendance_sessions WHERE id = ?", (session_id,))
    flash('Attendance session and associated records deleted permanently.', 'success')
    return redirect(url_for('admin_sessions'))

if __name__ == '__main__':
    # Run on port 5001 so it can run alongside the port 5000 attendance system without conflict!
    print("Starting QR Attendance System on http://127.0.0.1:5001 ...")
    app.run(debug=True, port=5001)
