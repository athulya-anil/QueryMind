# utils.py
import sqlite3
import pandas as pd
import random
import string
from IPython.display import display, HTML

def create_transactions_db(db_path='products.db'):
    """Create a sample SQLite DB with randomized product transactions."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("DROP TABLE IF EXISTS transactions;")
    cur.execute("""
        CREATE TABLE transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER,
            product_name TEXT,
            brand TEXT,
            category TEXT,
            color TEXT,
            action TEXT,
            qty_delta INTEGER,
            unit_price REAL,
            notes TEXT,
            ts DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    """)

    brands = ['Acme', 'Bolt', 'Nova', 'Zen', 'Aero']
    colors = ['red', 'blue', 'green', 'white', 'black']
    actions = ['insert', 'restock', 'sale', 'price_update']

    for _ in range(500):
        product_id = random.randint(1, 50)
        product_name = ''.join(random.choices(string.ascii_uppercase, k=5))
        brand = random.choice(brands)
        category = random.choice(['shoes', 'jackets', 'bikes', 'helmets'])
        color = random.choice(colors)
        action = random.choice(actions)
        qty_delta = random.randint(1, 20)
        if action == 'sale':
            qty_delta *= -1
        unit_price = round(random.uniform(10, 500), 2) if action != 'restock' else None
        cur.execute("""
            INSERT INTO transactions (product_id, product_name, brand, category, color, action, qty_delta, unit_price)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (product_id, product_name, brand, category, color, action, qty_delta, unit_price))

    conn.commit()
    conn.close()

def get_schema(db_path='products.db'):
    """Return schema of the transactions table."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(transactions);")
    schema = "\n".join([f"{row[1]} ({row[2]})" for row in cur.fetchall()])
    conn.close()
    return schema

def execute_sql(sql, db_path='products.db'):
    """Execute an SQL query and return a pandas DataFrame."""
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query(sql, conn)
    conn.close()
    return df

