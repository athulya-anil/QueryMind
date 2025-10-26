import re
import json
import pandas as pd
import hashlib
import pickle
import sqlite3


class ReflectionEngine:
    """
    ReflectionEngine: analyzes SQL output for anomalies and uses an LLM to propose corrections.
    """

    def __init__(self, client, model="llama-3.3-70b-versatile", db_path="apple_store.db", table_name="transactions"):
        self.client = client
        self.model = model
        self.db_path = db_path
        self.table_name = table_name  # table used for value/date introspection
        self._reflection_cache = {}  # Cache for full reflection results
        self._explanation_cache = {}  # Cache for explanations
        self._semantic_cache = {}  # Cache for semantic validation
        self._column_values_cache = {}  # Cache for column distinct values

    # ----- allow updating the target table name at runtime -----
    def set_table(self, table_name: str):
        """Update target table for value/date introspection and clear table-scoped caches."""
        self.table_name = table_name
        # clear caches that depend on the table contents
        self._column_values_cache.clear()
        self._semantic_cache.clear()

    def _get_df_hash(self, df: pd.DataFrame) -> str:
        """Generate stable hash for DataFrame content"""
        try:
            return hashlib.md5(pickle.dumps(df.values.tobytes())).hexdigest()[:16]
        except:
            # Fallback for non-numpy types
            return hashlib.md5(str(df.to_dict()).encode()).hexdigest()[:16]

    def _get_reflection_cache_key(self, question: str, sql_query: str, df: pd.DataFrame, schema: str) -> str:
        """Generate unique cache key for reflection"""
        df_hash = self._get_df_hash(df)
        combined = f"{question}|{sql_query}|{df_hash}|{schema}"
        return hashlib.md5(combined.encode()).hexdigest()

    def _get_semantic_cache_key(self, question: str, sql_query: str, schema: str, output_str: str) -> str:
        """Generate cache key for semantic validation - now includes output data"""
        combined = f"{question}|{sql_query}|{schema}|{output_str}"
        return hashlib.md5(combined.encode()).hexdigest()

    def _get_explanation_cache_key(self, issues: list, feedback: str, old_sql: str, new_sql: str) -> str:
        """Generate cache key for explanations"""
        combined = f"{str(issues)}|{feedback}|{old_sql}|{new_sql}"
        return hashlib.md5(combined.encode()).hexdigest()

    def _get_column_distinct_values(self, column_name: str, limit: int = 10) -> list:
        """
        Get distinct values from a specific column in the database.
        Useful for suggesting valid alternatives when filters return empty results.
        """
        cache_key = f"{self.table_name}:{column_name}_{limit}"  # include table in cache key
        if cache_key in self._column_values_cache:
            return self._column_values_cache[cache_key]
        
        try:
            conn = sqlite3.connect(self.db_path)
            query = f"SELECT DISTINCT {column_name} FROM {self.table_name} LIMIT {limit}"
            df = pd.read_sql_query(query, conn)
            conn.close()
            values = df[column_name].dropna().tolist()
            self._column_values_cache[cache_key] = values
            return values
        except Exception as e:
            return []

    def _get_date_range_stats(self) -> str:
        """
        Get actual date range from database to prevent hallucinations about date filters.
        """
        try:
            conn = sqlite3.connect(self.db_path)
            date_stats = pd.read_sql_query(
                f"SELECT MIN(ts) as min_date, MAX(ts) as max_date, COUNT(*) as total_records FROM {self.table_name}", 
                conn
            )
            conn.close()
            if not date_stats.empty:
                return f"\n- Date range: {date_stats['min_date'][0]} to {date_stats['max_date'][0]} ({date_stats['total_records'][0]} total records)"
        except Exception as e:
            pass
        return ""

    def _extract_filtered_columns(self, sql_query: str) -> list:
        """
        Extract column names that are being filtered in WHERE clause.
        This helps identify which columns to check for valid values.
        """
        columns = []
        # Match patterns like: WHERE column_name LIKE/= 'value'
        where_patterns = [
            r"WHERE\s+(\w+)\s+(?:LIKE|=|IN)",
            r"AND\s+(\w+)\s+(?:LIKE|=|IN)",
            r"OR\s+(\w+)\s+(?:LIKE|=|IN)"
        ]
        
        for pattern in where_patterns:
            matches = re.findall(pattern, sql_query, re.IGNORECASE)
            columns.extend(matches)
        
        return list(set(columns))  # Remove duplicates

    def _validate_sql_change(self, original_sql: str, refined_sql: str) -> bool:
        """
        Validate if the LLM's suggested change is meaningful.
        Returns False if it's just a cosmetic rewrite without logic change.
        """
        if refined_sql.upper() == "NULL" or original_sql.strip() == refined_sql.strip():
            return True
        
        # Check if WHERE clause logic actually changed
        try:
            old_where = re.findall(r"WHERE\s+(.+?)(?:GROUP|ORDER|LIMIT|;|$)", original_sql, re.IGNORECASE | re.DOTALL)
            new_where = re.findall(r"WHERE\s+(.+?)(?:GROUP|ORDER|LIMIT|;|$)", refined_sql, re.IGNORECASE | re.DOTALL)
            
            if old_where and new_where:
                # Normalize whitespace for comparison
                old_normalized = re.sub(r'\s+', ' ', old_where[0]).strip().lower()
                new_normalized = re.sub(r'\s+', ' ', new_where[0]).strip().lower()
                
                # If they're essentially the same, it's just a rewrite
                if old_normalized == new_normalized:
                    return False
        except:
            pass
        
        return True

    # ---------- 1 Data Anomaly Detection ----------
    def detect_output_anomalies(self, df: pd.DataFrame):
        issues = []

        if df.empty:
            return ["Empty dataframe — possible WHERE or JOIN condition error."]

        # Negative numbers
        if (df.select_dtypes("number") < 0).any().any():
            issues.append("Negative numeric values detected (possible refunds or sign errors).")

        # Duplicate rows
        if df.duplicated().sum() > 0:
            issues.append("Duplicate rows found in result set.")

        # Null-only columns
        if df.isna().all().any():
            null_cols = df.columns[df.isna().all()].tolist()
            issues.append(f"Empty/null-only column(s): {null_cols}")

        # Coverage check
        if "region" in df.columns and len(df["region"].unique()) < 4:
            issues.append("Some regions missing — possible filtering issue or incomplete data coverage.")

        if not issues:
            issues.append("No data-level anomalies detected.")
        return issues

    # ---------- 2 Schema Presence Pre-Check (backup only) ----------
    def detect_missing_fields(self, question: str, schema: str):
        """
        Compare user question keywords to schema columns and detect references to missing fields.
        (Used only as a fallback if the LLM fails.)
        """
        schema_cols = [s.split(" ")[0].strip().lower() for s in schema.splitlines() if "(" in s]
        q_lower = question.lower()
        missing_terms = []
        for word in re.findall(r"[a-zA-Z_]+", q_lower):
            if word not in schema_cols and len(word) > 3:
                if word in ["color", "rating", "brand", "model", "size", "version"]:
                    missing_terms.append(word)
        return missing_terms

    # ---------- 3 Semantic Reflection (LLM Reasoning) with External Feedback ----------
    def semantic_reflection(self, question, sql_query, schema, sample_output):
        # Convert sample_output to markdown for better LLM readability
        if isinstance(sample_output, list) and len(sample_output) > 0:
            df_sample = pd.DataFrame(sample_output)
            output_str = df_sample.to_markdown(index=False)
        else:
            output_str = "No output data available (empty result)"
        
        # Check cache first
        cache_key = self._get_semantic_cache_key(question, sql_query, schema, output_str)
        if cache_key in self._semantic_cache:
            return self._semantic_cache[cache_key]

        # If output is empty, get available values for filtered columns AND date range
        available_values_info = ""
        if output_str == "No output data available (empty result)":
            filtered_columns = self._extract_filtered_columns(sql_query)
            if filtered_columns:
                available_values_info = "\n\nAvailable values in filtered columns:"
                for col in filtered_columns:
                    values = self._get_column_distinct_values(col, limit=10)
                    if values:
                        available_values_info += f"\n- {col}: {values}"
            
            # Add date range statistics
            date_info = self._get_date_range_stats()
            if date_info:
                available_values_info += f"\n\nDatabase statistics:{date_info}"

        reflection_prompt = f"""
You are QueryMind, a SQL reasoning and reflection assistant.

Analyze whether the SQL query correctly answers the user's question based on the schema AND the actual output data.

User Question: {question}

Original SQL Query:
{sql_query}

Database Schema:
{schema}

SQL Output (first 3 rows):
{output_str}{available_values_info}

CRITICAL RULES TO PREVENT HALLUCINATION:
1. If output is EMPTY and filtered values don't exist in available values, set refined_sql to "NULL"
2. If output is EMPTY and date filter is outside actual date range, set refined_sql to "NULL"
3. DO NOT suggest SQL syntax changes if the SQL is already syntactically correct
4. DO NOT invent "date format issues" - check actual date ranges first
5. Empty results usually mean: (a) filtered value doesn't exist, or (b) time range has no data
6. Only suggest SQL changes if there's an actual SQL LOGIC error (like missing ABS(), wrong aggregation)
7. If SQL syntax looks correct but data doesn't exist, return "NULL" with data availability explanation

EXAMPLES OF CORRECT RESPONSES:

Example 1 - Empty due to missing data value:
Query: WHERE region = 'NY'
Available regions: ['North', 'South', 'East', 'West']
Correct: {{"feedback": "No region 'NY' exists in data. Available regions: North, South, East, West.", "refined_sql": "NULL"}}

Example 2 - Empty due to date outside range:
Query: WHERE ts LIKE '2023%'
Date range: 2025-09-01 to 2025-10-25
Correct: {{"feedback": "No data from 2023. Database only contains data from Sept-Oct 2025.", "refined_sql": "NULL"}}

Example 3 - Actual SQL logic error:
Query: SUM(revenue)
Output: -12500 (negative)
Correct: {{"feedback": "Negative total due to refunds in data. Need ABS() to get absolute revenue.", "refined_sql": "SUM(ABS(revenue))"}}

Return your response as STRICT JSON with exactly two fields:
{{
  "feedback": "<Brief 1-2 sentence evaluation>",
  "refined_sql": "<Improved SQL query, or 'NULL' if data doesn't exist, or original if correct>"
}}

Rules:
- If question references missing schema fields, set refined_sql to "NULL"
- If filtered value doesn't exist in available values, set refined_sql to "NULL"
- If date range is outside database date range, set refined_sql to "NULL"
- Only change SQL if there's a real logic error (wrong function, missing clause, etc.)
- Be conservative: when in doubt, return original SQL or "NULL"
"""

        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": reflection_prompt}],
                temperature=0.3,  # Lower temperature to reduce hallucination
            )
            raw_output = resp.choices[0].message.content.strip()

            # Clean markdown code blocks if present
            if "```json" in raw_output:
                raw_output = raw_output.split("```json")[1].split("```")[0].strip()
            elif "```" in raw_output:
                raw_output = raw_output.split("```")[1].split("```")[0].strip()

            try:
                result = json.loads(raw_output)
                # Validate required fields
                if "feedback" not in result or "refined_sql" not in result:
                    raise ValueError("Missing required JSON fields")
                
                # Validate if the change is meaningful
                if not self._validate_sql_change(sql_query, result["refined_sql"]):
                    result["refined_sql"] = sql_query
                    result["feedback"] = "Query is already correct. Empty result is due to data availability."
                    
            except (json.JSONDecodeError, ValueError) as e:
                # Fallback for non-JSON LLM output
                if "missing" in raw_output.lower() or "not present" in raw_output.lower():
                    result = {
                        "feedback": "The question seems to reference fields not present in the schema. Please rephrase or use available columns.",
                        "refined_sql": "NULL",
                    }
                else:
                    result = {
                        "feedback": f"Reflection completed but response format was unexpected. Original query maintained.",
                        "refined_sql": sql_query,
                    }

        except Exception as e:
            result = {
                "feedback": f"Semantic reflection encountered an error: {str(e)[:100]}",
                "refined_sql": sql_query,
            }

        # Cache the result
        self._semantic_cache[cache_key] = result
        return result

    # ---------- 4 Generate Natural Explanation with Cache ----------
    def generate_reflection_explanation(self, issues, feedback, old_sql, new_sql, sample_output=None):
        """
        Generate human-friendly explanation of what was improved.
        Uses temperature=0.4 for more accurate, less creative explanations.
        Now includes actual output data for grounded explanations.
        """
        # Check cache first
        cache_key = self._get_explanation_cache_key(issues, feedback, old_sql, new_sql)
        if cache_key in self._explanation_cache:
            return self._explanation_cache[cache_key]

        # Convert sample_output to readable format if provided
        output_context = ""
        if sample_output:
            if isinstance(sample_output, list) and len(sample_output) > 0:
                df_sample = pd.DataFrame(sample_output)
                output_context = f"\n\nActual SQL Output (first 3 rows):\n{df_sample.to_markdown(index=False)}"
            else:
                output_context = "\n\nActual SQL Output: Empty result (no rows returned)"

        explanation_prompt = f"""
You are QueryMind, an AI SQL reflection assistant.

Context:
- Detected data issues: {issues}
- Reflection feedback: {feedback}
- Original SQL: {old_sql}
- Corrected SQL: {new_sql}{output_context}

Task: Explain in 2-3 sentences WHY the correction improves the query or what the issue was.
- Focus on the reasoning, not repeating SQL code
- Be concise and educational
- Use plain English
- Be accurate - base your explanation on the ACTUAL OUTPUT DATA shown above
- If output is empty, explain it's a data availability issue, not a query syntax issue
- Don't invent technical details that aren't evidenced by the actual data
- DO NOT claim date format issues if the SQL syntax was correct

Your explanation:
"""
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": explanation_prompt}],
                temperature=0.4,
            )
            explanation = resp.choices[0].message.content.strip()
        except Exception as e:
            explanation = f"(Explanation generation failed: {str(e)[:100]})"

        # Cache the result
        self._explanation_cache[cache_key] = explanation
        return explanation

    # ---------- 5 Combined Reflection with Cache ----------
    def reflect(self, question, sql_query, df, schema):
        """
        Main reflection pipeline with data-aware reasoning.
        Now properly includes output data in semantic analysis.
        """
        # Check full reflection cache first
        cache_key = self._get_reflection_cache_key(question, sql_query, df, schema)
        if cache_key in self._reflection_cache:
            return self._reflection_cache[cache_key]

        issues = self.detect_output_anomalies(df)
        sample_output = df.head(3).to_dict(orient="records")

        # Stage 1: Negative totals auto-fix 
        if any("Negative" in issue for issue in issues):
            fixed_sql = re.sub(r"SUM\(([^)]+)\)", r"SUM(ABS(\1))", sql_query, flags=re.IGNORECASE)
            feedback = "Detected negative totals from refunds → added ABS() around SUM() for correction."
            explanation = self.generate_reflection_explanation(
                issues=issues,
                feedback=feedback,
                old_sql=sql_query,
                new_sql=fixed_sql,
                sample_output=sample_output,  # Pass the actual output data
            )
            result = {
                "issues": issues,
                "feedback": feedback,
                "refined_sql": fixed_sql,
                "explanation": explanation,
            }
            # Cache before returning
            self._reflection_cache[cache_key] = result
            return result

        # Stage 2: Full Semantic Reasoning via LLM
        llm_result = self.semantic_reflection(question, sql_query, schema, sample_output)
        refined_sql = llm_result.get("refined_sql", sql_query)
        feedback = llm_result.get("feedback", "No semantic issues detected.")

        # Fallback: Use static check if LLM fails silently
        if refined_sql.strip().upper() == sql_query.strip().upper() and "missing" not in feedback.lower():
            missing_terms = self.detect_missing_fields(question, schema)
            if missing_terms:
                feedback = f"The question references missing field(s): {missing_terms}. Please rephrase or use available fields."
                refined_sql = "NULL"

        # Generate reflection explanation
        reflection_explanation = self.generate_reflection_explanation(
            issues=issues,
            feedback=feedback,
            old_sql=sql_query,
            new_sql=refined_sql,
            sample_output=sample_output,  # Pass the actual output data
        )

        # Simplify explanation if SQL was invalid or use LLM feedback
        if refined_sql.strip().upper() == "NULL":
            # If feedback mentions specific data issues, use it; otherwise use generic message
            if "2023" in question.lower() or "date" in feedback.lower():
                date_info = self._get_date_range_stats()
                if date_info:
                    reflection_explanation = f"The query returned no results because there's no data from the requested time period in the database.{date_info.replace('Database statistics:', 'Available data:')} Please adjust your date filter to match the available data range."
                else:
                    reflection_explanation = feedback  # Use LLM's feedback if date stats unavailable
            elif any(keyword in feedback.lower() for keyword in ["doesn't exist", "not present", "no region", "no product"]):
                reflection_explanation = feedback  # Use LLM's specific feedback about missing values
            else:
                reflection_explanation = (
                    "There's no matching data for your query criteria. "
                    "This could be because the filtered value doesn't exist in the database, or a referenced field is not in the schema. "
                    "Try checking available values or rephrasing your question using fields like 'product_name', 'category', or 'region'."
                )

        result = {
            "issues": issues,
            "feedback": feedback,
            "refined_sql": refined_sql,
            "explanation": reflection_explanation,
        }

        # Cache the result
        self._reflection_cache[cache_key] = result
        return result

    # ---------- 6 Cache Management ----------
    def clear_cache(self):
        """Clear all caches"""
        self._reflection_cache.clear()
        self._explanation_cache.clear()
        self._semantic_cache.clear()
        self._column_values_cache.clear()

    def get_cache_stats(self):
        """Get cache statistics"""
        return {
            "reflection_cache_size": len(self._reflection_cache),
            "explanation_cache_size": len(self._explanation_cache),
            "semantic_cache_size": len(self._semantic_cache),
            "column_values_cache_size": len(self._column_values_cache),
            "total_cached_items": len(self._reflection_cache) + len(self._explanation_cache) + len(self._semantic_cache) + len(self._column_values_cache)
        }
