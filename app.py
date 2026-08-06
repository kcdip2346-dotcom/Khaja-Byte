import os
import io
import csv
import json
import sqlite3
import hashlib
import datetime
import secrets
from functools import wraps

from flask import (Flask, render_template, request, redirect, url_for,
                   session, g, flash, Response, jsonify)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "khajabyte.db")

app = Flask(__name__)
app.secret_key = "khaja-byte-ing-college-secret-key"


# --------------------------------------------------------------------------
# CORS — required so the Flutter web app (Chrome) can call the API
# --------------------------------------------------------------------------

@app.after_request
def add_cors_headers(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Auth-Token"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return resp


@app.before_request
def handle_cors_preflight():
    if request.method == "OPTIONS":
        resp = Response(status=204)
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Auth-Token"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        return resp
    return None


# --------------------------------------------------------------------------
# Database helpers
# --------------------------------------------------------------------------

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def hash_password(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


def init_db():
    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()
    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'customer',
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS menu_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            description TEXT DEFAULT '',
            price REAL NOT NULL,
            available INTEGER DEFAULT 1,
            image TEXT DEFAULT '🍽️',
            photo TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            booking_date TEXT NOT NULL,
            time_slot TEXT NOT NULL,
            item_summary TEXT NOT NULL,
            items_json TEXT DEFAULT '[]',
            total REAL NOT NULL,
            status TEXT DEFAULT 'pending',
            payment_status TEXT DEFAULT 'unpaid',
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            txn_ref TEXT UNIQUE NOT NULL,
            user_id INTEGER NOT NULL,
            booking_id INTEGER,
            amount REAL NOT NULL,
            method TEXT NOT NULL,
            status TEXT DEFAULT 'success',
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            rating INTEGER NOT NULL,
            comment TEXT DEFAULT '',
            hygiene_issue INTEGER DEFAULT 0,
            status TEXT DEFAULT 'new',
            response TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS announcements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            author TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS tokens (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );
        """
    )

    # --- Migrations for databases created before these columns existed ---
    def ensure_column(table, col, ddl):
        cols = [r[1] for r in cur.execute("PRAGMA table_info({})".format(table))]
        if col not in cols:
            cur.execute("ALTER TABLE {} ADD COLUMN {}".format(table, ddl))

    ensure_column("menu_items", "photo", "photo TEXT DEFAULT ''")
    ensure_column("bookings", "items_json", "items_json TEXT DEFAULT '[]'")
    ensure_column("users", "uid", "uid TEXT DEFAULT ''")

    # Demo users get distinct names and stable unique identifiers (ING-<ROLE>-<id>)
    def upsert_demo_user(name, email, pw, role, uid):
        row = cur.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if row:
            cur.execute("UPDATE users SET name=?, uid=? WHERE email=?",
                        (name, uid, email))
        else:
            cur.execute(
                "INSERT INTO users (name, email, password, role, uid) VALUES (?,?,?,?,?)",
                (name, email, hash_password(pw), role, uid))

    upsert_demo_user("Aarav Sharma", "admin@ingcollege.edu.np",
                     "admin123", "admin", "ING-ADM-001")
    upsert_demo_user("Sunita Gurung", "staff@ingcollege.edu.np",
                     "staff123", "staff", "ING-STF-002")
    upsert_demo_user("Bibek Tamang", "student@ingcollege.edu.np",
                     "student123", "customer", "ING-STU-003")

    # Backfill uids for any remaining users (e.g. registered before uid existed)
    for u in cur.execute("SELECT * FROM users WHERE uid=''").fetchall():
        cur.execute("UPDATE users SET uid=? WHERE id=?",
                    ("ING-{}-{:03d}".format(u["role"][:3].upper(), u["id"]), u["id"]))

    if cur.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        pass  # demo users are handled by upsert_demo_user above

    if cur.execute("SELECT COUNT(*) FROM menu_items").fetchone()[0] == 0:
        menu = [
            ("Steam Momo", "Snacks", "Juicy steamed dumplings with spicy achar", 120, "🥟",
             "https://images.unsplash.com/photo-1496116218417-1a781b1c416c?auto=format&fit=crop&w=600&q=80"),
            ("Chicken Chowmein", "Main Course", "Nepali-style wok fried noodles", 150, "🍜",
             "https://images.unsplash.com/photo-1585032226651-759b368d7246?auto=format&fit=crop&w=600&q=80"),
            ("Vegetable Thukpa", "Main Course", "Warm noodle soup with fresh veggies", 160, "🍲",
             "https://images.unsplash.com/photo-1547592166-23ac45744acd?auto=format&fit=crop&w=600&q=80"),
            ("Samosa (2 pcs)", "Snacks", "Crispy fried pastry with potato filling", 40, "🥠",
             "https://images.unsplash.com/photo-1601050690597-df0568f70950?auto=format&fit=crop&w=600&q=80"),
            ("Paneer Sekuwa", "Main Course", "Grilled paneer with Himalayan spices", 220, "🧀", ""),
            ("Chicken Biryani", "Main Course", "Aromatic basmati rice with chicken", 280, "🍛",
             "https://images.unsplash.com/photo-1589302168068-964664d93dc0?auto=format&fit=crop&w=600&q=80"),
            ("Dal Bhat", "Main Course", "Lentil soup, rice & seasonal vegetables", 180, "🍚",
             "https://images.unsplash.com/photo-1512058564366-18510be2db19?auto=format&fit=crop&w=600&q=80"),
            ("Masala Tea", "Beverages", "Traditional Nepali spiced milk tea", 40, "☕",
             "https://images.unsplash.com/photo-1576092768241-dec231879fc3?auto=format&fit=crop&w=600&q=80"),
            ("Coca-Cola", "Beverages", "Classic cola, chilled 500ml", 80, "🥤",
             "https://images.unsplash.com/photo-1554866585-cd94860890b7?auto=format&fit=crop&w=600&q=80"),
            ("Fanta Orange", "Beverages", "Orange fizz, chilled 500ml", 80, "🧡",
             "https://images.unsplash.com/photo-1629203851122-3727ecdf080e?auto=format&fit=crop&w=600&q=80"),
            ("Sprite", "Beverages", "Lemon-lime soda, chilled 500ml", 80, "💛",
             "https://images.unsplash.com/photo-1625772299848-391b6a87d7b3?auto=format&fit=crop&w=600&q=80"),
            ("Thumbs Up", "Beverages", "Indian cola, chilled 500ml", 70, "👍",
             ""),
            ("Limca", "Beverages", "Indian lemon soda, chilled 500ml", 70, "🍋",
             ""),
            ("Frooti", "Beverages", "Mango drink, chilled 500ml", 90, "🥭",
             ""),
            ("Maaza", "Beverages", "Mango crush, chilled 500ml", 90, "🥭",
             ""),
            ("Fruit Salad", "Healthy", "Fresh seasonal fruits with yogurt", 90, "🥗",
             "https://images.unsplash.com/photo-1490474418585-ba9bad8fd0ea?auto=format&fit=crop&w=600&q=80"),
        ]
        cur.executemany(
            "INSERT INTO menu_items (name, category, description, price, image, photo) VALUES (?,?,?,?,?,?)",
            menu,
        )
    else:
        photos = {
            "Steam Momo": "https://images.unsplash.com/photo-1496116218417-1a781b1c416c?auto=format&fit=crop&w=600&q=80",
            "Chicken Chowmein": "https://images.unsplash.com/photo-1585032226651-759b368d7246?auto=format&fit=crop&w=600&q=80",
            "Vegetable Thukpa": "https://images.unsplash.com/photo-1547592166-23ac45744acd?auto=format&fit=crop&w=600&q=80",
            "Samosa (2 pcs)": "https://images.unsplash.com/photo-1601050690597-df0568f70950?auto=format&fit=crop&w=600&q=80",
            "Chicken Biryani": "https://images.unsplash.com/photo-1589302168068-964664d93dc0?auto=format&fit=crop&w=600&q=80",
            "Dal Bhat": "https://images.unsplash.com/photo-1512058564366-18510be2db19?auto=format&fit=crop&w=600&q=80",
            "Masala Tea": "https://images.unsplash.com/photo-1576092768241-dec231879fc3?auto=format&fit=crop&w=600&q=80",
            "Fruit Salad": "https://images.unsplash.com/photo-1490474418585-ba9bad8fd0ea?auto=format&fit=crop&w=600&q=80",
        }
        for name, url in photos.items():
            cur.execute("UPDATE menu_items SET photo=? WHERE name=? AND (photo IS NULL OR photo='')",
                        (url, name))

    if cur.execute("SELECT COUNT(*) FROM announcements").fetchone()[0] == 0:
        cur.execute(
            "INSERT INTO announcements (title, body, author) VALUES (?,?,?)",
            ("Welcome to Khaja Byte!", "Hello ING College family! Order, pre-book and pay online. "
             "Transparent prices in NPR — no surprises. Hygiene first, always. 🧼", "College Admin"),
        )
        cur.execute(
            "INSERT INTO announcements (title, body, author) VALUES (?,?,?)",
            ("Weekly Kitchen Hygiene Audit", "Our kitchen is deep-cleaned and audited every Friday. "
             "Food handling follows college hygiene standards. Report any hygiene issue via Feedback.", "Canteen Staff"),
        )

    db.commit()
    db.close()


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def get_user(user_id):
    row = get_db().execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    return row


def current_user():
    uid = session.get("user_id")
    if uid is None:
        return None
    user = get_user(uid)
    if user is None:
        session.clear()
        return None
    return user


def avg_rating_for(item_id=None):
    db = get_db()
    row = db.execute("SELECT AVG(rating) AS a, COUNT(*) AS c FROM feedback").fetchone()
    avg = row["a"] if row and row["a"] else 0
    count = row["c"] if row else 0
    return avg, count


def npr_format(value):
    return "रू {:,.0f}".format(value or 0)


app.jinja_env.filters["npr"] = npr_format


def can(user, perm):
    """Simple permission helper for templates."""
    role = user["role"]
    perms = {
        "admin": {"users", "revenue", "menu_manage", "bookings_manage",
                  "feedback_manage", "announce_manage", "all"},
        "staff": {"bookings_manage", "menu_availability",
                  "announce_view", "feedback_manage"},
        "customer": set(),
    }
    return perm in perms.get(role, set())


app.jinja_env.globals["can"] = can


# --------------------------------------------------------------------------
# Auth decorators
# --------------------------------------------------------------------------

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in first.", "warn")
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper


def role_required(*roles):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user = current_user()
            if user is None:
                flash("Please log in first.", "warn")
                return redirect(url_for("login"))
            if user["role"] not in roles:
                flash("You are not allowed to access that page.", "error")
                return redirect(url_for("dashboard"))
            g.user = user
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def user_context():
    """User + app-wide data injected into every template."""
    user = current_user()
    db = get_db()
    return dict(
        user=user,
        college="ING College of Innovation and Leadership",
        today=datetime.date.today().isoformat(),
        recent_announcements=db.execute(
            "SELECT * FROM announcements ORDER BY created_at DESC LIMIT 5").fetchall() if user else [],
        unread_feedback=db.execute(
            "SELECT COUNT(*) c FROM feedback WHERE status='new'").fetchone()["c"] if user and user["role"] in ("admin", "staff") else 0,
    )


@app.context_processor
def inject_globals():
    return user_context()


# --------------------------------------------------------------------------
# Public pages
# --------------------------------------------------------------------------

@app.route("/")
def landing():
    db = get_db()
    items = db.execute("SELECT * FROM menu_items WHERE available=1").fetchall()
    avg, count = avg_rating_for()
    return render_template("landing.html", items=items[:6], avg_rating=avg,
                           feedback_count=count)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = get_db().execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if user and user["password"] == hash_password(password):
            session["user_id"] = user["id"]
            flash("Welcome back, {}!".format(user["name"]), "success")
            return redirect(url_for("dashboard"))
        flash("Invalid email or password.", "error")
    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        role = request.form.get("role", "customer")
        if role not in ("customer", "staff"):
            role = "customer"
        if not name or not email or not password:
            flash("All fields are required.", "warn")
        elif len(password) < 6:
            flash("Password must be at least 6 characters.", "warn")
        else:
            db = get_db()
            if db.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
                flash("An account with this email already exists.", "error")
            else:
                db.execute(
                    "INSERT INTO users (name, email, password, role) VALUES (?,?,?,?)",
                    (name, email, hash_password(password), role))
                db.commit()
                flash("Account created! Please log in.", "success")
                return redirect(url_for("login"))
    return render_template("register.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("landing"))


@app.route("/dashboard")
@login_required
def dashboard():
    user = current_user()
    if user["role"] == "admin":
        return redirect(url_for("admin_dashboard"))
    if user["role"] == "staff":
        return redirect(url_for("staff_dashboard"))
    return redirect(url_for("customer_dashboard"))


# --------------------------------------------------------------------------
# Customer area
# --------------------------------------------------------------------------

@app.route("/customer")
@login_required
def customer_dashboard():
    user = current_user()
    db = get_db()
    bookings = db.execute(
        "SELECT * FROM bookings WHERE user_id=? ORDER BY created_at DESC LIMIT 3",
        (user["id"],)).fetchall()
    txns = db.execute(
        "SELECT * FROM transactions WHERE user_id=? ORDER BY created_at DESC LIMIT 5",
        (user["id"],)).fetchall()
    anns = db.execute(
        "SELECT * FROM announcements ORDER BY created_at DESC LIMIT 4").fetchall()
    avg, count = avg_rating_for()
    return render_template("customer_dashboard.html", bookings=bookings,
                           txns=txns, anns=anns, avg_rating=avg, feedback_count=count)


@app.route("/menu")
@login_required
def menu_page():
    db = get_db()
    items = db.execute("SELECT * FROM menu_items ORDER BY category, name").fetchall()
    slots = ["11:00 AM", "12:00 PM", "1:00 PM", "2:00 PM", "4:00 PM", "5:30 PM"]
    return render_template("menu.html", items=items, slots=slots)


@app.route("/order", methods=["POST"])
@login_required
def place_order():
    user = current_user()
    db = get_db()
    items = request.form.get("items", "")
    booking_date = request.form.get("booking_date", "")
    time_slot = request.form.get("time_slot", "")
    method = request.form.get("method", "card")
    payment_name = request.form.get("payment_name", "").strip()
    payment_detail = request.form.get("payment_detail", "").strip()

    if not items or not booking_date or not time_slot:
        flash("Please select items, date and time slot.", "warn")
        return redirect(url_for("menu_page"))

    try:
        parsed = [tuple(x.split(":", 1)) for x in items.split(",") if x]
        cart = [(int(iid), int(qty)) for iid, qty in parsed]
    except (ValueError, IndexError):
        flash("Invalid cart contents.", "error")
        return redirect(url_for("menu_page"))

    if not cart:
        flash("Your cart is empty.", "warn")
        return redirect(url_for("menu_page"))

    summary_parts = []
    line_items = []
    total = 0.0
    for item_id, qty in cart:
        row = db.execute("SELECT * FROM menu_items WHERE id=?", (item_id,)).fetchone()
        if not row or not row["available"]:
            flash("Sorry, an item in your cart is no longer available.", "error")
            return redirect(url_for("menu_page"))
        total += row["price"] * qty
        summary_parts.append("{} x {}".format(qty, row["name"]))
        line_items.append({"id": row["id"], "name": row["name"],
                           "image": row["image"], "qty": qty,
                           "price": row["price"]})
    item_summary = ", ".join(summary_parts)
    items_json = json.dumps(line_items)

    if method in ("card", "esewa", "khalti"):
        if not payment_name or not payment_detail:
            flash("Please fill in your payment details.", "warn")
            return redirect(url_for("menu_page"))
        payment_status = "paid"
    else:
        payment_status = "unpaid"

    txn_ref = "KB-" + secrets.token_hex(3).upper()
    cur = db.execute(
        "INSERT INTO bookings (user_id, booking_date, time_slot, item_summary, items_json, total, status, payment_status)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (user["id"], booking_date, time_slot, item_summary, items_json, total,
         "pending", payment_status))
    booking_id = cur.lastrowid
    db.execute(
        "INSERT INTO transactions (txn_ref, user_id, booking_id, amount, method, status) VALUES (?,?,?,?,?,?)",
        (txn_ref, user["id"], booking_id, total, method,
         "success" if payment_status == "paid" else "pending"))
    db.commit()

    if payment_status == "paid":
        flash("Order placed & paid! Booking #KB{:04d} · Reference {} · {}".format(
            booking_id, txn_ref, npr_format(total)), "success")
    else:
        flash("Pre-booking received! Please pay रू {:,.0f} at the counter. Booking #KB{:04d}".format(
            total, booking_id), "success")
    return redirect(url_for("bookings_page"))


@app.route("/bookings")
@login_required
def bookings_page():
    user = current_user()
    rows = get_db().execute(
        "SELECT * FROM bookings WHERE user_id=? ORDER BY created_at DESC",
        (user["id"],)).fetchall()
    return render_template("bookings.html", bookings=rows)


@app.route("/bookings/<int:booking_id>/cancel", methods=["POST"])
@login_required
def cancel_booking(booking_id):
    user = current_user()
    db = get_db()
    booking = db.execute(
        "SELECT * FROM bookings WHERE id=? AND user_id=?", (booking_id, user["id"])).fetchone()
    if not booking:
        flash("Booking not found.", "error")
    elif booking["status"] in ("completed", "cancelled"):
        flash("This booking can no longer be cancelled.", "warn")
    else:
        db.execute("UPDATE bookings SET status='cancelled' WHERE id=?", (booking_id,))
        if booking["payment_status"] == "paid":
            db.execute(
                "INSERT INTO transactions (txn_ref, user_id, booking_id, amount, method, status) VALUES (?,?,?,?,?,?)",
                ("REF-" + secrets.token_hex(3).upper(), user["id"], booking_id,
                 booking["total"], "Refund", "success"))
        db.commit()
        flash("Booking cancelled.{}".format(
            " Paid amount refunded to your account." if booking["payment_status"] == "paid" else ""),
            "success")
    return redirect(url_for("bookings_page"))


@app.route("/feedback", methods=["GET", "POST"])
@login_required
def feedback_page():
    user = current_user()
    db = get_db()
    if request.method == "POST":
        rating = request.form.get("rating", type=int, default=0)
        comment = request.form.get("comment", "").strip()
        hygiene = 1 if request.form.get("hygiene_issue") else 0
        if not 1 <= rating <= 5:
            flash("Please select a star rating (1–5).", "warn")
        elif not comment:
            flash("Please write a short comment.", "warn")
        else:
            db.execute(
                "INSERT INTO feedback (user_id, rating, comment, hygiene_issue) VALUES (?,?,?,?)",
                (user["id"], rating, comment, hygiene))
            db.commit()
            flash("Thank you! Your feedback helps keep Khaja Byte clean & fair.", "success")
            return redirect(url_for("feedback_page"))
    mine = db.execute(
        "SELECT * FROM feedback WHERE user_id=? ORDER BY created_at DESC",
        (user["id"],)).fetchall()
    return render_template("feedback.html", feedbacks=mine)


@app.route("/transactions")
@login_required
def transactions_page():
    user = current_user()
    rows = get_db().execute(
        "SELECT * FROM transactions WHERE user_id=? ORDER BY created_at DESC",
        (user["id"],)).fetchall()
    return render_template("transactions.html", txns=rows)


@app.route("/announcements")
@login_required
def announcements_page():
    rows = get_db().execute(
        "SELECT * FROM announcements ORDER BY created_at DESC").fetchall()
    return render_template("announcements.html", anns=rows)


# --------------------------------------------------------------------------
# Admin area
# --------------------------------------------------------------------------

@app.route("/admin")
@login_required
@role_required("admin")
def admin_dashboard():
    db = get_db()
    users = db.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
    items = db.execute("SELECT COUNT(*) c FROM menu_items").fetchone()["c"]
    today = datetime.date.today().isoformat()
    todays_bookings = db.execute(
        "SELECT COUNT(*) c FROM bookings WHERE booking_date=?", (today,)).fetchone()["c"]
    revenue = db.execute(
        "SELECT COALESCE(SUM(amount),0) s FROM transactions"
        " WHERE status='success' AND method != 'Refund'").fetchone()["s"]
    pending = db.execute(
        "SELECT COUNT(*) c FROM bookings WHERE status='pending'").fetchone()["c"]
    new_fb = db.execute(
        "SELECT COUNT(*) c FROM feedback WHERE status='new'").fetchone()["c"]
    hygiene_fb = db.execute(
        "SELECT COUNT(*) c FROM feedback WHERE hygiene_issue=1 AND status='new'").fetchone()["c"]
    avg, count = avg_rating_for()
    recent_bookings = db.execute(
        "SELECT b.*, u.name AS uname FROM bookings b JOIN users u ON u.id=b.user_id"
        " ORDER BY b.created_at DESC LIMIT 6").fetchall()
    recent_fb = db.execute(
        "SELECT f.*, u.name AS uname FROM feedback f JOIN users u ON u.id=f.user_id"
        " ORDER BY f.created_at DESC LIMIT 6").fetchall()
    recent_txns = db.execute(
        "SELECT t.*, u.name AS uname FROM transactions t JOIN users u ON u.id=t.user_id"
        " ORDER BY t.created_at DESC LIMIT 6").fetchall()
    return render_template(
        "admin_dashboard.html", stats=dict(users=users, items=items,
                                           todays_bookings=todays_bookings,
                                           revenue=revenue, pending=pending,
                                           new_fb=new_fb, hygiene_fb=hygiene_fb,
                                           avg=avg, count=count),
        recent_bookings=recent_bookings, recent_fb=recent_fb, recent_txns=recent_txns)


@app.route("/admin/menu", methods=["GET", "POST"])
@login_required
@role_required("admin")
def admin_menu():
    db = get_db()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        category = request.form.get("category", "").strip()
        description = request.form.get("description", "").strip()
        price = request.form.get("price", type=float, default=0)
        image = request.form.get("image", "").strip() or "🍽️"
        if not name or not category or price <= 0:
            flash("Name, category and a valid NPR price are required.", "warn")
        else:
            db.execute(
                "INSERT INTO menu_items (name, category, description, price, image) VALUES (?,?,?,?,?)",
                (name, category, description, price, image))
            db.commit()
            flash("Menu item added.", "success")
            return redirect(url_for("admin_menu"))
    rows = db.execute("SELECT * FROM menu_items ORDER BY category, name").fetchall()
    return render_template("admin_menu.html", items=rows)


@app.route("/admin/menu/<int:item_id>/toggle", methods=["POST"])
@login_required
@role_required("admin", "staff")
def admin_toggle_item(item_id):
    db = get_db()
    row = db.execute("SELECT * FROM menu_items WHERE id=?", (item_id,)).fetchone()
    if row:
        new = 0 if row["available"] else 1
        db.execute("UPDATE menu_items SET available=? WHERE id=?", (new, item_id))
        db.commit()
        flash("{} is now {}.".format(row["name"], "available" if new else "sold out"), "success")
    return redirect(request.referrer or url_for("admin_menu"))


@app.route("/admin/menu/<int:item_id>/edit", methods=["POST"])
@login_required
@role_required("admin")
def admin_edit_item(item_id):
    db = get_db()
    name = request.form.get("name", "").strip()
    category = request.form.get("category", "").strip()
    description = request.form.get("description", "").strip()
    price = request.form.get("price", type=float, default=0)
    image = request.form.get("image", "").strip() or "🍽️"
    if name and category and price > 0:
        db.execute(
            "UPDATE menu_items SET name=?, category=?, description=?, price=?, image=? WHERE id=?",
            (name, category, description, price, image, item_id))
        db.commit()
        flash("Menu item updated.", "success")
    else:
        flash("Name, category and a valid NPR price are required.", "warn")
    return redirect(url_for("admin_menu"))


@app.route("/admin/menu/<int:item_id>/delete", methods=["POST"])
@login_required
@role_required("admin")
def admin_delete_item(item_id):
    db = get_db()
    db.execute("DELETE FROM menu_items WHERE id=?", (item_id,))
    db.commit()
    flash("Menu item removed.", "success")
    return redirect(url_for("admin_menu"))


@app.route("/admin/bookings")
@login_required
@role_required("admin", "staff")
def admin_bookings():
    rows = get_db().execute(
        "SELECT b.*, u.name AS uname, u.email AS uemail FROM bookings b"
        " JOIN users u ON u.id=b.user_id ORDER BY b.booking_date DESC, b.id DESC").fetchall()
    return render_template("admin_bookings.html", bookings=rows)


@app.route("/admin/bookings/<int:booking_id>/status", methods=["POST"])
@login_required
@role_required("admin", "staff")
def admin_booking_status(booking_id):
    status = request.form.get("status", "")
    db = get_db()
    if status in ("confirmed", "completed", "cancelled", "pending"):
        db.execute("UPDATE bookings SET status=? WHERE id=?", (status, booking_id))
        db.commit()
        flash("Booking #KB{:04d} → {}".format(booking_id, status.title()), "success")
    return redirect(url_for("admin_bookings"))


@app.route("/admin/feedback")
@login_required
@role_required("admin", "staff")
def admin_feedback():
    rows = get_db().execute(
        "SELECT f.*, u.name AS uname FROM feedback f JOIN users u ON u.id=f.user_id"
        " ORDER BY f.hygiene_issue DESC, f.created_at DESC").fetchall()
    return render_template("admin_feedback.html", feedbacks=rows)


@app.route("/admin/feedback/<int:fb_id>/respond", methods=["POST"])
@login_required
@role_required("admin")
def admin_feedback_respond(fb_id):
    response = request.form.get("response", "").strip()
    status = "responded" if response else "read"
    db = get_db()
    db.execute("UPDATE feedback SET response=?, status=? WHERE id=?",
               (response, status, fb_id))
    db.commit()
    flash("Feedback updated.", "success")
    return redirect(url_for("admin_feedback"))


@app.route("/admin/announcements", methods=["GET", "POST"])
@login_required
@role_required("admin")
def admin_announcements():
    db = get_db()
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        body = request.form.get("body", "").strip()
        if not title or not body:
            flash("Title and message are required.", "warn")
        else:
            db.execute(
                "INSERT INTO announcements (title, body, author) VALUES (?,?,?)",
                (title, body, g.user["name"]))
            db.commit()
            flash("Announcement published.", "success")
            return redirect(url_for("admin_announcements"))
    rows = db.execute("SELECT * FROM announcements ORDER BY created_at DESC").fetchall()
    return render_template("admin_announcements.html", anns=rows)


@app.route("/admin/announcements/<int:ann_id>/delete", methods=["POST"])
@login_required
@role_required("admin")
def admin_delete_announcement(ann_id):
    db = get_db()
    db.execute("DELETE FROM announcements WHERE id=?", (ann_id,))
    db.commit()
    flash("Announcement deleted.", "success")
    return redirect(url_for("admin_announcements"))


@app.route("/admin/users")
@login_required
@role_required("admin")
def admin_users():
    rows = get_db().execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
    return render_template("admin_users.html", users=rows)


@app.route("/admin/transactions")
@login_required
@role_required("admin")
def admin_transactions():
    rows = get_db().execute(
        "SELECT t.*, u.name AS uname, b.booking_date AS bdate, b.time_slot AS bslot"
        " FROM transactions t JOIN users u ON u.id=t.user_id"
        " LEFT JOIN bookings b ON b.id=t.booking_id"
        " ORDER BY t.created_at DESC").fetchall()
    total = sum(r["amount"] for r in rows if r["status"] == "success" and r["method"] != "Refund")
    return render_template("admin_transactions.html", txns=rows, total=total)


# --------------------------------------------------------------------------
# Staff area
# --------------------------------------------------------------------------

@app.route("/staff")
@login_required
@role_required("staff")
def staff_dashboard():
    db = get_db()
    today = datetime.date.today().isoformat()
    todays = db.execute(
        "SELECT b.*, u.name AS uname FROM bookings b JOIN users u ON u.id=b.user_id"
        " WHERE b.booking_date=? ORDER BY b.time_slot", (today,)).fetchall()
    pending = sum(1 for r in todays if r["status"] == "pending")
    anns = db.execute("SELECT * FROM announcements ORDER BY created_at DESC LIMIT 3").fetchall()
    return render_template("staff_dashboard.html", todays=todays, pending=pending, anns=anns)


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile_page():
    user = current_user()
    db = get_db()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        cur_pw = request.form.get("current_password", "")
        new_pw = request.form.get("new_password", "")
        if name:
            db.execute("UPDATE users SET name=? WHERE id=?", (name, user["id"]))
            db.commit()
            session.clear()
            flash("Name updated. Please log in again.", "success")
            return redirect(url_for("login"))
        if cur_pw and new_pw:
            if user["password"] != hash_password(cur_pw):
                flash("Current password is incorrect.", "error")
            elif len(new_pw) < 6:
                flash("New password must be at least 6 characters.", "warn")
            else:
                db.execute("UPDATE users SET password=? WHERE id=?",
                           (hash_password(new_pw), user["id"]))
                db.commit()
                session.clear()
                flash("Password changed! Please log in again.", "success")
                return redirect(url_for("login"))
        elif not cur_pw and not new_pw:
            flash("Nothing to update.", "warn")
        else:
            flash("Fill both current and new password to change it.", "warn")
    return render_template("profile.html")


@app.route("/invoice/<int:booking_id>")
@login_required
def invoice_page(booking_id):
    user = current_user()
    db = get_db()
    if user["role"] in ("admin", "staff"):
        booking = db.execute(
            "SELECT b.*, u.name AS uname, u.email AS uemail FROM bookings b"
            " JOIN users u ON u.id=b.user_id WHERE b.id=?", (booking_id,)).fetchone()
    else:
        booking = db.execute(
            "SELECT b.*, u.name AS uname, u.email AS uemail FROM bookings b"
            " JOIN users u ON u.id=b.user_id WHERE b.id=? AND b.user_id=?",
            (booking_id, user["id"])).fetchone()
    if not booking:
        flash("Invoice not found.", "error")
        return redirect(url_for("bookings_page"))
    txn = db.execute(
        "SELECT * FROM transactions WHERE booking_id=? ORDER BY id DESC LIMIT 1",
        (booking_id,)).fetchone()
    try:
        lines = json.loads(booking["items_json"]) if booking["items_json"] else []
    except (ValueError, TypeError):
        lines = []
    return render_template("invoice.html", b=booking, txn=txn, lines=lines)


@app.route("/admin/transactions/export")
@login_required
@role_required("admin")
def admin_export_transactions():
    db = get_db()
    rows = db.execute(
        "SELECT t.txn_ref, t.created_at, u.name AS uname, b.booking_date AS bdate,"
        " b.time_slot AS bslot, t.method, t.amount, t.status"
        " FROM transactions t JOIN users u ON u.id=t.user_id"
        " LEFT JOIN bookings b ON b.id=t.booking_id"
        " ORDER BY t.created_at DESC").fetchall()
    buf = io.StringIO()
    buf.write("\ufeff")  # BOM so Excel opens Nepali text correctly
    writer = csv.writer(buf)
    writer.writerow(["Reference", "Date", "Customer", "Booking Date",
                     "Slot", "Method", "Amount (NPR)", "Status"])
    for r in rows:
        writer.writerow([r["txn_ref"], r["created_at"], r["uname"],
                         r["bdate"] or "", r["bslot"] or "",
                         r["method"], "{:.0f}".format(r["amount"]), r["status"]])
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition":
                 "attachment; filename=khaja-byte-transactions-{}.csv".format(
                     datetime.date.today().isoformat())})


# --------------------------------------------------------------------------
# JSON API (used by the Khājā Byte Flutter mobile app)
# --------------------------------------------------------------------------

def api_require_user():
    token = request.headers.get("X-Auth-Token", "")
    if not token:
        return None, ({"error": "Not authenticated"}, 401)
    row = get_db().execute(
        "SELECT u.* FROM users u JOIN tokens t ON t.user_id=u.id WHERE t.token=?",
        (token,)).fetchone()
    if not row:
        return None, ({"error": "Invalid or expired token"}, 401)
    return row, None


def api_require_roles(user, *roles):
    if user["role"] not in roles:
        return ({"error": "Access denied"}, 403)
    return None


def api_user_dict(u):
    return {"id": u["id"], "name": u["name"], "email": u["email"],
            "role": u["role"], "uid": u["uid"],
            "created_at": u["created_at"]}


def api_item_dict(i):
    return {"id": i["id"], "name": i["name"], "category": i["category"],
            "description": i["description"], "price": i["price"],
            "available": bool(i["available"]), "image": i["image"],
            "photo": i["photo"]}


def api_booking_dict(b):
    return {"id": b["id"], "user_id": b["user_id"],
            "booking_date": b["booking_date"], "time_slot": b["time_slot"],
            "item_summary": b["item_summary"], "total": b["total"],
            "status": b["status"], "payment_status": b["payment_status"],
            "created_at": b["created_at"],
            "items_json": b["items_json"],
            "uname": b["uname"] if "uname" in b.keys() else None,
            "uemail": b["uemail"] if "uemail" in b.keys() else None}


def api_feedback_dict(f):
    return {"id": f["id"], "user_id": f["user_id"],
            "uname": f["uname"] if "uname" in f.keys() else None,
            "rating": f["rating"], "comment": f["comment"],
            "hygiene_issue": bool(f["hygiene_issue"]), "status": f["status"],
            "response": f["response"], "created_at": f["created_at"]}


@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    user = get_db().execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    if not user or user["password"] != hash_password(password):
        return jsonify({"error": "Invalid email or password"}), 401
    token = secrets.token_hex(16)
    get_db().execute("INSERT INTO tokens (token, user_id) VALUES (?,?)",
                     (token, user["id"]))
    get_db().commit()
    return jsonify({"token": token, "user": api_user_dict(user)})


@app.route("/api/register", methods=["POST"])
def api_register():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    role = data.get("role") or "customer"
    if role not in ("customer", "staff"):
        role = "customer"
    if not name or not email or not password:
        return jsonify({"error": "All fields are required"}), 400
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400
    db = get_db()
    if db.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
        return jsonify({"error": "An account with this email already exists"}), 409
    cur = db.execute(
        "INSERT INTO users (name, email, password, role) VALUES (?,?,?,?)",
        (name, email, hash_password(password), role))
    uid = "ING-{}-{:03d}".format(role[:3].upper(), cur.lastrowid)
    db.execute("UPDATE users SET uid=? WHERE id=?", (uid, cur.lastrowid))
    db.commit()
    token = secrets.token_hex(16)
    db.execute("INSERT INTO tokens (token, user_id) VALUES (?,?)",
               (token, cur.lastrowid))
    db.commit()
    user = get_user(cur.lastrowid)
    return jsonify({"token": token, "user": api_user_dict(user)})


@app.route("/api/logout", methods=["POST"])
def api_logout():
    token = request.headers.get("X-Auth-Token", "")
    if token:
        get_db().execute("DELETE FROM tokens WHERE token=?", (token,))
        get_db().commit()
    return jsonify({"ok": True})


@app.route("/api/me")
def api_me():
    user, err = api_require_user()
    if err:
        return jsonify(err[0]), err[1]
    return jsonify({"user": api_user_dict(user)})


@app.route("/api/menu")
def api_menu():
    rows = get_db().execute(
        "SELECT * FROM menu_items ORDER BY category, name").fetchall()
    return jsonify({"items": [api_item_dict(r) for r in rows]})


@app.route("/api/announcements")
def api_announcements():
    rows = get_db().execute(
        "SELECT * FROM announcements ORDER BY created_at DESC").fetchall()
    return jsonify({"announcements": [dict(r) for r in rows]})


@app.route("/api/order", methods=["POST"])
def api_order():
    user, err = api_require_user()
    if err:
        return jsonify(err[0]), err[1]
    data = request.get_json(silent=True) or {}
    items = data.get("items") or []
    booking_date = (data.get("booking_date") or "").strip()
    time_slot = (data.get("time_slot") or "").strip()
    method = data.get("method") or "card"
    payment_name = (data.get("payment_name") or "").strip()
    payment_detail = (data.get("payment_detail") or "").strip()

    if not items or not booking_date or not time_slot:
        return jsonify({"error": "Please select items, date and time slot"}), 400
    try:
        cart = [(int(i["id"]), int(i["qty"])) for i in items]
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "Invalid cart contents"}), 400
    if not cart:
        return jsonify({"error": "Your cart is empty"}), 400

    db = get_db()
    summary_parts, line_items, total = [], [], 0.0
    for item_id, qty in cart:
        row = db.execute("SELECT * FROM menu_items WHERE id=?", (item_id,)).fetchone()
        if not row or not row["available"]:
            return jsonify({"error": "An item in your cart is no longer available"}), 409
        total += row["price"] * qty
        summary_parts.append("{} x {}".format(qty, row["name"]))
        line_items.append({"id": row["id"], "name": row["name"],
                           "image": row["image"], "qty": qty, "price": row["price"]})
    item_summary = ", ".join(summary_parts)

    if method in ("card", "esewa", "khalti"):
        if not payment_name or not payment_detail:
            return jsonify({"error": "Please fill in your payment details"}), 400
        payment_status = "paid"
    else:
        payment_status = "unpaid"

    txn_ref = "KB-" + secrets.token_hex(3).upper()
    cur = db.execute(
        "INSERT INTO bookings (user_id, booking_date, time_slot, item_summary, items_json, total, status, payment_status)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (user["id"], booking_date, time_slot, item_summary,
         json.dumps(line_items), total, "pending", payment_status))
    booking_id = cur.lastrowid
    db.execute(
        "INSERT INTO transactions (txn_ref, user_id, booking_id, amount, method, status) VALUES (?,?,?,?,?,?)",
        (txn_ref, user["id"], booking_id, total, method,
         "success" if payment_status == "paid" else "pending"))
    db.commit()
    return jsonify({"booking_id": booking_id, "txn_ref": txn_ref,
                    "total": total, "payment_status": payment_status})


@app.route("/api/bookings")
def api_bookings():
    user, err = api_require_user()
    if err:
        return jsonify(err[0]), err[1]
    rows = get_db().execute(
        "SELECT b.*, u.name AS uname, u.email AS uemail FROM bookings b"
        " JOIN users u ON u.id=b.user_id WHERE b.user_id=?"
        " ORDER BY b.created_at DESC", (user["id"],)).fetchall()
    return jsonify({"bookings": [api_booking_dict(r) for r in rows]})


@app.route("/api/bookings/<int:booking_id>/cancel", methods=["POST"])
def api_cancel_booking(booking_id):
    user, err = api_require_user()
    if err:
        return jsonify(err[0]), err[1]
    db = get_db()
    booking = db.execute("SELECT * FROM bookings WHERE id=? AND user_id=?",
                         (booking_id, user["id"])).fetchone()
    if not booking:
        return jsonify({"error": "Booking not found"}), 404
    if booking["status"] in ("completed", "cancelled"):
        return jsonify({"error": "This booking can no longer be cancelled"}), 400
    db.execute("UPDATE bookings SET status='cancelled' WHERE id=?", (booking_id,))
    if booking["payment_status"] == "paid":
        db.execute(
            "INSERT INTO transactions (txn_ref, user_id, booking_id, amount, method, status) VALUES (?,?,?,?,?,?)",
            ("REF-" + secrets.token_hex(3).upper(), user["id"], booking_id,
             booking["total"], "Refund", "success"))
    db.commit()
    return jsonify({"ok": True, "refunded": booking["payment_status"] == "paid"})


@app.route("/api/transactions")
def api_transactions():
    user, err = api_require_user()
    if err:
        return jsonify(err[0]), err[1]
    rows = get_db().execute(
        "SELECT * FROM transactions WHERE user_id=? ORDER BY created_at DESC",
        (user["id"],)).fetchall()
    return jsonify({"transactions": [dict(r) for r in rows]})


@app.route("/api/invoice/<int:booking_id>")
def api_invoice(booking_id):
    user, err = api_require_user()
    if err:
        return jsonify(err[0]), err[1]
    if user["role"] in ("admin", "staff"):
        booking = get_db().execute(
            "SELECT b.*, u.name AS uname, u.email AS uemail FROM bookings b"
            " JOIN users u ON u.id=b.user_id WHERE b.id=?", (booking_id,)).fetchone()
    else:
        booking = get_db().execute(
            "SELECT b.*, u.name AS uname, u.email AS uemail FROM bookings b"
            " JOIN users u ON u.id=b.user_id WHERE b.id=? AND b.user_id=?",
            (booking_id, user["id"])).fetchone()
    if not booking:
        return jsonify({"error": "Invoice not found"}), 404
    txn = get_db().execute(
        "SELECT * FROM transactions WHERE booking_id=? ORDER BY id DESC LIMIT 1",
        (booking_id,)).fetchone()
    try:
        lines = json.loads(booking["items_json"]) if booking["items_json"] else []
    except (ValueError, TypeError):
        lines = []
    return jsonify({"booking": api_booking_dict(booking),
                    "lines": lines, "txn": dict(txn) if txn else None})


@app.route("/api/feedback", methods=["GET", "POST"])
def api_feedback():
    user, err = api_require_user()
    if err:
        return jsonify(err[0]), err[1]
    db = get_db()
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        rating = data.get("rating", 0)
        comment = (data.get("comment") or "").strip()
        hygiene = 1 if data.get("hygiene_issue") else 0
        if not 1 <= rating <= 5:
            return jsonify({"error": "Rating must be 1–5"}), 400
        if not comment:
            return jsonify({"error": "Please write a short comment"}), 400
        db.execute(
            "INSERT INTO feedback (user_id, rating, comment, hygiene_issue) VALUES (?,?,?,?)",
            (user["id"], rating, comment, hygiene))
        db.commit()
        return jsonify({"ok": True})
    rows = db.execute(
        "SELECT f.*, u.name AS uname FROM feedback f JOIN users u ON u.id=f.user_id"
        " WHERE f.user_id=? ORDER BY f.created_at DESC", (user["id"],)).fetchall()
    avg = db.execute("SELECT AVG(rating) a, COUNT(*) c FROM feedback").fetchone()
    return jsonify({"feedback": [api_feedback_dict(r) for r in rows],
                    "avg_rating": avg["a"] or 0, "count": avg["c"]})


@app.route("/api/profile", methods=["POST"])
def api_profile():
    user, err = api_require_user()
    if err:
        return jsonify(err[0]), err[1]
    data = request.get_json(silent=True) or {}
    db = get_db()
    if data.get("name"):
        db.execute("UPDATE users SET name=? WHERE id=?", (data["name"].strip(), user["id"]))
        db.commit()
        return jsonify({"ok": True})
    cur_pw = data.get("current_password", "")
    new_pw = data.get("new_password", "")
    if cur_pw and new_pw:
        if user["password"] != hash_password(cur_pw):
            return jsonify({"error": "Current password is incorrect"}), 400
        if len(new_pw) < 6:
            return jsonify({"error": "New password must be at least 6 characters"}), 400
        db.execute("UPDATE users SET password=? WHERE id=?",
                   (hash_password(new_pw), user["id"]))
        db.commit()
        return jsonify({"ok": True})
    return jsonify({"error": "Nothing to update"}), 400


@app.route("/api/admin/stats")
def api_admin_stats():
    user, err = api_require_user()
    if err:
        return jsonify(err[0]), err[1]
    denied = api_require_roles(user, "admin", "staff")
    if denied:
        return jsonify(denied[0]), denied[1]
    db = get_db()
    today = datetime.date.today().isoformat()
    revenue = db.execute(
        "SELECT COALESCE(SUM(amount),0) s FROM transactions"
        " WHERE status='success' AND method != 'Refund'").fetchone()["s"]
    stats = {
        "users": db.execute("SELECT COUNT(*) c FROM users").fetchone()["c"],
        "items": db.execute("SELECT COUNT(*) c FROM menu_items").fetchone()["c"],
        "todays_bookings": db.execute(
            "SELECT COUNT(*) c FROM bookings WHERE booking_date=?", (today,)).fetchone()["c"],
        "revenue": revenue,
        "pending": db.execute(
            "SELECT COUNT(*) c FROM bookings WHERE status='pending'").fetchone()["c"],
        "new_fb": db.execute(
            "SELECT COUNT(*) c FROM feedback WHERE status='new'").fetchone()["c"],
        "hygiene_fb": db.execute(
            "SELECT COUNT(*) c FROM feedback WHERE hygiene_issue=1 AND status='new'").fetchone()["c"],
        "avg_rating": (db.execute("SELECT AVG(rating) a FROM feedback").fetchone()["a"] or 0),
        "review_count": db.execute("SELECT COUNT(*) c FROM feedback").fetchone()["c"],
    }
    return jsonify({"stats": stats})


@app.route("/api/admin/bookings")
def api_admin_bookings():
    user, err = api_require_user()
    if err:
        return jsonify(err[0]), err[1]
    denied = api_require_roles(user, "admin", "staff")
    if denied:
        return jsonify(denied[0]), denied[1]
    rows = get_db().execute(
        "SELECT b.*, u.name AS uname, u.email AS uemail FROM bookings b"
        " JOIN users u ON u.id=b.user_id ORDER BY b.booking_date DESC, b.id DESC").fetchall()
    return jsonify({"bookings": [api_booking_dict(r) for r in rows]})


@app.route("/api/admin/bookings/<int:booking_id>/status", methods=["POST"])
def api_admin_booking_status(booking_id):
    user, err = api_require_user()
    if err:
        return jsonify(err[0]), err[1]
    denied = api_require_roles(user, "admin", "staff")
    if denied:
        return jsonify(denied[0]), denied[1]
    status = (request.get_json(silent=True) or {}).get("status", "")
    if status not in ("pending", "confirmed", "completed", "cancelled"):
        return jsonify({"error": "Invalid status"}), 400
    get_db().execute("UPDATE bookings SET status=? WHERE id=?", (status, booking_id))
    get_db().commit()
    return jsonify({"ok": True})


@app.route("/api/admin/menu", methods=["GET", "POST"])
def api_admin_menu():
    user, err = api_require_user()
    if err:
        return jsonify(err[0]), err[1]
    denied = api_require_roles(user, "admin", "staff")
    if denied:
        return jsonify(denied[0]), denied[1]
    db = get_db()
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        name = (data.get("name") or "").strip()
        category = (data.get("category") or "").strip()
        description = (data.get("description") or "").strip()
        price = data.get("price", 0)
        image = (data.get("image") or "").strip() or "🍽️"
        photo = (data.get("photo") or "").strip()
        if not name or not category or not price or price <= 0:
            return jsonify({"error": "Name, category and a valid NPR price are required"}), 400
        db.execute(
            "INSERT INTO menu_items (name, category, description, price, image, photo) VALUES (?,?,?,?,?,?)",
            (name, category, description, price, image, photo))
        db.commit()
        return jsonify({"ok": True})
    rows = db.execute("SELECT * FROM menu_items ORDER BY category, name").fetchall()
    return jsonify({"items": [api_item_dict(r) for r in rows]})


@app.route("/api/admin/menu/<int:item_id>/toggle", methods=["POST"])
def api_admin_toggle_item(item_id):
    user, err = api_require_user()
    if err:
        return jsonify(err[0]), err[1]
    denied = api_require_roles(user, "admin", "staff")
    if denied:
        return jsonify(denied[0]), denied[1]
    db = get_db()
    row = db.execute("SELECT * FROM menu_items WHERE id=?", (item_id,)).fetchone()
    if not row:
        return jsonify({"error": "Item not found"}), 404
    new = 0 if row["available"] else 1
    db.execute("UPDATE menu_items SET available=? WHERE id=?", (new, item_id))
    db.commit()
    return jsonify({"ok": True, "available": bool(new)})


@app.route("/api/admin/menu/<int:item_id>/edit", methods=["POST"])
def api_admin_edit_item(item_id):
    user, err = api_require_user()
    if err:
        return jsonify(err[0]), err[1]
    denied = api_require_roles(user, "admin")
    if denied:
        return jsonify(denied[0]), denied[1]
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    category = (data.get("category") or "").strip()
    description = (data.get("description") or "").strip()
    price = data.get("price", 0)
    image = (data.get("image") or "").strip() or "🍽️"
    if not name or not category or not price or price <= 0:
        return jsonify({"error": "Name, category and a valid NPR price are required"}), 400
    get_db().execute(
        "UPDATE menu_items SET name=?, category=?, description=?, price=?, image=? WHERE id=?",
        (name, category, description, price, image, item_id))
    get_db().commit()
    return jsonify({"ok": True})


@app.route("/api/admin/menu/<int:item_id>/delete", methods=["POST"])
def api_admin_delete_item(item_id):
    user, err = api_require_user()
    if err:
        return jsonify(err[0]), err[1]
    denied = api_require_roles(user, "admin")
    if denied:
        return jsonify(denied[0]), denied[1]
    get_db().execute("DELETE FROM menu_items WHERE id=?", (item_id,))
    get_db().commit()
    return jsonify({"ok": True})


@app.route("/api/admin/feedback")
def api_admin_feedback():
    user, err = api_require_user()
    if err:
        return jsonify(err[0]), err[1]
    denied = api_require_roles(user, "admin", "staff")
    if denied:
        return jsonify(denied[0]), denied[1]
    rows = get_db().execute(
        "SELECT f.*, u.name AS uname FROM feedback f JOIN users u ON u.id=f.user_id"
        " ORDER BY f.hygiene_issue DESC, f.created_at DESC").fetchall()
    return jsonify({"feedback": [api_feedback_dict(r) for r in rows]})


@app.route("/api/admin/feedback/<int:fb_id>/respond", methods=["POST"])
def api_admin_feedback_respond(fb_id):
    user, err = api_require_user()
    if err:
        return jsonify(err[0]), err[1]
    denied = api_require_roles(user, "admin")
    if denied:
        return jsonify(denied[0]), denied[1]
    response = (request.get_json(silent=True) or {}).get("response", "").strip()
    status = "responded" if response else "read"
    get_db().execute("UPDATE feedback SET response=?, status=? WHERE id=?",
                     (response, status, fb_id))
    get_db().commit()
    return jsonify({"ok": True})


@app.route("/api/admin/announcements", methods=["GET", "POST"])
def api_admin_announcements():
    user, err = api_require_user()
    if err:
        return jsonify(err[0]), err[1]
    denied = api_require_roles(user, "admin")
    if denied:
        return jsonify(denied[0]), denied[1]
    db = get_db()
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        title = (data.get("title") or "").strip()
        body = (data.get("body") or "").strip()
        if not title or not body:
            return jsonify({"error": "Title and message are required"}), 400
        db.execute("INSERT INTO announcements (title, body, author) VALUES (?,?,?)",
                   (title, body, user["name"]))
        db.commit()
        return jsonify({"ok": True})
    rows = db.execute("SELECT * FROM announcements ORDER BY created_at DESC").fetchall()
    return jsonify({"announcements": [dict(r) for r in rows]})


@app.route("/api/admin/announcements/<int:ann_id>/delete", methods=["POST"])
def api_admin_delete_announcement(ann_id):
    user, err = api_require_user()
    if err:
        return jsonify(err[0]), err[1]
    denied = api_require_roles(user, "admin")
    if denied:
        return jsonify(denied[0]), denied[1]
    get_db().execute("DELETE FROM announcements WHERE id=?", (ann_id,))
    get_db().commit()
    return jsonify({"ok": True})


@app.route("/api/admin/transactions")
def api_admin_transactions():
    user, err = api_require_user()
    if err:
        return jsonify(err[0]), err[1]
    denied = api_require_roles(user, "admin")
    if denied:
        return jsonify(denied[0]), denied[1]
    rows = get_db().execute(
        "SELECT t.*, u.name AS uname, b.booking_date AS bdate, b.time_slot AS bslot"
        " FROM transactions t JOIN users u ON u.id=t.user_id"
        " LEFT JOIN bookings b ON b.id=t.booking_id"
        " ORDER BY t.created_at DESC").fetchall()
    return jsonify({"transactions": [dict(r) for r in rows]})


@app.route("/api/admin/users")
def api_admin_users():
    user, err = api_require_user()
    if err:
        return jsonify(err[0]), err[1]
    denied = api_require_roles(user, "admin")
    if denied:
        return jsonify(denied[0]), denied[1]
    rows = get_db().execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
    return jsonify({"users": [api_user_dict(r) for r in rows]})


@app.route("/api/staff/today")
def api_staff_today():
    user, err = api_require_user()
    if err:
        return jsonify(err[0]), err[1]
    denied = api_require_roles(user, "staff")
    if denied:
        return jsonify(denied[0]), denied[1]
    today = datetime.date.today().isoformat()
    rows = get_db().execute(
        "SELECT b.*, u.name AS uname FROM bookings b JOIN users u ON u.id=b.user_id"
        " WHERE b.booking_date=? ORDER BY b.time_slot", (today,)).fetchall()
    anns = get_db().execute(
        "SELECT * FROM announcements ORDER BY created_at DESC LIMIT 3").fetchall()
    return jsonify({"today": [api_booking_dict(r) for r in rows],
                    "announcements": [dict(r) for r in anns]})


# --------------------------------------------------------------------------

init_db()

if __name__ == "__main__":
    app.run(debug=True)
