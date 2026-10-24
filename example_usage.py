from client import AgenticSqlQuerySelfCorrectionClient
import json, sys
sys.stdout.reconfigure(encoding='utf-8')

def main():
    client = AgenticSqlQuerySelfCorrectionClient()
    print("=== AGENTIC SQL QUERY SELF-CORRECTION ===")
    
    test_queries = [
        # Query 1: Column typo (custmr_email) + trailing comma + missing group by
        "SELECT user_email, COUNT(id) as total_orders, FROM users",
        
        # Query 2: Column typo (totl_amount) + missing GROUP BY
        "SELECT full_name, SUM(total_amount) FROM users JOIN orders ON users.id = orders.user_id",
        
        # Query 3: Table typo (ordrs)
        "SELECT id, order_status FROM ordrs WHERE order_status = 'pending'"
    ]
    
    for i, q in enumerate(test_queries, 1):
        res = client.correct_sql_query(q)
        print(f"
--- Case {i} ---")
        print(f"Original : {res['original_query']}")
        print(f"Corrected: {res['corrected_query']}")
        print(f"Fixes ({res['modifications_count']}):")
        for f in res['fixes_applied']:
            print(f"  - [{f['type']}] {f}")

if __name__ == "__main__":
    main()
