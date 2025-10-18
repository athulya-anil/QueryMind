# 🧠 QueryMind: Self-Reflecting AI SQL Agent  

> **Live App:** https://querymind-ai.streamlit.app/

QueryMind is an **AI-powered SQL reasoning app** built by **Athulya Anil**.  
It generates, executes, and *self-corrects* SQL queries using **reflective reasoning** —  
catching logic or numeric errors (like negative refunds) and automatically rewriting queries to fix them.

You can ask questions like:
- *"Which product generated the highest total revenue?"*  
- *"Show total revenue by category in desc order."*  
- *"Which product had the most refunds?"*  
- *"What is the best selling colour?"* → triggers semantic reflection warning  


---

## Features

- Convert **natural language → SQL** with Groq's `llama-3.3-70b-versatile`
- Built-in **self-reflection logic**:
  - Detects and fixes negative totals with `ABS()`
  - Identifies semantic mismatches (e.g., "colour" not in schema)
- Local **Apple Store–style dataset** with sales, refunds, and revenue fields
- Deployabled on **Streamlit Cloud**

---

## Tech Stack

| Layer | Technology |
|--------|-------------|
| **Frontend** | Streamlit |
| **Database** | SQLite |
| **AI Model** | Groq Llama-3.3-70B Versatile |
| **Language** | Python 3.11+ |
| **Dependencies** | pandas, groq, tabulate |

---

## Run Locally

```bash
# Clone the repo
git clone https://github.com/athulya-anil/QueryMind.git
cd QueryMind

# (Optional) Create a virtual environment
python -m venv venv
source venv/bin/activate  # Mac/Linux
venv\Scripts\activate     # Windows

# Install dependencies
pip install -r requirements.txt

# Run the app
streamlit run app.py
```

---

## Secrets Configuration

For local use, create a `.streamlit/secrets.toml` file:

```toml
[general]
GROQ_API_KEY = "your_groq_api_key_here"
```

For Streamlit Cloud:
1. Go to ⚙️ Settings → Secrets
2. Add `GROQ_API_KEY` in your app configuration.

---

## Example Reflection Flow

| Step | Example | Behavior |
|------|---------|----------|
| **V1** | `SELECT category, SUM(revenue)` | Negative totals appear due to refunds |
| **Reflection** | Detects negatives → wraps in `ABS()` | |
| **V2** | `SELECT category, SUM(ABS(revenue))` | Output corrected automatically |

---

## License

MIT License © 2025 Athulya Anil