import db

conn = db.get_connection()
cursor = conn.cursor()
cursor.execute("select table_name from information_schema.tables where table_schema = 'public'")
for row in cursor.fetchall():
    print(row[0])
conn.close()