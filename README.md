# 🐣 QueryMind: Self-Reflecting AI SQL Agent

<img src="assets/QueryMind.gif" width="600">

**Web App:** https://querymind-ai.streamlit.app/

An intelligent SQL agent that **writes, executes, and self-corrects** database queries in real-time. Built for data analysts, business users, and anyone who needs to query databases without writing SQL.

## What It Does

### 1. **Self-Correcting Intelligence**
Unlike traditional SQL generators, QueryMind **reflects on its own output** and automatically fixes errors:

1. **Converts natural language → SQL** using Groq's LLaMA 3.3 70B
2. **Executes the query** against SQLite
3. **Reflects on the actual output data** to detect:
   - Negative totals from refunds → wraps in `ABS()`
   - Empty results → checks if filtered values actually exist in the database
   - Missing schema fields → explains what's unavailable
   - Date filters outside actual date range → flags with database statistics
   - Duplicate rows → identifies aggregation issues
   - Null-only columns → detects missing data
   - Incomplete coverage → warns about filtered regions
4. **Rewrites & re-executes** the corrected query only when there's a real logic error
5. **Explains the fix** in plain English, grounded in actual data

### 2. **Fast Performance** 
- **4-layer caching system** (reflection + semantic + explanation + column values)
- **Sub-100ms response time** for cached queries
- **10x faster** than traditional SQL generation tools
- Smart cache invalidation with TTL-based expiration

### 3. **Production-Ready**
- Multi-stage validation (rule-based + LLM semantic checks with actual data)
- Data-aware reflection that validates against real database values and date ranges
- Conservative correction logic that only suggests changes for real errors
- Fallback logic for edge cases
- Comprehensive error handling
- Cache statistics dashboard for monitoring

---

## Architecture

```
User Question (Plain English)
     ↓
Generate SQL (Groq LLaMA 3.3 70B) [CACHED]
     ↓
Execute Query v1 [CACHED]
     ↓
Reflection Engine [CACHED]
  ├─ Data Anomaly Detection (rule-based)
  │   ├─ Empty DataFrames
  │   ├─ Negative values
  │   ├─ Duplicates
  │   ├─ Null columns
  │   └─ Coverage gaps
  ├─ Semantic Validation (LLM + Actual Data)
  │   ├─ Analyzes v1 SQL output (first 3 rows)
  │   ├─ Checks filtered values against database
  │   ├─ Validates date ranges against actual min/max
  │   ├─ Intent matching
  │   └─ Schema field verification
  └─ Auto-Correction Logic
      ├─ ABS() wrapper for negatives
      ├─ NULL response for unavailable data
      └─ Data-grounded explanations
     ↓
Execute Query v2 (corrected) [CACHED]
     ↓
Plain English Explanation
```

**All stages are intelligently cached for instant repeat queries!**

**Video Demo:** https://youtu.be/pjX5gr85adc?si=bju8oNf4UZvLuqSn

---

## Example: Auto-Correction in Action

### Before Reflection:
```sql
SELECT product_name, SUM(revenue) 
FROM transactions 
GROUP BY product_name 
ORDER BY total_revenue DESC LIMIT 1;

-- Result: -$27,668.67 (AirPods Pro)
-- Problem: Negative revenue from refunds skews results
```

### After Reflection:

**QueryMind detects the issue:**
- Negative numeric values detected in actual output

**Auto-corrected SQL:**
```sql
SELECT product_name, SUM(ABS(revenue)) 
FROM transactions 
GROUP BY product_name 
ORDER BY total_revenue DESC LIMIT 1;
```

**Result:** $145,892.34 (iPhone 15 Pro) 

**Explanation:**  
*"The reflection detected negative revenue values caused by refunds. Added ABS() to calculate absolute revenue for accurate product ranking."*

---

## Data Validation Example

**You ask:** *"What were sales in New York?"*

**Generated SQL:**
```sql
SELECT * FROM transactions WHERE region = 'NY';
```

**QueryMind checks actual database:**
- Query returns empty
- Available regions: `['North', 'South', 'East', 'West']`

**QueryMind Response:**
> **No region 'NY' exists in data. Available regions: North, South, East, West.**

**Why this matters:** Prevents hallucinated SQL "fixes" when the real issue is data availability, not query syntax.

