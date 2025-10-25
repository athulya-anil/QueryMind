from groq import Groq
import re
from reflection_engine import ReflectionEngine
import streamlit as st
import sqlite3, pandas as pd, json, random, datetime

# ---------------------- SETUP ----------------------
st.set_page_config(page_title="Demo | QueryMind", page_icon="🐣", layout="wide")
st.title("🐣 QueryMind: Self-Reflecting AI SQL Agent")
st.caption("AI agent that writes and self-corrects SQL queries using reflection")

# ---------------------- FOOTER ----------------------
st.markdown("""
<style>
.custom-footer {
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    text-align: center;
    background-color: #f8f9fa;
    border-top: 1px solid #e6e6e6;
    padding: 10px;
    font-size: 0.9rem;
    color: #555;
    z-index: 1000;
    opacity: 0.97;
    backdrop-filter: blur(5px);
}
</style>

<div class="custom-footer">
Built by <b>Athulya Anil</b> • Powered by <b>Groq</b> + <b>Streamlit</b> • QueryMind © 2025
</div>
""", unsafe_allow_html=True)        

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

    # Force a large refund for MacBook to ensure negative total revenue
    # This demonstrates the reflection engine's ability to detect and fix negative revenue issues
    cur.execute("""
        INSERT INTO transactions (product_id, product_name, category, region, qty_sold, unit_price, revenue, notes, ts)
        VALUES (301, 'MacBook Air M3', 'Laptop', 'North', -100, 1300, -130000, 'refund', CURRENT_TIMESTAMP)
    """)
    
    # Force another refund for testing reflection
    cur.execute("""
        INSERT INTO transactions (product_id, product_name, category, region, qty_sold, unit_price, revenue, notes, ts)
        VALUES (201, 'AirPods Pro', 'Earbuds', 'North', -50, 250, -12500, 'refund', CURRENT_TIMESTAMP)
    """)
    conn.commit()
    conn.close()
    return "Apple Store DB ready!"


msg = create_apple_store_db()
st.sidebar.success(msg)

# ---------------------- SIDEBAR SECTIONS ----------------------
# About Data Reflection
with st.sidebar.expander("About QueryMind"):
    st.markdown("""
    ### What is QueryMind?
    
    QueryMind uses **agentic AI reflection** to:
    
    1. **Analyze** your SQL query output
    2. **Detect** anomalies (negatives, nulls, missing data)
    3. **Suggest** corrections based on actual results
    4. **Explain** what was fixed and why
    
    This mirrors how a data analyst would review and improve their own queries!
    
    ### How It Works:
    - **Stage 1:** Generate SQL from your question
    - **Stage 2:** Execute and analyze the output data
    - **Stage 3:** LLM reflects on results
    - **Stage 4:** Auto-correct and re-execute
    
    Inspired by Andrew Ng's **Agentic AI** course.
    """)

# Helper
with st.sidebar.expander("Try These Questions"):
    st.markdown("""
    ### Sample Questions to Test:
    
    - Which product generated the highest total revenue? *(tests base SQL generation + aggregation correctness)*
    - What's the total revenue by region? *(checks group-by logic + region coverage anomaly detection)*
    - Which product was the best seller in October 2025? *(tests time-based filtering + date-range validation)*
    - Which product was most popular in New York? *(tests anti-hallucination logic + empty-data reasoning)*
    - List the top 3 products by revenue. *(verifies ranking, sorting, and reflection stability/caching)*

    """)
# Cache Statistics
with st.sidebar.expander("Cache Statistics"):
    cache_stats = reflector.get_cache_stats()
    
    st.markdown("### Reflection Engine Cache")
    
    # Visual metrics
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Total Items", cache_stats['total_cached_items'])
    with col2:
        cache_efficiency = "High" if cache_stats['total_cached_items'] > 5 else "Low"
        st.metric("Efficiency", cache_efficiency)
    
    # Detailed breakdown
    st.markdown("**Cache Breakdown:**")
    st.json({
        "Reflection Cache": cache_stats['reflection_cache_size'],
        "Semantic Cache": cache_stats['semantic_cache_size'],
        "Explanation Cache": cache_stats['explanation_cache_size']
    })
    
    if st.button("Clear All Caches", use_container_width=True, type="primary"):
        reflector.clear_cache()
        st.cache_data.clear()
        st.success("All caches cleared!")
        st.rerun()

# Developer Stats
with st.sidebar.expander("Developer Stats"):
    st.write("**Raw Cache Data:**")
    st.json(reflector.get_cache_stats())

# ---------------------- UTILITIES ----------------------
@st.cache_data(ttl=600)  # Cache for 10 minutes
def execute_sql(sql: str, db_path: str = "apple_store.db"):
    """Execute SQL query with caching"""
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query(sql, conn)
    conn.close()
    return df


