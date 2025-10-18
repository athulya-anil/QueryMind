from groq import Groq
import re
from reflection_engine import ReflectionEngine
import streamlit as st
import sqlite3, pandas as pd, json, random, datetime

# ---------------------- SETUP ----------------------
st.set_page_config(page_title="QueryMind", page_icon="🐣", layout="wide")
st.title("🐣 QueryMind: Self-Reflecting AI SQL Agent")
st.caption("AI agent that writes and self-corrects SQL queries using reflection")

# Initialize Groq client (use st.secrets for deployment)
client = Groq(api_key=st.secrets["GROQ_API_KEY"])

reflector = ReflectionEngine(client)

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

    # Force a refund for testing reflection
    cur.execute("""
        INSERT INTO transactions (product_id, product_name, category, region, qty_sold, unit_price, revenue, notes, ts)
        VALUES (201, 'AirPods Pro', 'Earbuds', 'North', -50, 250, -12500, 'refund', CURRENT_TIMESTAMP)
    """)
    conn.commit()
    conn.close()
    return "Apple Store DB ready!"


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

# ---------------------- USER INPUT ----------------------
st.subheader("Ask a question about Apple Store data")

# Keep the example visible
st.markdown("Example: Which product generated the highest total revenue?")

# Create two columns for layout
col1, col2 = st.columns([8, 1], vertical_alignment="center")

with col1:
    user_question = st.text_input(
        "Ask a question about Apple Store data",
        key="user_question",
        placeholder="Ask your question here...",
        label_visibility="collapsed"
    )

with col2:
    submit = st.button("Enter", use_container_width=True)

# button style (keeps the same green tone but aligns cleaner)
st.markdown("""
<style>
div[data-testid="stButton"] > button {
    background-color: #00C851 !important;
    color: white !important;
    font-weight: 600 !important;
    border: none !important;
    border-radius: 6px !important;
    padding: 0.55em 0 !important;
    height: 2.5em !important;
    margin-top: 0 !important; /* removes that misalignment */
    transition: 0.2s ease-in-out;
}
div[data-testid="stButton"] > button:hover {
    background-color: #007E33 !important;
}
</style>
""", unsafe_allow_html=True)

if not submit:
    st.stop()

if user_question:
    # Extract schema
    conn = sqlite3.connect("apple_store.db")
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(transactions);")
    schema = "\n".join([f"{row[1]} ({row[2]})" for row in cur.fetchall()])
    conn.close()

    # Generate SQL
    with st.spinner("Generating SQL..."):
        sql_v1 = generate_sql(user_question, schema)
        sql_v1 = sql_v1.replace("table", "transactions")
    st.code(sql_v1, language="sql")

    # Execute SQL V1
    try:
        df_v1 = execute_sql(sql_v1)
        st.write("**Initial Output (Before Reflection)**")
        st.dataframe(df_v1, hide_index=True)
    except Exception as e:
        st.error(f"SQL Execution Error: {e}")
        df_v1 = pd.DataFrame()
        
    if not df_v1.empty:
        with st.spinner("Reflecting and improving query..."):
            reflection_data = reflector.reflect(user_question, sql_v1, df_v1, schema)

        issues = reflection_data.get("issues", [])
        feedback = reflection_data.get("feedback", "")
        refined_sql = reflection_data.get("refined_sql", sql_v1)
        explanation = reflection_data.get("explanation", "")

        # ---------------------- Display Reflection ----------------------
        st.subheader("Reflection Results")

        # Show detected anomalies
        if issues and not (len(issues) == 1 and "No data-level anomalies" in issues[0]):
            st.markdown("**Detected Data Anomalies:**")
            for issue in issues:
                st.markdown(f"- {issue}")

        # Reflection feedback
        if not explanation or "Detected" not in feedback:
            st.markdown("**Reflection Feedback:**")
            st.info(feedback)

        # Show refined SQL
        st.code(refined_sql, language="sql")

        # Handle invalid or missing-field queries
        if refined_sql.strip().upper() == "NULL":
            if explanation:
                st.markdown(f"""
                <div style='background-color:#f1f3f4;border-radius:8px;padding:10px 14px;margin-top:10px;'>
                <b>QueryMind:</b> {explanation}
                </div>
                """, unsafe_allow_html=True)
            st.stop()
        else:
            try:
                df_v2 = execute_sql(refined_sql)
                st.success("Corrected Output (After Reflection)")
                st.dataframe(df_v2, hide_index=True)
            except Exception as e:
                st.error(f"Execution Error after Reflection: {e}")

        # ChatGPT-style explanation bubble (from LLM)
        if explanation:
            st.markdown(f"""
            <div style='background-color:#f1f3f4;border-radius:8px;padding:10px 14px;margin-top:10px;'>
            <b>QueryMind:</b> {explanation}
            </div>
            """, unsafe_allow_html=True)