---

## Date Range Validation Example

**You ask:** *"Show sales from 2023"*

**QueryMind checks database:**
- Query returns empty
- Actual date range: `2025-09-01 to 2025-10-25`

**QueryMind Response:**
> **No data from 2023. Database only contains data from Sept-Oct 2025.**

**Why this matters:** Stops hallucinated "date format fixes" by validating against actual min/max dates in the database.

---

## Tech Stack

| Layer | Technology | Purpose |
|-------|------------|---------|
| **Frontend** | Streamlit | Interactive UI |
| **AI Model** | Groq LLaMA 3.3 70B Versatile | Natural language → SQL |
| **Database** | SQLite | Local data storage |
| **Caching** | Multi-layer in-memory + Streamlit cache | Performance optimization |
| **Language** | Python 3.11 | Core logic |

---

## Run Locally

```bash
# Clone the repository
git clone https://github.com/athulya-anil/QueryMind.git
cd QueryMind
# Create and activate a virtual environment
python -m venv venv 
source venv/bin/activate # On Windows use: venv\Scripts\activate
# Install dependencies
pip install -r requirements.txt
# Run the Streamlit app
streamlit run Demo.py
```

**Add Configure API Key:**
```toml
# .streamlit/secrets.toml
GROQ_API_KEY = "your_key_here"
```

---

## Reflection Engine Deep Dive

### Stage 1: Data Anomaly Detection (Rule-Based)

```python
def detect_output_anomalies(df: pd.DataFrame):
    # Checks for:
    - Empty DataFrames → WHERE/JOIN errors
    - Negative values → Refunds or sign errors
    - Duplicate rows → Aggregation issues
    - Null-only columns → Missing data
    - Coverage gaps → Missing regions (< 4 unique)
```

### Stage 2: Semantic Validation (LLM + Actual Data)

```python
def semantic_reflection(question, sql_query, schema, sample_output):
    # LLM analyzes actual SQL output (first 3 rows) to determine:
    - Does query match user intent?
    - Are referenced fields in schema?
    - For empty results:
      * Retrieves available values from filtered columns
      * Validates date filters against actual min/max dates
      * Returns NULL with data-grounded explanation if unavailable
    # Returns: {"feedback": "...", "refined_sql": "..."}
```

**Fallback Logic:** If LLM fails, uses regex-based field detection for terms like:
`color`, `rating`, `brand`, `model`, `size`, `version`

**Anti-Hallucination Features:**
- Lower temperature (0.3) for more accurate responses
- Validates SQL changes are meaningful, not cosmetic rewrites
- Includes actual output data in LLM prompt (as markdown)
- Retrieves available column values for empty results
- Fetches database date range statistics to validate time filters

### Stage 3: Auto-Correction

**Negative totals:**
```python
# Detects: SUM(revenue) with negative values in actual output
# Fixes:   SUM(ABS(revenue))
fixed_sql = re.sub(r"SUM\(([^)]+)\)", r"SUM(ABS(\1))", sql_query)
```

**Invalid queries:**
```python
# Returns: "NULL" + helpful explanation with actual data
# Example: "Try using 'product_name', 'category', or 'region'"
# Example: "Available regions: North, South, East, West"
# Example: "Database contains data from Sept-Oct 2025 only"
```

### Stage 4: Natural Language Explanation

```python
def generate_reflection_explanation(issues, feedback, old_sql, new_sql, sample_output):
    # LLM generates 2-3 sentence explanation that:
    - References actual output data
    - Focuses on WHY the fix improves accuracy
    - Cites real database values/dates for empty results
    - Uses temperature=0.4 for accuracy
```

---

## How Reflection Works

1. **Execute initial query** → Get results DataFrame
2. **Scan for anomalies** → Rule-based checks on actual data
3. **If negatives detected** → Auto-apply `ABS()` fix
4. **If no anomalies** → Run LLM semantic validation with actual output data
5. **For empty results** → Retrieve available values and date ranges from database
6. **If invalid fields or missing data** → Return `NULL` + data-grounded explanation
7. **Generate explanation** → LLM summarizes the fix using actual data references
8. **Re-execute corrected query** → Show final results

---

## License

MIT © 2025 Athulya Anil
