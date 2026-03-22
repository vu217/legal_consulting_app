"""
Experimental LangGraph RAG prototype (not used by the FastAPI/React app).

Uses Qdrant collection "rag_docs" — distinct from the main pipeline ("legal_cases").
Prefer master_agent.py + shared_retriever.py for production flows.
"""

from typing import TypedDict, List
from langgraph.graph import StateGraph
from langgraph.graph import END
from langchain_ollama import ChatOllama, OllamaEmbeddings
from langchain_qdrant import QdrantVectorStore

QDRANT_URL = "http://localhost:6333"
COLLECTION = "rag_docs"
LLM_MODEL  = "deepseek-r1:8b"

class AgentState(TypedDict):
    query: str
    context: List[str]
    sources: List[str]
    output: str
    hops: int

def load_retriever():
    embeddings = OllamaEmbeddings(model="nomic-embed-text")
    vectorstore = QdrantVectorStore.from_existing_collection(
        embedding=embeddings,
        url=QDRANT_URL,
        collection_name=COLLECTION,
    )
    return vectorstore.as_retriever(search_kwargs={"k": 5})

llm = ChatOllama(model=LLM_MODEL)

def retrieve_node(state: AgentState) -> AgentState:
    retriever = load_retriever()  # loads only when query runs
    docs = retriever.invoke(state["query"])
    context = [d.page_content for d in docs]
    sources = list(set([d.metadata.get("source", "unknown") for d in docs]))
    return {**state, "context": context, "sources": sources, "hops": state.get("hops", 0) + 1}

def should_synthesize(state: AgentState) -> str:
    if state["hops"] >= 2 or len(" ".join(state["context"])) > 800:
        return "synthesize"
    return "retrieve"

def synthesize_node(state: AgentState) -> AgentState:
    context = "\n\n".join(state["context"])
    prompt = f"""You are a helpful legal assistant. Use only the context below to answer.

Context:
{context}

Question: {state['query']}
Answer:"""
    response = llm.invoke(prompt)
    return {**state, "output": response.content}

graph = StateGraph(AgentState)
graph.add_node("retrieve", retrieve_node)
graph.add_node("synthesize", synthesize_node)
graph.add_conditional_edges("retrieve", should_synthesize, {
    "synthesize": "synthesize",
    "retrieve":   "retrieve",
})
graph.add_edge("synthesize", END)
graph.set_entry_point("retrieve")

agent = graph.compile()
