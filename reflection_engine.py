import re
import json
import pandas as pd


class ReflectionEngine:
    """
    ReflectionEngine: analyzes SQL output for anomalies and uses an LLM to propose corrections.
    Restores semantic field-existence detection from your original refine_sql_with_feedback(),
    but now the LLM explains missing fields naturally when detected.
    """

    def __init__(self, client, model="llama-3.3-70b-versatile"):
        self.client = client
        self.model = model

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
            issues.append("✅ No data-level anomalies detected.")
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

    # ---------- 3 Semantic Reflection (LLM Reasoning) ----------
    def semantic_reflection(self, question, sql_query, schema, sample_output):
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

        return result

    # ---------- 4 Generate Natural Explanation ----------
    def generate_reflection_explanation(self, issues, feedback, old_sql, new_sql):
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
            explanation = f"(⚠️ Explanation generation failed: {e})"

        return explanation

    # ---------- 5 Combined Reflection ----------
    def reflect(self, question, sql_query, df, schema):
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
            return {
                "issues": issues,
                "feedback": feedback,
                "refined_sql": fixed_sql,
                "explanation": explanation,
            }

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
                "There’s no matching column for your question in the database schema. "
                "Try rephrasing your question using available fields such as 'product_name', 'category', or 'region'."
            )
        return {
            "issues": issues,
            "feedback": feedback,
            "refined_sql": refined_sql,
            "explanation": reflection_explanation,
        }
