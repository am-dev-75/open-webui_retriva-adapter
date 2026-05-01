
import sqlite3
import os

db_path = "data/adapter.db"
if not os.path.exists(db_path):
    print(f"DB not found at {db_path}")
else:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM kb_mappings;")
        rows = cursor.fetchall()
        print(f"KB Mappings ({len(rows)}):")
        for row in rows:
            print(row)
            
        cursor.execute("SELECT * FROM file_mappings;")
        rows = cursor.fetchall()
        print(f"File Mappings ({len(rows)}):")
        for row in rows:
            print(row)
    except Exception as e:
        print(f"Error: {e}")
    finally:
        conn.close()
