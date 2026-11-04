import sqlite3

# 1. Buka / buat koneksi ke database
conn = sqlite3.connect("data/database.db")
cursor = conn.cursor()

# 2. Buat tabel dengan kolom 'a' sebagai Primary Key
cursor.execute("""
    CREATE TABLE IF NOT EXISTS tabel_contoh (
        a INTEGER PRIMARY KEY AUTOINCREMENT,
        b INT
    )
""")

# 3. Tambahkan (insert) data
cursor.execute("INSERT INTO tabel_contoh (a, b) VALUES (1, 2)")

# 4. Simpan perubahan dan tutup koneksi
conn.commit()
conn.close()

print("Tabel berhasil dibuat dan data terisi!")
