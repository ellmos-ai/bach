import sqlite3, os, json, re

DB = '/Users/lukas/services/bach/system/data/bach-ASUS-GEI.db'
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

ids = [str(i) for i in range(965, 975)]

# 1. connector_messages around BACH IDs 1428-1455
print('=== connector_messages id 1428..1455 ===')
for r in conn.execute("SELECT id, connector_name, direction, sender, recipient, content, attachments_json, status, created_at FROM connector_messages WHERE id BETWEEN 1428 AND 1455 ORDER BY id").fetchall():
    print(f"id={r['id']} conn={r['connector_name']} dir={r['direction']} sender={r['sender']} recip={r['recipient']} status={r['status']} content={str(r['content'])[:200]}")
    if r['attachments_json']:
        print('  attachments=', str(r['attachments_json'])[:250])

# 2. Search connector_messages.content for #965..#974 and raw ids
print('\n=== connector_messages content search ===')
for i in ids:
    for pat in (f'#{i}', f'telegram_id\": {i}', f'"message_id": {i}', f'message_id={i}', f'id={i}'):
        rows = conn.execute("SELECT id, connector_name, direction, content FROM connector_messages WHERE content LIKE ? LIMIT 20", (f'%{pat}%',)).fetchall()
        for r in rows:
            print(f"#{i} pattern={pat} id={r['id']} conn={r['connector_name']} dir={r['direction']} content={str(r['content'])[:300]}")

# 3. Search messages.body and metadata
print('\n=== messages body/metadata search ===')
for i in ids:
    for pat in (f'#{i}', f'"message_id": {i}', f'telegram_id\": {i}', f'message_id={i}'):
        rows = conn.execute("SELECT id, direction, sender, recipient, subject, body, metadata FROM messages WHERE body LIKE ? OR metadata LIKE ? LIMIT 20", (f'%{pat}%', f'%{pat}%')).fetchall()
        for r in rows:
            print(f"#{i} pattern={pat} msg_id={r['id']} subj={r['subject']} body={str(r['body'])[:250]}")
            if r['metadata']:
                print('  metadata=', str(r['metadata'])[:250])

# 4. Check comm_messages
print('\n=== comm_messages search ===')
for i in ids:
    for pat in (f'#{i}', f'"message_id": {i}', f'telegram_id\": {i}'):
        rows = conn.execute("SELECT id, direction, sender, recipient, subject, content, metadata FROM comm_messages WHERE content LIKE ? OR metadata LIKE ? LIMIT 20", (f'%{pat}%', f'%{pat}%')).fetchall()
        for r in rows:
            print(f"#{i} pattern={pat} msg_id={r['id']} subj={r['subject']} content={str(r['content'])[:300]}")

# 5. Count messages in connector_messages by connector_name
print('\n=== connector_messages counts by connector_name ===')
for r in conn.execute("SELECT connector_name, COUNT(*) FROM connector_messages GROUP BY connector_name").fetchall():
    print(r)

conn.close()
