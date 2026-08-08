import os
import json
import sqlite3
import hashlib
import datetime
import secrets

from flask import (Flask, request, g, jsonify)

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
            credit_balance REAL DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS canteens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            location TEXT NOT NULL,
            open_time TEXT DEFAULT '09:00',
            close_time TEXT DEFAULT '17:00',
            active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS menu_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            description TEXT DEFAULT '',
            price REAL NOT NULL,
            own_cup_price REAL DEFAULT NULL,
            available INTEGER DEFAULT 1,
            image TEXT DEFAULT '🍽️',
            photo TEXT DEFAULT '',
            canteen_id INTEGER DEFAULT 1,
            prep_time INTEGER DEFAULT 15,
            daily_quantity INTEGER DEFAULT 0,
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
            canteen_id INTEGER DEFAULT 1,
            customer_name TEXT DEFAULT '',
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
            photo TEXT DEFAULT '',
            booking_id INTEGER DEFAULT NULL,
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

        CREATE TABLE IF NOT EXISTS offers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            canteen_id INTEGER DEFAULT 1,
            title TEXT NOT NULL,
            body TEXT DEFAULT '',
            discount_pct INTEGER DEFAULT 0,
            menu_item_id INTEGER DEFAULT NULL,
            start_date TEXT DEFAULT '',
            end_date TEXT DEFAULT '',
            active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS credits_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            type TEXT NOT NULL,
            booking_id INTEGER DEFAULT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            booking_id INTEGER DEFAULT NULL,
            read INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT DEFAULT '',
            updated_at TEXT DEFAULT (datetime('now'))
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
    ensure_column("users", "credit_balance", "credit_balance REAL DEFAULT 0")
    ensure_column("menu_items", "canteen_id", "canteen_id INTEGER DEFAULT 1")
    ensure_column("menu_items", "prep_time", "prep_time INTEGER DEFAULT 15")
    ensure_column("menu_items", "daily_quantity", "daily_quantity INTEGER DEFAULT 0")
    ensure_column("menu_items", "own_cup_price", "own_cup_price REAL DEFAULT NULL")
    ensure_column("menu_items", "ingredients", "ingredients TEXT DEFAULT ''")
    ensure_column("bookings", "canteen_id", "canteen_id INTEGER DEFAULT 1")
    ensure_column("bookings", "customer_name", "customer_name TEXT DEFAULT ''")
    ensure_column("feedback", "photo", "photo TEXT DEFAULT ''")
    ensure_column("feedback", "booking_id", "booking_id INTEGER DEFAULT NULL")

    # --- Seed default canteens ---
    if cur.execute("SELECT COUNT(*) FROM canteens").fetchone()[0] == 0:
        cur.execute("INSERT INTO canteens (name, location, open_time, close_time) VALUES (?,?,?,?)",
                    ("Ground Floor", "Main Building", "09:00", "17:00"))
        cur.execute("INSERT INTO canteens (name, location, open_time, close_time) VALUES (?,?,?,?)",
                    ("B1 Canteen", "Basement 1", "09:00", "17:00"))

    # --- Seed default settings ---
    if cur.execute("SELECT COUNT(*) FROM settings").fetchone()[0] == 0:
        cur.execute("INSERT INTO settings (key, value) VALUES (?,?)",
                    ("points_per_npr", "1"))
        cur.execute("INSERT INTO settings (key, value) VALUES (?,?)",
                    ("points_value_npr", "1"))

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

    # Add demo credits to student account
    cur.execute("UPDATE users SET credit_balance = 500 WHERE email = 'student@ingcollege.edu.np'")
    cur.execute("INSERT INTO credits_transactions (user_id, amount, type) VALUES (?, ?, ?)",
                (3, 500, "topup_esewa"))

    # Backfill uids for any remaining users (e.g. registered before uid existed)
    for u in cur.execute("SELECT * FROM users WHERE uid=''").fetchall():
        cur.execute("UPDATE users SET uid=? WHERE id=?",
                    ("ING-{}-{:03d}".format(u["role"][:3].upper(), u["id"]), u["id"]))

    # Sample bookings with different customer names for demo
    if cur.execute("SELECT COUNT(*) FROM bookings").fetchone()[0] == 0:
        today = datetime.date.today().isoformat()
        yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        sample_bookings = [
            (3, today, '12:00 PM', '2 x French Fries, 1 x Popcorn Chicken', '[{"id":1,"name":"French Fries","image":"🍟","qty":2,"price":160},{"id":4,"name":"Popcorn Chicken","image":"🍗","qty":1,"price":170}]', 490, 'completed', 'paid', 'Bibek Tamang'),
            (3, today, '12:30 PM', '1 x Chicken Chilli, 1 x Chicken Rice', '[{"id":8,"name":"Chicken Chilli","image":"🍗","qty":1,"price":240},{"id":20,"name":"Chicken Rice","image":"🍚","qty":1,"price":165}]', 405, 'confirmed', 'paid', 'Rohan K.'),
            (3, today, '1:00 PM', '2 x Steam Mo:Mo (Chicken)', '[{"id":15,"name":"Steam Mo:Mo (Chicken)","image":"🥟","qty":2,"price":150}]', 300, 'pending', 'paid', 'Priya S.'),
            (3, today, '1:30 PM', '1 x Plain Popcorn (Large), 2 x Coca-Cola', '[{"id":30,"name":"Plain Popcorn (Large)","image":"🍿","qty":1,"price":90},{"id":37,"name":"Coca-Cola","image":"🥤","qty":2,"price":80}]', 250, 'pending', 'paid', 'Anjali T.'),
            (3, yesterday, '11:00 AM', '1 x Bolognese (Chicken), 1 x Cappuccino', '[{"id":12,"name":"Bolognese (Chicken)","image":"🍝","qty":1,"price":270},{"id":39,"name":"Cappuccino","image":"☕","qty":1,"price":150}]', 420, 'completed', 'paid', 'Sujan M.'),
            (3, yesterday, '2:00 PM', '1 x C Mo:Mo (Veg), 1 x Chips Chilli', '[{"id":22,"name":"C Mo:Mo (Veg)","image":"🥟","qty":1,"price":135},{"id":3,"name":"Chips Chilli","image":"🌶️","qty":1,"price":180}]', 315, 'cancelled', 'paid', 'Nisha A.'),
        ]
        for booking in sample_bookings:
            user_id, date, slot, summary, items_json, total, status, payment, customer_name = booking
            cur.execute(
                "INSERT INTO bookings (user_id, booking_date, time_slot, item_summary, items_json, total, status, payment_status, canteen_id, customer_name) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (user_id, date, slot, summary, items_json, total, status, payment, 1, customer_name))
            booking_id = cur.lastrowid
            txn_ref = "KB-" + secrets.token_hex(3).upper()
            cur.execute(
                "INSERT INTO transactions (txn_ref, user_id, booking_id, amount, method, status) VALUES (?,?,?,?,?,?)",
                (txn_ref, user_id, booking_id, total, 'esewa', 'success'))

        # Sample notifications (marked as read so they don't show as unread)
        cur.execute("INSERT INTO notifications (user_id, title, body, booking_id, read) VALUES (?,?,?,?,?)",
                    (3, "Order Ready! 🎉", "Your order KB-0001 is ready for pickup!", 1, 1))
        cur.execute("INSERT INTO notifications (user_id, title, body, booking_id, read) VALUES (?,?,?,?,?)",
                    (3, "Order Confirmed", "Your order KB-0002 has been confirmed.", 2, 1))

        # Sample offers (time-bound: start_date=today, end_date=tomorrow)
        tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
        if cur.execute("SELECT COUNT(*) FROM offers").fetchone()[0] == 0:
            cur.execute("INSERT INTO offers (title, body, discount_pct, menu_item_id, start_date, end_date, active) VALUES (?,?,?,?,?,?,?)",
                        ("Mo:Mo Monday", "All Mo:Mo varieties at 15% off!", 15, 15, today, tomorrow, 1))
            cur.execute("INSERT INTO offers (title, body, discount_pct, menu_item_id, start_date, end_date, active) VALUES (?,?,?,?,?,?,?)",
                        ("Happy Hour", "Buy 1 Get 1 Free on beverages!", 50, 37, today, tomorrow, 1))
            cur.execute("INSERT INTO offers (title, body, discount_pct, menu_item_id, start_date, end_date, active) VALUES (?,?,?,?,?,?,?)",
                        ("Weekend Pasta Deal", "All pasta at 20% off!", 20, 12, today, tomorrow, 1))

    # Sample feedback (demo reviews from students) — standalone so it seeds even if bookings exist
    if cur.execute("SELECT COUNT(*) FROM feedback").fetchone()[0] == 0:
        import datetime as _dt
        now = _dt.datetime.now()
        def fb_dt(hours_ago):
            return (now - _dt.timedelta(hours=hours_ago)).strftime("%Y-%m-%d %H:%M:%S")
        demo_feedback = [
            (3, 5, "Steam Mo:Mo were absolutely delicious — hot, juicy and fresh! The wait was short too.", 0, "responded", "Thank you! Glad you loved the Mo:Mo — we steam them in fresh batches every hour. 😊", fb_dt(2)),
            (3, 4, "Chicken rice bowl is great value for money. Portion could be slightly bigger for the price.", 0, "responded", "Noted! We've increased the portion size from this week. Enjoy!", fb_dt(5)),
            (3, 3, "Popcorn was a bit soggy today. It got cold by the time I reached the counter.", 0, "read", "", fb_dt(8)),
            (3, 2, "Found a strand of hair in my fries. Please check the kitchen gloves policy.", 1, "new", "", fb_dt(26)),
            (3, 5, "Love the own-cup discount! Cheaper drinks AND less plastic. Great initiative 🥤🌱", 0, "read", "", fb_dt(30)),
            (3, 1, "Queue was very long during lunch break and one item was sold out after waiting 10 minutes.", 0, "new", "", fb_dt(49)),
            (3, 4, "Cappuccino was perfect — better than the café outside campus!", 0, "read", "", fb_dt(52)),
            (3, 5, "The combo deal (Mo:Mo + drink) is such a steal. Will be my go-to every Monday!", 0, "new", "", fb_dt(74)),
        ]
        for uid, rating, comment, hygiene, status, response, created_at in demo_feedback:
            cur.execute(
                "INSERT INTO feedback (user_id, rating, comment, hygiene_issue, status, response, created_at) VALUES (?,?,?,?,?,?,?)",
                (uid, rating, comment, hygiene, status, response, created_at))

    if cur.execute("SELECT COUNT(*) FROM menu_items").fetchone()[0] == 0:
        # Full menu: (name, category, description, price, image, photo, canteen_id, prep_time, own_cup_price)
        menu = [
            # === GROUND FLOOR CANTEEN (canteen_id=1) ===
            # Light Bites - Vegetarian
            ("French Fries", "Light Bites", "Crispy golden fries with seasoning", 160, "🍟", "", 1, 10, None),
            ("ING Special Aloo", "Light Bites", "Signature spiced potato fry", 120, "🥔", "", 1, 10, None),
            ("Chips Chilli", "Light Bites", "Potato chips tossed in chilli sauce", 180, "🌶️", "", 1, 10, None),
            # Light Bites - Non-Vegetarian
            ("Popcorn Chicken", "Light Bites", "Bite-sized crispy chicken pieces", 170, "🍗", "", 1, 12, None),
            ("Chicken Sausage", "Light Bites", "Grilled chicken sausage", 60, "🌭", "", 1, 8, None),
            ("Chicken Chilli", "Light Bites", "Indo-Chinese chilli chicken", 240, "🍗", "", 1, 15, None),
            ("Sausage Chilli", "Light Bites", "Sausages tossed in chilli sauce", 225, "🌭", "", 1, 15, None),
            # Light Bites - Pasta
            ("Bolognese (Chicken)", "Light Bites", "Rich chicken meat sauce pasta", 270, "🍝", "", 1, 18, None),
            ("Alfredo (Creamy Chicken)", "Light Bites", "Creamy white sauce with chicken", 270, "🍝", "", 1, 18, None),
            ("Alfredo (Creamy Veg)", "Light Bites", "Creamy white sauce vegetarian pasta", 270, "🍝", "", 1, 15, None),
            ("Arrabiatta (Spicy Veg)", "Light Bites", "Spicy tomato sauce pasta", 210, "🍝", "", 1, 15, None),
            # Mains - Rice & Noodles
            ("Veg Rice", "Mains", "Steamed rice with vegetable stir-fry", 120, "🍚", "", 1, 12, None),
            ("Egg Rice", "Mains", "Egg fried rice with vegetables", 135, "🍳", "", 1, 12, None),
            ("Chicken Rice", "Mains", "Chicken fried rice with vegetables", 165, "🍗", "", 1, 15, None),
            ("Mixed Rice", "Mains", "Mixed fried rice with egg & chicken", 195, "🍚", "", 1, 18, None),
            ("Popcorn Chicken Rice Bowl", "Mains", "Crispy chicken over seasoned rice", 210, "🍗", "", 1, 18, None),
            ("ING Rice Bowl", "Mains", "Signature rice bowl special", 175, "🍚", "", 1, 15, None),
            # Mains - Combo Meals
            ("Non Veg Premium", "Mains", "Full non-veg meal with sides", 275, "🍱", "", 1, 20, None),
            ("Non Veg Regular", "Mains", "Regular non-veg meal", 220, "🍱", "", 1, 18, None),
            ("Veg Premium", "Mains", "Full veg meal with sides", 250, "🍱", "", 1, 18, None),
            ("Veg Regular", "Mains", "Regular veg meal", 190, "🍱", "", 1, 15, None),
            # Mains - Add Ons
            ("Chicken Add-on", "Add Ons", "Extra chicken serving", 100, "🍗", "", 1, 8, None),
            ("Egg Add-on", "Add Ons", "Extra fried egg", 50, "🍳", "", 1, 5, None),
            ("Cheese Add-on", "Add Ons", "Extra cheese topping", 60, "🧀", "", 1, 3, None),
            # MO:MO
            ("Steam Mo:Mo (Veg)", "MO:MO", "Steamed veg dumplings with achar", 100, "🥟", "", 1, 12, None),
            ("Steam Mo:Mo (Chicken)", "MO:MO", "Steamed chicken dumplings with achar", 150, "🥟", "", 1, 15, None),
            ("Steam Mo:Mo (Buff)", "MO:MO", "Steamed buff dumplings with achar", 140, "🥟", "", 1, 15, None),
            ("Kothey Mo:Mo (Veg)", "MO:MO", "Pan-fried veg dumplings", 110, "🥟", "", 1, 12, None),
            ("Kothey Mo:Mo (Chicken)", "MO:MO", "Pan-fried chicken dumplings", 160, "🥟", "", 1, 15, None),
            ("Kothey Mo:Mo (Buff)", "MO:MO", "Pan-fried buff dumplings", 150, "🥟", "", 1, 15, None),
            ("Fried Mo:Mo (Veg)", "MO:MO", "Deep-fried crispy veg dumplings", 120, "🥟", "", 1, 12, None),
            ("Fried Mo:Mo (Chicken)", "MO:MO", "Deep-fried crispy chicken dumplings", 170, "🥟", "", 1, 15, None),
            ("Fried Mo:Mo (Buff)", "MO:MO", "Deep-fried crispy buff dumplings", 160, "🥟", "", 1, 15, None),
            ("Jhol Mo:Mo (Veg)", "MO:MO", "Veg dumplings in spicy broth", 120, "🥟", "", 1, 12, None),
            ("Jhol Mo:Mo (Chicken)", "MO:MO", "Chicken dumplings in spicy broth", 170, "🥟", "", 1, 15, None),
            ("Jhol Mo:Mo (Buff)", "MO:MO", "Buff dumplings in spicy broth", 160, "🥟", "", 1, 15, None),
            ("C Mo:Mo (Veg)", "MO:MO", "Chilli veg dumplings", 135, "🥟", "", 1, 12, None),
            ("C Mo:Mo (Chicken)", "MO:MO", "Chilli chicken dumplings", 185, "🥟", "", 1, 15, None),
            ("C Mo:Mo (Buff)", "MO:MO", "Chilli buff dumplings", 165, "🥟", "", 1, 15, None),
            ("Fried Chilli Mo:Mo (Veg)", "MO:MO", "Fried chilli veg dumplings", 135, "🥟", "", 1, 12, None),
            ("Fried Chilli Mo:Mo (Chicken)", "MO:MO", "Fried chilli chicken dumplings", 185, "🥟", "", 1, 15, None),
            ("Fried Chilli Mo:Mo (Buff)", "MO:MO", "Fried chilli buff dumplings", 165, "🥟", "", 1, 15, None),
            # Combos
            ("Mo:Mo + Drink Combo", "Combos", "Steam Mo:Mo (Chicken) + beverage of choice", 199, "🥟🥤", "", 1, 15, None),
            ("Rice Bowl Combo", "Combos", "Chicken fried rice + egg + pickle", 175, "🍚", "", 1, 18, None),
            ("Pasta Special Combo", "Combos", "Bolognese pasta + garlic bread", 299, "🍝", "", 1, 20, None),
            ("Snack Pack Combo", "Combos", "French fries + popcorn chicken + drink", 250, "🍟", "", 1, 15, None),
            ("Veg Thali Combo", "Combos", "Dal bhat + seasonal veg + pickle + papad", 180, "🍱", "", 1, 20, None),
            ("Chicken Thali Combo", "Combos", "Chicken curry + rice + dal + pickle", 220, "🍱", "", 1, 20, None),
            # Sides & Extras
            ("Garlic Bread", "Sides", "Toasted garlic butter bread", 85, "🍞", "", 1, 5, None),
            ("Seasonal Veg Curry", "Sides", "Fresh seasonal vegetable curry", 90, "🥦", "", 1, 10, None),
            ("Achaar (Pickle)", "Sides", "Traditional Nepali spicy pickle", 25, "🥒", "", 1, 0, None),
            ("Papad", "Sides", "Crispy roasted papad", 20, "🫓", "", 1, 2, None),
            ("Dal (Lentil Soup)", "Sides", "Traditional dal tadka", 60, "🍲", "", 1, 8, None),
            ("Chicken Curry", "Sides", "Spicy chicken curry", 150, "🍗", "", 1, 15, None),
            ("Extra Rice", "Sides", "Steamed basmati rice", 40, "🍚", "", 1, 5, None),
            ("Extra Egg", "Sides", "Fried egg", 30, "🍳", "", 1, 5, None),
            # Popcorn Menu
            ("Plain Popcorn (Small)", "Popcorn", "Lightly salted popcorn", 55, "🍿", "", 1, 5, None),
            ("Plain Popcorn (Large)", "Popcorn", "Lightly salted popcorn large", 90, "🍿", "", 1, 5, None),
            ("Cheese Popcorn (Small)", "Popcorn", "Cheese flavored popcorn", 100, "🍿", "", 1, 5, None),
            ("Cheese Popcorn (Large)", "Popcorn", "Cheese flavored popcorn large", 150, "🍿", "", 1, 5, None),
            # Beverages
            ("Masala Tea", "Beverages", "Traditional Nepali spiced milk tea", 40, "☕", "", 1, 5, None),
            ("Black Tea", "Beverages", "Classic black tea", 40, "☕", "", 1, 3, 25),
            ("Espresso", "Beverages", "Single shot espresso", 105, "☕", "", 1, 5, 90),
            ("Americano", "Beverages", "Espresso with hot water", 110, "☕", "", 1, 5, 95),
            ("Cappuccino", "Beverages", "Espresso with steamed milk foam", 150, "☕", "", 1, 7, 135),
            ("Cafe Latte", "Beverages", "Espresso with steamed milk", 150, "☕", "", 1, 7, 135),
            ("Caramel Latte", "Beverages", "Latte with caramel syrup", 180, "☕", "", 1, 7, 165),
            ("Cafe Mocha", "Beverages", "Chocolate espresso drink", 210, "☕", "", 1, 7, 195),
            ("Hot Chocolate", "Beverages", "Rich hot chocolate", 150, "☕", "", 1, 5, 135),
            ("Mocha Madness", "Beverages", "Ultimate chocolate coffee", 280, "☕", "", 1, 8, 265),
            ("Coca-Cola", "Beverages", "Classic cola, chilled 500ml", 80, "🥤", "", 1, 2, None),
            ("Fanta Orange", "Beverages", "Orange fizz, chilled 500ml", 80, "🧡", "", 1, 2, None),
            ("Sprite", "Beverages", "Lemon-lime soda, chilled 500ml", 80, "💛", "", 1, 2, None),
            ("Thumbs Up", "Beverages", "Indian cola, chilled 500ml", 70, "👍", "", 1, 2, None),
            ("Limca", "Beverages", "Indian lemon soda, chilled 500ml", 70, "🍋", "", 1, 2, None),
            ("Frooti", "Beverages", "Mango drink, chilled 500ml", 90, "🥭", "", 1, 2, None),
            ("Maaza", "Beverages", "Mango crush, chilled 500ml", 90, "🥭", "", 1, 2, None),
            ("Fruit Salad", "Healthy", "Fresh seasonal fruits with yogurt", 90, "🥗", "", 1, 5, None),

            # === B1 CANTEEN (canteen_id=2) ===
            # Bakery
            ("Veg Patty", "Bakery", "Spiced potato patty in pastry", 125, "🥐", "", 2, 5, None),
            ("Chicken Patty", "Bakery", "Chicken filled patty", 130, "🥐", "", 2, 5, None),
            ("Chocolate Danish", "Bakery", "Flaky danish with chocolate", 120, "🍫", "", 2, 3, None),
            ("Chocolate Donut", "Bakery", "Chocolate glazed donut", 55, "🍩", "", 2, 2, None),
            ("Cream Donut", "Bakery", "Cream filled donut", 55, "🍩", "", 2, 2, None),
            ("Chocolate Muffin", "Bakery", "Rich chocolate muffin", 65, "🧁", "", 2, 2, None),
            ("Vanilla Muffin", "Bakery", "Classic vanilla muffin", 65, "🧁", "", 2, 2, None),
            # B1 Light Bites
            ("Veg Sandwich", "Light Bites", "Grilled veg sandwich", 55, "🥪", "", 2, 5, None),
            ("Paneer Roll", "Light Bites", "Paneer wrap with spices", 175, "🌯", "", 2, 8, None),
            ("Spicy Veg Burger", "Light Bites", "Veg patty burger with cheese", 230, "🍔", "", 2, 10, None),
            ("Spicy Chicken Burger", "Light Bites", "Crispy chicken burger with cheese", 250, "🍔", "", 2, 12, None),
            ("Chicken Sandwich", "Light Bites", "Grilled chicken sandwich", 100, "🥪", "", 2, 8, None),
            ("Chicken Roll", "Light Bites", "Chicken wrap with spices", 190, "🌯", "", 2, 8, None),
            # B1 Beverages (with BYO cup pricing)
            ("Lemon Iced Tea", "Beverages", "Refreshing lemon iced tea", 90, "🧋", "", 2, 3, 75),
            ("Peach Iced Tea", "Beverages", "Peach flavored iced tea", 180, "🧋", "", 2, 3, 165),
            ("Lemonade", "Beverages", "Fresh lemonade", 160, "🍋", "", 2, 3, 145),
            ("Watermelon Juice", "Beverages", "Fresh watermelon juice", 100, "🍉", "", 2, 3, 85),
            ("Virgin Mojito", "Beverages", "Mint lime mocktail", 180, "🍹", "", 2, 3, 165),
            ("Iced Americano", "Beverages", "Chilled americano", 120, "☕", "", 2, 3, 105),
            ("Iced Cappuccino", "Beverages", "Chilled cappuccino", 160, "☕", "", 2, 3, 145),
            ("Iced Latte", "Beverages", "Chilled cafe latte", 160, "☕", "", 2, 3, 145),
            ("Iced Caramel Latte", "Beverages", "Chilled caramel latte", 190, "☕", "", 2, 3, 175),
            ("Iced Mocha", "Beverages", "Chilled chocolate mocha", 220, "☕", "", 2, 3, 205),
            ("CoolRouni Kulfi", "Beverages", "Traditional kulfi ice cream", 80, "🍦", "", 2, 2, None),
            # B1 Specials
            ("Pakistani Chicken Biryani", "Mains", "Aromatic Pakistani style biryani", 195, "🍛", "", 2, 20, None),
            ("Chicken Khana Set", "Mains", "Complete chicken meal with sides", 220, "🍱", "", 2, 20, None),
            ("Veg Khana Set", "Mains", "Complete veg meal with sides", 150, "🍱", "", 2, 18, None),
        ]
        cur.executemany(
            "INSERT INTO menu_items (name, category, description, price, image, photo, canteen_id, prep_time, own_cup_price) VALUES (?,?,?,?,?,?,?,?,?)",
            menu,
        )

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
            "credit_balance": u["credit_balance"] if "credit_balance" in u.keys() else 0,
            "created_at": u["created_at"]}


