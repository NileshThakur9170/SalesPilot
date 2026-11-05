import sqlite3
import secrets
import csv
import io
import json
import uuid
from datetime import datetime, date, timedelta
from functools import wraps
from pathlib import Path

from flask import Flask, jsonify, request, redirect, url_for, session, flash, render_template, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
DB_FILE = BASE_DIR / "salespilot_users.db"
SECRET_FILE = BASE_DIR / "salespilot_secret.key"
EXCEL_FILE = BASE_DIR / "sales_data.xlsx"
UPLOAD_DIR = BASE_DIR / "user_uploads"
STAGING_DIR = UPLOAD_DIR / ".staging"
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
REQUIRED_COLUMNS = ["Order ID", "Order Date", "Region", "City", "Segment", "Ship Mode",
                    "Category", "Sub-Category", "Product Name", "Sales Rep", "Customer Name",
                    "Quantity", "Unit Price", "Discount", "Sales", "Cost"]

if SECRET_FILE.exists():
    SECRET_KEY = SECRET_FILE.read_text(encoding="utf-8").strip()
else:
    SECRET_KEY = secrets.token_hex(32)
    SECRET_FILE.write_text(SECRET_KEY, encoding="utf-8")

app = Flask(__name__, static_folder=str(BASE_DIR), static_url_path="", template_folder=str(BASE_DIR))
app.secret_key = SECRET_KEY
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
)

def get_db():
    connection = sqlite3.connect(DB_FILE)
    connection.row_factory = sqlite3.Row
    return connection

