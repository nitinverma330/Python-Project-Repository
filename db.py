import os
import mysql.connector
from mysql.connector import pooling, Error
from datetime import datetime, date
from werkzeug.security import generate_password_hash
from dotenv import load_dotenv

# Load environment configuration
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_PORT = int(os.getenv('DB_PORT', 3306))
DB_USER = os.getenv('DB_USER', 'root')
DB_PASSWORD = os.getenv('DB_PASSWORD', '')
DB_NAME = os.getenv('DB_NAME', 'student_attendance')

_pool = None

def get_connection_pool():
    global _pool
    if _pool is None:
        try:
            _pool = pooling.MySQLConnectionPool(
                pool_name="qr_attendance_pool",
                pool_size=10,
                pool_reset_session=True,
                host=DB_HOST,
                port=DB_PORT,
                user=DB_USER,
                password=DB_PASSWORD,
                database=DB_NAME
            )
        except Exception as e:
            print("MySQL Pool Initialization Warning:", e)
            _pool = None
    return _pool

def configure_connection(conn):
    try:
        cur = conn.cursor()
        cur.execute("SET SESSION sql_mode = 'NO_ENGINE_SUBSTITUTION'")
        cur.close()
    except Exception:
        pass
    return conn

def get_db():
    conn = None
    pool = get_connection_pool()
    if pool:
        try:
            conn = pool.get_connection()
            conn.ping(reconnect=True, attempts=3, delay=1)
        except Exception as e:
            print("Pool connection error:", e)
            conn = None

    if not conn:
        conn = mysql.connector.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME
        )

    return configure_connection(conn)

