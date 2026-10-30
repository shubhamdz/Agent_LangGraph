import streamlit as st
from langgraph_backend import chatbot,model
from langchain_core.messages import HumanMessage
import uuid

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

def load_conversation(thread_id):
    state = chatbot.get_state(config={'configurable': {'thread_id': thread_id}})
    # Check if messages key exists in state values, return empty list if not
    return state.values.get('messages', [])

def generate_chat_title(user_message, assistant_message):

    prompt = f"""
    Generate a short, meaningful title for this conversation.

    User message: {user_message}
    Assistant response: {assistant_message}

    Rules:
    - Maximum 5 words.
    - Return only the title.
    - Do not use quotation marks.
    """

    response = model.invoke(prompt)

    return response.content.strip().strip('"')

#****************************************   session setup *****************************************
if 'message_history' not in st.session_state:
    st.session_state['message_history'] = []

if 'thread_id' not in st.session_state:
    st.session_state['thread_id'] = generate_thread_id()

if 'thread_id_list' not in st.session_state:
    st.session_state['thread_id_list'] = []

if "thread_names" not in st.session_state:
    st.session_state["thread_names"] = {}

add_thread(st.session_state['thread_id'])

#**************************************** SideBar UI *****************************************
st.sidebar.title('LangGraph Chatbot')

if st.sidebar.button('New Chat'):
    reset_chat()

st.sidebar.header('My Converations')
for thread_id in st.session_state['thread_id_list'][::-1]:
    thread_name = st.session_state['thread_names'][thread_id]
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

# loading the conversation history
for message in st.session_state['message_history']:
    with st.chat_message(message['role']):
        st.text(message['content'])

#[{'role': 'user', 'content': 'Hi'}
#{'role': 'assistant', 'content': 'Hi=ello'}]

user_input = st.chat_input('Type here')
# st.session_state -> dict -> 
CONFIG = {'configurable': {'thread_id': st.session_state['thread_id']}}


if user_input:
    thread_id = st.session_state['thread_id']
    # first add the message to message_history
    st.session_state['message_history'].append({'role': 'user', 'content': user_input})
    with st.chat_message('user'):
        st.text(user_input)

    # first add the message to message_history
    with st.chat_message('assistant'):

        ai_message = st.write_stream(
            message_chunk.content for message_chunk, metadata in chatbot.stream(
                {'messages': [HumanMessage(content=user_input)]},
                config= CONFIG,
                stream_mode= 'messages'
            )
        )
    
    st.session_state['message_history'].append({'role': 'assistant', 'content': ai_message})

    if st.session_state['thread_names'][thread_id] == "New Chat":
        chat_name = generate_chat_title(user_input, ai_message)
        st.session_state['thread_names'][thread_id] = chat_name
        st.rerun()