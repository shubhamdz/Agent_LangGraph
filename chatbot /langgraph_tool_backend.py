# backend.py

from langgraph.graph import StateGraph, START, END
from typing import TypedDict, Annotated
from langchain_core.messages import BaseMessage, HumanMessage
from langchain_groq import ChatGroq
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from langchain_community.tools import DuckDuckGoSearchRun
from langchain_core.tools import tool
from dotenv import load_dotenv
import sqlite3
import requests
import os

api_key = os.getenv("ALPHA_VANTAGE_API_KEY")

load_dotenv()

# -------------------
# 1. LLM
# -------------------
llm = ChatGroq(model='openai/gpt-oss-120b')

# -------------------
# 2. Tools
# -------------------
# Tools
search_tool = DuckDuckGoSearchRun(region="us-en")

@tool
def calculator(first_num: float, second_num: float, operation: str) -> dict:
    """
    Perform a basic arithmetic operation on two numbers.
    Supported operations: add, sub, mul, div
    """
    try:
        if operation == "add":
            result = first_num + second_num
        elif operation == "sub":
            result = first_num - second_num
        elif operation == "mul":
            result = first_num * second_num
        elif operation == "div":
            if second_num == 0:
                return {"error": "Division by zero is not allowed"}
            result = first_num / second_num
        else:
            return {"error": f"Unsupported operation '{operation}'"}
        
        return {"first_num": first_num, "second_num": second_num, "operation": operation, "result": result}
    except Exception as e:
        return {"error": str(e)}




@tool
def get_stock_price(symbol: str) -> dict:
    """
    Fetch latest stock price for a given symbol (e.g. 'AAPL', 'TSLA') 
    using Alpha Vantage with API key in the URL.
    """
    url = f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={symbol}&apikey=SI0BIIU7H6WEOE0Y"
    r = requests.get(url)
    return r.json()



tools = [search_tool, get_stock_price, calculator]
llm_with_tools = llm.bind_tools(tools)

# -------------------
# 3. State
# -------------------
class ChatState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]

# -------------------
# 4. Nodes
# -------------------
def chat_node(state: ChatState):
    """LLM node that may answer or request a tool call."""
    messages = state["messages"]
    response = llm_with_tools.invoke(messages)
    return {"messages": [response]}

tool_node = ToolNode(tools)

# -------------------
# 5. Checkpointer
# -------------------
conn = sqlite3.connect(database="chatbot.db", check_same_thread=False)
# Create metadata table
conn.execute("""
    CREATE TABLE IF NOT EXISTS threads (
        thread_id TEXT PRIMARY KEY,
        thread_name TEXT DEFAULT 'New Chat'
    )
""")

conn.commit()
checkpointer = SqliteSaver(conn=conn)

# -------------------
# 6. Graph
# -------------------
graph = StateGraph(ChatState)
graph.add_node("chat_node", chat_node)
graph.add_node("tools", tool_node)

graph.add_edge(START, "chat_node")

graph.add_conditional_edges("chat_node",tools_condition)
graph.add_edge('tools', 'chat_node')

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