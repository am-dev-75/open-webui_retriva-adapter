
import sqlite3
import os

db_path = "data/adapter.db"
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM kb_mappings WHERE owui_kb_id LIKE 'KB_REPRO_%';")
        cursor.execute("DELETE FROM file_mappings WHERE owui_file_id LIKE 'f-repro-%';")
        conn.commit()
        print("Test data cleaned up.")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        conn.close()
