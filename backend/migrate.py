import sqlite3

def migrate():
    print("Starting migration...")
    conn = sqlite3.connect('backend/transcriptions.db')
    cursor = conn.cursor()
    
    queries = [
        "ALTER TABLE tasks RENAME COLUMN filename TO file_path",
        "ALTER TABLE tasks RENAME COLUMN result TO transcript",
        "ALTER TABLE tasks ADD COLUMN summary TEXT",
        "ALTER TABLE tasks ADD COLUMN error_message TEXT"
    ]
    
    for q in queries:
        try:
            cursor.execute(q)
            print(f"Success: {q}")
        except Exception as e:
            print(f"Skipped/Failed: {q} - {e}")
            
    conn.commit()
    conn.close()
    print("Migration finished.")

if __name__ == "__main__":
    migrate()
