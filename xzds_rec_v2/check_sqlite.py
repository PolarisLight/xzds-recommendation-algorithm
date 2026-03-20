import sqlite3
import json

conn = sqlite3.connect("xzds_rec_v2.sqlite")  # 按你的实际路径改
cur = conn.cursor()

print("=== tables ===")
cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
for row in cur.fetchall():
    print(row)

print("\n=== users ===")
cur.execute("SELECT * FROM users;")
for row in cur.fetchall():
    print(row)

print("\n=== items ===")
cur.execute("SELECT * FROM items;")
for row in cur.fetchall():
    print(row)

print("\n=== user_events ===")
cur.execute("SELECT * FROM user_events;")
for row in cur.fetchall():
    print(row)

conn.close()