def api_item_dict(i):
    return {"id": i["id"], "name": i["name"], "category": i["category"],
            "description": i["description"], "price": i["price"],
            "own_cup_price": i["own_cup_price"] if "own_cup_price" in i.keys() else None,
            "available": bool(i["available"]), "image": i["image"],
            "photo": i["photo"],
            "canteen_id": i["canteen_id"] if "canteen_id" in i.keys() else 1,
            "prep_time": i["prep_time"] if "prep_time" in i.keys() else 15,
            "daily_quantity": i["daily_quantity"] if "daily_quantity" in i.keys() else 0,
            "ingredients": i["ingredients"] if "ingredients" in i.keys() else ""}


CANCEL_LEAD_MINUTES = 30


def booking_cancel_deadline(b):
    """Cancellation deadline = 30 minutes before the booked time slot, which is
    also the point where food preparation begins. Booking date/time is stored
    in local 12-hour format; it is shifted to UTC so the deadline can be
    compared against created_at (UTC)."""
    try:
        raw = "{} {}".format(b["booking_date"], b["time_slot"])
        try:
            bt_local = datetime.datetime.strptime(raw, "%Y-%m-%d %I:%M %p")
        except ValueError:
            bt_local = datetime.datetime.strptime(raw, "%Y-%m-%d %H:%M")
        offset = datetime.datetime.now().astimezone().utcoffset()
        bt_utc = bt_local - offset
        return bt_utc - datetime.timedelta(minutes=CANCEL_LEAD_MINUTES)
    except (ValueError, KeyError, TypeError):
        return None


