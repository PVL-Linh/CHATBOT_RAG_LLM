import psycopg2
from dotenv import load_dotenv
import os

load_dotenv()  # Load file .env

# Cách 1: Dùng biến riêng (khuyến nghị - an toàn, dễ đọc)
USER = os.getenv("DB_USER")
PASSWORD = os.getenv("DB_PASSWORD")
HOST = os.getenv("DB_HOST")
PORT = os.getenv("DB_PORT")
DBNAME = os.getenv("DB_NAME")

# Cách 2: Hoặc dùng DATABASE_URL trực tiếp (cũng được)
# DATABASE_URL = os.getenv("DATABASE_URL")

if not all([USER, PASSWORD, HOST, PORT, DBNAME]):
    raise ValueError("Thiếu biến môi trường DB trong .env")

try:
    connection = psycopg2.connect(
        user=USER,
        password=PASSWORD,
        host=HOST,
        port=PORT,
        dbname=DBNAME,
        sslmode="require"  # Bắt buộc với Supabase
    )
    print("✅ Kết nối Supabase thành công!")

    cursor = connection.cursor()
    cursor.execute("SELECT NOW(), version();")
    result = cursor.fetchone()
    print("Thời gian server:", result[0])
    print("Phiên bản Postgres:", result[1][:50] + "...")  # in ngắn

    cursor.close()
    connection.close()
    print("Đóng kết nối thành công.")
except Exception as e:
    print(f"❌ Kết nối thất bại: {e}")