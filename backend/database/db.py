import psycopg2
import psycopg2.extras

from config import Config


def get_connection():
    conn = psycopg2.connect(
        host=Config.DB_HOST,
        port=Config.DB_PORT,
        user=Config.DB_USER,
        password=Config.DB_PASSWORD,
        dbname=Config.DB_NAME,
        cursor_factory=psycopg2.extras.RealDictCursor,
    )
    conn.autocommit = True
    return conn
