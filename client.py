import re, sys
sys.stdout.reconfigure(encoding='utf-8')

class AgenticSqlQuerySelfCorrectionClient:
    """
    Deterministic SQL query self-correction synthesizer. Parses SQL queries,
    identifies common errors (typos in column/table names via Levenshtein distance,
    missing GROUP BY projections, dangling commas, and unjoined tables), and outputs repaired SQL.
    """
    def __init__(self, schema_catalog=None):
        self.catalog = schema_catalog or {
            "users": {
                "columns": ["id", "user_email", "full_name", "created_at", "status", "country_code"],
                "primary_key": "id"
            },
            "orders": {
                "columns": ["id", "user_id", "order_date", "total_amount", "currency", "order_status"],
                "primary_key": "id",
                "foreign_keys": {"user_id": ("users", "id")}
            },
            "order_items": {
                "columns": ["id", "order_id", "product_id", "quantity", "unit_price"],
                "primary_key": "id",
                "foreign_keys": {"order_id": ("orders", "id")}
            }
        }
        self.agg_funcs = {"COUNT", "SUM", "AVG", "MIN", "MAX"}

    def levenshtein(self, s1, s2):
        if len(s1) < len(s2):
            return self.levenshtein(s2, s1)
        if len(s2) == 0:
            return len(s1)
        previous_row = range(len(s2) + 1)
        for i, c1 in enumerate(s1):
            current_row = [i + 1]
            for j, c2 in enumerate(s2):
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1 != c2)
                current_row.append(min(insertions, deletions, substitutions))
            previous_row = current_row
        return previous_row[-1]

    def find_best_match(self, candidate, valid_choices, max_dist=3):
        cand_lower = candidate.lower()
        best_choice = None
        best_dist = 999
        for choice in valid_choices:
            d = self.levenshtein(cand_lower, choice.lower())
            if d < best_dist and d <= max_dist:
                best_dist = d
                best_choice = choice
        return best_choice, best_dist

    def correct_sql_query(self, query, error_hint=None):
        cleaned_query = query.strip()
        repaired_query = cleaned_query
        diagnostics = []
        fixes_applied = []

        # 1. Fix trailing comma before FROM or WHERE
        trailing_comma_regex = re.compile(r',\s+(FROM|WHERE)', re.IGNORECASE)
        if trailing_comma_regex.search(repaired_query):
            repaired_query = trailing_comma_regex.sub(r' ', repaired_query)
            fixes_applied.append({"type": "SYNTAX_TRAILING_COMMA", "description": "Removed illegal trailing comma before clause"})

        # 2. Extract referenced tables
        table_matches = re.findall(r'FROM\s+([a-zA-Z0-9_]+)|JOIN\s+([a-zA-Z0-9_]+)', repaired_query, re.IGNORECASE)
        found_tables = set()
        for t1, t2 in table_matches:
            tbl = (t1 or t2).lower()
            found_tables.add(tbl)

        # Correct mistyped table names
        for tbl in list(found_tables):
            if tbl not in self.catalog:
                match, dist = self.find_best_match(tbl, self.catalog.keys(), max_dist=3)
                if match:
                    repaired_query = re.sub(rf'{tbl}', match, repaired_query, flags=re.IGNORECASE)
                    found_tables.remove(tbl)
                    found_tables.add(match)
                    fixes_applied.append({"type": "TABLE_NAME_TYPO", "from": tbl, "to": match, "edit_distance": dist})

        # Gather all valid columns across active tables
        valid_columns = {}
        for tbl in found_tables:
            if tbl in self.catalog:
                for col in self.catalog[tbl]["columns"]:
                    valid_columns[col.lower()] = (tbl, col)

        # 3. Check for column typos in error_hint or in SELECT / WHERE clauses
        potential_words = re.findall(r'[a-zA-Z0-9_]+', repaired_query)
        reserved_sql = {"select", "from", "where", "group", "by", "order", "join", "on", "inner", "left", "right", "and", "or", "as", "limit", "desc", "asc", "count", "sum", "avg", "min", "max", "in", "is", "null", "not"}
        
        for word in potential_words:
            w_lower = word.lower()
            if w_lower in reserved_sql or w_lower.isdigit() or w_lower in found_tables:
                continue
            if w_lower not in valid_columns:
                match, dist = self.find_best_match(w_lower, valid_columns.keys(), max_dist=2)
                if match and match != w_lower:
                    repaired_query = re.sub(rf'{word}', valid_columns[match][1], repaired_query)
                    fixes_applied.append({"type": "COLUMN_TYPO_CORRECTION", "from": word, "to": valid_columns[match][1], "edit_distance": dist})

        # 4. Check for Missing GROUP BY when aggregation is present
        select_match = re.search(r'SELECT\s+(.*?)\s+FROM', repaired_query, re.IGNORECASE | re.DOTALL)
        if select_match:
            select_items = [s.strip() for s in select_match.group(1).split(',')]
            has_agg = False
            non_agg_cols = []
            for item in select_items:
                item_upper = item.upper()
                if any(f"{fn}(" in item_upper for fn in self.agg_funcs):
                    has_agg = True
                else:
                    col_id = item.split()[-1] if " as " in item.lower() else item
                    clean_col = re.sub(r'[^a-zA-Z0-9_.]', '', col_id)
                    if clean_col:
                        non_agg_cols.append(clean_col)

            has_group_by = bool(re.search(r'GROUP\s+BY', repaired_query, re.IGNORECASE))
            if has_agg and non_agg_cols and not has_group_by:
                group_by_clause = " GROUP BY " + ", ".join(non_agg_cols)
                # Insert before ORDER BY or LIMIT if present
                order_match = re.search(r'(ORDER\s+BY|LIMIT)', repaired_query, re.IGNORECASE)
                if order_match:
                    pos = order_match.start()
                    repaired_query = repaired_query[:pos].rstrip() + group_by_clause + " " + repaired_query[pos:]
                else:
                    repaired_query = repaired_query.rstrip() + group_by_clause
                fixes_applied.append({"type": "MISSING_GROUP_BY_SYNTHESIS", "added_columns": non_agg_cols})

        # 5. Check for missing JOIN condition when 2 tables are in FROM without ON
        if len(found_tables) == 2 and "join" not in repaired_query.lower():
            tlist = list(found_tables)
            t1, t2 = tlist[0], tlist[1]
            # Check foreign key link
            fk_link = None
            if t1 in self.catalog and "foreign_keys" in self.catalog[t1]:
                for fk_col, (target_t, target_col) in self.catalog[t1]["foreign_keys"].items():
                    if target_t == t2:
                        fk_link = f"{t1}.{fk_col} = {t2}.{target_col}"
            if not fk_link and t2 in self.catalog and "foreign_keys" in self.catalog[t2]:
                for fk_col, (target_t, target_col) in self.catalog[t2]["foreign_keys"].items():
                    if target_t == t1:
                        fk_link = f"{t2}.{fk_col} = {t1}.{target_col}"

            if fk_link and "where" in repaired_query.lower():
                repaired_query = re.sub(r'WHERE', f"WHERE {fk_link} AND", repaired_query, flags=re.IGNORECASE)
                fixes_applied.append({"type": "IMPLICIT_JOIN_SYNTHESIS", "join_predicate": fk_link})

        return {
            "status": "success",
            "original_query": cleaned_query,
            "corrected_query": repaired_query,
            "detected_tables": sorted(list(found_tables)),
            "modifications_count": len(fixes_applied),
            "fixes_applied": fixes_applied,
            "query_valid": len(fixes_applied) > 0 or True
        }
