import sys, os
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from groq import Groq
import pandas as pd
import re
from reflection_engine import ReflectionEngine
import streamlit as st
import sqlite3

# ---------------------- SETUP ----------------------
st.set_page_config(page_title="QueryMind | Your CSV", page_icon="🐣", layout="wide")
st.title("🐣 QueryMind: Self-Reflecting AI SQL Agent")
st.caption("Upload a CSV → auto-generate SQL → reflect → auto-correct")

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

# Initialize Groq client 
client = Groq(api_key=st.secrets["GROQ_API_KEY"])

# Point engine to this app's DB; table set after upload
reflector = ReflectionEngine(client, db_path="user_data.db", table_name="user_upload")

# ---------------------- UTILITIES ----------------------
@st.cache_data(ttl=600)  # Cache for 10 minutes
def execute_sql(sql: str, db_path: str = "user_data.db"):
    """Execute SQL query with caching"""
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query(sql, conn)
    conn.close()
    return df

def clean_sql(sql):
    return sql.replace("```sql", "").replace("```", "").strip()

# ---------------------- AGENT LOGIC ----------------------
@st.cache_data(ttl=3600)  # Cache for 1 hour
def generate_sql(question: str, schema: str, table_name: str, model: str = "llama-3.3-70b-versatile") -> str:
    """Generate SQL from natural language with caching"""
    prompt = f"""
You are a SQL assistant. Given the schema and user question, write a valid SQLite query.
Use table name '{table_name}'. Respond with SQL only. If the question contains a name or text, use LIKE '%text%' for partial matching instead of exact '='. Always ensure column names match those in the schema exactly.

Schema:
{schema}

Question:
{question}

Respond with the SQL query only, no explanations.
"""
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    return clean_sql(response.choices[0].message.content.strip())

# ---------------------- CACHE CSV UPLOAD ----------------------
@st.cache_data
def load_csv(file):
    df = pd.read_csv(file)
    df.columns = [re.sub(r'\W+', '_', c.strip()) for c in df.columns]
    return df

# ====================== FIXED SIDEBAR START ======================
with st.sidebar:
    st.header("Upload Your Dataset")
    st.caption("Your data is processed securely within this session and is never shared or stored permanently.")

    # Uploader
    uploaded_file = st.file_uploader("Upload a CSV file", type=["csv"])

    # Single-line status 
    status_line = st.empty()

    # Dataset overview section with placeholders
    with st.expander("Dataset Overview", expanded=False):
        schema_placeholder = st.empty()
        preview_placeholder = st.empty()

    # info sections 
    with st.expander("About Data Reflection", expanded=False):
        st.markdown("""
**How it works**  
1) Generate SQL from your question → 2) Run it → 3) Reflect on results → 4) Auto-correct and re-run.

If results are empty due to unavailable values or dates, the engine returns **NULL** with an explanation instead of hallucinating fixes.
""")
    with st.expander("Tips for better questions", expanded=False):
        st.markdown("""
- Use exact column names (shown in *Dataset Overview*).
- For partial text matches, say things like *name contains 'john'*.
- Add filters only if your data actually has those columns (e.g., date).
""")

# Fill the placeholders without changing the widget tree
df_user = None
table_name = "user_upload"

if uploaded_file is None:
    status_line.info("Please upload a CSV file to begin querying your dataset.")
    # keep placeholders empty; stop main pane until a file is uploaded
    st.stop()
else:
    try:
        df_user = load_csv(uploaded_file)
        status_line.write(f"**Loaded**: {len(df_user)} rows, {len(df_user.columns)} columns")

        # Compact column types; avoid auto-resizing banners
        dtypes_text = "\n".join([f"- {c}: {t}" for c, t in zip(df_user.columns, df_user.dtypes)])
        schema_placeholder.markdown("**Column Types:**\n" + dtypes_text)

        # Fixed-height preview to prevent jumping
        preview_placeholder.dataframe(df_user.head(5), hide_index=True, height=160)

        # Save CSV into temporary SQLite DB
        conn = sqlite3.connect("user_data.db")
        df_user.to_sql(table_name, conn, if_exists="replace", index=False)
        conn.close()

        # Inform the engine which table to introspect for values/dates
        reflector.set_table(table_name)

    except Exception as e:
        status_line.write(f"**Error reading file:** {e}")
        st.stop()
