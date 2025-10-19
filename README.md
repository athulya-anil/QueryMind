# 🐣 QueryMind: Self-Reflecting AI SQL Agent

**Live Demo:** https://querymind-ai.streamlit.app/

An AI SQL agent that writes queries, detects errors, and **auto-corrects itself** using reflection loops.

---

## What It Does

1. **Converts natural language → SQL** using Groq's LLaMA 3.3 70B
2. **Executes the query** against SQLite
3. **Reflects on the output** to detect:
   - Negative totals from refunds → wraps in `ABS()`
   - Missing schema fields → explains what's unavailable
   - Empty results → flags WHERE/JOIN errors
   - Duplicate rows → identifies aggregation issues
   - Null-only columns → detects missing data
   - Incomplete coverage → warns about filtered regions
4. **Rewrites & re-executes** the corrected query
5. **Explains the fix** in plain English

---

## Architecture

```
User Question
     ↓
Generate SQL (LLM)
     ↓
Execute Query v1
     ↓
Reflection Engine
  ├─ Data Anomaly Detection (rule-based)
  │   ├─ Empty DataFrames
  │   ├─ Negative values
  │   ├─ Duplicates
  │   ├─ Null columns
  │   └─ Coverage gaps
  ├─ Semantic Validation (LLM)
  │   ├─ Intent matching
  │   └─ Schema field verification
  └─ Auto-Correction Logic
      ├─ ABS() wrapper for negatives
      ├─ NULL response for invalid queries
      └─ Natural language explanation
     ↓
Execute Query v2 (corrected)
     ↓
User-Friendly Explanation
```

---

## Example: Auto-Correction in Action

**Question:** *"Which product generated the highest total revenue?"*

**Initial SQL:**
```sql
SELECT product_name, SUM(revenue) 
FROM transactions 
GROUP BY product_name 
ORDER BY total_revenue DESC LIMIT 1
```
**Problem:** Returns negative revenue due to refunds

**Reflection Detects:**
- Negative numeric values detected (possible refunds or sign errors)

**Auto-Corrected SQL:**
```sql
SELECT product_name, SUM(ABS(revenue)) 
FROM transactions 
GROUP BY product_name 
ORDER BY total_revenue DESC LIMIT 1
```

**Explanation:**  
*"The reflection detected negative revenue values caused by refunds. Added ABS() to calculate absolute revenue for accurate product ranking."*

**Result:** Correct product ranking

---

## Example: Semantic Validation

**Question:** *"What is the best selling colour?"*

**Initial SQL:**
```sql
SELECT colour, SUM(qty_sold) 
FROM transactions 
GROUP BY colour 
ORDER BY SUM(qty_sold) DESC LIMIT 1
```

**Reflection Detects:**
- The field 'colour' does not exist in schema

**Response:**
```
refined_sql: NULL
explanation: "There's no matching column for your question in the database schema. 
Try rephrasing your question using available fields such as 'product_name', 
'category', or 'region'."
```

---

## Tech Stack

- **Frontend:** Streamlit
- **LLM:** Groq LLaMA 3.3 70B Versatile
- **Database:** SQLite
- **Language:** Python 3.11

---

## Run Locally

```bash
git clone https://github.com/athulya-anil/QueryMind.git
cd QueryMind
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
streamlit run Demo.py
```

**Add Groq API key:**
```toml
# .streamlit/secrets.toml
GROQ_API_KEY = "your_key_here"
```

---

## Features

| Feature | Description |
|---------|-------------|
| **Demo Dataset** | Pre-loaded Apple Store transactions (100+ rows) |
| **Custom Upload** | Use your own CSV files |
| **Auto-Correction** | Fixes negative sums, invalid fields, duplicate results |
| **Semantic Check** | Detects queries referencing non-existent columns |
| **Multi-Stage Validation** | Rule-based + LLM reasoning with fallback logic |
| **Natural Explanations** | Plain-English reasoning for every correction |

---

## File Structure

```
QueryMind/
├── Demo.py                      # Apple Store demo
├── pages/
│   └── Use_Your_Own_Dataset.py  # CSV upload mode
├── reflection_engine.py         # Core reflection logic
├── requirements.txt
└── README.md
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

### Stage 2: Semantic Validation (LLM)

```python
def semantic_reflection(question, sql_query, schema, sample_output):
    # LLM analyzes:
    - Does query match user intent?
    - Are referenced fields in schema?
    # Returns: {"feedback": "...", "refined_sql": "..."}
```

**Fallback Logic:** If LLM fails, uses regex-based field detection for terms like:
`color`, `rating`, `brand`, `model`, `size`, `version`

### Stage 3: Auto-Correction

**Negative totals:**
```python
# Detects: SUM(revenue) with negative values
# Fixes:   SUM(ABS(revenue))
fixed_sql = re.sub(r"SUM\(([^)]+)\)", r"SUM(ABS(\1))", sql_query)
```

**Invalid queries:**
```python
# Returns: "NULL" + helpful explanation
# Example: "Try using 'product_name', 'category', or 'region'"
```

### Stage 4: Natural Language Explanation

```python
def generate_reflection_explanation(issues, feedback, old_sql, new_sql):
    # LLM generates 2-3 sentence explanation
    # Focuses on WHY the fix improves accuracy
```

---

## Demo Dataset Schema

**Table:** `transactions`

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Primary key |
| `product_id` | INTEGER | Product identifier |
| `product_name` | TEXT | Product display name |
| `category` | TEXT | Product category |
| `region` | TEXT | Sales region (North/South/East/West) |
| `qty_sold` | INTEGER | Quantity (negative = refund) |
| `unit_price` | REAL | Price per unit |
| `revenue` | REAL | Total revenue (qty × price) |
| `notes` | TEXT | "sale" or "refund" |
| `ts` | DATETIME | Transaction timestamp |

**Sample products:** iPhone 15 Pro, AirPods Pro, MacBook Air M3, Apple Watch Series 10

---

## How Reflection Works

1. **Execute initial query** → Get results DataFrame
2. **Scan for anomalies** → Rule-based checks
3. **If negatives detected** → Auto-apply `ABS()` fix
4. **If no anomalies** → Run LLM semantic validation
5. **If invalid fields** → Return `NULL` + explanation
6. **Generate explanation** → LLM summarizes the fix
7. **Re-execute corrected query** → Show final results

---

## License

MIT © 2025 Athulya Anil