import sqlite3

conn = sqlite3.connect("src/app/Data_app/prompts.db")
cur = conn.cursor()

cur.execute("DELETE FROM prompts WHERE key = ?", ("system:GENERIC",))
conn.commit()
conn.close()

print("Đã xóa khỏi bảng prompts.")