def booking_cancellable(b):
    """A pre-order may be cancelled only up to 30 minutes before the booked
    time, i.e. before the kitchen starts preparing the meal."""
    if b["status"] not in ("pending", "confirmed"):
        return False
    deadline = booking_cancel_deadline(b)
    if deadline is None:
        return False
    return datetime.datetime.utcnow() < deadline


def api_booking_dict(b):
    db = get_db()
    deadline = booking_cancel_deadline(b)
    # Live queue position: pending orders ahead of this one at the same canteen & date
    prep_time = 0
    try:
        import json as _json
        lines = _json.loads(b["items_json"]) if b["items_json"] else []
        item_ids = [l.get("id") for l in lines if l.get("id")]
        if item_ids:
            marks = ",".join("?" * len(item_ids))
            rows = db.execute(f"SELECT id, prep_time FROM menu_items WHERE id IN ({marks})", item_ids).fetchall()
            preps = {r["id"]: r["prep_time"] or 15 for r in rows}
            for l in lines:
                prep_time += (preps.get(l.get("id"), 15) or 15) * (l.get("qty") or 1)
    except Exception:
        prep_time = 15
    queue_wait = 0
    if b["status"] in ("pending", "confirmed"):
        ahead = db.execute(
            "SELECT COUNT(*) c FROM bookings WHERE booking_date=? AND canteen_id=?"
            " AND status IN ('pending','confirmed') AND id <= ?",
            (b["booking_date"], b["canteen_id"] if "canteen_id" in b.keys() else 1, b["id"])).fetchone()["c"]
        queue_wait = max(ahead, 1) * 15
    return {"id": b["id"], "user_id": b["user_id"],
            "booking_date": b["booking_date"], "time_slot": b["time_slot"],
            "item_summary": b["item_summary"], "total": b["total"],
            "status": b["status"], "payment_status": b["payment_status"],
            "created_at": b["created_at"],
            "items_json": b["items_json"],
            "canteen_id": b["canteen_id"] if "canteen_id" in b.keys() else 1,
            "customer_name": b["customer_name"] if "customer_name" in b.keys() else "",
            "uname": b["uname"] if "uname" in b.keys() else None,
            "uemail": b["uemail"] if "uemail" in b.keys() else None,
            "queue_wait": queue_wait, "prep_time": prep_time,
            "total_time": queue_wait + prep_time,
            "cancellable": booking_cancellable(b),
            "cancel_by": deadline.strftime("%Y-%m-%d %H:%M:%S") if deadline else None}