def init_db():
    """Ensure database, tables, and seed records exist in MySQL."""
    # First ensure the database exists
    try:
        init_conn = mysql.connector.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD
        )
        cur = init_conn.cursor()
        cur.execute(f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        init_conn.commit()
        cur.close()
        init_conn.close()
    except Exception as e:
        print("Database creation notice:", e)

    conn = get_db()
    cursor = conn.cursor()

    # 1. Faculty table (single unified table for instructors)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS faculty (
        id INT AUTO_INCREMENT UNIQUE,
        faculty_id VARCHAR(50) PRIMARY KEY,
        name VARCHAR(100) NOT NULL,
        email VARCHAR(150) UNIQUE NOT NULL,
        password VARCHAR(255) NOT NULL,
        phone VARCHAR(20) NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Drop legacy/redundant teachers table if present
    try:
        cursor.execute("DROP TABLE IF EXISTS teachers")
        conn.commit()
    except Exception:
        pass

    # 2. Students table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS students (
        id INT AUTO_INCREMENT PRIMARY KEY,
        student_id VARCHAR(50) UNIQUE NOT NULL,
        name VARCHAR(100) NOT NULL,
        email VARCHAR(150) UNIQUE NOT NULL,
        password VARCHAR(255) NOT NULL,
        phone VARCHAR(20) NULL,
        course VARCHAR(100) NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 3. Admins table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS admins (
        id INT AUTO_INCREMENT PRIMARY KEY,
        username VARCHAR(50) UNIQUE NOT NULL,
        name VARCHAR(100) NOT NULL,
        email VARCHAR(150) UNIQUE NOT NULL,
        password VARCHAR(255) NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 4. Attendance Sessions created by Faculty
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS attendance_sessions (
        session_id INT AUTO_INCREMENT PRIMARY KEY,
        id INT NULL,
        session_token VARCHAR(64) UNIQUE NOT NULL,
        session_code VARCHAR(10) NOT NULL,
        subject VARCHAR(100) NOT NULL,
        course VARCHAR(100) NOT NULL,
        faculty_id VARCHAR(50) NOT NULL,
        teacher_id VARCHAR(50) NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        expires_at DATETIME NOT NULL,
        is_active TINYINT(1) DEFAULT 1
    );
    """)

    # 5. Attendance Records marked by Students
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS attendance_records (
        record_id INT AUTO_INCREMENT PRIMARY KEY,
        id INT NULL,
        session_id INT NOT NULL,
        student_id VARCHAR(50) NOT NULL,
        student_name VARCHAR(100) NULL,
        marked_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        status VARCHAR(20) DEFAULT 'Present',
        method VARCHAR(20) DEFAULT 'QR',
        UNIQUE KEY uq_session_student (session_id, student_id)
    );
    """)

    conn.commit()

    # Ensure id columns and compatibility columns exist on preexisting tables
    for alter_sql in [
        "ALTER TABLE faculty ADD COLUMN id INT AUTO_INCREMENT UNIQUE FIRST",
        "ALTER TABLE attendance_sessions ADD COLUMN id INT NULL AFTER session_id",
        "ALTER TABLE attendance_sessions ADD COLUMN teacher_id VARCHAR(50) NULL AFTER faculty_id",
        "ALTER TABLE attendance_records ADD COLUMN id INT NULL AFTER record_id",
        "ALTER TABLE attendance_records ADD COLUMN student_name VARCHAR(100) NULL AFTER student_id",
        "ALTER TABLE students ADD COLUMN id INT AUTO_INCREMENT UNIQUE FIRST"
    ]:
        try:
            cursor.execute(alter_sql)
            conn.commit()
        except Exception:
            pass

    # Align session IDs and student names
    try:
        cursor.execute("UPDATE attendance_sessions SET id = session_id WHERE id IS NULL")
        cursor.execute("UPDATE attendance_sessions SET teacher_id = faculty_id WHERE teacher_id IS NULL AND faculty_id IS NOT NULL")
        cursor.execute("UPDATE attendance_sessions SET faculty_id = teacher_id WHERE faculty_id IS NULL AND teacher_id IS NOT NULL")
        cursor.execute("UPDATE attendance_records SET id = record_id WHERE id IS NULL")
        cursor.execute("""
            UPDATE attendance_records r
            JOIN students s ON r.student_id = s.student_id
            SET r.student_name = s.name
            WHERE r.student_name IS NULL
        """)
        conn.commit()
    except Exception as e:
        print("Data alignment notice:", e)

    # Pre-seed default Admin profile only (No demo teachers or students)
    cursor.execute("SELECT id FROM admins WHERE username = 'admin'")
    if not cursor.fetchone():
        cursor.execute(
            "INSERT INTO admins (username, name, email, password) VALUES (%s, %s, %s, %s)",
            ('admin', 'System Administrator', 'admin@university.edu', generate_password_hash('admin123'))
        )

    conn.commit()
    cursor.close()
    conn.close()

def normalize_row(row):
    """Normalize row dictionary for template and JSON consumption."""
    if not row:
        return row
    d = dict(row)
    for k, v in list(d.items()):
        if isinstance(v, (datetime, date)):
            d[k] = v.strftime('%Y-%m-%d %H:%M:%S')
    if 'session_id' in d and 'id' not in d:
        d['id'] = d['session_id']
    if 'record_id' in d and 'id' not in d:
        d['id'] = d['record_id']
    if 'faculty_id' in d and 'teacher_id' not in d:
        d['teacher_id'] = d['faculty_id']
    if 'teacher_id' in d and 'faculty_id' not in d:
        d['faculty_id'] = d['teacher_id']
    return d

def query_one(query, params=()):
    """Fetch a single record as a dictionary from MySQL."""
    query = query.replace('?', '%s')
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(query, params)
        row = cursor.fetchone()
        return normalize_row(row)
    finally:
        cursor.close()
        conn.close()

def query_all(query, params=()):
    """Fetch multiple records as a list of dictionaries from MySQL."""
    query = query.replace('?', '%s')
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(query, params)
        rows = cursor.fetchall()
        return [normalize_row(r) for r in rows]
    finally:
        cursor.close()
        conn.close()

def execute_query(query, params=()):
    """Execute an INSERT/UPDATE/DELETE query on MySQL."""
    query = query.replace('?', '%s')
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(query, params)
        conn.commit()
        last_id = cursor.lastrowid
        row_count = cursor.rowcount

        # Automatically align id and faculty/teacher IDs on newly inserted sessions
        if 'attendance_sessions' in query.lower() and 'insert' in query.lower() and last_id:
            try:
                cursor.execute(
                    "UPDATE attendance_sessions SET id = session_id, faculty_id = COALESCE(faculty_id, teacher_id), teacher_id = COALESCE(teacher_id, faculty_id) WHERE session_id = %s",
                    (last_id,)
                )
                conn.commit()
            except Exception:
                pass

        return last_id or row_count
    except Exception as e:
        print("MySQL Execute Error:", e)
        return None
    finally:
        cursor.close()
        conn.close()
