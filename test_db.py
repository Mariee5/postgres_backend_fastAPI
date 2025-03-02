from sqlalchemy import create_engine

DATABASE_URL = "postgresql+psycopg2://postgres:forme1234@localhost/poster_db"
engine = create_engine(DATABASE_URL)

try:
    connection = engine.connect()
    print("Database connection successful!")
    connection.close()
except Exception as e:
    print(f"Database connection failed: {e}")