def api_feedback_dict(f):
    return {"id": f["id"], "user_id": f["user_id"],
            "uname": f["uname"] if "uname" in f.keys() else None,
            "rating": f["rating"], "comment": f["comment"],
            "hygiene_issue": bool(f["hygiene_issue"]), "status": f["status"],
            "response": f["response"], "photo": f["photo"] if "photo" in f.keys() else "",
            "booking_id": f["booking_id"] if "booking_id" in f.keys() else None,
            "created_at": f["created_at"]}


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
    canteen_id = request.args.get("canteen_id", 0, type=int)
    if canteen_id:
        rows = get_db().execute(
            "SELECT * FROM menu_items WHERE canteen_id=? ORDER BY category, name", (canteen_id,)).fetchall()
    else:
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
    canteen_id = data.get("canteen_id", 1)
    use_own_cup = data.get("use_own_cup", False)
    redeem_points = data.get("redeem_points", 0)
    customer_name = (data.get("customer_name") or "").strip() or user["name"]

    if method == "cash":
        return jsonify({"error": "Cash is not accepted. Please choose a prepaid method."}), 400
    if not items or not booking_date or not time_slot:
        return jsonify({"error": "Please select items, date and time slot"}), 400
    try:
        cart = []
        excludes = []
        for i in items:
            cart.append((int(i["id"]), int(i["qty"])))
            excludes.append([str(x).strip() for x in (i.get("exclude") or [])
                             if str(x).strip()])
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "Invalid cart contents"}), 400
    if not cart:
        return jsonify({"error": "Your cart is empty"}), 400

    db = get_db()
    summary_parts, line_items, total = [], [], 0.0
    total_prep_time = 0
    for idx, (item_id, qty) in enumerate(cart):
        row = db.execute("SELECT * FROM menu_items WHERE id=?", (item_id,)).fetchone()
        if not row or not row["available"]:
            return jsonify({"error": "An item in your cart is no longer available"}), 409
        item_price = row["price"]
        if use_own_cup and row.get("own_cup_price") is not None:
            item_price = row["own_cup_price"]
        total += item_price * qty
        total_prep_time = max(total_prep_time, row["prep_time"] if "prep_time" in row.keys() else 15)
        excluded = excludes[idx] if idx < len(excludes) else []
        note = " (no {})".format(", ".join(excluded)) if excluded else ""
        summary_parts.append("{} x {}{}".format(qty, row["name"], note))
        line = {"id": row["id"], "name": row["name"],
                "image": row["image"], "qty": qty, "price": item_price}
        if excluded:
            line["exclude"] = excluded
        line_items.append(line)
    item_summary = ", ".join(summary_parts)

    if method in ("card", "esewa", "khalti"):
        if not payment_name or not payment_detail:
            return jsonify({"error": "Please fill in your payment details"}), 400
        payment_status = "paid"
    else:
        payment_status = "unpaid"

    # Credits payment (use credits balance to pay)
    credits_discount = 0
    use_credits = data.get("use_credits", 0) or data.get("useWallet", 0)
    if use_credits and float(use_credits) > 0:
        user_credits = user["credit_balance"] if "credit_balance" in user.keys() else 0
        credits_discount = min(float(use_credits), user_credits)
        credits_discount = min(credits_discount, total)  # Can't exceed total
        total = max(0, total - credits_discount)

    txn_ref = "KB-" + secrets.token_hex(3).upper()
    cur = db.execute(
        "INSERT INTO bookings (user_id, booking_date, time_slot, item_summary, items_json, total, status, payment_status, canteen_id, customer_name)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        (user["id"], booking_date, time_slot, item_summary,
         json.dumps(line_items), total, "pending", payment_status, canteen_id, customer_name))
    booking_id = cur.lastrowid
    db.execute(
        "INSERT INTO transactions (txn_ref, user_id, booking_id, amount, method, status) VALUES (?,?,?,?,?,?)",
        (txn_ref, user["id"], booking_id, total, method,
         "success" if payment_status == "paid" else "pending"))

    # Deduct credits balance if used
    if credits_discount > 0:
        db.execute("UPDATE users SET credit_balance = credit_balance - ? WHERE id=?", (credits_discount, user["id"]))
        db.execute("INSERT INTO credits_transactions (user_id, amount, type, booking_id) VALUES (?,?,?,?)",
                   (user["id"], -credits_discount, "spend", booking_id))

    # Queue estimation: count pending orders for today at same canteen
    today = datetime.date.today().isoformat()
    pending_count = db.execute(
        "SELECT COUNT(*) c FROM bookings WHERE booking_date=? AND canteen_id=? AND status='pending'",
        (today, canteen_id)).fetchone()["c"]
    queue_wait_minutes = pending_count * 15  # avg 15 min per order

    db.commit()
    return jsonify({"booking_id": booking_id, "txn_ref": txn_ref,
                    "total": total, "payment_status": payment_status,
                    "credits_used": credits_discount,
                    "credit_balance": (user["credit_balance"] if "credit_balance" in user.keys() else 0) - credits_discount,
                    "prep_time": total_prep_time, "queue_wait": queue_wait_minutes})


