# pip install -U langchain langchain-openai langchain-community faiss-cpu pypdf python-dotenv

import os
from dotenv import load_dotenv
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_groq import ChatGroq
from langchain_cohere import CohereEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableParallel, RunnablePassthrough, RunnableLambda
from langchain_core.output_parsers import StrOutputParser
import os 
import time

os.environ['LANGCHAIN_PROJECT'] = 'RAG_v1'


load_dotenv()  # expects OPENAI_API_KEY in .env

PDF_PATH = "islr.pdf"  # <-- change to your PDF filename

# 1) Load PDF
loader = PyPDFLoader(PDF_PATH)
docs = loader.load()  # one Document per page

# 2) Chunk
splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)
splits = splitter.split_documents(docs)

# 3) Embed + index
emb = CohereEmbeddings(
    model="embed-english-light-v3.0",
    cohere_api_key=os.environ["COHERE_API_KEY"],
)

import time

batch_size = 20
vs = None

for i in range(0, len(splits), batch_size):

    batch = splits[i:i + batch_size]

    try:
        if vs is None:
            vs = FAISS.from_documents(batch, emb)
        else:
            vs.add_documents(batch)

        print(f"Processed {min(i + batch_size, len(splits))}/{len(splits)}")

    except Exception as e:
        if "429" in str(e):
            print("Rate limit reached. Waiting 60 seconds...")
            time.sleep(60)

            # Retry the same batch
            if vs is None:
                vs = FAISS.from_documents(batch, emb)
            else:
                vs.add_documents(batch)
        else:
            raise

print("FAISS indexing completed!")

retriever = vs.as_retriever(
    search_type="similarity",
    search_kwargs={"k": 4}
)


# 4) Prompt
prompt = ChatPromptTemplate.from_messages([
    ("system", "Answer ONLY from the provided context. If not found, say you don't know."),
    ("human", "Question: {question}\n\nContext:\n{context}")
])

# 5) Chain
llm = ChatGroq(model = 'openai/gpt-oss-120b',temperature=0.7)
def format_docs(docs): return "\n\n".join(d.page_content for d in docs)

parallel = RunnableParallel({
    "context": retriever | RunnableLambda(format_docs),
    "question": RunnablePassthrough()
})

chain = parallel | prompt | llm | StrOutputParser()

# 6) Ask questions
print("PDF RAG ready. Ask a question (or Ctrl+C to exit).")
q = input("\nQ: ")
ans = chain.invoke(q.strip())
print("\nA:", ans)
