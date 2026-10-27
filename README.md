# Smart QR Attendance System

A modern, standalone QR Code Attendance System where teachers dynamically create time-limited attendance QR sessions, and students scan using their device camera or enter a session PIN to instantly register their attendance in real time.

---

## Features

### Admin Features
* **Admin Dashboard**: Real-time KPI statistics (Total Faculty, Total Students, Active QR Sessions, Total Present Records).
* **Faculty Management**: Create new teacher accounts, edit faculty details and passwords, remove faculty members.
* **Student Roster Management**: Enroll new students, update profiles and course allocations, view attendance history per student, and remove student records.
* **Session Oversight**: View all classroom QR sessions campus-wide, monitor live sessions, forcefully close sessions, or delete archived sessions.

### Teacher / Faculty Features
* **Teacher Login**: Secure authentication for educators.
* **Create QR Session**: Specify subject name, course/batch, and validity timer (5, 10, 15, 30, or 60 minutes).
* **Live Projector Display**:
  * Large, high-resolution dynamic QR Code.
  * Real-time countdown timer.
  * 6-digit fallback PIN code for students in back rows or without working cameras.
  * Live Attendee Counter and Roster table that auto-refreshes every 2.5 seconds without reloading the page.
  * Immediate "End Session" button to manually lock attendance when class starts.
* **History & Logs**: Review past sessions and see complete student rosters with exact timestamps.

### Student Features
* **Camera QR Scanner**: In-browser camera viewfinder using HTML5-QRCode. Works smoothly on both smartphones and laptops.
* **Direct QR Link**: Scanning the QR code with any smartphone camera app immediately directs students to the attendance confirmation page.
* **Fallback 6-Digit PIN Entry**: Manually input the session PIN if camera permissions are restricted.
* **Duplicate Prevention**: Prevents students from scanning twice for the same lecture.
* **Anti-Cheating Expiry**: Automatically denies attendance submissions once the session timer elapses.
* **Instant Confirmation**: Shows verification checkmark with class name, course, and timestamp.

---

## Default Admin Credentials

### Admin Account
* **Username**: `admin`
* **Password**: `admin123`

> Once logged in as Admin, you can enroll faculty members and students, manage courses, and monitor live attendance sessions campus-wide.

---

## How to Run

1. Clone the repository and navigate into the folder:
   ```bash
   git clone https://github.com/nitinverma330/Python-Project-Repository.git
   cd Python-Project-Repository
   ```

2. Create virtual environment and install dependencies:
   ```bash
   python -m venv venv
   .\venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. Configure Database Connection in `.env` (copy from `.env.example`):
   ```ini
   DB_HOST=localhost
   DB_PORT=3306
   DB_USER=root
   DB_PASSWORD=your_mysql_password
   DB_NAME=student_attendance
   SECRET_KEY=your_secret_key
   ```

4. Run the application:
   ```bash
   python app.py
   ```

3. Open your browser:
   ```text
   http://127.0.0.1:5001
   ```
   *(Runs on port 5001 so it does not conflict with port 5000)*.

---

## Tech Stack
* **Backend**: Python, Flask
* **Database**: MySQL 8.0 (via `mysql-connector-python` connection pool with auto-reconnection and environment variables)
* **QR Engine**: `qrcode`, `Pillow`
* **Camera Scanning**: `html5-qrcode` JavaScript library
* **Styling**: 100% Pure Vanilla CSS (Responsive, Clean, Modern, No external framework dependencies)