@app.route("/api/bookings")
def api_bookings():
    user, err = api_require_user()
    if err:
        return jsonify(err[0]), err[1]
    rows = get_db().execute(
        "SELECT b.*, u.name AS uname, u.email AS uemail FROM bookings b"
        " JOIN users u ON u.id=b.user_id WHERE b.user_id=?"
        " ORDER BY CASE b.status WHEN 'pending' THEN 0 WHEN 'confirmed' THEN 1"
        " WHEN 'completed' THEN 2 ELSE 3 END, b.booking_date DESC, b.created_at DESC", (user["id"],)).fetchall()
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
    if not booking_cancellable(booking):
        return jsonify({
            "error": ("Orders can be cancelled free up to {} minutes before "
                      "the booked time — food preparation has started, so this "
                      "booking can no longer be cancelled or modified."
                      ).format(CANCEL_LEAD_MINUTES)
        }), 400
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
        photo = (data.get("photo") or "").strip()
        booking_id = data.get("booking_id") or None
        if not 1 <= rating <= 5:
            return jsonify({"error": "Rating must be 1–5"}), 400
        if not comment:
            return jsonify({"error": "Please write a short comment"}), 400
        db.execute(
            "INSERT INTO feedback (user_id, rating, comment, hygiene_issue, photo, booking_id) VALUES (?,?,?,?,?,?)",
            (user["id"], rating, comment, hygiene, photo, booking_id))
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
        if user["role"] not in ("admin",):
            return jsonify({"error": "Only admins can change their name. Please contact the canteen admin."}), 403
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
        " JOIN users u ON u.id=b.user_id"
        " ORDER BY CASE b.status WHEN 'pending' THEN 0 WHEN 'confirmed' THEN 1"
        " WHEN 'completed' THEN 2 ELSE 3 END, b.booking_date DESC, b.created_at DESC").fetchall()
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
    db = get_db()
    booking = db.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
    if not booking:
        return jsonify({"error": "Booking not found"}), 404
    db.execute("UPDATE bookings SET status=? WHERE id=?", (status, booking_id))
    # Create notification for status change
    ref = f"KB-{booking_id:04d}"
    notif_title = ""
    notif_body = ""
    if status == "confirmed":
        notif_title = "Order Confirmed"
        notif_body = f"Your order {ref} has been confirmed and is being prepared."
    elif status == "completed":
        notif_title = "Order Ready! 🎉"
        notif_body = f"Your order {ref} is ready for pickup!"
    elif status == "cancelled":
        notif_title = "Order Cancelled"
        notif_body = f"Your order {ref} has been cancelled."
    if notif_title:
        create_notification(booking["user_id"], notif_title, notif_body, booking_id)
    db.commit()
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
        own_cup_price = data.get("own_cup_price") or None
        canteen_id = data.get("canteen_id", 1)
        prep_time = data.get("prep_time", 15)
        daily_quantity = data.get("daily_quantity", 0)
        ingredients = (data.get("ingredients") or "").strip()
        if not name or not category or not price or price <= 0:
            return jsonify({"error": "Name, category and a valid NPR price are required"}), 400
        db.execute(
            "INSERT INTO menu_items (name, category, description, price, image, photo, canteen_id, prep_time, daily_quantity, own_cup_price, ingredients) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (name, category, description, price, image, photo, canteen_id, prep_time, daily_quantity, own_cup_price, ingredients))
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
    photo = (data.get("photo") or "").strip()
    own_cup_price = data.get("own_cup_price") or None
    prep_time = data.get("prep_time", 15)
    daily_quantity = data.get("daily_quantity", 0)
    ingredients = (data.get("ingredients") or "").strip()
    if not name or not category or not price or price <= 0:
        return jsonify({"error": "Name, category and a valid NPR price are required"}), 400
    get_db().execute(
        "UPDATE menu_items SET name=?, category=?, description=?, price=?, image=?, photo=?, own_cup_price=?, prep_time=?, daily_quantity=?, ingredients=? WHERE id=?",
        (name, category, description, price, image, photo, own_cup_price, prep_time, daily_quantity, ingredients, item_id))
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


@app.route("/api/admin/feedback/<int:fb_id>/review", methods=["POST"])
def api_admin_feedback_review(fb_id):
    user, err = api_require_user()
    if err:
        return jsonify(err[0]), err[1]
    denied = api_require_roles(user, "admin", "staff")
    if denied:
        return jsonify(denied[0]), denied[1]
    get_db().execute("UPDATE feedback SET status='read' WHERE id=?", (fb_id,))
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


@app.route("/api/admin/users/<int:user_id>/credits", methods=["POST"])
def api_admin_user_credits(user_id):
    user, err = api_require_user()
    if err:
        return jsonify(err[0]), err[1]
    denied = api_require_roles(user, "admin")
    if denied:
        return jsonify(denied[0]), denied[1]
    data = request.get_json(silent=True) or {}
    amount = data.get("amount", 0)
    if amount == 0:
        return jsonify({"error": "Amount must not be 0"}), 400
    db = get_db()
    target = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not target:
        return jsonify({"error": "User not found"}), 404
    if target["id"] == user["id"]:
        return jsonify({"error": "You cannot adjust your own balance here"}), 400
    db.execute("UPDATE users SET credit_balance = credit_balance + ? WHERE id=?",
               (amount, user_id))
    txn_type = "admin_topup" if amount > 0 else "admin_deduct"
    db.execute(
        "INSERT INTO credits_transactions (user_id, amount, type, booking_id) VALUES (?,?,?,?)",
        (user_id, abs(amount), txn_type, None))
    db.commit()
    new_balance = db.execute(
        "SELECT credit_balance FROM users WHERE id=?", (user_id,)).fetchone()["credit_balance"]
    return jsonify({"ok": True, "balance": new_balance})


@app.route("/api/admin/users/<int:user_id>/role", methods=["POST"])
def api_admin_user_role(user_id):
    user, err = api_require_user()
    if err:
        return jsonify(err[0]), err[1]
    denied = api_require_roles(user, "admin")
    if denied:
        return jsonify(denied[0]), denied[1]
    data = request.get_json(silent=True) or {}
    role = data.get("role", "")
    if role not in ("admin", "staff", "customer"):
        return jsonify({"error": "Invalid role"}), 400
    if user_id == user["id"]:
        return jsonify({"error": "You cannot change your own role"}), 400
    db = get_db()
    if not db.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone():
        return jsonify({"error": "User not found"}), 404
    db.execute("UPDATE users SET role=? WHERE id=?", (role, user_id))
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/admin/users/<int:user_id>/name", methods=["POST"])
def api_admin_user_name(user_id):
    user, err = api_require_user()
    if err:
        return jsonify(err[0]), err[1]
    denied = api_require_roles(user, "admin")
    if denied:
        return jsonify(denied[0]), denied[1]
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Name cannot be empty"}), 400
    db = get_db()
    if not db.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone():
        return jsonify({"error": "User not found"}), 404
    db.execute("UPDATE users SET name=? WHERE id=?", (name, user_id))
    db.commit()
    return jsonify({"ok": True})


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
        " WHERE b.booking_date=?"
        " ORDER BY CASE b.status WHEN 'pending' THEN 0 WHEN 'confirmed' THEN 1"
        " WHEN 'completed' THEN 2 ELSE 3 END, b.time_slot, b.id", (today,)).fetchall()
    anns = get_db().execute(
        "SELECT * FROM announcements ORDER BY created_at DESC LIMIT 3").fetchall()
    return jsonify({"today": [api_booking_dict(r) for r in rows],
                    "announcements": [dict(r) for r in anns]})


