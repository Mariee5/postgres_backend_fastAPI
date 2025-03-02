import os
from fastapi import FastAPI, File, UploadFile, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import google.generativeai as genai
from PIL import Image
import io
from models import SessionLocal, Poster
from dotenv import load_dotenv
import json
from datetime import datetime, date
from sqlalchemy import and_, or_
from typing import Optional, List

# Load environment variables
load_dotenv()

# Configure Gemini API
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel('gemini-2.0-flash')

app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def clean_time_string(time_str: str) -> str:
    """Clean time string by removing extra words and standardizing format"""
    # Remove common suffixes and prefixes
    time_str = time_str.lower()
    words_to_remove = ['onwards', 'onward', 'starting', 'from', 'at']
    for word in words_to_remove:
        time_str = time_str.replace(word, '').strip()
    
    # Standardize AM/PM format
    time_str = time_str.replace('pm', ' PM').replace('am', ' AM')
    
    return time_str.strip()

@app.post("/analyze-poster")
async def analyze_poster(file: UploadFile = File(...)):
    try:
        # Read and validate the image
        contents = await file.read()
        image = Image.open(io.BytesIO(contents))
        
        # Prepare the prompt for Gemini
        prompt = """
        Please analyze this poster image and extract the following information in JSON format:
        - Title of the event
        - Name of the organizer/speaker
        - Location
        - Social media handles
        - Date
        - Time
        - Venue
        - Hosting department name
        
        Please format the response as a valid JSON object with these exact keys:
        {
            "title": "",
            "name": "",
            "location": "",
            "socials": "",
            "event_date": "", # use this format %Y-%m-%d
            "event_time": "", # use this format %H:%M:%S
            "venue": "",
            "hosted_department": ""
        }
        Return only the JSON object, nothing else.
        """

        # Generate response from Gemini
        response = model.generate_content([prompt, image])
        
        # Parse the response to get JSON data
        try:
            # Clean the response text and parse JSON
            response_text = response.text.strip()
            response_text = response_text.replace('```json', '').replace('```', '').strip()
            extracted_data = json.loads(response_text)
            
            # Parse date and time strings into proper objects
            try:
                # Assuming date format is "YYYY-MM-DD" or similar standard format
                if extracted_data.get("event_date"):
                    extracted_data["event_date"] = datetime.strptime(
                        extracted_data["event_date"], 
                        "%Y-%m-%d"
                    ).date()
                
                # Updated time parsing
                if extracted_data.get("event_time"):
                    time_str = clean_time_string(extracted_data["event_time"])
                    # Try different time formats
                    time_formats = [
                        "%I:%M %p",    # 5:30 PM
                        "%I:%M%p",     # 5:30PM
                        "%I:%M",       # 5:30
                        "%H:%M",       # 17:30
                        "%I %p",       # 5 PM
                        "%H:%M:%S",    # 17:30:00
                        "%I:%M:%S %p", # 5:30:00 PM
                    ]
                    parsed_time = None
                    
                    for fmt in time_formats:
                        try:
                            parsed_time = datetime.strptime(time_str, fmt).time()
                            break
                        except ValueError:
                            continue
                    
                    if parsed_time is None:
                        # If no exact match found, try to extract time using regex
                        import re
                        time_pattern = re.compile(r'(\d{1,2}):?(\d{2})?\s*(am|pm|AM|PM)?')
                        match = time_pattern.search(time_str)
                        
                        if match:
                            hour = int(match.group(1))
                            minute = int(match.group(2)) if match.group(2) else 0
                            period = match.group(3)
                            
                            # Adjust hour for PM times
                            if period and period.lower() == 'pm' and hour != 12:
                                hour += 12
                            elif period and period.lower() == 'am' and hour == 12:
                                hour = 0
                                
                            parsed_time = datetime.strptime(f"{hour:02d}:{minute:02d}", "%H:%M").time()
                        else:
                            raise ValueError(f"Could not parse time string: {extracted_data['event_time']}")
                    
                    extracted_data["event_time"] = parsed_time
            
            except ValueError as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid date/time format in the response: {str(e)}"
                )
            
            # Store in database
            db = next(get_db())
            poster_data = Poster(**extracted_data)
            db.add(poster_data)
            db.commit()
            db.refresh(poster_data)
            
            return {
                "message": "Poster analyzed successfully",
                "data": extracted_data
            }
            
        except json.JSONDecodeError as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to parse Gemini response as JSON. Response: {response.text}"
            )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/events/upcoming", response_model=List[dict])
