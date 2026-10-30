
from dotenv import load_dotenv
from langgraph.graph import StateGraph, START, END
from typing import TypedDict, Annotated
from langchain_core.messages import BaseMessage
from langchain_groq import ChatGroq
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph.message import add_messages
import sqlite3

load_dotenv()

model = ChatGroq(model="openai/gpt-oss-120b")


class ChatState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]


def chat_node(state: ChatState):
    messages = state['messages']
    response = model.invoke(messages)

    return {'messages': [response]}


# Database connection
conn = sqlite3.connect(
    database="chatbot.db",
    check_same_thread=False
)

# Create metadata table
conn.execute("""
    CREATE TABLE IF NOT EXISTS threads (
        thread_id TEXT PRIMARY KEY,
        thread_name TEXT DEFAULT 'New Chat'
    )
""")

conn.commit()

# LangGraph checkpointer
checkpointer = SqliteSaver(conn=conn)

# Build graph
graph = StateGraph(ChatState)

graph.add_node('chat_node', chat_node)
graph.add_edge(START, 'chat_node')
graph.add_edge('chat_node', END)

chatbot = graph.compile(checkpointer=checkpointer)


# ---------------- THREAD MANAGEMENT ----------------

# Retrieve threads from LangGraph checkpoints
def retrieve_checkpoint_threads():

    all_threads = set()

    for checkpoint in checkpointer.list(None):
        all_threads.add(
            checkpoint.config['configurable']['thread_id']
        )

    return list(all_threads)


# Retrieve threads from SQLite metadata
def retrieve_all_threads():

    cursor = conn.execute(
        "SELECT thread_id FROM threads"
    )

    return [row[0] for row in cursor.fetchall()]


# Add a new thread
def add_thread(thread_id):

    conn.execute("""
        INSERT OR IGNORE INTO threads
        (thread_id, thread_name)
        VALUES (?, ?)
    """, (thread_id, "New Chat"))

    conn.commit()


# Update conversation title
def update_thread_name(thread_id, thread_name):

    conn.execute("""
        UPDATE threads
        SET thread_name = ?
        WHERE thread_id = ?
    """, (thread_name, thread_id))

    conn.commit()


# Retrieve conversation titles
def retrieve_thread_names():

    cursor = conn.execute("""
        SELECT thread_id, thread_name
        FROM threads
    """)

    return dict(cursor.fetchall())


# Migrate existing LangGraph conversations
def migrate_existing_threads():

    for thread_id in retrieve_checkpoint_threads():
        add_thread(thread_id)


# Run migration once when backend loads
migrate_existing_threads()


def delete_all_threads():

    # Delete all LangGraph checkpoints
    checkpointer.conn.execute("DELETE FROM checkpoints")
    checkpointer.conn.execute("DELETE FROM writes")

    # Delete all conversation metadata
    conn.execute("DELETE FROM threads")

    conn.commit()