# --------------------------------------------------------------------------
# New API endpoints for multi-canteen, offers, points, settings
# --------------------------------------------------------------------------

@app.route("/api/canteens")
def api_canteens():
    rows = get_db().execute("SELECT * FROM canteens WHERE active=1 ORDER BY id").fetchall()
    return jsonify({"canteens": [dict(r) for r in rows]})


@app.route("/api/categories")
def api_categories():
    rows = get_db().execute("SELECT DISTINCT category FROM menu_items ORDER BY category").fetchall()
    return jsonify({"categories": [r["category"] for r in rows]})


@app.route("/api/offers")
def api_offers():
    today = datetime.date.today().isoformat()
    rows = get_db().execute(
        "SELECT * FROM offers WHERE active=1 AND (start_date='' OR start_date<=?) AND (end_date='' OR end_date>=?) ORDER BY discount_pct DESC",
        (today, today)).fetchall()
    return jsonify({"offers": [dict(r) for r in rows]})


@app.route("/api/settings/hours", methods=["GET", "POST"])
def api_settings_hours():
    db = get_db()
    if request.method == "POST":
        user, err = api_require_user()
        if err:
            return jsonify(err[0]), err[1]
        denied = api_require_roles(user, "admin", "staff")
        if denied:
            return jsonify(denied[0]), denied[1]
        data = request.get_json(silent=True) or {}
        canteen_id = data.get("canteen_id", 1)
        open_time = data.get("open_time", "09:00")
        close_time = data.get("close_time", "17:00")
        db.execute("UPDATE canteens SET open_time=?, close_time=? WHERE id=?", (open_time, close_time, canteen_id))
        db.commit()
        return jsonify({"ok": True})
    canteen_id = request.args.get("canteen_id", 1, type=int)
    row = db.execute("SELECT * FROM canteens WHERE id=?", (canteen_id,)).fetchone()
    if not row:
        return jsonify({"error": "Canteen not found"}), 404
    return jsonify({"open_time": row["open_time"], "close_time": row["close_time"]})