def clean_sql(sql):
    return sql.replace("```sql", "").replace("```", "").strip()


# ---------------------- AGENT LOGIC ----------------------
@st.cache_data(ttl=3600)  # Cache for 1 hour
def generate_sql(question: str, schema: str, model: str = "llama-3.3-70b-versatile") -> str:
    """Generate SQL from natural language with caching - using temperature=0 for deterministic output"""
    prompt = f"""
    You are a SQL assistant. Given the schema and user question, write a valid SQLite query.
    Use table name 'transactions'. Respond with SQL only. If the question contains a name or text, use LIKE '%text%' for partial matching instead of exact '='. Always ensure column names match those in the schema exactly.

    Schema:
    {schema}

    Question:
    {question}

    Respond with the SQL query only, no explanations.
    """
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,  # Deterministic generation
    )
    sql = clean_sql(response.choices[0].message.content.strip())
    
    # DEMO HACK: Force V1 to use plain SUM(revenue) for demo purposes
    # This intentionally creates negative totals when refunds exist,
    # demonstrating the reflection engine's auto-fix capability
    if "revenue" in question.lower() or "total" in question.lower():
        sql = re.sub(r"SUM\(ABS\(revenue\)\)", "SUM(revenue)", sql, flags=re.IGNORECASE)
        sql = re.sub(r"ABS\(revenue\)", "revenue", sql, flags=re.IGNORECASE)
    
    return sql

# ---------------------- USER INPUT ----------------------
st.subheader("Ask any question about Apple Store data")

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

# button  
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

st.markdown("""
<style>
/* Remove "Press Enter to apply" text */
div[data-testid="InputInstructions"] {
    display: none !important;
}

/* Alternative: if the above doesn't work, try this */
.stTextInput > div > div > input + div {
    display: none !important;
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

    # Execute SQL V1 and run reflection
    try:
        df_v1 = execute_sql(sql_v1)
        st.write("**Initial Output (Before Reflection)**")
        st.dataframe(df_v1, hide_index=True)
        
        # Run reflection regardless of whether df is empty or not
        with st.spinner("Reflecting and improving query..."):
            reflection_data = reflector.reflect(user_question, sql_v1, df_v1, schema)
    except Exception as e:
        st.error(f"SQL Execution Error: {e}")
        st.stop()
    
    # Extract reflection results
    issues = reflection_data.get("issues", [])
    feedback = reflection_data.get("feedback", "")
    refined_sql = reflection_data.get("refined_sql", sql_v1)
    explanation = reflection_data.get("explanation", "")

    # ---------------------- Display Reflection ----------------------
    st.subheader("Reflection Results")

    # Show refined SQL first
    st.code(refined_sql, language="sql")
    
    # SQL comparison if changed
    if sql_v1.strip() != refined_sql.strip() and refined_sql.strip().upper() != "NULL":
        with st.expander("View SQL Changes"):
            col_before, col_after = st.columns(2)
            with col_before:
                st.markdown("**Before:**")
                st.code(sql_v1, language="sql")
            with col_after:
                st.markdown("**After:**")
                st.code(refined_sql, language="sql")
    
    # Show explanation in a clean bubble
    if explanation:
        st.markdown(f"""
        <div style='background-color:#f1f3f4;border-radius:8px;padding:12px 16px;border-left:4px solid #00C851;margin-top:16px;margin-bottom:24px;'>
        <div style='font-weight:600;color:#333;margin-bottom:8px;'>🐣 QueryMind:</div>
        <div style='color:#555;line-height:1.6;'>{explanation}</div>
        </div>
        """, unsafe_allow_html=True)

    # Handle invalid or missing-field queries
    if refined_sql.strip().upper() == "NULL":
        st.error("Query cannot be executed - missing required fields in schema")
        st.stop()
    else:
        try:
            df_v2 = execute_sql(refined_sql)
            st.success("Corrected Output (After Reflection)")
            st.dataframe(df_v2, hide_index=True)
            
            # Before/After Comparison if data changed
            if not df_v1.equals(df_v2) and len(df_v1) > 0 and len(df_v2) > 0:
                with st.expander("Before/After Comparison"):
                    col_before, col_after = st.columns(2)
                    with col_before:
                        st.markdown("**Before Reflection:**")
                        st.dataframe(df_v1, hide_index=True)
                    with col_after:
                        st.markdown("**After Reflection:**")
                        st.dataframe(df_v2, hide_index=True)
        except Exception as e:
            st.error(f"Execution Error after Reflection: {str(e)}")
            st.warning("The refined query could not be executed. This might indicate a data availability issue rather than a query problem.")