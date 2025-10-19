import sys, os
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from groq import Groq
import pandas as pd
import re
from reflection_engine import ReflectionEngine
import streamlit as st
import sqlite3

# ---------------------- SETUP ----------------------
st.set_page_config(page_title="QueryMind", page_icon="🐣", layout="wide")
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

# ---------------------- USER UPLOAD ----------------------
st.sidebar.header("Upload Your Dataset")
st.sidebar.caption("Your data stays local and is never uploaded to the cloud.")

uploaded_file = st.sidebar.file_uploader("Upload a CSV file", type=["csv"])
if not uploaded_file:
    st.sidebar.error("Please upload a CSV file to begin querying your dataset.")
    st.stop()

if uploaded_file:
    try:
        df_user = load_csv(uploaded_file)
        st.sidebar.success(f"Loaded {len(df_user)} rows, {len(df_user.columns)} columns")

        with st.sidebar.expander("Dataset Overview"):
            st.write("**Column Types:**")
            st.write(df_user.dtypes)
            st.write("**Sample Rows:**")
            st.dataframe(df_user.head(5))

        # Save CSV into temporary SQLite DB
        conn = sqlite3.connect("user_data.db")
        table_name = "user_upload"
        df_user.to_sql(table_name, conn, if_exists="replace", index=False)
        conn.close()

    except Exception as e:
        st.sidebar.error(f"Error reading your file: {e}")
        st.stop()

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
    if not uploaded_file:
        st.error("No dataset uploaded. Please upload a valid CSV file to continue.")
        st.stop()
    try:
        conn = sqlite3.connect("user_data.db")
        cur = conn.cursor()
        cur.execute(f"PRAGMA table_info({table_name});")
        schema = "\n".join([f"{row[1]} ({row[2]})" for row in cur.fetchall()])
        conn.close()
    except Exception as e:
        st.error("Could not read your uploaded CSV file. Please check its format and try again.")
        st.stop()

    # Generate SQL (now cached)
    with st.spinner("Generating SQL..."):
        sql_v1 = generate_sql(user_question, schema, table_name)
        sql_v1 = sql_v1.replace("table", table_name)
    st.code(sql_v1, language="sql")

    # Execute SQL V1 (now cached)
    try:
        df_v1 = execute_sql(sql_v1, db_path="user_data.db")
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
                df_v2 = execute_sql(refined_sql, db_path="user_data.db")
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