@app.route("/api/admin/offers", methods=["GET", "POST"])
def api_admin_offers():
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
        discount_pct = data.get("discount_pct", 0)
        menu_item_id = data.get("menu_item_id") or None
        canteen_id = data.get("canteen_id", 1)
        start_date = data.get("start_date", "")
        end_date = data.get("end_date", "")
        if not title:
            return jsonify({"error": "Title is required"}), 400
        db.execute(
            "INSERT INTO offers (title, body, discount_pct, menu_item_id, canteen_id, start_date, end_date) VALUES (?,?,?,?,?,?,?)",
            (title, body, discount_pct, menu_item_id, canteen_id, start_date, end_date))
        db.commit()
        return jsonify({"ok": True})
    rows = db.execute("SELECT * FROM offers ORDER BY created_at DESC").fetchall()
    return jsonify({"offers": [dict(r) for r in rows]})


@app.route("/api/admin/offers/<int:offer_id>", methods=["PUT", "DELETE"])
def api_admin_offer_detail(offer_id):
    user, err = api_require_user()
    if err:
        return jsonify(err[0]), err[1]
    denied = api_require_roles(user, "admin")
    if denied:
        return jsonify(denied[0]), denied[1]
    db = get_db()
    if request.method == "DELETE":
        db.execute("DELETE FROM offers WHERE id=?", (offer_id,))
        db.commit()
        return jsonify({"ok": True})
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    body = (data.get("body") or "").strip()
    discount_pct = data.get("discount_pct", 0)
    menu_item_id = data.get("menu_item_id") or None
    canteen_id = data.get("canteen_id", 1)
    start_date = data.get("start_date", "")
    end_date = data.get("end_date", "")
    active = data.get("active", 1)
    db.execute(
        "UPDATE offers SET title=?, body=?, discount_pct=?, menu_item_id=?, canteen_id=?, start_date=?, end_date=?, active=? WHERE id=?",
        (title, body, discount_pct, menu_item_id, canteen_id, start_date, end_date, active, offer_id))
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/admin/settings", methods=["GET", "POST"])
def api_admin_settings():
    user, err = api_require_user()
    if err:
        return jsonify(err[0]), err[1]
    denied = api_require_roles(user, "admin")
    if denied:
        return jsonify(denied[0]), denied[1]
    db = get_db()
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        for key, value in data.items():
            db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (key, str(value)))
        db.commit()
        return jsonify({"ok": True})
    rows = db.execute("SELECT * FROM settings").fetchall()
    return jsonify({r["key"]: r["value"] for r in rows})