async def get_upcoming_events():
    try:
        db = next(get_db())
        today = date.today()
        
        # Get all events with dates equal to or after today, ordered by date
        upcoming_events = db.query(Poster).filter(
            Poster.event_date >= today
        ).order_by(Poster.event_date).all()
        
        return [
            {
                "id": event.id,
                "title": event.title,
                "name": event.name,
                "location": event.location,
                "socials": event.socials,
                "event_date": event.event_date.isoformat(),
                "event_time": event.event_time.isoformat() if event.event_time else None,
                "venue": event.venue,
                "hosted_department": event.hosted_department
            } for event in upcoming_events
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/events/by-location/{location}", response_model=List[dict])
async def get_events_by_location(
    location: str,
    upcoming_only: bool = Query(default=False, description="Filter for upcoming events only")
):
    try:
        db = next(get_db())
        query = db.query(Poster).filter(Poster.location.ilike(f"%{location}%"))
        
        if upcoming_only:
            today = date.today()
            query = query.filter(Poster.event_date >= today)
            
        events = query.order_by(Poster.event_date).all()
        
        return [
            {
                "id": event.id,
                "title": event.title,
                "name": event.name,
                "location": event.location,
                "socials": event.socials,
                "event_date": event.event_date.isoformat(),
                "event_time": event.event_time.isoformat() if event.event_time else None,
                "venue": event.venue,
                "hosted_department": event.hosted_department
            } for event in events
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/events/by-date/{date}", response_model=List[dict])
async def get_events_by_date(date: str):
    try:
        # Parse the date string to date object
        try:
            search_date = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
            
        db = next(get_db())
        events = db.query(Poster).filter(
            Poster.event_date == search_date
        ).order_by(Poster.event_time).all()
        
        return [
            {
                "id": event.id,
                "title": event.title,
                "name": event.name,
                "location": event.location,
                "socials": event.socials,
                "event_date": event.event_date.isoformat(),
                "event_time": event.event_time.isoformat() if event.event_time else None,
                "venue": event.venue,
                "hosted_department": event.hosted_department
            } for event in events
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/events/by-venue/{venue}", response_model=List[dict])
async def get_events_by_venue(
    venue: str,
    upcoming_only: bool = Query(default=False, description="Filter for upcoming events only")
):
    try:
        db = next(get_db())
        query = db.query(Poster).filter(Poster.venue.ilike(f"%{venue}%"))
        
        if upcoming_only:
            today = date.today()
            query = query.filter(Poster.event_date >= today)
            
        events = query.order_by(Poster.event_date).all()
        
        return [
            {
                "id": event.id,
                "title": event.title,
                "name": event.name,
                "location": event.location,
                "socials": event.socials,
                "event_date": event.event_date.isoformat(),
                "event_time": event.event_time.isoformat() if event.event_time else None,
                "venue": event.venue,
                "hosted_department": event.hosted_department
            } for event in events
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/events/by-department/{department}", response_model=List[dict])
async def get_events_by_department(
    department: str,
    upcoming_only: bool = Query(default=False, description="Filter for upcoming events only")
):
    try:
        db = next(get_db())
        query = db.query(Poster).filter(Poster.hosted_department.ilike(f"%{department}%"))
        
        if upcoming_only:
            today = date.today()
            query = query.filter(Poster.event_date >= today)
            
        events = query.order_by(Poster.event_date).all()
        
        return [
            {
                "id": event.id,
                "title": event.title,
                "name": event.name,
                "location": event.location,
                "socials": event.socials,
                "event_date": event.event_date.isoformat(),
                "event_time": event.event_time.isoformat() if event.event_time else None,
                "venue": event.venue,
                "hosted_department": event.hosted_department
            } for event in events
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Remove or comment out the if __name__ == "__main__" block
# if __name__ == "__main__":
#     import uvicorn
#     uvicorn.run(app, host="0.0.0.0", port=8080) 