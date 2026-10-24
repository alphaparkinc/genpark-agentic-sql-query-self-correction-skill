import sys, json
from client import AgenticSqlQuerySelfCorrectionClient
sys.stdout.reconfigure(encoding='utf-8')

def handle_mcp():
    client = AgenticSqlQuerySelfCorrectionClient()
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        print(json.dumps({"status": "ready", "skill": "genpark-agentic-sql-query-self-correction-skill"}))
        return
    req = json.loads(sys.stdin.read() or "{}")
    query = req.get("query", "SELECT user_email, COUNT(id) FROM users")
    res = client.correct_sql_query(query)
    print(json.dumps(res, indent=2))

if __name__ == "__main__":
    handle_mcp()
