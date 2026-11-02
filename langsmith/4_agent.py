from langchain_groq import ChatGroq
from langchain_core.tools import tool
import requests
from langchain_community.tools import DuckDuckGoSearchRun
from langchain_classic.agents import create_react_agent, AgentExecutor
from langsmith import Client
from dotenv import load_dotenv
from ddgs import DDGS
from langchain_core.tools import tool

load_dotenv()

@tool
def duckduckgo_search(query: str) -> str:
    """Search the internet for relevant information."""

    try:
        results = DDGS().text(
            query,
            max_results=5,
            backend="duckduckgo"
        )

        if not results:
            return "No search results found."

        return str(results)

    except Exception as e:
        return f"Search service error: {e}"

search_tool = duckduckgo_search

@tool
def get_weather_data(city: str) -> str:
  """
  This function fetches the current weather data for a given city
  """
  url = f'https://api.weatherstack.com/current?access_key=f07d9636974c4120025fadf60678771b&query={city}'

  response = requests.get(url)

  return response.json()

llm = ChatGroq(model = 'qwen/qwen3.8-27b')

# Step 2: Pull the ReAct prompt from LangChain Hub
client = Client()

prompt = client.pull_prompt(
    "hwchase17/react",
    dangerously_pull_public_prompt=True
)  # pulls the standard ReAct agent prompt

# Step 3: Create the ReAct agent manually with the pulled prompt
agent = create_react_agent(
    llm=llm,
    tools=[search_tool, get_weather_data],
    prompt=prompt
)

# Step 4: Wrap it with AgentExecutor
agent_executor = AgentExecutor(
    agent=agent,
    tools=[search_tool, get_weather_data],
    verbose=True,
    max_iterations=5,
    handle_parsing_errors=True
)

# What is the release date of Dhadak 2?
# What is the current temp of gurgaon
# Identify the birthplace city of Kalpana Chawla (search) and give its current temperature.

# Step 5: Invoke
response = agent_executor.invoke({"input": "Identify the birthplace city of Kalpana Chawla (search) and give its current temperature."})
print(response)

print(response['output'])