# --------------------------------------------------------------------------
# Credits & Notifications
# --------------------------------------------------------------------------

@app.route("/api/credits", methods=["GET"])
def api_credits():
    user, err = api_require_user()
    if err:
        return jsonify(err[0]), err[1]
    db = get_db()
    rows = db.execute(
        "SELECT * FROM credits_transactions WHERE user_id=? ORDER BY created_at DESC LIMIT 20",
        (user["id"],)).fetchall()
    return jsonify({"balance": user["credit_balance"] if "credit_balance" in user.keys() else 0,
                    "history": [dict(r) for r in rows]})

@app.route("/api/admin/credits-transactions", methods=["GET"])
def api_admin_credits_transactions():
    user, err = api_require_user()
    if err:
        return jsonify(err[0]), err[1]
    denied = api_require_roles(user, "admin", "staff")
    if denied:
        return jsonify(denied[0]), denied[1]
    db = get_db()
    rows = db.execute(
        "SELECT ct.*, u.name AS uname FROM credits_transactions ct"
        " JOIN users u ON u.id=ct.user_id ORDER BY ct.created_at DESC LIMIT 50"
    ).fetchall()
    return jsonify([dict(r) for r in rows])

@app.route("/api/credits/topup", methods=["POST"])
def api_credits_topup():
    user, err = api_require_user()
    if err:
        return jsonify(err[0]), err[1]
    data = request.get_json(silent=True) or {}
    amount = data.get("amount", 0)
    method = data.get("method", "esewa")
    if not amount or amount <= 0:
        return jsonify({"error": "Amount must be greater than 0"}), 400
    if method not in ("esewa", "khalti", "banking"):
        return jsonify({"error": "Invalid payment method"}), 400
    db = get_db()
    # Add amount directly to credits balance (real money)
    db.execute("UPDATE users SET credit_balance = credit_balance + ? WHERE id=?", (amount, user["id"]))
    db.execute("INSERT INTO credits_transactions (user_id, amount, type, booking_id) VALUES (?,?,?,?)",
               (user["id"], amount, f"topup_{method}", None))
    db.commit()
    new_balance = db.execute("SELECT credit_balance FROM users WHERE id=?", (user["id"],)).fetchone()["credit_balance"]
    txn_ref = "TOPUP-" + secrets.token_hex(4).upper()
    return jsonify({"ok": True, "balance": new_balance, "txn_ref": txn_ref})
    user, err = api_require_user()
    if err:
        return jsonify(err[0]), err[1]
    db = get_db()
    rows = db.execute(
        "SELECT * FROM credits_transactions WHERE user_id=? ORDER BY created_at DESC LIMIT 20",
        (user["id"],)).fetchall()
    return jsonify({"balance": user["credit_balance"] if "credit_balance" in user.keys() else 0,
                    "history": [dict(r) for r in rows]})


@app.route("/api/notifications", methods=["GET"])
def api_notifications():
    user, err = api_require_user()
    if err:
        return jsonify(err[0]), err[1]
    db = get_db()
    rows = db.execute(
        "SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC LIMIT 20",
        (user["id"],)).fetchall()
    unread = db.execute(
        "SELECT COUNT(*) c FROM notifications WHERE user_id=? AND read=0",
        (user["id"],)).fetchone()["c"]
    return jsonify({"notifications": [dict(r) for r in rows], "unread": unread})


@app.route("/api/notifications/<int:notif_id>/read", methods=["POST"])
def api_notification_read(notif_id):
    user, err = api_require_user()
    if err:
        return jsonify(err[0]), err[1]
    db = get_db()
    db.execute("UPDATE notifications SET read=1 WHERE id=? AND user_id=?", (notif_id, user["id"]))
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/notifications/read-all", methods=["POST"])
def api_notification_read_all():
    user, err = api_require_user()
    if err:
        return jsonify(err[0]), err[1]
    db = get_db()
    db.execute("UPDATE notifications SET read=1 WHERE user_id=?", (user["id"],))
    db.commit()
    return jsonify({"ok": True})


def create_notification(user_id, title, body, booking_id=None):
    """Helper to create a notification for a user."""
    db = get_db()
    db.execute(
        "INSERT INTO notifications (user_id, title, body, booking_id) VALUES (?,?,?,?)",
        (user_id, title, body, booking_id))
    db.commit()


# --------------------------------------------------------------------------

init_db()

if __name__ == "__main__":
    # Port 5000 is used by macOS AirPlay Receiver, so default to 5001.
    # Bind 0.0.0.0 so phones on the same Wi-Fi can reach the API.
    app.run(debug=True, host="0.0.0.0",
            port=int(os.environ.get("PORT", 5001)))
