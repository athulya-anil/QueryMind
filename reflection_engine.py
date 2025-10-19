import re
import json
import pandas as pd
import hashlib
import pickle


class ReflectionEngine:
    """
    ReflectionEngine: analyzes SQL output for anomalies and uses an LLM to propose corrections.
    Now includes intelligent caching to reduce LLM calls and improve performance.
    """

    def __init__(self, client, model="llama-3.3-70b-versatile"):
        self.client = client
        self.model = model
        self._reflection_cache = {}  # Cache for full reflection results
        self._explanation_cache = {}  # Cache for explanations
        self._semantic_cache = {}  # Cache for semantic validation

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

    def _get_semantic_cache_key(self, question: str, sql_query: str, schema: str) -> str:
        """Generate cache key for semantic validation"""
        combined = f"{question}|{sql_query}|{schema}"
        return hashlib.md5(combined.encode()).hexdigest()

    def _get_explanation_cache_key(self, issues: list, feedback: str, old_sql: str, new_sql: str) -> str:
        """Generate cache key for explanations"""
        combined = f"{str(issues)}|{feedback}|{old_sql}|{new_sql}"
        return hashlib.md5(combined.encode()).hexdigest()

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

    # ---------- 3 Semantic Reflection (LLM Reasoning) with Cache ----------
    def semantic_reflection(self, question, sql_query, schema, sample_output):
        # Check cache first
        cache_key = self._get_semantic_cache_key(question, sql_query, schema)
        if cache_key in self._semantic_cache:
            return self._semantic_cache[cache_key]

        reflection_prompt = f"""
        You are QueryMind, a SQL reasoning and reflection assistant.

        Analyze whether the SQL query correctly answers the user's question based on the provided schema.

        Question: {question}
        SQL Query: {sql_query}
        Schema:
        {schema}

        If the question refers to something not present in the schema (for example, colour, rating, model, etc.), 
        identify which field(s) are missing and respond in valid JSON:
        {{
          "feedback": "The question references missing field(s): ['<missing_field_names>'] which do not exist in the schema. Suggest rephrasing or using available columns.",
          "refined_sql": "NULL"
        }}

        If the SQL query seems correct, respond with:
        {{
          "feedback": "No semantic issues detected.",
          "refined_sql": "{sql_query}"
        }}
        """

        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": reflection_prompt}],
                temperature=0,
            )
            raw_output = resp.choices[0].message.content.strip()

            try:
                result = json.loads(raw_output)
            except json.JSONDecodeError:
                # fallback for non-JSON LLM output
                if "missing" in raw_output.lower() or "not present" in raw_output.lower():
                    result = {
                        "feedback": "The question seems to reference fields not present in the schema. Please rephrase or use available columns.",
                        "refined_sql": "NULL",
                    }
                else:
                    result = {
                        "feedback": f"Model returned non-JSON output: {raw_output[:120]}...",
                        "refined_sql": sql_query,
                    }

        except Exception as e:
            result = {
                "feedback": f"Semantic reflection failed: {e}",
                "refined_sql": sql_query,
            }

        # Cache the result
        self._semantic_cache[cache_key] = result
        return result

    # ---------- 4 Generate Natural Explanation with Cache ----------
    def generate_reflection_explanation(self, issues, feedback, old_sql, new_sql):
        # Check cache first
        cache_key = self._get_explanation_cache_key(issues, feedback, old_sql, new_sql)
        if cache_key in self._explanation_cache:
            return self._explanation_cache[cache_key]

        explanation_prompt = f"""
        You are QueryMind, an AI SQL reflection assistant.

        Context:
        - Detected issues: {issues}
        - Feedback summary: {feedback}
        - Original SQL: {old_sql}
        - Corrected SQL: {new_sql}

        Explain concisely (in 2-3 sentences) WHY the new reflection/fix improves the query.
        Avoid repeating SQL code, just summarize the reasoning in plain English.
        """
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": explanation_prompt}],
                temperature=0.4,
            )
            explanation = resp.choices[0].message.content.strip()
        except Exception as e:
            explanation = f"(Explanation generation failed: {e})"

        # Cache the result
        self._explanation_cache[cache_key] = explanation
        return explanation

    # ---------- 5 Combined Reflection with Cache ----------
    def reflect(self, question, sql_query, df, schema):
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

        # Generate friendly reflection explanation
        reflection_explanation = self.generate_reflection_explanation(
            issues=issues,
            feedback=feedback,
            old_sql=sql_query,
            new_sql=refined_sql,
        )

        # Simplify explanation if SQL was invalid
        if refined_sql.strip().upper() == "NULL":
            reflection_explanation = (
                "There's no matching column for your question in the database schema. "
                "Try rephrasing your question using available fields such as 'product_name', 'category', or 'region'."
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

    def get_cache_stats(self):
        """Get cache statistics"""
        return {
            "reflection_cache_size": len(self._reflection_cache),
            "explanation_cache_size": len(self._explanation_cache),
            "semantic_cache_size": len(self._semantic_cache),
            "total_cached_items": len(self._reflection_cache) + len(self._explanation_cache) + len(self._semantic_cache)
        }