import streamlit as st
import google.generativeai as genai
import os
import redis
import json
import uuid
from datetime import datetime, timedelta

# --- Configuration ---
try:
    api_key = st.secrets["API_KEY"]
    genai.configure(api_key=api_key)
except (KeyError, FileNotFoundError):
    st.error("Gemini API key not found. Please set it as a Streamlit secret.")
    st.stop()

# --- Redis Configuration ---
try:
    redis_url = st.secrets["REDIS_URL"]
    redis_client = redis.from_url(redis_url, decode_responses=True)
    redis_client.ping()
    st.success("Connected to Redis!")
except Exception as e:
    st.error(f"Could not connect to Redis: {e}")
    st.info("Please ensure REDIS_URL is correctly set in your Streamlit secrets.")
    st.stop()

# --- Constants ---
CHAT_SESSIONS_KEY = "teachpy:chat_sessions"
CURRENT_SESSION_KEY = "teachpy:current_session"

PERSONA_INSTRUCTION = """
You are an expert Python teacher chatbot named "TeachPy". Your sole focus is to teach Python.

**YOUR MISSION:**
To guide learners from beginner to advanced levels in a structured, step-by-step manner.

**INITIAL ASSESSMENT:**
1.  Start by warmly greeting the learner.
2.  Determine their preferred Python version (Python 2 or Python 3). Advise Python 3 for new learners.
3.  Assess their current expertise level (Beginner, Intermediate, Advanced).

**LEARNING ROADMAP:**
1.  Based on their level, present a clear, tailored Python learning roadmap.
2.  The roadmap must outline the topics and progression steps they will follow.
3.  **YOU MUST** get their confirmation before starting the lessons.

**TEACHING METHODOLOGY:**
1.  **Strictly adhere to the roadmap.** Do not jump between topics.
2.  Deliver lessons in short, digestible chunks.
3.  Use clear and simple explanations.
4.  Incorporate visual aids (use Markdown for diagrams, code blocks, etc.) to explain complex concepts.
5.  Provide practical coding exercises and quizzes after each major concept.
6.  **Ensure the learner fully understands a concept before moving to the next.** Ask them if they are ready to proceed.
7. When it is important teach a

**BEST PRACTICES & FEEDBACK:**
1.  All Python code you provide **MUST** be PEP 8 compliant.
2.  Provide constructive, encouraging feedback on the learner's code and answers.
3.  Gently correct any misconceptions.

**SCOPE & FOCUS:**
1.  **Stick strictly to Python.** Do not discuss other programming languages, general software development, or any unrelated topics. If asked, politely decline and redirect back to the Python lesson.
2.  Your ultimate goal is to build the learner's confidence and expertise smoothly.

**FORMATTING:**
1.  Remove any unimportant formatting or fluff. Communication must be clear and focused.
2.  Use **bold** and *italic* formatting to emphasize important points.
3.  Capitalize and **bold** the main topics or headings (e.g., "**PYTHON ROADMAP FOR BEGINNERS**").
"""

# --- Model Initialization ---
def get_gemini_model():
    return genai.GenerativeModel(
        model_name="gemini-2.0-flash",
        system_instruction=PERSONA_INSTRUCTION
    )

# --- Chat Session Management ---

#To change the date from YYYY-MM-DD to a more readable format (to name of the day)
def format_chat_timestamp(timestamp_str):
    """Convert timestamp string to relative day format"""
    # Parse the timestamp string
    timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M")
    now = datetime.now()
    
    # Calculate time differences
    today = now.date()
    yesterday = today - timedelta(days=1)
    timestamp_date = timestamp.date()
    
    if timestamp_date == today:
        return "Today"
    elif timestamp_date == yesterday:
        return "Yesterday"
    else:
        # Return day name (Monday, Tuesday, etc.)
        return timestamp.strftime("%A")
# In your session creation code:
def create_new_session():
    """Creates a new chat session with a unique ID"""
    session_id = str(uuid.uuid4())
    # In your session creation code:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")  # Keep this for storage
    display_time = format_chat_timestamp(timestamp)  # Use this for display

    session_data = {
        "id": session_id,
        "title": f"New Session ({display_time})",  # Use the formatted time here
        "messages": [],
        "created_at": timestamp,  # Keep original timestamp
        "display_time": display_time  # Store formatted version too
    }
    
    # Store the new session in Redis
    redis_client.hset(CHAT_SESSIONS_KEY, session_id, json.dumps(session_data))
    redis_client.set(CURRENT_SESSION_KEY, session_id)
    
    # Add initial welcome message
    initial_message = {
        "role": "assistant",
        "content": "Hello! I am TeachPy. To get started, could you please tell me which version of Python you'd like to learn (Python 2 or Python 3) and what you would consider your current skill level: *Beginner*, *Intermediate*, or *Advanced*?"
    }
    add_message_to_session(session_id, initial_message)
    
    return session_id

def get_current_session():
    """Gets or creates the current session"""
    session_id = redis_client.get(CURRENT_SESSION_KEY)
    if not session_id:
        return create_new_session()
    return session_id.decode('utf-8')

