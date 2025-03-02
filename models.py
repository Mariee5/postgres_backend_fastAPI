from sqlalchemy import Column, Integer, String, DateTime, Date, Time, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
from dotenv import load_dotenv
import os
from database import SessionLocal
from database import Base

# Load environment variables
load_dotenv()

Base = declarative_base()

class Poster(Base):
    __tablename__ = "posters"
    
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String)
    name = Column(String)
    location = Column(String)
    socials = Column(String)
    event_date = Column(Date)
    event_time = Column(Time)
    venue = Column(String)
    hosted_department = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

# Database connection
DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create tables
Base.metadata.create_all(bind=engine) 