def init_db():
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS datasets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                original_filename TEXT NOT NULL,
                row_count INTEGER NOT NULL DEFAULT 0,
                columns_json TEXT NOT NULL,
                mapping_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)
        existing_dataset_columns = {row["name"] for row in db.execute("PRAGMA table_info(datasets)").fetchall()}
        if "mapping_json" not in existing_dataset_columns:
            db.execute("ALTER TABLE datasets ADD COLUMN mapping_json TEXT NOT NULL DEFAULT '{}' ")
        db.execute("""
            CREATE TABLE IF NOT EXISTS dataset_rows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dataset_id INTEGER NOT NULL,
                row_json TEXT NOT NULL,
                FOREIGN KEY(dataset_id) REFERENCES datasets(id) ON DELETE CASCADE
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_datasets_user ON datasets(user_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_rows_dataset ON dataset_rows(dataset_id)")
    UPLOAD_DIR.mkdir(exist_ok=True)
    STAGING_DIR.mkdir(parents=True, exist_ok=True)

def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to continue.", "info")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped_view

def read_excel_data():
    from openpyxl import load_workbook
    if not EXCEL_FILE.exists():
        raise FileNotFoundError("sales_data.xlsx was not found")
    workbook = load_workbook(EXCEL_FILE, read_only=True, data_only=True)
    try:
        sheet = workbook.active
        rows = list(sheet.iter_rows(values_only=True))
    finally:
        workbook.close()
    if not rows:
        return []
    headers = [str(header).strip() if header is not None else "" for header in rows[0]]
    data = []
    for row in rows[1:]:
        if not any(value is not None for value in row):
            continue
        record = {}
        for header, value in zip(headers, row):
            if not header:
                continue
            if isinstance(value, (datetime, date)):
                value = value.isoformat()
            record[header] = value
        data.append(record)
    return data

def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    with get_db() as db:
        return db.execute(
            "SELECT id, name, email, created_at, password_hash FROM users WHERE id = ?",
            (user_id,)
        ).fetchone()

@app.route("/")
def landing():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return send_from_directory(BASE_DIR, "landing.html")

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    form_data = {"name": "", "email": ""}
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        form_data = {"name": name, "email": email}
        if not name or not email or not password or not confirm_password:
            flash("Please complete all fields.", "error")
        elif len(name) > 80:
            flash("Name must be 80 characters or fewer.", "error")
        elif len(email) > 254 or "@" not in email or "." not in email.rsplit("@", 1)[-1]:
            flash("Enter a valid email address.", "error")
        elif len(password) < 8:
            flash("Password must be at least 8 characters.", "error")
        elif password != confirm_password:
            flash("Passwords do not match.", "error")
        else:
            try:
                with get_db() as db:
                    cursor = db.execute(
                        """INSERT INTO users (name, email, password_hash, created_at)
                           VALUES (?, ?, ?, ?)""",
                        (name, email, generate_password_hash(password),
                         datetime.now().isoformat(timespec="seconds"))
                    )
                    user_id = cursor.lastrowid
                session.clear()
                session["user_id"] = user_id
                session["user_name"] = name
                session.permanent = True
                return redirect(url_for("dashboard"))
            except sqlite3.IntegrityError:
                flash("An account with this email already exists. Log in or use another email.", "error")
    return render_template("signup.html", form_data=form_data)

@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    form_data = {"email": ""}
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        form_data = {"email": email}
        with get_db() as db:
            user = db.execute(
                "SELECT id, name, password_hash FROM users WHERE email = ?", (email,)
            ).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            session.permanent = True
            return redirect(url_for("dashboard"))
        flash("Incorrect email or password. Check your details and try again.", "error")
    return render_template("login.html", form_data=form_data)

@app.route("/logout", methods=["POST"])
@login_required
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


def get_user_datasets(user_id):
    with get_db() as db:
        rows = db.execute(
            "SELECT id, name, original_filename, row_count, created_at, updated_at "
            "FROM datasets WHERE user_id=? ORDER BY updated_at DESC, id DESC", (user_id,)
        ).fetchall()
    return [dict(row) for row in rows]

def get_active_dataset_id(user_id):
    datasets = get_user_datasets(user_id)
    chosen = session.get("dataset_id")
    if chosen and any(int(d["id"]) == int(chosen) for d in datasets):
        return int(chosen)
    if datasets:
        chosen = int(datasets[0]["id"])
        session["dataset_id"] = chosen
        return chosen
    session.pop("dataset_id", None)
    return None


COLUMN_ALIASES = {
    "Sales": ["sales", "revenue", "sales amount", "revenue amount", "total amount", "net sales", "amount", "total sales", "turnover"],
    "Order Date": ["order date", "date", "transaction date", "invoice date", "sale date", "created date", "booking date"],
    "Order ID": ["order id", "order no", "order number", "invoice no", "invoice number", "transaction id", "bill no", "receipt no"],
    "Product Name": ["product name", "product", "item", "item name", "product title", "sku name", "service"],
    "Quantity": ["quantity", "qty", "units", "units sold", "count", "volume"],
    "Cost": ["cost", "total cost", "purchase cost", "cogs", "cost amount"],
    "Profit": ["profit", "net profit", "gross profit", "earnings"],
    "Customer Name": ["customer name", "customer", "client", "buyer", "account name"],
    "Region": ["region", "territory", "area", "zone", "state"],
    "City": ["city", "town", "location"],
    "Category": ["category", "product category", "type"],
    "Sub-Category": ["sub-category", "subcategory", "sub category", "subtype"],
    "Segment": ["segment", "customer segment"],
    "Sales Rep": ["sales rep", "salesperson", "sales person", "agent", "employee", "owner"],
    "Discount": ["discount", "discount amount", "discount percent", "discount percentage"],
    "Unit Price": ["unit price", "price", "selling price", "rate", "price per unit"],
    "Ship Mode": ["ship mode", "shipping method", "delivery method", "shipping type"],
}

def suggest_column_mapping(headers):
    normalized = {str(h).strip().lower().replace("_", " ").replace("-", " "): h for h in headers}
    result = {}
    for target, aliases in COLUMN_ALIASES.items():
        found = None
        for alias in aliases:
            key = alias.lower().replace("_", " ").replace("-", " ")
            if key in normalized:
                found = normalized[key]
                break
        if found is None:
            # Conservative substring match for common labels; avoid mapping ambiguous short names.
            for key, original in normalized.items():
                if len(key) >= 5 and any(alias in key or key in alias for alias in aliases if len(alias) >= 5):
                    found = original
                    break
        if found is not None:
            result[target] = found
    return result

def parse_sales_upload(file_bytes, filename):
    suffix = Path(filename).suffix.lower()
    if suffix not in {".xlsx", ".csv"}:
        raise ValueError("Only .xlsx and .csv files are supported.")
    if not file_bytes:
        raise ValueError("The uploaded file is empty.")
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise ValueError("File size exceeds the 20 MB limit.")
    if suffix == ".csv":
        try:
            content = file_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            content = file_bytes.decode("cp1252")
        reader = csv.DictReader(io.StringIO(content))
        if not reader.fieldnames:
            raise ValueError("CSV must contain a header row.")
        headers = [str(h or "").strip() for h in reader.fieldnames]
        records = []
        for row in reader:
            record = {str(k or "").strip(): v for k, v in row.items() if k}
            if any(str(v or "").strip() for v in record.values()):
                records.append(record)
    else:
        from openpyxl import load_workbook
        try:
            wb = load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
            ws = wb.active
            iterator = ws.iter_rows(values_only=True)
            first = next(iterator, None)
            if not first:
                wb.close()
                raise ValueError("Excel file has no header row.")
            headers = [str(v).strip() if v is not None else "" for v in first]
            records = []
            for values in iterator:
                if not any(v is not None and str(v).strip() for v in values):
                    continue
                item = {}
                for key, value in zip(headers, values):
                    if not key:
                        continue
                    if isinstance(value, (datetime, date)):
                        value = value.isoformat()
                    item[key] = value
                records.append(item)
            wb.close()
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError(f"Could not read Excel file: {exc}")
    if len(set(headers)) != len(headers):
        raise ValueError("The file contains duplicate column names.")
    if not headers or not any(headers):
        raise ValueError("Could not detect column headers. Make sure the first row contains column names.")
    if not records:
        raise ValueError("No data rows found below the header.")
    return headers, records

@app.route("/dashboard")
@login_required
def dashboard():
    if not get_active_dataset_id(session["user_id"]):
        return redirect(url_for("upload_page"))
    return send_from_directory(BASE_DIR, "index.html")

@app.route("/upload")
@login_required
def upload_page():
    return send_from_directory(BASE_DIR, "upload.html")

@app.route("/api/datasets")
@login_required
def api_datasets():
    items = get_user_datasets(session["user_id"])
    return jsonify({"success": True, "datasets": items,
                    "current_dataset_id": get_active_dataset_id(session["user_id"])})

@app.route("/api/datasets/select", methods=["POST"])
@login_required
def select_dataset():
    dataset_id = request.form.get("dataset_id", type=int)
    with get_db() as db:
        row = db.execute("SELECT id FROM datasets WHERE id=? AND user_id=?",
                         (dataset_id, session["user_id"])).fetchone()
    if not row:
        return jsonify({"success": False, "error": "Dataset not found."}), 404
    session["dataset_id"] = dataset_id
    return jsonify({"success": True})

@app.route("/api/datasets/preview", methods=["POST"])
@login_required
def preview_dataset():
    uploaded = request.files.get("file")
    if not uploaded or not uploaded.filename:
        return jsonify({"success": False, "error": "Choose an Excel or CSV file."}), 400
    filename = secure_filename(uploaded.filename)
    try:
        raw = uploaded.read()
        headers, rows = parse_sales_upload(raw, filename)
        token = uuid.uuid4().hex
        stage_dir = STAGING_DIR / str(session["user_id"])
        stage_dir.mkdir(parents=True, exist_ok=True)
        (stage_dir / token).write_bytes(raw)
        session["upload_token"] = token
        session["upload_filename"] = filename
        return jsonify({"success": True, "token": token, "filename": filename,
                        "row_count": len(rows), "columns": headers, "suggested_mapping": suggest_column_mapping(headers),
                        "preview": rows[:5]})
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400

@app.route("/api/datasets/import", methods=["POST"])
@login_required
def import_dataset():
    payload = request.get_json(silent=True) or {}
    mode = payload.get("mode", "new")
    token = session.get("upload_token")
    filename = session.get("upload_filename", "uploaded-file")
    if mode not in {"new", "append", "replace"} or not token:
        return jsonify({"success": False, "error": "Upload and preview a file first."}), 400
    staged = STAGING_DIR / str(session["user_id"]) / token
    if not staged.is_file():
        return jsonify({"success": False, "error": "Upload preview expired. Please upload again."}), 400
    try:
        headers, rows = parse_sales_upload(staged.read_bytes(), filename)
        user_id = session["user_id"]
        now = datetime.now().isoformat(timespec="seconds")
        incoming_mapping = payload.get("mapping") or suggest_column_mapping(headers)
        if not isinstance(incoming_mapping, dict) or any(
            standard not in COLUMN_ALIASES or source not in headers
            for standard, source in incoming_mapping.items()
        ):
            return jsonify({"success": False, "error": "Invalid column mapping. Please review the mapping and try again."}), 400
        canonical_mapping = {standard: standard for standard in incoming_mapping}
        with get_db() as db:
            if mode == "new":
                name = str(payload.get("name") or Path(filename).stem).strip()[:80] or "New dataset"
                cur = db.execute(
                    "INSERT INTO datasets(user_id,name,original_filename,row_count,columns_json,mapping_json,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (user_id, name, filename, 0, json.dumps(headers),
                     json.dumps(canonical_mapping), now, now))
                dataset_id = cur.lastrowid
            else:
                dataset_id = int(payload.get("dataset_id") or 0)
                target = db.execute("SELECT id,columns_json,mapping_json FROM datasets WHERE id=? AND user_id=?",
                                    (dataset_id, user_id)).fetchone()
                if not target:
                    return jsonify({"success": False, "error": "Select a dataset belonging to your account."}), 404
                saved_mapping = json.loads(target["mapping_json"] or "{}")
                if set(canonical_mapping.keys()) != set(saved_mapping.keys()):
                    return jsonify({"success": False, "error": "The mapped business fields must match the selected dataset. Create a new dataset for a different structure."}), 400
                if mode == "replace":
                    db.execute("DELETE FROM dataset_rows WHERE dataset_id=?", (dataset_id,))
                    db.execute("UPDATE datasets SET columns_json=?, mapping_json=? WHERE id=? AND user_id=?",
                               (json.dumps(headers), json.dumps(canonical_mapping), dataset_id, user_id))
            existing = set()
            if mode == "append":
                for item in db.execute("SELECT row_json FROM dataset_rows WHERE dataset_id=?", (dataset_id,)):
                    existing.add(item["row_json"])
            inserted = 0
            skipped = 0
            for row in rows:
                stored_row = dict(row)
                for standard_field, source_field in incoming_mapping.items():
                    stored_row[standard_field] = row.get(source_field)
                serialized = json.dumps(stored_row, ensure_ascii=False, default=str, sort_keys=True)
                if mode == "append" and serialized in existing:
                    skipped += 1
                    continue
                db.execute("INSERT INTO dataset_rows(dataset_id,row_json) VALUES(?,?)",
                           (dataset_id, serialized))
                existing.add(serialized)
                inserted += 1
            db.execute("UPDATE datasets SET row_count=(SELECT COUNT(*) FROM dataset_rows WHERE dataset_id=?), "
                       "original_filename=?, updated_at=? WHERE id=? AND user_id=?",
                       (dataset_id, filename, now, dataset_id, user_id))
        session["dataset_id"] = int(dataset_id)
        session.pop("upload_token", None)
        session.pop("upload_filename", None)
        staged.unlink(missing_ok=True)
        return jsonify({"success": True, "dataset_id": dataset_id, "inserted": inserted,
                        "skipped_duplicates": skipped})
    except (ValueError, TypeError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"success": False, "error": f"Import failed: {exc}"}), 500

@app.route("/api/sales")
@login_required
def get_sales():
    dataset_id = get_active_dataset_id(session["user_id"])
    if not dataset_id:
        return jsonify({"success": False, "error": "Upload a dataset to continue.", "needs_upload": True}), 404
    with get_db() as db:
        rows = db.execute(
            "SELECT r.row_json FROM dataset_rows r JOIN datasets d ON d.id=r.dataset_id "
            "WHERE d.id=? AND d.user_id=? ORDER BY r.id", (dataset_id, session["user_id"])
        ).fetchall()
    data = [json.loads(row["row_json"]) for row in rows]
    with get_db() as db:
        dataset = db.execute("SELECT mapping_json FROM datasets WHERE id=? AND user_id=?",
                             (dataset_id, session["user_id"])).fetchone()
    mapping = json.loads(dataset["mapping_json"] or "{}") if dataset else {}
    mapped_data = []
    for original in data:
        item = dict(original)
        for standard_field, source_field in mapping.items():
            if source_field in original:
                item[standard_field] = original[source_field]
        # The dashboard expects a stable identifier; create one only for display/table purposes.
        if not item.get("Order ID"):
            item["Order ID"] = str(len(mapped_data) + 1)
        mapped_data.append(item)
    return jsonify({"success": True, "count": len(mapped_data), "data": mapped_data,
                    "dataset_id": dataset_id, "mapping": mapping})


@app.route("/api/me")
@login_required
def api_me():
    user = current_user()
    if not user:
        session.clear()
        return jsonify({"success": False, "error": "Account not found."}), 401
    return jsonify({"success": True, "user": {
        "id": user["id"], "name": user["name"], "email": user["email"],
        "created_at": user["created_at"]
    }})

@app.route("/api/notifications")
@login_required
def api_notifications():
    from flask import get_flashed_messages
    messages = get_flashed_messages(with_categories=True)
    return jsonify({"success": True, "messages": [
        {"category": category, "message": message}
        for category, message in messages
    ]})

@app.route("/account/profile", methods=["POST"])
@login_required
def update_account_profile():
    payload = request.get_json(silent=True) or {}
    name = str(payload.get("name", "")).strip()
    email = str(payload.get("email", "")).strip().lower()
    password = str(payload.get("current_password", ""))
    if not name or len(name) > 80:
        return jsonify({"success": False, "error": "Name is required and must be 80 characters or fewer."}), 400
    if len(email) > 254 or "@" not in email or "." not in email.rsplit("@", 1)[-1]:
        return jsonify({"success": False, "error": "Enter a valid email address."}), 400
    user = current_user()
    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify({"success": False, "error": "Your current password is incorrect."}), 400
    try:
        with get_db() as db:
            db.execute("UPDATE users SET name=?, email=? WHERE id=?",
                       (name, email, session["user_id"]))
        session["user_name"] = name
        flash("Profile updated successfully.", "success")
        return jsonify({"success": True})
    except sqlite3.IntegrityError:
        return jsonify({"success": False, "error": "That email address is already registered."}), 409

@app.route("/account/password", methods=["POST"])
@login_required
def update_account_password():
    payload = request.get_json(silent=True) or {}
    current_password = str(payload.get("current_password", ""))
    new_password = str(payload.get("new_password", ""))
    confirm_password = str(payload.get("confirm_password", ""))
    user = current_user()
    if not user or not check_password_hash(user["password_hash"], current_password):
        return jsonify({"success": False, "error": "Your current password is incorrect."}), 400
    if len(new_password) < 8:
        return jsonify({"success": False, "error": "New password must be at least 8 characters."}), 400
    if new_password != confirm_password:
        return jsonify({"success": False, "error": "New passwords do not match."}), 400
    with get_db() as db:
        db.execute("UPDATE users SET password_hash=? WHERE id=?",
                   (generate_password_hash(new_password), session["user_id"]))
    flash("Password changed successfully.", "success")
    return jsonify({"success": True})

@app.context_processor
def inject_user():
    return {"current_user_name": session.get("user_name")}

init_db()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