def get_session_messages(session_id):
    """Retrieves messages for a specific session"""
    session_data = redis_client.hget(CHAT_SESSIONS_KEY, session_id)
    if session_data:
        return json.loads(session_data)["messages"]
    return []

def add_message_to_session(session_id, message):
    """Adds a message to a specific session"""
    session_data = redis_client.hget(CHAT_SESSIONS_KEY, session_id)
    if session_data:
        session = json.loads(session_data)
        session["messages"].append(message)
        # Update the session title if it's the first user message
        if message["role"] == "user" and len(session["messages"]) == 2:
            session["title"] = f"{message['content'][:30]}..."
        redis_client.hset(CHAT_SESSIONS_KEY, session_id, json.dumps(session))

def get_all_sessions():
    """Retrieves all chat sessions"""
    sessions = []
    for session_id, session_data in redis_client.hgetall(CHAT_SESSIONS_KEY).items():
        session = json.loads(session_data)
        sessions.append({
            "id": session_id.decode('utf-8'),
            "title": session["title"],
            "created_at": session["created_at"],
            "message_count": len(session["messages"])
        })
    # Sort sessions by creation date (newest first)
    return sorted(sessions, key=lambda x: x["created_at"], reverse=True)

def delete_session(session_id):
    """Deletes a chat session"""
    redis_client.hdel(CHAT_SESSIONS_KEY, session_id)
    current_session = redis_client.get(CURRENT_SESSION_KEY)
    if current_session and current_session.decode('utf-8') == session_id:
        redis_client.delete(CURRENT_SESSION_KEY)

# --- Streamlit App ---
def main():
    st.markdown(
    """
    <style>
    body {
        font-size: 15px;
    }
    .sidebar .sidebar-content {
        width: 300px;
    }
    </style>
    """,
    unsafe_allow_html=True
    )

    st.set_page_config(
        page_title="TeachPy",
        page_icon="🐍",
        layout="wide"
    )

    # Initialize session state
    if "chat_session" not in st.session_state:
        st.session_state.chat_session = get_gemini_model().start_chat(history=[])

    # Get or create current session
    current_session_id = get_current_session()
    st.session_state.current_session_id = current_session_id

    # --- Sidebar ---
    with st.sidebar:
        st.header("Chat History")
        
        # Button to create new chat
        if st.button("➕ New Chat", use_container_width=True):
            current_session_id = create_new_session()
            st.session_state.current_session_id = current_session_id
            st.session_state.chat_session = get_gemini_model().start_chat(history=[])
            st.rerun()
        
        st.divider()
        
        # List of all chat sessions
        sessions = get_all_sessions()
        if sessions:
            st.subheader("Previous Chats")
            for session in sessions:
                cols = st.columns([1, 4])
                with cols[0]:
                    if st.button("🗑️", key=f"del_{session['id']}"):
                        delete_session(session['id'])
                        if session['id'] == current_session_id:
                            current_session_id = create_new_session()
                            st.session_state.current_session_id = current_session_id
                            st.session_state.chat_session = get_gemini_model().start_chat(history=[])
                        st.rerun()
                with cols[1]:
                    if st.button(session["title"], key=session["id"], use_container_width=True):
                        if session["id"] != current_session_id:
                            current_session_id = session["id"]
                            st.session_state.current_session_id = current_session_id
                            redis_client.set(CURRENT_SESSION_KEY, current_session_id)
                            st.session_state.chat_session = get_gemini_model().start_chat(history=[])
                            st.rerun()

    # --- Main Chat Area ---
    st.title("🐍 TeachPy: Your Personal Python Tutor")
    st.write("Welcome! I'm here to help you master Python, one step at a time.")

    # Load messages for current session
    messages = get_session_messages(current_session_id)
    
    # Display chat messages
    for message in messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # User input
    user_prompt = st.chat_input("What would you like to learn today?")
    
    if user_prompt:
        # Add user message to session
        user_message = {"role": "user", "content": user_prompt}
        add_message_to_session(current_session_id, user_message)
        
        with st.chat_message("user"):
            st.markdown(user_prompt)

        # Get model response
        try:
            with st.spinner("TeachPy is thinking..."):
                response = st.session_state.chat_session.send_message(user_prompt)
                response_text = response.text
                
                # Add assistant response to session
                assistant_message = {"role": "assistant", "content": response_text}
                add_message_to_session(current_session_id, assistant_message)
                
                with st.chat_message("assistant"):
                    st.markdown(response_text)

        except Exception as e:
            st.error(f"An error occurred: {e}")
            # Remove the last user message if the API call failed
            session_data = redis_client.hget(CHAT_SESSIONS_KEY, current_session_id)
            if session_data:
                session = json.loads(session_data)
                if session["messages"] and session["messages"][-1]["role"] == "user":
                    session["messages"].pop()
                    redis_client.hset(CHAT_SESSIONS_KEY, current_session_id, json.dumps(session))

if __name__ == "__main__":
    main()
