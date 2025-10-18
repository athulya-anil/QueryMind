import re
import streamlit as st
import sqlite3, pandas as pd, json, random, datetime
from groq import Groq


# ---------------------- SETUP ----------------------
st.set_page_config(page_title="QueryMind", page_icon="🧠", layout="wide")
st.title("🧠 QueryMind: Self-Reflecting AI SQL Agent")
st.caption("AI agent that writes and self-corrects SQL queries using reflection 🪞")

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
            color TEXT,
            release_date DATE,
            region TEXT,
            customer_segment TEXT,
            store_type TEXT,
            qty_sold INTEGER,
            unit_price REAL,
            revenue REAL,
            notes TEXT,
            ts DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # base product info
    products = [
        (101, "iPhone 15 Pro", "Phone", 999),
        (201, "AirPods Pro", "Earbuds", 249),
        (301, "MacBook Air M3", "Laptop", 1299),
        (501, "Apple Watch Series 10", "Watch", 399),
    ]
    regions = ["North", "South", "East", "West"]
    colors = ["Silver", "Space Black", "Blue Titanium", "Starlight", "Midnight", "Red"]
    segments = ["Student", "Business", "Regular"]
    store_types = ["Online", "Physical"]

    product_releases = {
        "iPhone 15 Pro": "2023-09-22",
        "AirPods Pro": "2022-10-15",
        "MacBook Air M3": "2024-03-05",
        "Apple Watch Series 10": "2024-09-20",
    }

    for _ in range(250):
        pid, name, category, base_price = random.choice(products)
        region = random.choice(regions)
        color = random.choice(colors)
        release_date = product_releases[name]
        customer_segment = random.choice(segments)
        store_type = random.choice(store_types)

        # Randomly simulate refunds
        if random.random() < 0.3:
            qty_sold = -random.randint(1, 10)
            note = "refund"
        else:
            qty_sold = random.randint(1, 20)
            note = "sale"

        unit_price = round(base_price * random.uniform(0.9, 1.1), 2)
        revenue = qty_sold * unit_price
        ts = datetime.datetime.now() - datetime.timedelta(days=random.randint(0, 90))

        cur.execute("""
            INSERT INTO transactions (
                product_id, product_name, category, color, release_date,
                region, customer_segment, store_type, qty_sold,
                unit_price, revenue, notes, ts
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (pid, name, category, color, release_date, region,
              customer_segment, store_type, qty_sold, unit_price, revenue, note, ts))

    conn.commit()
    conn.close()
    return "✅ Apple Store DB ready (with colors, release dates, and customer segments)."


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
    """Reflect on SQL execution results and correct issues."""
    # --- 1️⃣ Handle numeric anomalies ---
    has_negative = any(
        df_feedback[col].dtype.kind in "if" and (df_feedback[col] < 0).any()
        for col in df_feedback.columns
    )
    if has_negative:
        fixed_sql = re.sub(r"SUM\(([^)]+)\)", r"SUM(ABS(\1))", sql_query, flags=re.IGNORECASE)
        feedback = "Detected negative totals from refunds → added ABS() around SUM() for correction."
        return feedback, fixed_sql

    # --- 2️⃣ Handle semantic mismatches ---
    reflection_prompt = f"""
    You are a SQL reasoning agent. Analyze whether the SQL query logically answers the user's question
    given the table schema.

    Question: {question}
    SQL: {sql_query}
    Schema:
    {schema}

    If the question refers to something not present in the schema (e.g. color, size, store rating, etc.),
    return JSON:
    {{
      "feedback": "what's missing or misaligned",
      "refined_sql": "NULL"
    }}
    Otherwise, if the SQL looks fine, return:
    {{
      "feedback": "No semantic issues detected.",
      "refined_sql": "{sql_query}"
    }}
    """
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": reflection_prompt}],
            temperature=0,
        )
        result = json.loads(resp.choices[0].message.content)
        feedback = result.get("feedback", "Semantic reflection complete.")
        refined_sql = result.get("refined_sql", sql_query)
        return feedback, refined_sql
    except Exception as e:
        return f"Semantic reflection failed: {e}", sql_query


# ---------------------- APP LOGIC ----------------------
st.subheader("🗨️ Ask a question about Apple Store data")
user_question = st.text_input("Example: Which product generated the highest total revenue?")

if user_question:
    # Extract schema dynamically
    conn = sqlite3.connect("apple_store.db")
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(transactions);")
    schema = "\n".join([f"{row[1]} ({row[2]})" for row in cur.fetchall()])
    conn.close()

    # --- SQL Generation ---
    with st.spinner("🧠 Generating SQL..."):
        sql_v1 = generate_sql(user_question, schema)
        sql_v1 = sql_v1.replace("table", "transactions")
    st.code(sql_v1, language="sql")

    # --- Execute Initial SQL ---
    try:
        df_v1 = execute_sql(sql_v1)
        st.write("📊 **V1 Output (Before Reflection)**")
        st.dataframe(df_v1, use_container_width=True, hide_index=True)
    except Exception as e:
        st.error(f"SQL Execution Error: {e}")
        df_v1 = pd.DataFrame()

    # --- Reflection Phase ---
    if not df_v1.empty:
        feedback, sql_v2 = refine_sql_with_feedback(user_question, sql_v1, df_v1, schema)
        st.info(f"🪞 Reflection Feedback: {feedback}")
        st.code(sql_v2, language="sql")

        # Execute corrected SQL
        try:
            df_v2 = execute_sql(sql_v2)
            st.success("✅ Corrected Output (After Reflection)")
            st.dataframe(df_v2, use_container_width=True, hide_index=True)
        except Exception as e:
            st.error(f"Execution Error after Reflection: {e}")