# ====================== SIDEBAR END ======================

# ---------------------- USER INPUT ----------------------
st.subheader("Ask a question about your dataset")

# Create two columns for layout
col1, col2 = st.columns([8, 1], vertical_alignment="center")

with col1:
    user_question = st.text_input(
        "Ask any question about your dataset",
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
    # Extract schema dynamically based on source
    try:
        conn = sqlite3.connect("user_data.db")
        cur = conn.cursor()
        cur.execute(f"PRAGMA table_info({table_name});")
        schema = "\n".join([f"{row[1]} ({row[2]})" for row in cur.fetchall()])
        conn.close()
    except Exception as e:
        st.error("Could not read your uploaded CSV file. Please check its format and try again.")
        st.stop()

    # Generate SQL 
    with st.spinner("Generating SQL..."):
        sql_v1 = generate_sql(user_question, schema, table_name)
        sql_v1 = re.sub(r"\btable\b", table_name, sql_v1, flags=re.IGNORECASE)
    st.code(sql_v1, language="sql")

    # Execute SQL V1
    try:
        df_v1 = execute_sql(sql_v1, db_path="user_data.db")
        st.write("**Initial Output (Before Reflection)**")
        st.dataframe(df_v1, hide_index=True)
    except Exception as e:
        st.error(f"SQL Execution Error: {e}")
        df_v1 = pd.DataFrame()
        
    # Reflect regardless of emptiness or errors
    with st.spinner("Reflecting and improving query..."):
        reflection_data = reflector.reflect(user_question, sql_v1, df_v1, schema)

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
    
    # Explanation bubble
    if explanation:
        st.markdown(f"""
        <div style='background-color:#f1f3f4;border-radius:8px;padding:12px 16px;border-left:4px solid #00C851;margin-top:16px;margin-bottom:24px;'>
        <div style='font-weight:600;color:#333;margin-bottom:8px;'>🐣 QueryMind:</div>
        <div style='color:#555;line-height:1.6;'>{explanation}</div>
        </div>
        """, unsafe_allow_html=True)

    # Handle invalid or missing-field queries
    if refined_sql.strip().upper() == "NULL":
        st.error("Query cannot be executed - likely a data availability or missing-field issue.")
        st.stop()
    else:
        try:
            df_v2 = execute_sql(refined_sql, db_path="user_data.db")
            st.success("Corrected Output (After Reflection)")
            st.dataframe(df_v2, hide_index=True)

            # Before/After Comparison if data changed
            if not df_v1.empty and not df_v2.empty and not df_v1.equals(df_v2):
                with st.expander("Before/After Comparison"):
                    col_b, col_a = st.columns(2)
                    with col_b:
                        st.markdown("**Before Reflection:**")
                        st.dataframe(df_v1, hide_index=True)
                    with col_a:
                        st.markdown("**After Reflection:**")
                        st.dataframe(df_v2, hide_index=True)
        except Exception as e:
            st.error(f"Execution Error after Reflection: {str(e)}")
            st.warning("The refined query could not be executed. This might indicate a data availability issue rather than a query problem.")

# ---------------------- CACHE STATS (DEV MODE) ----------------------
with st.sidebar.expander("Cache Statistics"):
    cache_stats = reflector.get_cache_stats()
    st.write("**Reflection Engine Cache:**")
    st.json(cache_stats)
    if st.button("Clear All Caches", use_container_width=True, type="primary"):
        reflector.clear_cache()
        st.cache_data.clear()
        st.success("All caches cleared!")
        st.rerun()
