"""
CLI Utility to reset an administrator or user password in library.db
Usage:
    python reset_admin_password.py [username] [new_password]
Example:
    python reset_admin_password.py Gennie367 mypassword123
"""
import sys
import os
import sqlite3
import hashlib
import secrets

def reset_password(username="Gennie367", new_password="admin123"):
    db_file = os.getenv("DB_FILE") or os.path.join(os.path.dirname(__file__), "library.db")
    if not os.path.exists(db_file):
        print(f"Error: Database {db_file} not found.")
        return False

    salt = secrets.token_hex(16)
    p_hash = hashlib.pbkdf2_hmac('sha256', new_password.strip().encode('utf-8'), salt.encode('utf-8'), 100000).hex()

    conn = sqlite3.connect(db_file)
    cur = conn.cursor()
    cur.execute("SELECT id, username, role FROM users WHERE LOWER(username) = LOWER(?)", (username.strip(),))
    user = cur.fetchone()

    if not user:
        print(f"User '{username}' not found in {db_file}.")
        users = cur.execute("SELECT id, username, role FROM users").fetchall()
        print(f"Existing users: {users}")
        conn.close()
        return False

    user_id, uname, role = user
    cur.execute("UPDATE users SET password_hash = ?, salt = ? WHERE id = ?", (p_hash, salt, user_id))
    # Invalidate old sessions
    cur.execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

    print(f"✅ Success! Password for user '{uname}' (role: {role}) has been reset to: {new_password}")
    return True

if __name__ == "__main__":
    u = sys.argv[1] if len(sys.argv) > 1 else "Gennie367"
    p = sys.argv[2] if len(sys.argv) > 2 else "admin123"
    reset_password(u, p)
