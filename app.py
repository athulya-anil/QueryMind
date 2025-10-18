# app.py
import streamlit as st
import sqlite3, pandas as pd, json, random, datetime
from groq import Groq

# ---------------------- SETUP ----------------------
st.set_page_config(page_title="QueryMind", page_icon="🧠", layout="wide")
st.title("🧠 QueryMind: Self-Reflecting AI SQL Agent")
st.caption("Built by Athulya Anil — An AI that writes and self-corrects SQL queries using reflection 💡")

# Initialize Groq client (use st.secrets for deployment)
client = Groq(api_key=st.secrets["GROQ_API_KEY"])

# ---------------------- DATABASE CREATION ----------------------
@st.cache_data
def create_apple_store_db(db_path="apple_store.db"):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("DROP TABLE IF EXISTS transactions;")
    cur.execute("""
        CREATE TABLE transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER,
            product_name TEXT,
            category TEXT,
            region TEXT,
            qty_sold INTEGER,
            unit_price REAL,
            revenue REAL,
            notes TEXT,
            ts DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    """)

    products = [
        (101, "iPhone 15 Pro", "Phone", 999),
        (201, "AirPods Pro", "Earbuds", 249),
        (301, "MacBook Air M3", "Laptop", 1299),
        (501, "Apple Watch Series 10", "Watch", 399),
    ]
    regions = ["North", "South", "East", "West"]

    for _ in range(100):
        pid, name, category, base_price = random.choice(products)
        region = random.choice(regions)
        if random.random() < 0.5:
            qty_sold = -random.randint(3, 15)
            note = "refund"
        else:
            qty_sold = random.randint(1, 10)
            note = "sale"
        unit_price = round(base_price * random.uniform(0.9, 1.1), 2)
        revenue = qty_sold * unit_price
        ts = datetime.datetime.now() - datetime.timedelta(days=random.randint(0, 60))
        cur.execute("""
            INSERT INTO transactions (product_id, product_name, category, region, qty_sold, unit_price, revenue, notes, ts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (pid, name, category, region, qty_sold, unit_price, revenue, note, ts))

    conn.commit()
    conn.close()
    return "✅ Apple Store DB ready (with negative refunds)."

msg = create_apple_store_db()
st.sidebar.success(msg)

# ---------------------- UTILITIES ----------------------
def execute_sql(sql, db_path="apple_store.db"):
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query(sql, conn)
    conn.close()
    return df

def clean_sql(sql):
    return sql.replace("```sql", "").replace("```", "").strip()

# ---------------------- AGENT LOGIC ----------------------
def generate_sql(question: str, schema: str, model="llama-3.3-70b-versatile") -> str:
    prompt = f"""
    You are a SQL assistant. Given the schema and user question, write a valid SQLite query.
    Use table name 'transactions'. Respond with SQL only.

    Schema:
    {schema}

    Question:
    {question}
    """
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    return clean_sql(response.choices[0].message.content.strip())

def refine_sql_with_feedback(question, sql_query, df_feedback, schema, model="llama-3.3-70b-versatile"):
    """Detect negatives → auto-fix with ABS()"""
    import re
    has_negative = any(
        df_feedback[col].dtype.kind in "if" and (df_feedback[col] < 0).any()
        for col in df_feedback.columns
    )
    if has_negative:
        fixed_sql = re.sub(r"SUM\(([^)]+)\)", r"SUM(ABS(\1))", sql_query, flags=re.IGNORECASE)
        feedback = "Detected negative totals → added ABS() around SUM() for correction."
        return feedback, fixed_sql
    return "No numeric issues detected.", sql_query

# ---------------------- APP LOGIC ----------------------
st.subheader("🗨️ Ask a question about Apple Store data")
user_question = st.text_input("Example: Which product generated the highest total revenue?")

if user_question:
    # Extract schema
    conn = sqlite3.connect("apple_store.db")
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(transactions);")
    schema = "\n".join([f"{row[1]} ({row[2]})" for row in cur.fetchall()])
    conn.close()

    # Generate SQL
    with st.spinner("🧠 Generating SQL..."):
        sql_v1 = generate_sql(user_question, schema)
        sql_v1 = sql_v1.replace("table", "transactions")
    st.code(sql_v1, language="sql")

    # Execute SQL V1
    try:
        df_v1 = execute_sql(sql_v1)
        st.write("📊 **V1 Output (Before Reflection)**")
        st.dataframe(df_v1)
    except Exception as e:
        st.error(f"SQL Execution Error: {e}")
        df_v1 = pd.DataFrame()

    # Reflection & Correction
    if not df_v1.empty:
        feedback, sql_v2 = refine_sql_with_feedback(user_question, sql_v1, df_v1, schema)
        st.info(f"🪞 Reflection Feedback: {feedback}")
        st.code(sql_v2, language="sql")

        try:
            df_v2 = execute_sql(sql_v2)
            st.success("✅ Corrected Output (After Reflection)")
            st.dataframe(df_v2)
        except Exception as e:
            st.error(f"Execution Error after Reflection: {e}")

