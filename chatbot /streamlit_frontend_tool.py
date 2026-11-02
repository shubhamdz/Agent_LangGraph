import streamlit as st
from langgraph_tool_backend import (
    chatbot,
    llm,
    retrieve_all_threads,
    retrieve_thread_names,
    add_thread as db_add_thread,
    update_thread_name,
    delete_all_threads
)
from langchain_core.messages import HumanMessage,AIMessage,ToolMessage
import uuid
import os
os.environ['LANGCHAIN_PROJECT'] = 'Chatbot'

#**************************************** Utilitie*****************************************

def generate_thread_id():
    thread_id = str(uuid.uuid4())
    return thread_id

def reset_chat():
    thread_id = generate_thread_id()
    st.session_state['thread_id'] = thread_id
    add_thread(st.session_state['thread_id'])
    st.session_state['message_history'] = []

def add_thread(thread_id):
    if thread_id not in st.session_state['thread_id_list']:
        st.session_state['thread_id_list'].append(thread_id)
    if thread_id not in st.session_state['thread_names']:
        st.session_state['thread_names'][thread_id] = "New Chat"
    db_add_thread(thread_id)

def load_conversation(thread_id):
    state = chatbot.get_state(config={'configurable': {'thread_id': thread_id}})
    # Check if messages key exists in state values, return empty list if not
    return state.values.get('messages', [])

def generate_chat_title(user_message, assistant_message, thread_id):

    prompt = f"""
    Generate a short, meaningful title for this conversation.

    User message: {user_message}
    Assistant response: {assistant_message}

    Rules:
    - Maximum 5 words.
    - Return only the title.
    - Do not use quotation marks.
    """

    response = llm.invoke(
        prompt,
        config={
            "metadata": {
                "thread_id": thread_id
            },
            "run_name": "generate_chat_title"
        }
    )

    return response.content.strip().strip('"')

#****************************************   session setup *****************************************
if 'message_history' not in st.session_state:
    st.session_state['message_history'] = []

if 'thread_id' not in st.session_state:
    st.session_state['thread_id'] = generate_thread_id()

if 'thread_id_list' not in st.session_state:
    st.session_state['thread_id_list'] = retrieve_all_threads()

if 'thread_names' not in st.session_state:
    st.session_state['thread_names'] = retrieve_thread_names()

add_thread(st.session_state['thread_id'])

#**************************************** SideBar UI *****************************************
st.sidebar.title('LangGraph Chatbot')

if st.sidebar.button('New Chat'):
    reset_chat()

st.sidebar.header('My Converations')
for thread_id in st.session_state['thread_id_list'][::-1]:
    thread_name = st.session_state['thread_names'].get(thread_id, "New Chat")
    if st.sidebar.button(thread_name, key=thread_id):
        st.session_state['thread_id'] = thread_id
        messages = load_conversation(thread_id)

        temp_mess = []
        for msg in messages:
            if isinstance(msg, HumanMessage):
                temp_mess.append({'role': 'user', 'content': msg.content})
            else:
                temp_mess.append({'role': 'assistant', 'content': msg.content})

        st.session_state['message_history'] = temp_mess
        st.rerun()

# loading the conversation history
for message in st.session_state['message_history']:
    with st.chat_message(message['role']):
        st.text(message['content'])

#[{'role': 'user', 'content': 'Hi'}
#{'role': 'assistant', 'content': 'Hi=ello'}]

user_input = st.chat_input('Type here')
# st.session_state -> dict -> 
CONFIG = {'configurable': {'thread_id': st.session_state['thread_id']},
            'metadata':{
                "thread_id": st.session_state['thread_id']
                },
            'run_name':'chat_turn'
            }


if user_input:
    thread_id = st.session_state['thread_id']
    # first add the message to message_history
    st.session_state['message_history'].append({'role': 'user', 'content': user_input})
    with st.chat_message('user'):
        st.text(user_input)

    # first add the message to message_history
    with st.chat_message("assistant"):
        # Use a mutable holder so the generator can set/modify it
        status_holder = {"box": None}

        def ai_only_stream():
            for message_chunk, metadata in chatbot.stream(
                {"messages": [HumanMessage(content=user_input)]},
                config=CONFIG,
                stream_mode="messages",
            ):
                # Lazily create & update the SAME status container when any tool runs
                if isinstance(message_chunk, ToolMessage):
                    tool_name = getattr(message_chunk, "name", "tool")
                    if status_holder["box"] is None:
                        status_holder["box"] = st.status(
                            f"🔧 Using `{tool_name}` …", expanded=True
                        )
                    else:
                        status_holder["box"].update(
                            label=f"🔧 Using `{tool_name}` …",
                            state="running",
                            expanded=True,
                        )

                # Stream ONLY assistant tokens
                if isinstance(message_chunk, AIMessage):
                    yield message_chunk.content

        ai_message = st.write_stream(ai_only_stream())

        # Finalize only if a tool was actually used
        if status_holder["box"] is not None:
            status_holder["box"].update(
                label="✅ Tool finished", state="complete", expanded=False
            )
    
    st.session_state['message_history'].append({'role': 'assistant', 'content': ai_message})

    if st.session_state['thread_names'].get(thread_id) == "New Chat":
        chat_name = generate_chat_title(user_input, ai_message,thread_id)
        st.session_state['thread_names'][thread_id] = chat_name
        update_thread_name(thread_id, chat_name)
        st.rerun()

if st.sidebar.button("Clear All Chats"):

    delete_all_threads()

    st.session_state['thread_id_list'] = []
    st.session_state['thread_names'] = {}
    st.session_state['message_history'] = []

    st.session_state['thread_id'] = generate_thread_id()

    add_thread(st.session_state['thread_id'])

    st.rerun()